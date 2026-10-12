"""Dados FICTÍCIOS para demonstração (nenhuma pessoa ou medição real).

Uso:  python -m app.seed            # cria os dados se ainda não existirem (idempotente)
      python -m app.seed --reset    # apaga TUDO e recria (somente fora de produção)
"""
import argparse
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.models import (AuditLog, Charger, ChargerStatus, ChargingSession, Condominium, Invoice,
                        InvoiceDelivery, InvoiceItem, InvoiceStatus, Notification, Payment, Role,
                        SessionSource, SessionStatus, Tariff, User, UserStatus, Vehicle)
from app.services import billing_service as bs
from app.services.notification_service import send_invoice

DEMO_CONDO = "Residencial Aurora (demonstração)"
SYNDIC_EMAIL, SYNDIC_PASSWORD = "sindico@example.com", "Sindico@2026dev"
RESIDENT_PASSWORD = "Morador@2026dev"
EFFICIENCY = Decimal("0.85")

# nome, e-mail, bloco, unidade, perfil de consumo, veículo
RESIDENTS = [
    ("Ana Souza", "ana.souza@example.com", "A", "101", "moderate", "Nissan Leaf"),
    ("Bruno Lima", "bruno.lima@example.com", "A", "202", "heavy", "BYD Dolphin"),
    ("Carla Mendes", "carla.mendes@example.com", "A", "303", "light", "Renault Kwid E-Tech"),
    ("Diego Ferreira", "diego.ferreira@example.com", "A", "404", "light", None),
    ("Elaine Costa", "elaine.costa@example.com", "B", "101", "moderate", "BYD Dolphin Mini"),
    ("Fábio Rocha", "fabio.rocha@example.com", "B", "202", "moderate", "Volvo EX30"),
    ("Gabriela Alves", "gabriela.alves@example.com", "B", "303", "heavy", "Tesla Model 3"),
    ("Henrique Dias", "henrique.dias@example.com", "B", "404", "moderate", "GWM Ora 03"),
    ("Isabela Martins", "isabela.martins@example.com", "C", "101", "light", "Peugeot e-208"),
    ("João Pereira", "joao.pereira@example.com", "C", "202", "heavy", "BMW iX1"),
    ("Karina Ribeiro", "karina.ribeiro@example.com", "C", "303", "moderate", "JAC E-JS1"),
    ("Lucas Barbosa", "lucas.barbosa@example.com", "C", "404", "light", None),
    ("Marina Teixeira", "marina.teixeira@example.com", "D", "101", "moderate", "Chevrolet Bolt"),
    ("Nelson Araújo", "nelson.araujo@example.com", "D", "202", "light", "Fiat 500e"),
    ("Olívia Nunes", "olivia.nunes@example.com", "D", "303", "heavy", "Mini Cooper SE"),
]
# frequência mensal, kWh médio por recarga, desvio, pesos de horário local (início da recarga)
PROFILES = {
    "light": (3, 13, 4),
    "moderate": (7, 20, 5),
    "heavy": (12, 28, 6),
}
HOURS = list(range(0, 24))
HOUR_WEIGHTS = [2, 1, 1, 1, 1, 2, 4, 6, 5, 3, 2, 2, 3, 3, 2, 2, 3, 6, 12, 14, 12, 9, 6, 3]
# nome, código, potência (kW), local, vaga, status
CHARGERS = [
    ("Carregador 1", "CH-01", "7.4", "Garagem térreo", "V-01", ChargerStatus.AVAILABLE),
    ("Carregador 2", "CH-02", "7.4", "Garagem térreo", "V-02", ChargerStatus.AVAILABLE),
    ("Carregador 3", "CH-03", "11.0", "Garagem subsolo", "V-15", ChargerStatus.AVAILABLE),
    ("Carregador 4", "CH-04", "7.4", "Garagem subsolo", "V-16", ChargerStatus.IN_USE),
    ("Carregador 5", "CH-05", "11.0", "Bloco C", "V-30", ChargerStatus.MAINTENANCE),
    ("Carregador 6", "CH-06", "7.4", "Bloco D", "V-41", ChargerStatus.IN_USE),
]


