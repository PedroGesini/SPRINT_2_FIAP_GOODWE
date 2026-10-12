from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import ChargerStatus


class ChargerIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    code: str = Field(min_length=2, max_length=30)
    manufacturer: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    power_kw: Decimal = Field(gt=0, le=350)
    location: str | None = Field(default=None, max_length=120)
    parking_spot: str | None = Field(default=None, max_length=20)
    connector_type: str | None = Field(default=None, max_length=30)
    installed_on: date | None = None
    notes: str | None = None


class ChargerUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    manufacturer: str | None = None
    model: str | None = None
    power_kw: Decimal | None = Field(default=None, gt=0, le=350)
    location: str | None = None
    parking_spot: str | None = None
    connector_type: str | None = None
    installed_on: date | None = None
    notes: str | None = None


class ChargerStatusIn(BaseModel):
    status: ChargerStatus


class ChargerPublic(BaseModel):
    """Dados que o morador pode consultar."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    power_kw: Decimal
    location: str | None = None
    parking_spot: str | None = None
    connector_type: str | None = None
    status: ChargerStatus
    status_updated_at: datetime


class ChargerFull(ChargerPublic):
    manufacturer: str | None = None
    model: str | None = None
    installed_on: date | None = None
    notes: str | None = None
