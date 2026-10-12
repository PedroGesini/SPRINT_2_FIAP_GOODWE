"""Tarifas, sessões de recarga, faturas, pagamentos, envios, notificações e auditoria."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, Date, DateTime, Enum, ForeignKey, Integer,
                        Numeric, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.core import utcnow
from app.models.enums import (InvoiceItemKind, InvoiceStatus, SessionSource,
                              SessionStatus)


class Tariff(Base):
    __tablename__ = "tariffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    condominium_id: Mapped[int] = mapped_column(ForeignKey("condominiums.id"), index=True)
    price_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    fixed_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ChargingSession(Base):
    __tablename__ = "charging_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    condominium_id: Mapped[int] = mapped_column(ForeignKey("condominiums.id"), index=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    charger_id: Mapped[int] = mapped_column(ForeignKey("chargers.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    start_reading_kwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    end_reading_kwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    energy_kwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    tariff_price_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 4))  # tarifa congelada
    energy_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), default=SessionStatus.IN_PROGRESS)
    source: Mapped[SessionSource] = mapped_column(Enum(SessionSource), default=SessionSource.SIMULATION)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)

    @property
    def duration_minutes(self) -> int | None:
        if self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds() // 60)


class Invoice(Base):
    __tablename__ = "invoices"
    # Uma fatura ativa por morador/período; novas versões incrementam `version`.
    __table_args__ = (UniqueConstraint("resident_id", "period_start", "period_end", "version",
                                       name="uq_invoice_resident_period_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    condominium_id: Mapped[int] = mapped_column(ForeignKey("condominiums.id"), index=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    total_kwh: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0"))
    tariff_price_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    allocation_criterion: Mapped[str] = mapped_column(String(60), default="consumo_kwh")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    status: Mapped[InvoiceStatus] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.ISSUED)
    issued_at: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    kind: Mapped[InvoiceItemKind] = mapped_column(Enum(InvoiceItemKind))
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("charging_sessions.id"))

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)  # nunca é transação real
    registered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class InvoiceDelivery(Base):
    __tablename__ = "invoice_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(20), default="in_app")  # in_app | email_simulated
    status: Mapped[str] = mapped_column(String(20), default="simulated")  # simulated | sent | error
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    condominium_id: Mapped[int | None] = mapped_column(ForeignKey("condominiums.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)  # nunca senhas, tokens ou CPF
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
