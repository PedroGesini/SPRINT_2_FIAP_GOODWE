"""Sessões de recarga: início, encerramento e validações de estado."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (Charger, ChargerStatus, ChargingSession, SessionSource, OCPPDevice,
                        SessionStatus, Tariff, User, UserStatus)
from app.services.audit_service import log_action
from app.services.billing_service import (BillingError, consumption_from_readings,
                                          energy_cost, money)
from app.models.core import utcnow


class ChargingError(Exception):
    pass


def active_tariff(db: Session, condominium_id: int) -> Tariff:
    t = db.scalars(select(Tariff).where(Tariff.condominium_id == condominium_id,
                                        Tariff.active.is_(True))
                   .order_by(Tariff.valid_from.desc())).first()
    if t is None:
        raise ChargingError("Nenhuma tarifa ativa configurada para o condomínio.")
    return t


def start_session(db: Session, *, charger: Charger, resident: User, actor: User,
                  start_reading_kwh: Decimal | None = None, vehicle_id: int | None = None,
                  source: SessionSource = SessionSource.SIMULATION,
                  started_at: datetime | None = None) -> ChargingSession:
    if resident.condominium_id != charger.condominium_id:
        raise ChargingError("Morador e carregador pertencem a condomínios diferentes.")
    if resident.status != UserStatus.ACTIVE:
        raise ChargingError("Apenas moradores ativos podem iniciar recargas.")
    if source == SessionSource.SIMULATION and db.scalar(select(OCPPDevice.id).where(OCPPDevice.charger_id==charger.id)):
        raise ChargingError('Carregador gerenciado por OCPP: inicie a recarga pelo equipamento/RFID.')
    if charger.status != ChargerStatus.AVAILABLE:
        raise ChargingError(f"Carregador indisponível (status: {charger.status.value}).")
    busy = db.scalars(select(ChargingSession).where(
        ChargingSession.charger_id == charger.id,
        ChargingSession.status == SessionStatus.IN_PROGRESS)).first()
    if busy:
        raise ChargingError("Já existe uma sessão em andamento neste carregador.")

    tariff = active_tariff(db, charger.condominium_id)
    session = ChargingSession(
        condominium_id=charger.condominium_id, resident_id=resident.id, vehicle_id=vehicle_id,
        charger_id=charger.id, started_at=started_at or utcnow(),
        start_reading_kwh=start_reading_kwh, tariff_price_per_kwh=tariff.price_per_kwh,
        status=SessionStatus.IN_PROGRESS, source=source)
    charger.status = ChargerStatus.IN_USE
    charger.status_updated_at = utcnow()
    db.add(session)
    db.flush()
    log_action(db, condominium_id=charger.condominium_id, actor_id=actor.id,
               action="session.started", entity="charging_session", entity_id=session.id,
               details={"charger_id": charger.id, "resident_id": resident.id})
    return session


def end_session(db: Session, *, session: ChargingSession, actor: User,
                end_reading_kwh: Decimal | None = None, energy_kwh: Decimal | None = None,
                ended_at: datetime | None = None) -> ChargingSession:
    """Encerra a sessão. Informe a leitura final do medidor OU o consumo (simulação)."""
    if session.status != SessionStatus.IN_PROGRESS:
        raise ChargingError("Apenas sessões em andamento podem ser encerradas.")
    ended = ended_at or utcnow()
    if ended <= session.started_at:
        raise ChargingError("O término deve ser posterior ao início.")
    try:
        if end_reading_kwh is not None:
            if session.start_reading_kwh is None:
                raise ChargingError("Sessão sem leitura inicial; informe o consumo diretamente.")
            kwh = consumption_from_readings(session.start_reading_kwh, end_reading_kwh)
            session.end_reading_kwh = Decimal(end_reading_kwh)
        elif energy_kwh is not None:
            kwh = Decimal(energy_kwh).quantize(Decimal("0.001"))
        else:
            raise ChargingError("Informe a leitura final ou o consumo em kWh.")
        cost = energy_cost(kwh, session.tariff_price_per_kwh)
    except BillingError as exc:
        raise ChargingError(str(exc)) from exc
    session.ended_at = ended
    session.energy_kwh = kwh
    session.energy_cost = cost
    session.status = SessionStatus.COMPLETED
    charger = db.get(Charger, session.charger_id)
    if charger.status == ChargerStatus.IN_USE:
        charger.status = ChargerStatus.AVAILABLE
        charger.status_updated_at = utcnow()
    log_action(db, condominium_id=session.condominium_id, actor_id=actor.id,
               action="session.ended", entity="charging_session", entity_id=session.id,
               details={"energy_kwh": str(kwh), "cost": str(money(cost))})
    return session


def simulate_energy(charger: Charger, started_at: datetime, ended_at: datetime) -> Decimal:
    """Consumo FICTÍCIO para o modo demonstração (≈85% da potência nominal). Não é medição real."""
    hours = Decimal((ended_at - started_at).total_seconds()) / Decimal(3600)
    kwh = Decimal(charger.power_kw) * hours * Decimal("0.85")
    return min(max(kwh, Decimal("0.001")), Decimal("100")).quantize(Decimal("0.001"))


def register_manual_session(db: Session, *, charger: Charger, resident: User, actor: User,
                            started_at: datetime, ended_at: datetime,
                            energy_kwh: Decimal | None = None,
                            start_reading_kwh: Decimal | None = None,
                            end_reading_kwh: Decimal | None = None,
                            vehicle_id: int | None = None) -> ChargingSession:
    """Registro histórico feito pelo síndico (sessão já encerrada)."""
    if resident.condominium_id != charger.condominium_id:
        raise ChargingError("Morador e carregador pertencem a condomínios diferentes.")
    if ended_at <= started_at:
        raise ChargingError("O término deve ser posterior ao início.")
    overlap = db.scalars(select(ChargingSession).where(
        ChargingSession.charger_id == charger.id,
        ChargingSession.status != SessionStatus.CANCELLED,
        ChargingSession.started_at < ended_at,
        (ChargingSession.ended_at.is_(None)) | (ChargingSession.ended_at > started_at))).first()
    if overlap:
        raise ChargingError("Conflito: já existe sessão neste carregador no intervalo informado.")
    try:
        if start_reading_kwh is not None and end_reading_kwh is not None:
            kwh = consumption_from_readings(start_reading_kwh, end_reading_kwh)
        elif energy_kwh is not None:
            kwh = Decimal(energy_kwh).quantize(Decimal("0.001"))
        else:
            raise ChargingError("Informe as leituras do medidor ou o consumo em kWh.")
        tariff = active_tariff(db, charger.condominium_id)
        cost = energy_cost(kwh, tariff.price_per_kwh)
    except BillingError as exc:
        raise ChargingError(str(exc)) from exc
    session = ChargingSession(
        condominium_id=charger.condominium_id, resident_id=resident.id, vehicle_id=vehicle_id,
        charger_id=charger.id, started_at=started_at, ended_at=ended_at,
        start_reading_kwh=start_reading_kwh, end_reading_kwh=end_reading_kwh,
        energy_kwh=kwh, tariff_price_per_kwh=tariff.price_per_kwh, energy_cost=cost,
        status=SessionStatus.COMPLETED, source=SessionSource.MANUAL)
    db.add(session)
    db.flush()
    log_action(db, condominium_id=charger.condominium_id, actor_id=actor.id,
               action="session.manual_registered", entity="charging_session",
               entity_id=session.id, details={"energy_kwh": str(kwh), "cost": str(cost)})
    return session
