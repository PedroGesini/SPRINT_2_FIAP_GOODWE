from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.validators import normalize_cpf, normalize_plate
from app.models import Role, User, UserStatus, Vehicle
from app.services.audit_service import log_action


class ResidentError(Exception):
    pass


def create_resident(db: Session, *, condominium_id: int, name: str, email: str, password: str,
                    phone: str | None = None, cpf: str | None = None, block: str | None = None,
                    unit: str | None = None, plate: str | None = None,
                    vehicle_model: str | None = None, status: UserStatus = UserStatus.PENDING,
                    actor_id: int | None = None) -> User:
    email = email.strip().lower()
    cpf = normalize_cpf(cpf)
    plate = normalize_plate(plate)
    if db.scalars(select(User).where(User.email == email)).first():
        raise ResidentError("Já existe uma conta com este e-mail.")
    if cpf and db.scalars(select(User).where(User.cpf == cpf)).first():
        raise ResidentError("Já existe uma conta com este CPF.")
    if plate and db.scalars(select(Vehicle).where(Vehicle.plate == plate)).first():
        raise ResidentError("Esta placa já está cadastrada.")
    user = User(condominium_id=condominium_id, name=name.strip(), email=email, phone=phone,
                cpf=cpf, block=block, unit=unit, password_hash=hash_password(password),
                role=Role.RESIDENT, status=status)  # perfil nunca vem do cliente
    db.add(user)
    db.flush()
    if plate:
        db.add(Vehicle(owner_id=user.id, plate=plate, model=vehicle_model))
    log_action(db, condominium_id=condominium_id, actor_id=actor_id or user.id,
               action="resident.created", entity="user", entity_id=user.id,
               details={"status": status.value, "unit": unit, "block": block})
    return user


_TRANSITIONS = {
    UserStatus.PENDING: {UserStatus.ACTIVE, UserStatus.REJECTED},
    UserStatus.ACTIVE: {UserStatus.INACTIVE},
    UserStatus.INACTIVE: {UserStatus.ACTIVE},
    UserStatus.REJECTED: {UserStatus.ACTIVE},
}


def change_status(db: Session, user: User, new: UserStatus, actor: User) -> User:
    if new not in _TRANSITIONS.get(user.status, set()):
        raise ResidentError(f"Transição inválida: {user.status.value} -> {new.value}.")
    old = user.status
    user.status = new
    log_action(db, condominium_id=user.condominium_id, actor_id=actor.id,
               action="resident.status_changed", entity="user", entity_id=user.id,
               details={"from": old.value, "to": new.value})
    return user
