import csv
import io
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import charger_in_scope, resident_in_scope, session_in_scope
from app.core.permissions import get_current_user, is_staff, require_staff
from app.db.session import get_db
from app.models import (Charger, ChargingSession, SessionSource, SessionStatus, User,
                        Vehicle)
from app.schemas.common import Page
from app.schemas.session import SessionEndIn, SessionManualIn, SessionOut, SessionStartIn
from app.services import charging_service as cs

router = APIRouter(prefix="/sessions", tags=["Sessões de recarga"])


def _filtered(user: User, *, date_from: date | None, date_to: date | None, resident_id: int | None,
              charger_id: int | None, status: SessionStatus | None):
    stmt = select(ChargingSession).where(ChargingSession.condominium_id == user.condominium_id)
    if not is_staff(user):
        stmt = stmt.where(ChargingSession.resident_id == user.id)  # morador: sempre só as suas
    elif resident_id:
        stmt = stmt.where(ChargingSession.resident_id == resident_id)
    if date_from:
        stmt = stmt.where(ChargingSession.started_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(ChargingSession.started_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))
    if charger_id:
        stmt = stmt.where(ChargingSession.charger_id == charger_id)
    if status:
        stmt = stmt.where(ChargingSession.status == status)
    return stmt


@router.get("", response_model=Page[SessionOut])
def list_sessions(date_from: date | None = None, date_to: date | None = None,
                  resident_id: int | None = None, charger_id: int | None = None,
                  status: SessionStatus | None = None, page: int = Query(1, ge=1),
                  size: int = Query(20, ge=1, le=100), user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    stmt = _filtered(user, date_from=date_from, date_to=date_to, resident_id=resident_id,
                     charger_id=charger_id, status=status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ChargingSession.started_at.desc())
                      .offset((page - 1) * size).limit(size)).all()
    return Page(items=[SessionOut.model_validate(s) for s in rows], total=total, page=page, size=size)


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text  # evita injeção de fórmulas


@router.get("/export.csv")
def export_csv(date_from: date | None = None, date_to: date | None = None,
               resident_id: int | None = None, charger_id: int | None = None,
               status: SessionStatus | None = None, staff: User = Depends(require_staff),
               db: Session = Depends(get_db)):
    stmt = _filtered(staff, date_from=date_from, date_to=date_to, resident_id=resident_id,
                     charger_id=charger_id, status=status).order_by(ChargingSession.started_at)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "morador", "unidade", "carregador", "inicio", "fim", "duracao_min",
                "kwh", "tarifa_kwh", "custo", "status", "origem"])
    for s in db.scalars(stmt):
        r, c = db.get(User, s.resident_id), db.get(Charger, s.charger_id)
        w.writerow([s.id, _csv_safe(r.name), _csv_safe(f"{r.block or ''}-{r.unit or ''}"),
                    _csv_safe(c.code), s.started_at.isoformat(),
                    s.ended_at.isoformat() if s.ended_at else "", s.duration_minutes or "",
                    s.energy_kwh or "", s.tariff_price_per_kwh, s.energy_cost or "",
                    s.status.value, s.source.value])
    buf.seek(0)
    return StreamingResponse(iter(["\ufeff" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=sessoes.csv"})


@router.get("/{session_id}", response_model=SessionOut)
def detail(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return session_in_scope(db, user, session_id)


@router.post("/start", response_model=SessionOut, status_code=201)
def start(data: SessionStartIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if is_staff(user):
        if data.resident_id is None:
            raise HTTPException(422, "Informe resident_id.")
        resident = resident_in_scope(db, user, data.resident_id)
    else:
        resident = user
    charger = charger_in_scope(db, user, data.charger_id)
    if data.vehicle_id is not None:
        vehicle = db.get(Vehicle, data.vehicle_id)
        if vehicle is None or vehicle.owner_id != resident.id:
            raise HTTPException(422, "Veículo não pertence ao morador.")
    session = cs.start_session(db, charger=charger, resident=resident, actor=user,
                               start_reading_kwh=data.start_reading_kwh, vehicle_id=data.vehicle_id,
                               source=SessionSource.SIMULATION)
    db.commit()
    return session


@router.post("/{session_id}/end", response_model=SessionOut)
def end(session_id: int, data: SessionEndIn, user: User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    session = session_in_scope(db, user, session_id)
    if session.source == SessionSource.INTEGRATION:
        raise HTTPException(409, 'Sessão OCPP: aguarde StopTransaction do equipamento.')
    explicit = data.energy_kwh is not None or data.end_reading_kwh is not None
    if explicit and not is_staff(user):
        raise HTTPException(403, "Somente o síndico pode informar o consumo manualmente.")
    ended_at = None
    if data.simulated_duration_minutes:
        if session.source != SessionSource.SIMULATION:
            raise HTTPException(422, "Duração simulada só vale para sessões de simulação.")
        ended_at = session.started_at + timedelta(minutes=data.simulated_duration_minutes)
    if explicit:
        done = cs.end_session(db, session=session, actor=user, end_reading_kwh=data.end_reading_kwh,
                              energy_kwh=data.energy_kwh, ended_at=ended_at)
    else:
        if session.source != SessionSource.SIMULATION:
            raise HTTPException(422, "Informe a leitura final ou o consumo em kWh.")
        end_time = ended_at or datetime.now(timezone.utc)
        charger = db.get(Charger, session.charger_id)
        kwh = cs.simulate_energy(charger, session.started_at, end_time) if end_time > session.started_at else None
        if kwh is None:
            raise cs.ChargingError("O término deve ser posterior ao início.")
        done = cs.end_session(db, session=session, actor=user, energy_kwh=kwh, ended_at=end_time)
    db.commit()
    return done


@router.post("/manual", response_model=SessionOut, status_code=201)
def manual(data: SessionManualIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    resident = resident_in_scope(db, staff, data.resident_id)
    charger = charger_in_scope(db, staff, data.charger_id)
    session = cs.register_manual_session(
        db, charger=charger, resident=resident, actor=staff, started_at=data.started_at,
        ended_at=data.ended_at, energy_kwh=data.energy_kwh, start_reading_kwh=data.start_reading_kwh,
        end_reading_kwh=data.end_reading_kwh, vehicle_id=data.vehicle_id)
    db.commit()
    return session
