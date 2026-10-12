"""Repara apenas o login das contas fictícias do EV ChargeOps.

Uso: copie para backend/ (ou backend/tests/) e rode:
    python corrigir_login_chargeops.py
ou, se estiver em backend/tests/:
    python tests/corrigir_login_chargeops.py

Não elimina dados. Aceita somente banco SQLite e ambiente development.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def localizar_backend() -> Path:
    atual = Path(__file__).resolve()
    for pasta in atual.parents:
        if (pasta / "app" / "main.py").is_file():
            return pasta
    raise SystemExit("ERRO: não encontrei backend/app/main.py. Coloque o arquivo dentro de backend ou backend/tests.")


def main() -> None:
    backend = localizar_backend()
    os.chdir(backend)  # SQLite e .env do projeto são relativos à pasta backend
    sys.path.insert(0, str(backend))

    from sqlalchemy import select
    from app.core.config import get_settings
    from app.core.security import hash_password, verify_password
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    import app.models  # noqa: F401: registrar modelos
    from app.models import Condominium, Role, User, UserStatus
    from app.seed import DEMO_CONDO, SYNDIC_EMAIL, SYNDIC_PASSWORD, RESIDENT_PASSWORD, run_seed

    settings = get_settings()
    if settings.environment != "development":
        raise SystemExit("BLOQUEADO: correção permitida somente com ENVIRONMENT=development.")
    if engine.url.get_backend_name() != "sqlite":
        raise SystemExit("BLOQUEADO: este utilitário aceita somente SQLite local.")
    db_name = engine.url.database
    if not db_name or db_name == ":memory:":
        raise SystemExit("BLOQUEADO: banco de dados SQLite em memória não é suportado.")
    db_path = Path(db_name).resolve()
    print("Backend:", backend)
    print("Banco utilizado:", db_path)
    if db_path.is_file():
        backup = db_path.with_name(f"{db_path.stem}-backup-login-{datetime.now():%Y%m%d-%H%M%S}{db_path.suffix}")
        with sqlite3.connect(str(db_path)) as src, sqlite3.connect(str(backup)) as dest:
            src.backup(dest)
        print("Backup criado:", backup)
    else:
        print("Banco inexistente. Os dados fictícios serão inicializados sem sobrescrever outros bancos.")

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        condominio = db.scalar(select(Condominium).where(Condominium.name == DEMO_CONDO))
        if condominio is None:
            result = run_seed(db)
            print("Dados de demonstração:", result)
            condominio = db.scalar(select(Condominium).where(Condominium.name == DEMO_CONDO))
        if condominio is None:
            raise SystemExit("ERRO: condomínio de demonstração não encontrado.")

        credenciais = (
            (SYNDIC_EMAIL, SYNDIC_PASSWORD, Role.SYNDIC),
            ("ana.souza@example.com", RESIDENT_PASSWORD, Role.RESIDENT),
            ("bruno.lima@example.com", RESIDENT_PASSWORD, Role.RESIDENT),
        )
        modificados = []
        for email, senha, papel in credenciais:
            usuario = db.scalar(select(User).where(
                User.email == email, User.condominium_id == condominio.id
            ))
            if usuario is None:
                print("Conta não encontrada:", email)
                continue
            if usuario.role != papel:
                raise SystemExit(f"BLOQUEADO: papel inesperado para {email}; nenhuma alteração será confirmada.")
            if usuario.status != UserStatus.ACTIVE:
                print(f"AVISO: {email} está com status {usuario.status}; a senha não altera o status.")
            usuario.password_hash = hash_password(senha)
            modificados.append((usuario, email, senha))
        if not modificados:
            raise SystemExit("ERRO: não encontrei nenhuma conta de demonstração para corrigir.")
        db.commit()
        for usuario, email, senha in modificados:
            db.refresh(usuario)
            if not verify_password(senha, usuario.password_hash):
                raise SystemExit(f"ERRO: verificação da senha falhou para {email}.")
            print("OK: credencial conferida:", email)

    print("Concluído: outras contas, carregadores, recargas e faturas foram preservados.")
    print("Aguarde um minuto se houve HTTP 429, inicie o backend desta pasta e tente login novamente.")


if __name__ == "__main__":
    main()