def _cpf(seed: int) -> str:
    digits = [int(c) for c in f"{(seed * 7919) % 900_000_000 + 100_000_000:09d}"]
    for n in (9, 10):
        total = sum(d * (n + 1 - i) for i, d in enumerate(digits[:n]))
        digits.append((total * 10) % 11 % 10)
    s = "".join(map(str, digits))
    return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"


def _plate(rng: random.Random) -> str:
    L = lambda: rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ")
    return f"{L()}{L()}{L()}{rng.randint(0, 9)}{L()}{rng.randint(0, 9)}{rng.randint(0, 9)}"


def reset_database(db: Session) -> None:
    if get_settings().environment == "production":
        raise RuntimeError("Recusado: --reset não é permitido em produção.")
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(delete(table))
    db.commit()


class _Planner:
    """Aloca sessões sem sobrepor horários no mesmo carregador."""

    def __init__(self, chargers):
        self.chargers = chargers
        self.busy = {c.id: [] for c in chargers}
        self.resident_busy = {}

    def free(self, charger, resident_id, start, end, allow_resident_overlap=False) -> bool:
        if not all(end <= s or start >= e for s, e in self.busy[charger.id]):
            return False
        if allow_resident_overlap:
            return True
        return all(end <= s or start >= e for s, e in self.resident_busy.get(resident_id, []))

    def take(self, charger, resident_id, start, end):
        self.busy[charger.id].append((start, end))
        self.resident_busy.setdefault(resident_id, []).append((start, end))


