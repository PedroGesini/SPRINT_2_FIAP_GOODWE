from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import InvoiceItemKind, InvoiceStatus


class AdjustmentIn(BaseModel):
    reason: str = Field(min_length=5, max_length=200)
    amount: Decimal


class InvoiceGenerateIn(BaseModel):
    resident_id: int
    period_start: date
    period_end: date
    shared_total: Decimal = Field(default=Decimal("0"), ge=0)
    adjustments: list[AdjustmentIn] = []
    due_in_days: int = Field(default=10, ge=1, le=60)
    correction: bool = False

    @model_validator(mode="after")
    def _period(self):
        if self.period_end < self.period_start:
            raise ValueError("period_end deve ser maior ou igual a period_start.")
        return self


class InvoicePeriodIn(BaseModel):
    period_start: date
    period_end: date
    shared_total: Decimal = Field(default=Decimal("0"), ge=0)
    due_in_days: int = Field(default=10, ge=1, le=60)


class PaymentIn(BaseModel):
    amount: Decimal = Field(gt=0)


class CancelIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kind: InvoiceItemKind
    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal
    session_id: int | None = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    amount: Decimal
    paid_at: datetime
    simulated: bool


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    resident_id: int
    period_start: date
    period_end: date
    version: int
    total_kwh: Decimal
    tariff_price_per_kwh: Decimal
    allocation_criterion: str
    total_amount: Decimal
    status: InvoiceStatus
    issued_at: date
    due_date: date
    cancel_reason: str | None = None
    paid_amount: Decimal = Decimal("0.00")
    balance: Decimal = Decimal("0.00")
    items: list[ItemOut] = []
    payments: list[PaymentOut] = []


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    channel: str
    status: str
    sent_at: datetime
