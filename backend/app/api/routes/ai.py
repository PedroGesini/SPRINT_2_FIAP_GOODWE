import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.assistant import MODE_LABELS, answer_question, suggestions_for
from app.ai.copilot import handle_copilot
from app.ai.forecasting import forecast_consumption
from app.ai.providers import ExternalProvider
from app.core.config import get_settings
from app.core.permissions import get_current_user, require_staff
from app.db.session import get_db
from app.models import AIConversation, AIMessage, User
from app.models.core import utcnow
from app.services import analysis_service

router = APIRouter(prefix="/ai", tags=["Inteligência artificial"])
log = logging.getLogger("chargeops.ai")
MODE_LABELS["erro"] = "Falha ao consultar os dados; tente novamente"


def get_ai_provider() -> ExternalProvider | None:
    s = get_settings()
    return ExternalProvider(s.ai_api_key, s.ai_model) if s.ai_api_key else None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    conversation_id: int | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A mensagem não pode ficar em branco.")
        return v.strip()


def _own_conversation(db: Session, user: User, conv_id: int) -> AIConversation:
    conv = db.get(AIConversation, conv_id)
    if conv is None or conv.user_id != user.id:  # nem o síndico lê conversas de outros
        raise HTTPException(404, "Conversa não encontrada.")
    return conv


def _message_out(m: AIMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "mode": m.mode,
            "mode_label": MODE_LABELS.get(m.mode) if m.mode else None, "intent": m.intent,
            "tools_used": m.tools_used or [], "created_at": m.created_at}


@router.post("/chat")
def chat(data: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
         provider: ExternalProvider | None = Depends(get_ai_provider)):
    conv = _own_conversation(db, user, data.conversation_id) if data.conversation_id else None
    if conv is None:
        conv = AIConversation(user_id=user.id, title=data.message[:60])
        db.add(conv)
        db.flush()
    db.add(AIMessage(conversation_id=conv.id, role="user", content=data.message))
    try:
        reply = answer_question(db, user, data.message, provider)
    except Exception:  # falha inesperada: a conversa continua e o erro não vaza detalhes
        log.exception("Falha na assistente")
        db.rollback()
        reply = {"answer": "Não consegui consultar os dados agora. Tente novamente em instantes.",
                 "intent": "erro", "tools_used": [], "mode": "erro", "mode_label": MODE_LABELS["erro"],
                 "suggestions": suggestions_for(user)[:4], "data": None}
        conv = db.get(AIConversation, conv.id) or conv
    msg = AIMessage(conversation_id=conv.id, role="assistant", content=reply["answer"], mode=reply["mode"],
                    intent=reply["intent"], tools_used=reply["tools_used"])
    db.add(msg)
    conv.updated_at = utcnow()
    db.commit()
    return {"conversation_id": conv.id, "message": _message_out(msg), "answer": reply["answer"],
            "mode": reply["mode"], "mode_label": reply["mode_label"], "intent": reply["intent"],
            "tools_used": reply["tools_used"], "suggestions": reply["suggestions"]}


@router.get("/suggestions")
def suggestions(user: User = Depends(get_current_user)):
    return {"suggestions": suggestions_for(user)}


@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AIConversation).where(AIConversation.user_id == user.id)
                      .order_by(AIConversation.updated_at.desc())).all()
    return [{"id": c.id, "title": c.title, "created_at": c.created_at, "updated_at": c.updated_at} for c in rows]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _own_conversation(db, user, conversation_id)
    msgs = db.scalars(select(AIMessage).where(AIMessage.conversation_id == conv.id)
                      .order_by(AIMessage.id)).all()
    return {"id": conv.id, "title": conv.title, "messages": [_message_out(m) for m in msgs]}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _own_conversation(db, user, conversation_id)
    db.execute(delete(AIMessage).where(AIMessage.conversation_id == conv.id))
    db.delete(conv)
    db.commit()
    return Response(status_code=204)


@router.delete("/conversations", status_code=204)
def clear_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = db.scalars(select(AIConversation.id).where(AIConversation.user_id == user.id)).all()
    if ids:
        db.execute(delete(AIMessage).where(AIMessage.conversation_id.in_(ids)))
        db.execute(delete(AIConversation).where(AIConversation.id.in_(ids)))
        db.commit()
    return Response(status_code=204)



# ------------------------------------------------------------------ Copiloto operacional
class CopilotAction(BaseModel):
    action: Literal["set_charger_status", "start_session", "end_session"]
    charger_id: int = Field(gt=0)
    session_id: int | None = Field(default=None, gt=0)
    status: Literal["available", "maintenance", "unavailable", "in_progress", "completed"]


