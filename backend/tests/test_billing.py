from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import ChargerStatus, InvoiceItemKind, SessionStatus, Tariff
from app.services import billing_service as bs
from app.services import charging_service as cs

T0 = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)


def _charge(db, w, resident, kwh, start=T0, hours=2):
    s = cs.start_session(db, charger=w["charger"], resident=resident, actor=w["syndic"],
                         started_at=start)
    cs.end_session(db, session=s, actor=w["syndic"], energy_kwh=Decimal(kwh),
                   ended_at=start + timedelta(hours=hours))
    db.commit()
    return s


def test_consumption_from_readings():
    assert bs.consumption_from_readings(Decimal("100.5"), Decimal("120.5")) == Decimal("20.000")


def test_reading_final_menor_que_inicial_falha():
    with pytest.raises(bs.BillingError):
        bs.consumption_from_readings(Decimal("50"), Decimal("40"))


def test_energy_cost_exemplo_do_enunciado():
    assert bs.energy_cost(Decimal("20"), Decimal("0.95")) == Decimal("19.00")


def test_arredondamento_decimal_sem_erro_de_float():
    assert bs.energy_cost(Decimal("1.005"), Decimal("1.00")) == Decimal("1.01")


def test_rateio_proporcional_ao_consumo():
    assert bs.allocate_shared_cost(Decimal("100"), Decimal("25"), Decimal("100")) == Decimal("25.00")
    assert bs.allocate_shared_cost(Decimal("100"), Decimal("0"), Decimal("0")) == Decimal("0.00")


def test_ajuste_exige_justificativa():
    with pytest.raises(bs.BillingError):
        bs.build_breakdown([], adjustments=[("  ", Decimal("5"))])


def test_sessao_calcula_custo_com_tarifa_congelada(db, world):
    s = _charge(db, world, world["ana"], "20")
    assert s.energy_cost == Decimal("19.00")
    # mudar a tarifa depois não altera a sessão antiga
    db.add(Tariff(condominium_id=world["condo"].id, price_per_kwh=Decimal("2.00"),
                  valid_from=T0 + timedelta(days=30)))
    db.commit()
    db.refresh(s)
    assert s.tariff_price_per_kwh == Decimal("0.95")
    assert s.energy_cost == Decimal("19.00")


def test_carregador_ocupado_e_status_coerente(db, world):
    s = cs.start_session(db, charger=world["charger"], resident=world["ana"],
                         actor=world["syndic"], started_at=T0)
    assert world["charger"].status == ChargerStatus.IN_USE
    with pytest.raises(cs.ChargingError):
        cs.start_session(db, charger=world["charger"], resident=world["bruno"],
                         actor=world["syndic"])
    cs.end_session(db, session=s, actor=world["syndic"], energy_kwh=Decimal("5"),
                   ended_at=T0 + timedelta(hours=1))
    assert world["charger"].status == ChargerStatus.AVAILABLE


def test_carregador_em_manutencao_nao_inicia(db, world):
    with pytest.raises(cs.ChargingError):
        cs.start_session(db, charger=world["maintenance"], resident=world["ana"],
                         actor=world["syndic"])


def test_sessao_encerrada_nao_encerra_de_novo(db, world):
    s = _charge(db, world, world["ana"], "10")
    assert s.status == SessionStatus.COMPLETED
    with pytest.raises(cs.ChargingError):
        cs.end_session(db, session=s, actor=world["syndic"], energy_kwh=Decimal("10"))


def test_fatura_soma_consumo_e_itens(db, world):
    _charge(db, world, world["ana"], "20")
    _charge(db, world, world["ana"], "10", start=T0 + timedelta(days=1))
    inv = bs.generate_invoice(db, resident=world["ana"], period_start=T0.date().replace(day=1),
                              period_end=T0.date().replace(day=30), actor=world["syndic"])
    assert inv.total_kwh == Decimal("30.000")
    assert inv.total_amount == Decimal("28.50")
    assert [i.kind for i in inv.items] == [InvoiceItemKind.ENERGY] * 2


def test_fatura_com_taxa_fixa_e_custo_compartilhado(db, world):
    tariff = db.query(Tariff).filter_by(condominium_id=world["condo"].id).one()
    tariff.fixed_fee = Decimal("10.00")
    db.commit()
    _charge(db, world, world["ana"], "20")
    _charge(db, world, world["bruno"], "60", start=T0 + timedelta(days=1))
    inv = bs.generate_invoice(db, resident=world["ana"], period_start=T0.date().replace(day=1),
                              period_end=T0.date().replace(day=30), actor=world["syndic"],
                              shared_total=Decimal("80"))
    kinds = {i.kind for i in inv.items}
    assert kinds == {InvoiceItemKind.ENERGY, InvoiceItemKind.FIXED_FEE, InvoiceItemKind.SHARED_COST}
    # 20/80 do consumo => 25% de R$ 80,00 = R$ 20,00
    shared = next(i for i in inv.items if i.kind == InvoiceItemKind.SHARED_COST)
    assert shared.amount == Decimal("20.00")
    assert inv.total_amount == Decimal("19.00") + Decimal("10.00") + Decimal("20.00")


def test_fatura_duplicada_e_bloqueada(db, world):
    _charge(db, world, world["ana"], "20")
    args = dict(resident=world["ana"], period_start=T0.date().replace(day=1),
                period_end=T0.date().replace(day=30), actor=world["syndic"])
    bs.generate_invoice(db, **args)
    db.commit()
    with pytest.raises(bs.BillingError):
        bs.generate_invoice(db, **args)


def test_sessao_nao_e_faturada_duas_vezes(db, world):
    s = _charge(db, world, world["ana"], "20")
    bs.generate_invoice(db, resident=world["ana"], period_start=T0.date().replace(day=1),
                        period_end=T0.date().replace(day=30), actor=world["syndic"])
    db.commit()
    assert s.invoice_id is not None
    with pytest.raises(bs.BillingError):  # outro período sobreposto, sem sessões livres
        bs.generate_invoice(db, resident=world["ana"], period_start=T0.date().replace(day=2),
                            period_end=T0.date().replace(day=29), actor=world["syndic"])
