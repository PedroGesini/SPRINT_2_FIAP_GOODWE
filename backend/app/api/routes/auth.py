from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.permissions import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models import Condominium, User, UserStatus
from app.schemas.common import Message
from app.schemas.user import RegisterIn, UserOut, to_user_out
from app.services.resident_service import create_resident

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    """Cadastro público: cria SEMPRE um morador com status pendente de aprovação."""
    condo_id = data.condominium_id or db.scalars(select(Condominium.id).order_by(Condominium.id)).first()
    if condo_id is None or db.get(Condominium, condo_id) is None:
        raise HTTPException(400, "Condomínio não encontrado.")
    user = create_resident(db, condominium_id=condo_id, name=data.name, email=data.email,
                           password=data.password, phone=data.phone, cpf=data.cpf,
                           block=data.block, unit=data.unit, plate=data.plate,
                           vehicle_model=data.vehicle_model, status=UserStatus.PENDING)
    db.commit()
    return to_user_out(user)


@router.post("/login")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '-'}:{form.username.lower()}"
    if rate_limit.is_blocked(key):
        raise HTTPException(429, "Muitas tentativas. Aguarde um minuto e tente novamente.")
    user = db.scalars(select(User).where(User.email == form.username.strip().lower())).first()
    if user is None or not verify_password(form.password, user.password_hash):
        rate_limit.register_failure(key)
        raise HTTPException(401, "E-mail ou senha incorretos.")
    if user.status == UserStatus.PENDING:
        raise HTTPException(403, "Seu cadastro ainda aguarda aprovação do síndico.")
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(403, "Conta inativa. Procure o síndico.")
    return {"access_token": create_access_token(user.id, user.role.value),
            "token_type": "bearer", "role": user.role.value, "user": to_user_out(user)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return to_user_out(user)


@router.post("/logout", response_model=Message)
def logout(_: User = Depends(get_current_user)):
    """JWT sem estado: o cliente descarta o token. (Lista de revogação fica como melhoria.)"""
    return Message(detail="Sessão encerrada. Descarte o token no cliente.")


@router.post("/forgot-password", response_model=Message)
def forgot_password():
    return Message(detail="SIMULAÇÃO: nenhum e-mail foi enviado. Em produção, um link de "
                          "redefinição seria enviado ao endereço informado.")
