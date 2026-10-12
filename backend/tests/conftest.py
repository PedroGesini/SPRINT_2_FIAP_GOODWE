import os

os.environ.setdefault("ENVIRONMENT", "test")  # evita criar o banco de desenvolvimento nos testes

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models import (Charger, ChargerStatus, Condominium, Role, Tariff, User,
                        UserStatus)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture()
def world(db):
    condo = Condominium(name="Condomínio Demo")
    db.add(condo)
    db.flush()

    def mk(name, email, role=Role.RESIDENT, status=UserStatus.ACTIVE):
        u = User(condominium_id=condo.id, name=name, email=email, role=role, status=status,
                 password_hash=hash_password("senha-dev-123"))
        db.add(u)
        return u

    syndic = mk("Síndico Demo", "sindico@example.com", Role.SYNDIC)
    ana = mk("Ana Demo", "ana@example.com")
    bruno = mk("Bruno Demo", "bruno@example.com")
    charger = Charger(condominium_id=condo.id, name="Carregador 1", code="CH-01",
                      power_kw=Decimal("7.4"), status=ChargerStatus.AVAILABLE)
    charger2 = Charger(condominium_id=condo.id, name="Carregador 2", code="CH-02",
                       power_kw=Decimal("7.4"), status=ChargerStatus.MAINTENANCE)
    db.add_all([charger, charger2,
                Tariff(condominium_id=condo.id, price_per_kwh=Decimal("0.95"),
                       fixed_fee=Decimal("0.00"))])
    db.commit()
    return dict(condo=condo, syndic=syndic, ana=ana, bruno=bruno, charger=charger,
                maintenance=charger2)
