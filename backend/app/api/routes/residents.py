from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import resident_in_scope
from app.core.permissions import get_current_user, require_staff
from app.core.validators import normalize_plate
from app.db.session import get_db
from app.models import ChargingSession, Role, SessionStatus, User, UserStatus, Vehicle
from app.schemas.common import Page
from app.schemas.user import (ResidentCreateIn, ResidentUpdateIn, UserOut, VehicleIn,
                              VehicleOut, to_user_out)
from app.services.audit_service import log_action
from app.services.resident_service import ResidentError, change_status, create_resident

router = APIRouter(prefix="/residents", tags=["Moradores"])


@router.get("", response_model=Page[UserOut])
def list_residents(q: str | None = None, status: UserStatus | None = None,
                   page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                   staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    stmt = select(User).where(User.condominium_id == staff.condominium_id, User.role == Role.RESIDENT)
    if status:
        stmt = stmt.where(User.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.unit.ilike(like),
                              User.block.ilike(like), User.email.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.name).offset((page - 1) * size).limit(size)).all()
    return Page(items=[to_user_out(u) for u in rows], total=total, page=page, size=size)


@router.post("", response_model=UserOut, status_code=201)
def create(data: ResidentCreateIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    try:
        user = create_resident(db, condominium_id=staff.condominium_id, status=UserStatus.ACTIVE,
                               actor_id=staff.id, **data.model_dump())
    except ResidentError as exc:
        db.rollback()
        raise
    db.commit()
    return to_user_out(user)


@router.get("/{resident_id}", response_model=UserOut)
def detail(resident_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return to_user_out(resident_in_scope(db, user, resident_id))


@router.patch("/{resident_id}", response_model=UserOut)
def update(resident_id: int, data: ResidentUpdateIn, staff: User = Depends(require_staff),
           db: Session = Depends(get_db)):
    target = resident_in_scope(db, staff, resident_id)
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(target, k, v)
    log_action(db, condominium_id=staff.condominium_id, actor_id=staff.id, action="resident.updated",
               entity="user", entity_id=target.id, details={"fields": sorted(changes)})
    db.commit()
    return to_user_out(target)


def _transition(resident_id, new, staff, db):
    target = resident_in_scope(db, staff, resident_id)
    change_status(db, target, new, staff)
    db.commit()
    return to_user_out(target)


@router.post("/{resident_id}/approve", response_model=UserOut)
def approve(resident_id: int, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    return _transition(resident_id, UserStatus.ACTIVE, staff, db)


@router.post("/{resident_id}/reject", response_model=UserOut)
def reject(resident_id: int, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    return _transition(resident_id, UserStatus.REJECTED, staff, db)


@router.post("/{resident_id}/deactivate", response_model=UserOut)
def deactivate(resident_id: int, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    return _transition(resident_id, UserStatus.INACTIVE, staff, db)


@router.post("/{resident_id}/activate", response_model=UserOut)
def activate(resident_id: int, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    return _transition(resident_id, UserStatus.ACTIVE, staff, db)


@router.post("/{resident_id}/vehicles", response_model=VehicleOut, status_code=201)
def add_vehicle(resident_id: int, data: VehicleIn, staff: User = Depends(require_staff),
                db: Session = Depends(get_db)):
    target = resident_in_scope(db, staff, resident_id)
    plate = normalize_plate(data.plate)
    if db.scalars(select(Vehicle).where(Vehicle.plate == plate)).first():
        raise ResidentError("Esta placa já está cadastrada.")
    vehicle = Vehicle(owner_id=target.id, plate=plate, model=data.model)
    db.add(vehicle)
    log_action(db, condominium_id=staff.condominium_id, actor_id=staff.id,
               action="vehicle.added", entity="user", entity_id=target.id, details={"plate": plate})
    db.commit()
    return vehicle


@router.get("/{resident_id}/history")
def history(resident_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Resumo do consumo individual (o próprio morador ou o síndico)."""
    target = resident_in_scope(db, user, resident_id)
    row = db.execute(select(func.count(ChargingSession.id), func.coalesce(func.sum(ChargingSession.energy_kwh), 0),
                            func.coalesce(func.sum(ChargingSession.energy_cost), 0),
                            func.max(ChargingSession.started_at)).where(
        ChargingSession.resident_id == target.id,
        ChargingSession.status == SessionStatus.COMPLETED)).one()
    return {"resident_id": target.id, "sessions": row[0], "total_kwh": str(Decimal(row[1]).quantize(Decimal("0.001"))),
            "total_cost": str(Decimal(row[2]).quantize(Decimal("0.01"))), "last_session_at": row[3]}
