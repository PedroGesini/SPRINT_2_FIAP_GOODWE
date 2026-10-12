from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import charger_in_scope
from app.core.permissions import get_current_user, is_staff, require_staff
from app.db.session import get_db
from app.models import Charger, ChargerStatus, ChargingSession, SessionStatus, User, OCPPDevice
from app.models.core import utcnow
from app.schemas.charger import (ChargerFull, ChargerIn, ChargerPublic, ChargerStatusIn,
                                 ChargerUpdateIn)
from app.services.audit_service import log_action
from app.services.charging_service import ChargingError

router = APIRouter(prefix="/chargers", tags=["Carregadores"])


def _view(user: User, charger: Charger):
    schema = ChargerFull if is_staff(user) else ChargerPublic
    return schema.model_validate(charger)


@router.get("")
def list_chargers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Charger).where(Charger.condominium_id == user.condominium_id)
                      .order_by(Charger.code)).all()
    return [_view(user, c) for c in rows]


@router.get("/availability")
def availability(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Charger).where(Charger.condominium_id == user.condominium_id)).all()
    counts = {s.value: 0 for s in ChargerStatus}
    from app.models import OCPPDevice
    from app.services.ocpp_gateway import connections
    devices={d.charger_id:d.id for d in db.scalars(select(OCPPDevice).where(
        OCPPDevice.charger_id.in_([c.id for c in rows])))} if rows else {}
    views=[]
    for c in rows:
        public=ChargerPublic.model_validate(c)
        if c.id in devices and devices[c.id] not in connections:
            public.status=ChargerStatus.UNAVAILABLE
        counts[public.status.value] += 1
        views.append(public)
    return {"counts": counts, "total": len(rows),
            "chargers": views, "data_source": "misto (simulações e OCPP, quando conectado)"}


@router.get("/{charger_id}")
def detail(charger_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _view(user, charger_in_scope(db, user, charger_id))


@router.post("", response_model=ChargerFull, status_code=201)
def create(data: ChargerIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    if db.scalars(select(Charger).where(Charger.condominium_id == staff.condominium_id,
                                        Charger.code == data.code)).first():
        raise ChargingError("Já existe um carregador com este código.")
    charger = Charger(condominium_id=staff.condominium_id, status=ChargerStatus.AVAILABLE,
                      **data.model_dump())
    db.add(charger)
    db.flush()
    log_action(db, condominium_id=staff.condominium_id, actor_id=staff.id, action="charger.created",
               entity="charger", entity_id=charger.id, details={"code": charger.code})
    db.commit()
    return charger


@router.patch("/{charger_id}", response_model=ChargerFull)
def update(charger_id: int, data: ChargerUpdateIn, staff: User = Depends(require_staff),
           db: Session = Depends(get_db)):
    charger = charger_in_scope(db, staff, charger_id)
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(charger, k, v)
    log_action(db, condominium_id=staff.condominium_id, actor_id=staff.id, action="charger.updated",
               entity="charger", entity_id=charger.id, details={"fields": sorted(changes)})
    db.commit()
    return charger


@router.post("/{charger_id}/status", response_model=ChargerFull)
def set_status(charger_id: int, data: ChargerStatusIn, staff: User = Depends(require_staff),
               db: Session = Depends(get_db)):
    """O status 'em uso' só é definido por sessões; aqui apenas disponível/manutenção/indisponível."""
    charger = charger_in_scope(db, staff, charger_id)
    if data.status == ChargerStatus.IN_USE:
        raise ChargingError("O status 'em uso' é definido apenas pelo início de uma sessão.")
    active = db.scalars(select(ChargingSession).where(
        ChargingSession.charger_id == charger.id,
        ChargingSession.status == SessionStatus.IN_PROGRESS)).first()
    if active:
        raise ChargingError("Há uma sessão em andamento; encerre-a antes de alterar o status.")
    if db.scalar(select(OCPPDevice.id).where(OCPPDevice.charger_id==charger.id)):
        raise ChargingError('Carregador OCPP: use comando ChangeAvailability; o status vem do dispositivo.')
    old = charger.status
    charger.status = data.status
    charger.status_updated_at = utcnow()
    log_action(db, condominium_id=staff.condominium_id, actor_id=staff.id, action="charger.status_changed",
               entity="charger", entity_id=charger.id, details={"from": old.value, "to": data.status.value})
    db.commit()
    return charger


@router.get("/{charger_id}/usage")
def usage(charger_id: int, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    from app.schemas.session import SessionOut
    charger = charger_in_scope(db, staff, charger_id)
    rows = db.scalars(select(ChargingSession).where(ChargingSession.charger_id == charger.id)
                      .order_by(ChargingSession.started_at.desc()).limit(50)).all()
    return [SessionOut.model_validate(s) for s in rows]
