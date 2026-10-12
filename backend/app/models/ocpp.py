"""Identidade OCPP e telemetria: tabelas novas, preservam bancos existentes."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import ForeignKey, Integer, Numeric, String, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.core import utcnow

class OCPPDevice(Base):
    __tablename__ = 'ocpp_devices'
    id: Mapped[int] = mapped_column(primary_key=True)
    charger_id: Mapped[int] = mapped_column(ForeignKey('chargers.id'), unique=True, index=True)
    ocpp_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    vendor: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    firmware: Mapped[str | None] = mapped_column(String(100))
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime())
    connector_status: Mapped[str | None] = mapped_column(String(32))
    last_meter_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

class OCPPMeterReading(Base):
    __tablename__ = 'ocpp_meter_readings'
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey('ocpp_devices.id'), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey('charging_sessions.id'), index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    meter_kwh: Mapped[Decimal] = mapped_column(Numeric(14, 3))

class OCPPTag(Base):
    """RFID ou tag provisionada administrativamente e vinculada ao morador."""
    __tablename__ = 'ocpp_tags'
    __table_args__ = (UniqueConstraint('condominium_id','id_tag',name='uq_ocpp_tag_condo'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    condominium_id: Mapped[int] = mapped_column(ForeignKey('condominiums.id'), index=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    id_tag: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
