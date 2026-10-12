"""Condomínio, usuários, veículos e carregadores."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (Boolean, Date, DateTime, Enum, ForeignKey, Numeric,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.enums import ChargerStatus, Role, UserStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Condominium(Base):
    __tablename__ = "condominiums"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    condominium_id: Mapped[int] = mapped_column(ForeignKey("condominiums.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    cpf: Mapped[str | None] = mapped_column(String(14))  # dado sensível: sempre mascarar em listagens
    block: Mapped[str | None] = mapped_column(String(20))
    unit: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.RESIDENT)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="owner")


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("plate", name="uq_vehicle_plate"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plate: Mapped[str] = mapped_column(String(10))
    model: Mapped[str | None] = mapped_column(String(80))

    owner: Mapped[User] = relationship(back_populates="vehicles")


class Charger(Base):
    __tablename__ = "chargers"
    __table_args__ = (UniqueConstraint("condominium_id", "code", name="uq_charger_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    condominium_id: Mapped[int] = mapped_column(ForeignKey("condominiums.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(30))
    manufacturer: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    power_kw: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    location: Mapped[str | None] = mapped_column(String(120))
    parking_spot: Mapped[str | None] = mapped_column(String(20))
    connector_type: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[ChargerStatus] = mapped_column(Enum(ChargerStatus), default=ChargerStatus.AVAILABLE)
    installed_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    status_updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
