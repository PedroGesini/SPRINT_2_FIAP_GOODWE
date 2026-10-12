from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.validators import mask_cpf, normalize_cpf, normalize_plate
from app.models import Role, UserStatus


class _Checked(BaseModel):
    @field_validator("cpf", check_fields=False)
    @classmethod
    def _cpf(cls, v):
        return normalize_cpf(v)

    @field_validator("plate", check_fields=False)
    @classmethod
    def _plate(cls, v):
        return normalize_plate(v)


class RegisterIn(_Checked):
    name: str = Field(min_length=3, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    cpf: str | None = None
    block: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)
    password_confirm: str
    plate: str | None = None
    vehicle_model: str | None = Field(default=None, max_length=80)
    condominium_id: int | None = None  # omitido => condomínio de demonstração

    @model_validator(mode="after")
    def _same_password(self):
        if self.password != self.password_confirm:
            raise ValueError("As senhas não coincidem.")
        return self


class ResidentCreateIn(_Checked):
    name: str = Field(min_length=3, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    cpf: str | None = None
    block: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)
    plate: str | None = None
    vehicle_model: str | None = Field(default=None, max_length=80)


class ResidentUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    block: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=20)


class VehicleIn(_Checked):
    plate: str
    model: str | None = Field(default=None, max_length=80)


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plate: str
    model: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    phone: str | None = None
    block: str | None = None
    unit: str | None = None
    role: Role
    status: UserStatus
    cpf_masked: str | None = None
    vehicles: list[VehicleOut] = []


def to_user_out(user) -> UserOut:
    out = UserOut.model_validate(user)
    out.cpf_masked = mask_cpf(user.cpf)
    return out