@router.post("/copilot/chat")
def copilot_chat(data: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 provider: ExternalProvider | None = Depends(get_ai_provider)):
    """Respostas estruturadas: texto, KPIs, gráficos e proposta sem executar escrita."""
    conv = _own_conversation(db, user, data.conversation_id) if data.conversation_id else None
    if conv is None:
        conv = AIConversation(user_id=user.id, title=data.message[:60])
        db.add(conv)
        db.flush()
    response = handle_copilot(db, user, data.message, provider)
    db.add(AIMessage(conversation_id=conv.id, role="user", content=data.message))
    msg = AIMessage(conversation_id=conv.id, role="assistant", content=response["answer"],
                    mode=response["mode"], intent="copilot", tools_used=response["sources"])
    db.add(msg)
    conv.updated_at = utcnow()
    db.commit()
    return {**response, "conversation_id": conv.id, "message": _message_out(msg),
            "suggestions": suggestions_for(user)[:5]}


@router.post("/copilot/execute")
def copilot_execute(data: CopilotAction, staff: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Exige confirmação no frontend e revalida permissões + carregador e estado no backend."""
    from app.api.routes.chargers import set_status
    from app.schemas.charger import ChargerStatusIn
    from app.models import ChargerStatus
    from app.api.deps import charger_in_scope, session_in_scope
    from app.api.routes import sessions
    from app.schemas.session import SessionStartIn, SessionEndIn
    from app.core.permissions import is_staff

    charger = charger_in_scope(db, staff, data.charger_id)
    if data.action == "set_charger_status":
        if not is_staff(staff):
            raise HTTPException(403, "Somente o síndico pode alterar o status.")
        if data.status not in ("available", "maintenance", "unavailable"):
            raise HTTPException(422, "Status inválido para alteração de carregador.")
        updated = set_status(charger.id, ChargerStatusIn(status=ChargerStatus(data.status)), staff, db)
        return {"success": True, "charger_id": updated.id, "charger_code": updated.code,
                "status": updated.status.value, "message": f"Status simulado de {updated.code} atualizado com sucesso."}
    if data.action == "start_session":
        if is_staff(staff):
            raise HTTPException(403, "Inicie recargas administrativas pela tela de recargas informando um morador.")
        if data.status != "in_progress":
            raise HTTPException(422, "Status inválido para iniciar a recarga.")
        started = sessions.start(SessionStartIn(charger_id=charger.id), staff, db)
        return {"success": True, "charger_id": charger.id, "charger_code": charger.code,
                "status": started.status.value, "message": f"Recarga simulada #{started.id} iniciada no {charger.code}."}
    if data.action == "end_session":
        if data.status != "completed":
            raise HTTPException(422, "Status inválido para encerrar a recarga.")
        if not data.session_id:
            raise HTTPException(422, "Informe session_id.")
        s = session_in_scope(db, staff, data.session_id)
        if s.charger_id != charger.id:
            raise HTTPException(422, "A sessão informada não pertence ao carregador selecionado.")
        completed = sessions.end(s.id, SessionEndIn(), staff, db)
        return {"success": True, "charger_id": charger.id, "charger_code": charger.code,
                "status": completed.status.value, "message": f"Sessão simulada #{completed.id} encerrada com sucesso."}
    raise HTTPException(422, "Ação inválida.")


# ------------------------------------------------------------------ análises (somente síndico)
@router.post("/analysis/run")
def run_analysis(staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Executa anomalias + perfis e persiste os resultados."""
    result = analysis_service.run_and_store(db, staff.condominium_id, staff)
    db.commit()
    return result


@router.get("/anomalies")
def anomalies(refresh: bool = False, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    if not refresh:
        stored = analysis_service.stored_anomalies(db, staff.condominium_id)
        if stored:
            return stored
    result = analysis_service.run_and_store(db, staff.condominium_id, staff)
    db.commit()
    return {**result["anomalies"], "source": "recalculado"}


@router.get("/profiles")
def profiles(refresh: bool = False, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    if not refresh:
        stored = analysis_service.stored_profiles(db, staff.condominium_id)
        if stored:
            return stored
    result = analysis_service.run_and_store(db, staff.condominium_id, staff)
    db.commit()
    return {**result["profiles"], "source": "recalculado"}


@router.get("/forecast")
def forecast(staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    return forecast_consumption(db, staff.condominium_id)
