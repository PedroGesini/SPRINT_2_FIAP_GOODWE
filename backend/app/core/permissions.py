"""Autenticação e autorização aplicadas no backend (não apenas no frontend)."""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Role, User, UserStatus

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
STAFF_ROLES = (Role.SYNDIC, Role.PLATFORM_ADMIN)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_access_token(token)
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas ou expiradas.",
                                 headers={"WWW-Authenticate": "Bearer"})
    if not payload:
        raise unauthorized
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise unauthorized
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Conta inativa ou pendente de aprovação.")
    return user


def require_staff(user: User = Depends(get_current_user)) -> User:
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito ao síndico.")
    return user


def is_staff(user: User) -> bool:
    return user.role in STAFF_ROLES
