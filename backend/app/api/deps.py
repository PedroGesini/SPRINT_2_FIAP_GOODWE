"""Helpers de escopo: tudo é filtrado pelo condomínio e, para moradores, pelo próprio id."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import is_staff
from app.models import Charger, ChargingSession, Invoice, Role, User

NOT_FOUND = HTTPException(404, "Registro não encontrado.")


def resident_in_scope(db: Session, current: User, resident_id: int) -> User:
    target = db.get(User, resident_id)
    if target is None or target.condominium_id != current.condominium_id or target.role != Role.RESIDENT:
        raise NOT_FOUND
    if not is_staff(current) and target.id != current.id:
        raise NOT_FOUND  # 404 (e não 403) para não revelar a existência de outros moradores
    return target


def charger_in_scope(db: Session, current: User, charger_id: int) -> Charger:
    c = db.get(Charger, charger_id)
    if c is None or c.condominium_id != current.condominium_id:
        raise NOT_FOUND
    return c


def session_in_scope(db: Session, current: User, session_id: int) -> ChargingSession:
    s = db.get(ChargingSession, session_id)
    if s is None or s.condominium_id != current.condominium_id:
        raise NOT_FOUND
    if not is_staff(current) and s.resident_id != current.id:
        raise NOT_FOUND
    return s


def invoice_in_scope(db: Session, current: User, invoice_id: int) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None or inv.condominium_id != current.condominium_id:
        raise NOT_FOUND
    if not is_staff(current) and inv.resident_id != current.id:
        raise NOT_FOUND
    return inv
