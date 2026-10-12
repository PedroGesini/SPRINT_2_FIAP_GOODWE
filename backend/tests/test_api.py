from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core import rate_limit
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models import Charger, Condominium, Role, User, UserStatus, Tariff

PWD = "senha-dev-123"
CPF_OK = "529.982.247-25"


@pytest.fixture()
def client(db, world):
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    def _get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    rate_limit.reset()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login(client, email, password=PWD):
    r = client.post("/api/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def syndic_h(client):
    return login(client, "sindico@example.com")


@pytest.fixture()
def ana_h(client):
    return login(client, "ana@example.com")


@pytest.fixture()
def bruno_h(client):
    return login(client, "bruno@example.com")


T0 = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)


def manual_session(client, h, world, resident_key, kwh="20", start=T0):
    return client.post("/api/sessions/manual", headers=h, json={
        "resident_id": world[resident_key].id, "charger_id": world["charger"].id,
        "started_at": start.isoformat(), "ended_at": (start + timedelta(hours=2)).isoformat(),
        "energy_kwh": kwh})


# ---------------------------------------------------------------- cadastro e login
def test_cadastro_publico_cria_morador_pendente(client):
    r = client.post("/api/auth/register", json={
        "name": "Carla Teste", "email": "carla@example.com", "cpf": CPF_OK, "block": "A",
        "unit": "101", "password": PWD, "password_confirm": PWD, "plate": "ABC1D23",
        "role": "syndic"})  # tentativa de escolher perfil deve ser ignorada
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "resident" and body["status"] == "pending"
    assert body["cpf_masked"] == "***.***.***-25" and "cpf" not in body


def test_cadastro_rejeita_email_duplicado_senha_e_cpf_invalidos(client):
    base = {"name": "Dani Teste", "email": "dani@example.com", "password": PWD, "password_confirm": PWD}
    assert client.post("/api/auth/register", json=base).status_code == 201
    assert client.post("/api/auth/register", json=base).status_code == 409
    assert client.post("/api/auth/register", json={**base, "email": "x@example.com",
                                                   "password_confirm": "outra-senha"}).status_code == 422
    assert client.post("/api/auth/register", json={**base, "email": "y@example.com",
                                                   "cpf": "111.111.111-11"}).status_code == 422


def test_login_ok_erro_e_pendente(client):
    client.post("/api/auth/register", json={"name": "Eva Teste", "email": "eva@example.com",
                                            "password": PWD, "password_confirm": PWD})
    assert client.post("/api/auth/login", data={"username": "ana@example.com", "password": "errada"}).status_code == 401
    assert client.post("/api/auth/login", data={"username": "eva@example.com", "password": PWD}).status_code == 403
    h = login(client, "ana@example.com")
    assert client.get("/api/auth/me", headers=h).json()["email"] == "ana@example.com"


def test_rota_protegida_exige_token(client):
    assert client.get("/api/chargers").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer lixo"}).status_code == 401


def test_limite_de_tentativas_de_login(client):
    for _ in range(8):
        client.post("/api/auth/login", data={"username": "ana@example.com", "password": "x"})
    assert client.post("/api/auth/login", data={"username": "ana@example.com", "password": PWD}).status_code == 429


# ---------------------------------------------------------------- permissões
def test_morador_nao_lista_moradores_mas_sindico_sim(client, ana_h, syndic_h):
    assert client.get("/api/residents", headers=ana_h).status_code == 403
    r = client.get("/api/residents", headers=syndic_h)
    assert r.status_code == 200 and r.json()["total"] == 2


def test_sindico_aprova_cadastro_pendente(client, syndic_h):
    reg = client.post("/api/auth/register", json={"name": "Fábio Teste", "email": "fabio@example.com",
                                                  "password": PWD, "password_confirm": PWD}).json()
    assert client.post(f"/api/residents/{reg['id']}/approve", headers=syndic_h).json()["status"] == "active"
    login(client, "fabio@example.com")
    # transição inválida
    assert client.post(f"/api/residents/{reg['id']}/approve", headers=syndic_h).status_code == 409


