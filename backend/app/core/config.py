"""Configurações lidas de variáveis de ambiente (ver .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "EV ChargeOps"
    environment: str = "development"  # development | production
    database_url: str = "sqlite:///./chargeops_dev.db"
    jwt_secret: str = "troque-esta-chave-em-desenvolvimento"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    cors_origins: str = "http://localhost:5173"
    ai_api_key: str = ""  # vazio => assistente em modo local
    ai_model: str = "claude-sonnet-5-5"  # usado apenas se AI_API_KEY estiver definida
    default_tariff_per_kwh: str = "0.95"
    display_timezone: str = "America/Sao_Paulo"  # fuso usado nos gráficos por horário

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
