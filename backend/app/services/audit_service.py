from sqlalchemy.orm import Session

from app.models import AuditLog

_FORBIDDEN = {"password", "password_hash", "token", "cpf"}


def log_action(db: Session, *, condominium_id: int | None, actor_id: int | None,
               action: str, entity: str, entity_id: int | None = None,
               details: dict | None = None) -> AuditLog:
    safe = {k: v for k, v in (details or {}).items() if k.lower() not in _FORBIDDEN}
    entry = AuditLog(condominium_id=condominium_id, actor_id=actor_id, action=action,
                     entity=entity, entity_id=entity_id, details=safe or None)
    db.add(entry)
    return entry