def test_morador_nao_acessa_dados_de_outro_morador(client, world, syndic_h, ana_h, bruno_h):
    assert manual_session(client, syndic_h, world, "ana").status_code == 201
    inv = client.post("/api/invoices/generate", headers=syndic_h, json={
        "resident_id": world["ana"].id, "period_start": "2026-09-01", "period_end": "2026-09-30"}).json()
    sess_id = client.get("/api/sessions", headers=ana_h).json()["items"][0]["id"]
    # a dona acessa
    assert client.get(f"/api/invoices/{inv['id']}", headers=ana_h).status_code == 200
    assert client.get(f"/api/sessions/{sess_id}", headers=ana_h).status_code == 200
    # outro morador, alterando IDs na URL
    assert client.get(f"/api/invoices/{inv['id']}", headers=bruno_h).status_code == 404
    assert client.get(f"/api/sessions/{sess_id}", headers=bruno_h).status_code == 404
    assert client.get(f"/api/residents/{world['ana'].id}", headers=bruno_h).status_code == 404
    # listagens do outro morador vêm vazias, mesmo pedindo o resident_id da Ana
    assert client.get(f"/api/invoices?resident_id={world['ana'].id}", headers=bruno_h).json()["total"] == 0
    assert client.get(f"/api/sessions?resident_id={world['ana'].id}", headers=bruno_h).json()["total"] == 0


def test_isolamento_entre_condominios(client, db, world, syndic_h):
    other = Condominium(name="Outro Condomínio")
    db.add(other)
    db.flush()
    db.add(User(condominium_id=other.id, name="Síndico Outro", email="outro@example.com",
                role=Role.SYNDIC, status=UserStatus.ACTIVE, password_hash=hash_password(PWD)))
    db.commit()
    other_h = login(client, "outro@example.com")
    assert client.get(f"/api/residents/{world['ana'].id}", headers=other_h).status_code == 404
    assert client.get(f"/api/chargers/{world['charger'].id}", headers=other_h).status_code == 404
    assert client.get("/api/residents", headers=other_h).json()["total"] == 0


# ---------------------------------------------------------------- carregadores
def test_sindico_cria_carregador_e_morador_nao(client, syndic_h, ana_h):
    payload = {"name": "Carregador 3", "code": "CH-03", "power_kw": "11", "notes": "interno"}
    assert client.post("/api/chargers", headers=ana_h, json=payload).status_code == 403
    r = client.post("/api/chargers", headers=syndic_h, json=payload)
    assert r.status_code == 201 and r.json()["status"] == "available"
    assert client.post("/api/chargers", headers=syndic_h, json=payload).status_code == 409


def test_morador_ve_apenas_campos_publicos_do_carregador(client, world, ana_h, syndic_h):
    pub = client.get(f"/api/chargers/{world['charger'].id}", headers=ana_h).json()
    assert "notes" not in pub and "manufacturer" not in pub
    full = client.get(f"/api/chargers/{world['charger'].id}", headers=syndic_h).json()
    assert "notes" in full
    av = client.get("/api/chargers/availability", headers=ana_h).json()
    assert av["counts"]["available"] == 1 and av["counts"]["maintenance"] == 1


def test_status_em_uso_nao_pode_ser_manual(client, world, syndic_h):
    r = client.post(f"/api/chargers/{world['charger'].id}/status", headers=syndic_h, json={"status": "in_use"})
    assert r.status_code == 409


# ---------------------------------------------------------------- sessões
def test_fluxo_simulado_morador_inicia_e_encerra(client, world, ana_h, syndic_h):
    s = client.post("/api/sessions/start", headers=ana_h, json={"charger_id": world["charger"].id})
    assert s.status_code == 201, s.text
    status = client.get(f"/api/chargers/{world['charger'].id}", headers=ana_h).json()["status"]
    assert status == "in_use"
    assert client.post("/api/sessions/start", headers=syndic_h, json={
        "charger_id": world["charger"].id, "resident_id": world["bruno"].id}).status_code == 409
    # morador não pode digitar o próprio consumo
    assert client.post(f"/api/sessions/{s.json()['id']}/end", headers=ana_h,
                       json={"energy_kwh": "1"}).status_code == 403
    done = client.post(f"/api/sessions/{s.json()['id']}/end", headers=ana_h,
                       json={"simulated_duration_minutes": 120})
    assert done.status_code == 200, done.text
    body = done.json()
    # 7,4 kW x 2 h x 0,85 = 12,580 kWh (consumo fictício) x R$ 0,95 = R$ 11,95
    assert body["energy_kwh"] == "12.580" and body["energy_cost"] == "11.95"
    assert body["source"] == "simulation" and body["status"] == "completed"
    assert client.get(f"/api/chargers/{world['charger'].id}", headers=ana_h).json()["status"] == "available"
    assert client.post(f"/api/sessions/{s.json()['id']}/end", headers=syndic_h,
                       json={"energy_kwh": "5"}).status_code == 409


def test_sessao_manual_calcula_custo_e_bloqueia_conflito(client, world, syndic_h):
    r = manual_session(client, syndic_h, world, "ana", "20")
    assert r.status_code == 201 and r.json()["energy_cost"] == "19.00"
    overlap = manual_session(client, syndic_h, world, "bruno", "5", start=T0 + timedelta(minutes=30))
    assert overlap.status_code == 409


