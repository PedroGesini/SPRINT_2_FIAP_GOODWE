from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import SessionSource, SessionStatus


class SessionStartIn(BaseModel):
    charger_id: int
    resident_id: int | None = None  # obrigatório para o síndico; ignorado para o morador
    vehicle_id: int | None = None
    start_reading_kwh: Decimal | None = Field(default=None, ge=0)


class SessionEndIn(BaseModel):
    end_reading_kwh: Decimal | None = Field(default=None, ge=0)  # apenas síndico
    energy_kwh: Decimal | None = Field(default=None, gt=0, le=500)  # apenas síndico
    simulated_duration_minutes: int | None = Field(default=None, ge=1, le=720)  # só simulação


class SessionManualIn(BaseModel):
    resident_id: int
    charger_id: int
    vehicle_id: int | None = None
    started_at: datetime
    ended_at: datetime
    energy_kwh: Decimal | None = Field(default=None, gt=0, le=500)
    start_reading_kwh: Decimal | None = Field(default=None, ge=0)
    end_reading_kwh: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _tz(self):
        if self.started_at.tzinfo is None or self.ended_at.tzinfo is None:
            raise ValueError("Informe data e hora com fuso (ex.: 2026-09-10T18:00:00Z).")
        return self


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    resident_id: int
    vehicle_id: int | None = None
    charger_id: int
    started_at: datetime
    ended_at: datetime | None = None
    duration_minutes: int | None = None
    energy_kwh: Decimal | None = None
    tariff_price_per_kwh: Decimal
    energy_cost: Decimal | None = None
    status: SessionStatus
    source: SessionSource
    invoice_id: int | None = None