def run_seed(db: Session, *, seed: int = 42, now: datetime | None = None) -> dict:
    existing = db.scalars(select(Condominium).where(Condominium.name == DEMO_CONDO)).first()
    if existing:
        return {"created": False, "message": "Dados de demonstração já existem (use --reset para recriar)."}

    rng = random.Random(seed)
    tz = ZoneInfo(get_settings().display_timezone)
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(tz)

    condo = Condominium(name=DEMO_CONDO)
    db.add(condo)
    db.flush()
    db.add(Tariff(condominium_id=condo.id, price_per_kwh=Decimal("0.95"), fixed_fee=Decimal("4.90"),
                  valid_from=now - timedelta(days=400)))

    resident_hash = hash_password(RESIDENT_PASSWORD)
    syndic = User(condominium_id=condo.id, name="Roberto Santos (Síndico)", email=SYNDIC_EMAIL,
                  phone="(11) 90000-0001", block="-", unit="Administração", cpf=_cpf(1),
                  password_hash=hash_password(SYNDIC_PASSWORD), role=Role.SYNDIC,
                  status=UserStatus.ACTIVE)
    db.add(syndic)
    residents, profile_of = [], {}
    for i, (name, email, block, unit, profile, car) in enumerate(RESIDENTS, start=2):
        u = User(condominium_id=condo.id, name=name, email=email, phone=f"(11) 9{i:04d}-{i * 37 % 10000:04d}",
                 cpf=_cpf(i), block=block, unit=unit, password_hash=resident_hash,
                 role=Role.RESIDENT, status=UserStatus.ACTIVE)
        db.add(u)
        residents.append(u)
    db.flush()
    vehicles = {}
    for u, (_, _, _, _, profile, car) in zip(residents, RESIDENTS):
        profile_of[u.id] = profile
        if car:
            v = Vehicle(owner_id=u.id, plate=_plate(rng), model=car)
            db.add(v)
            vehicles[u.id] = v
    # cadastros pendentes (para demonstrar a aprovação pelo síndico)
    for j, (name, email) in enumerate([("Paulo Gomes", "paulo.gomes@example.com"),
                                       ("Quitéria Lopes", "quiteria.lopes@example.com")]):
        db.add(User(condominium_id=condo.id, name=name, email=email, block="D", unit=f"40{j + 5}",
                    password_hash=resident_hash, role=Role.RESIDENT, status=UserStatus.PENDING))
    chargers = []
    for name, code, power, loc, spot, status in CHARGERS:
        c = Charger(condominium_id=condo.id, name=name, code=code, manufacturer="GoodWe (demonstração)",
                    model="Equipamento de demonstração", power_kw=Decimal(power), location=loc,
                    parking_spot=spot, connector_type="Tipo 2", status=status,
                    installed_on=date(2025, 3, 1), notes="Dados simulados; sem integração real.",
                    status_updated_at=now - timedelta(hours=rng.randint(1, 48)))
        db.add(c)
        chargers.append(c)
    db.flush()
    by_code = {c.code: c for c in chargers}
    planner = _Planner(chargers)
    price = Decimal("0.95")
    sessions: list[ChargingSession] = []

    def add_session(resident, charger, start, kwh, *, source=SessionSource.SIMULATION,
                    allow_resident_overlap=False):
        kwh = Decimal(kwh).quantize(Decimal("0.001"))
        hours = float(kwh / (charger.power_kw * EFFICIENCY))
        end = start + timedelta(seconds=int(hours * 3600))
        if end >= now - timedelta(minutes=5) or not planner.free(
                charger, resident.id, start, end, allow_resident_overlap):
            return None
        planner.take(charger, resident.id, start, end)
        s = ChargingSession(
            condominium_id=condo.id, resident_id=resident.id,
            vehicle_id=vehicles[resident.id].id if resident.id in vehicles else None,
            charger_id=charger.id, started_at=start, ended_at=end, energy_kwh=kwh,
            tariff_price_per_kwh=price, energy_cost=bs.energy_cost(kwh, price),
            status=SessionStatus.COMPLETED, source=source)
        db.add(s)
        sessions.append(s)
        return s

    # ---- histórico regular: ~5 meses completos + mês atual
    first_month = (local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                   - timedelta(days=180)).replace(day=1)
    month = first_month
    while month <= local_now:
        nxt = (month + timedelta(days=32)).replace(day=1)
        span_end = min(nxt, local_now - timedelta(hours=2))
        days = max((span_end - month).total_seconds() / 86400, 0)
        for r in residents:
            freq, mean, sd = PROFILES[profile_of[r.id]]
            count = max(0, round(rng.gauss(freq, 1.5) * min(days / 30, 1)))
            for _ in range(count):
                for _try in range(12):
                    day_offset = rng.random() * days
                    hour = rng.choices(HOURS, HOUR_WEIGHTS)[0]
                    start_local = (month + timedelta(days=int(day_offset))).replace(
                        hour=hour, minute=rng.randint(0, 59))
                    start = start_local.astimezone(timezone.utc)
                    charger = rng.choice(chargers)
                    if charger.code == "CH-05" and start > now - timedelta(days=35):
                        continue  # em manutenção recentemente
                    kwh = min(max(rng.gauss(mean, sd), 4), 42)
                    if add_session(r, charger, start, kwh,
                                   source=SessionSource.MANUAL if rng.random() < 0.12
                                   else SessionSource.SIMULATION):
                        break
        month = nxt

    # ---- registros atípicos CONTROLADOS (para testar a detecção de anomalias)
    def local_dt(days_ago, hour, minute=0):
        d = (local_now - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return d.astimezone(timezone.utc)

    anomalies = []
    # 1) recarga muito acima do padrão, de madrugada, de um morador de baixo consumo
    for d in range(6, 16):
        if add_session(residents[2], by_code["CH-03"], local_dt(d, 2, 30), "82"):
            anomalies.append("consumo muito alto de madrugada (Carla Mendes)")
            break
    # 2) salto de consumo de um morador moderado nos últimos 30 dias
    placed = 0
    for d in range(2, 28, 4):
        if add_session(residents[7], by_code["CH-01"], local_dt(d, 20, 10), "38"):
            placed += 1
    if placed:
        anomalies.append(f"aumento recente de consumo ({placed} recargas altas - Henrique Dias)")
    # 3) possível duplicidade: duas sessões sobrepostas do mesmo morador em carregadores diferentes
    for d in range(3, 12):
        a = add_session(residents[4], by_code["CH-01"], local_dt(d, 19, 0), "22", allow_resident_overlap=True)
        b = add_session(residents[4], by_code["CH-02"], local_dt(d, 19, 30), "14", allow_resident_overlap=True) if a else None
        if a and b:
            anomalies.append("possível sessão duplicada (Elaine Costa)")
            break

    # ---- sessões em andamento (carregadores "em uso" coerentes)
    for code, resident, mins in (("CH-04", residents[1], 40), ("CH-06", residents[6], 95)):
        s = ChargingSession(
            condominium_id=condo.id, resident_id=resident.id,
            vehicle_id=vehicles[resident.id].id if resident.id in vehicles else None,
            charger_id=by_code[code].id, started_at=now - timedelta(minutes=mins),
            tariff_price_per_kwh=price, status=SessionStatus.IN_PROGRESS,
            source=SessionSource.SIMULATION)
        db.add(s)
    db.flush()

    # ---- faturas dos meses encerrados, pagamentos e envios
    current_start = local_now.replace(day=1).date()
    billed = 0
    for k in range(6, 0, -1):  # k = meses atrás
        ms = (current_start - timedelta(days=1 + 31 * (k - 1))).replace(day=1)
        me = ((ms + timedelta(days=32)).replace(day=1)) - timedelta(days=1)
        for r in residents:
            try:
                inv = bs.generate_invoice(db, resident=r, period_start=ms, period_end=me, actor=syndic,
                                          shared_total=Decimal("0"), due_in_days=10)
            except bs.BillingError:
                continue
            inv.issued_at = me + timedelta(days=1)
            inv.due_date = inv.issued_at + timedelta(days=10)
            db.flush()
            billed += 1
            paid_prob = 0.93 if k >= 3 else 0.8 if k == 2 else 0.45
            roll = rng.random()
            issued_dt = datetime.combine(inv.issued_at, datetime.min.time(), tzinfo=timezone.utc)
            if roll < paid_prob:
                p = bs.register_payment(db, inv, inv.total_amount, syndic)
                p.paid_at = issued_dt + timedelta(days=rng.randint(1, 9), hours=rng.randint(8, 20))
            elif roll < paid_prob + 0.05 and k <= 2:
                half = bs.money(Decimal(inv.total_amount) / 2)
                p = bs.register_payment(db, inv, half, syndic)  # pagamento parcial
                p.paid_at = issued_dt + timedelta(days=4)
            if inv.status != InvoiceStatus.PAID and rng.random() < 0.8:
                send_invoice(db, inv, syndic)
                if inv.status == InvoiceStatus.ISSUED:
                    inv.status = InvoiceStatus.PENDING
            db.flush()
    bs.refresh_overdue(db, condo.id)
    db.commit()
    return {"created": True, "residents": len(residents), "chargers": len(chargers),
            "sessions": len(sessions) + 2, "invoices": billed, "anomalies": anomalies}


def main() -> None:
    from app.db.session import SessionLocal, engine
    import app.models  # noqa: F401

    parser = argparse.ArgumentParser(description="Popula o banco com dados fictícios de demonstração.")
    parser.add_argument("--reset", action="store_true", help="apaga todos os dados antes de recriar")
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if args.reset:
            reset_database(db)
        result = run_seed(db)
    print(result)
    if result.get("created"):
        print(f"\nSíndico:  {SYNDIC_EMAIL} / {SYNDIC_PASSWORD}")
        print(f"Moradores: ana.souza@example.com e bruno.lima@example.com / {RESIDENT_PASSWORD}")
        print("Senhas EXCLUSIVAS de desenvolvimento: altere antes de qualquer uso real.")


if __name__ == "__main__":
    main()