def test_sessao_manual_por_leituras_do_medidor(client, world, syndic_h):
    r = client.post("/api/sessions/manual", headers=syndic_h, json={
        "resident_id": world["ana"].id, "charger_id": world["charger"].id,
        "started_at": T0.isoformat(), "ended_at": (T0 + timedelta(hours=1)).isoformat(),
        "start_reading_kwh": "100.5", "end_reading_kwh": "120.5"})
    assert r.status_code == 201 and r.json()["energy_kwh"] == "20.000"


def test_exportacao_csv_so_para_sindico(client, world, syndic_h, ana_h):
    manual_session(client, syndic_h, world, "ana")
    assert client.get("/api/sessions/export.csv", headers=ana_h).status_code == 403
    r = client.get("/api/sessions/export.csv", headers=syndic_h)
    assert r.status_code == 200 and "Ana Demo" in r.text and "kwh" in r.text


# ---------------------------------------------------------------- faturas
def _invoice(client, h, world, key="ana"):
    return client.post("/api/invoices/generate", headers=h, json={
        "resident_id": world[key].id, "period_start": "2026-09-01", "period_end": "2026-09-30"})


def test_fatura_pagamento_simulado_e_duplicidade(client, world, syndic_h, ana_h):
    manual_session(client, syndic_h, world, "ana", "20")
    r = _invoice(client, syndic_h, world)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["total_amount"] == "19.00" and inv["status"] == "issued" and len(inv["items"]) == 1
    assert _invoice(client, syndic_h, world).status_code == 409  # duplicada
    assert client.post(f"/api/invoices/{inv['id']}/payments", headers=ana_h,
                       json={"amount": "19.00"}).status_code == 403
    assert client.post(f"/api/invoices/{inv['id']}/payments", headers=syndic_h,
                       json={"amount": "50.00"}).status_code == 409  # maior que o saldo
    p = client.post(f"/api/invoices/{inv['id']}/payments", headers=syndic_h, json={"amount": "19.00"})
    assert p.status_code == 201 and p.json()["simulated"] is True
    paid = client.get(f"/api/invoices/{inv['id']}", headers=ana_h).json()
    assert paid["status"] == "paid" and paid["balance"] == "0.00"


def test_cancelar_exige_justificativa_e_permite_nova_versao(client, world, syndic_h):
    manual_session(client, syndic_h, world, "ana", "20")
    inv = _invoice(client, syndic_h, world).json()
    assert client.post(f"/api/invoices/{inv['id']}/cancel", headers=syndic_h,
                       json={"reason": "x"}).status_code == 422
    c = client.post(f"/api/invoices/{inv['id']}/cancel", headers=syndic_h,
                    json={"reason": "Erro na tarifa aplicada"})
    assert c.status_code == 200 and c.json()["status"] == "cancelled"
    new = _invoice(client, syndic_h, world)
    assert new.status_code == 201 and new.json()["version"] == 2


def test_envio_registra_historico_simulado_e_notificacao(client, db, world, syndic_h, ana_h):
    manual_session(client, syndic_h, world, "ana")
    inv = _invoice(client, syndic_h, world).json()
    assert client.post(f"/api/invoices/{inv['id']}/send", headers=ana_h).status_code == 403
    sent = client.post(f"/api/invoices/{inv['id']}/send", headers=syndic_h)
    assert sent.status_code == 201
    status_by_channel = {d["channel"]: d["status"] for d in sent.json()}
    assert status_by_channel == {"in_app": "sent", "email_simulated": "simulated"}
    assert len(client.get(f"/api/invoices/{inv['id']}/deliveries", headers=syndic_h).json()) == 2


def test_gerar_faturas_do_periodo_informa_ignorados(client, world, syndic_h):
    manual_session(client, syndic_h, world, "ana")
    r = client.post("/api/invoices/generate-period", headers=syndic_h,
                    json={"period_start": "2026-09-01", "period_end": "2026-09-30"}).json()
    assert len(r["created_invoice_ids"]) == 1
    assert [s["resident_id"] for s in r["skipped"]] == [world["bruno"].id]


def test_fatura_vencida_e_marcada_na_listagem(client, db, world, syndic_h, ana_h):
    from app.models import Invoice
    manual_session(client, syndic_h, world, "ana")
    inv = _invoice(client, syndic_h, world).json()
    row = db.get(Invoice, inv["id"])
    row.due_date = datetime.now(timezone.utc).date() - timedelta(days=3)
    db.commit()
    items = client.get("/api/invoices", headers=ana_h).json()["items"]
    assert items[0]["status"] == "overdue"
