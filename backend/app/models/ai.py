"""Conversas da assistente e resultados persistidos da IA analítica."""
from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.core import utcnow


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class AIMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(String(30))  # local | externo | erro
    intent: Mapped[str | None] = mapped_column(String(40))
    tools_used: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ConsumptionAnomaly(Base):
    __tablename__ = "consumption_anomalies"
    id: Mapped[int] = mapped_column(primary_key=True)
    condominium_id: Mapped[int] = mapped_column(ForeignKey("condominiums.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("charging_sessions.id"), index=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[float | None] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(10))  # alta | média
    kind: Mapped[str] = mapped_column(String(40))  # modelo | estatístico | sobreposição
    method: Mapped[str] = mapped_column(String(40))
    reasons: Mapped[list] = mapped_column(JSON)
    run_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ConsumptionProfile(Base):
    __tablename__ = "consumption_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    condominium_id: Mapped[int] = mapped_column(ForeignKey("condominiums.id"), index=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(30))
    monthly_kwh: Mapped[float] = mapped_column(Float)
    sessions_per_month: Mapped[float] = mapped_column(Float)
    avg_kwh_session: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(40))
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
