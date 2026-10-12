"""Geração da resposta (modo local): texto em pt-BR com valores, unidades e fórmulas."""
from app.ai.formatting import STATUS_PT, fmt_brl, fmt_date, fmt_kwh, fmt_num, fmt_pct

_s = lambda n, one, many: one if n == 1 else many


def consumo_mes(d, user):
    if d["sessions"] == 0:
        return f"Você ainda não tem recargas encerradas em {d['period_label']}."
    when = (f"Neste mês ({d['period_label']})" if d["comparison_basis"].startswith("mesmo")
            else f"Em {d['period_label']}")
    return (f"{when} você consumiu {fmt_kwh(d['kwh'])} em {d['sessions']} "
            f"{_s(d['sessions'], 'recarga', 'recargas')}, com custo de energia de {fmt_brl(d['cost'])}.\n"
            f"Cálculo: cada recarga custa kWh × tarifa (atual: {fmt_brl(d['tariff_per_kwh'])}/kWh); "
            f"o total é a soma das recargas.\n"
            f"Comparação ({d['comparison_basis']}): {fmt_kwh(d['previous_kwh'])} → {fmt_pct(d['change_pct'])}.")


consumo_mes_passado = consumo_mes


def _fatura_linhas(f):
    nota = ""
    if abs(round(f["total_kwh"] * f["tariff_per_kwh"], 2) - f["energy_total"]) >= 0.01:
        nota = "; soma dos valores arredondados de cada recarga"
    linhas = [f"- Energia: {fmt_kwh(f['total_kwh'])} × {fmt_brl(f['tariff_per_kwh'])}/kWh = {fmt_brl(f['energy_total'])}"
              f" ({f['energy_sessions']} {_s(f['energy_sessions'], 'recarga', 'recargas')}{nota})"]
    if f["fixed_fee"]:
        linhas.append(f"- Taxa fixa de infraestrutura: {fmt_brl(f['fixed_fee'])}")
    if f["shared_cost"]:
        linhas.append(f"- Custo compartilhado (rateio por kWh): {fmt_brl(f['shared_cost'])}")
    if f["adjustments"]:
        linhas.append(f"- Ajustes administrativos: {fmt_brl(f['adjustments'])}")
    return linhas


def fatura_atual(d, user):
    f = d["latest"]
    if not f:
        return (f"Você ainda não tem fatura emitida. A estimativa do mês corrente, com as recargas ainda não "
                f"faturadas, é {fmt_brl(d['estimated_current_month'])}.")
    head = (f"Sua fatura mais recente é a de {f['period_label']}: {fmt_brl(f['total'])}, vencimento em "
            f"{fmt_date(f['due_date'])}, situação {STATUS_PT.get(f['status'], f['status'])}.")
    tail = f"Saldo em aberto: {fmt_brl(f['balance'])}." if f["balance"] else "Não há saldo em aberto."
    return "\n".join([head, "Composição:", *_fatura_linhas(f), tail,
                      f"Estimativa do mês corrente (não faturado ainda): {fmt_brl(d['estimated_current_month'])}."])


def fatura_mais_cara(d, user):
    cur, prv, f = d["latest"], d["previous"], d["factors"]
    if not cur or not prv:
        return "Encontrei no máximo uma fatura sua, então não há outra para comparar."
    if f["total_delta"] <= 0:
        return (f"Sua fatura de {cur['period_label']} ({fmt_brl(cur['total'])}) não ficou mais cara que a de "
                f"{prv['period_label']} ({fmt_brl(prv['total'])}): diferença de {fmt_brl(f['total_delta'])}.")
    linhas = [f"Sua fatura de {cur['period_label']} ({fmt_brl(cur['total'])}) ficou {fmt_brl(f['total_delta'])} "
              f"mais cara que a de {prv['period_label']} ({fmt_brl(prv['total'])}). Fatores:"]
    if f["kwh_delta"]:
        linhas.append(f"- Consumo: {fmt_kwh(cur['total_kwh'])} contra {fmt_kwh(prv['total_kwh'])} "
                      f"({'+' if f['kwh_delta'] > 0 else ''}{fmt_num(f['kwh_delta'], 2)} kWh), efeito de {fmt_brl(f['energy_delta'])} na energia.")
    if f["tariff_changed"]:
        linhas.append(f"- Tarifa: de {fmt_brl(f['tariff_previous'])}/kWh para {fmt_brl(f['tariff_current'])}/kWh.")
    if f["fixed_fee_delta"]:
        linhas.append(f"- Taxa fixa: variação de {fmt_brl(f['fixed_fee_delta'])}.")
    if f["other_delta"]:
        linhas.append(f"- Rateios/ajustes: variação de {fmt_brl(f['other_delta'])}.")
    if len(linhas) == 1:
        linhas.append("- Não identifiquei um fator individual nos itens da fatura; consulte o detalhamento.")
    return "\n".join(linhas)


def qtd_recargas(d, user):
    return (f"Neste mês você fez {d['sessions_this_month']} {_s(d['sessions_this_month'], 'recarga', 'recargas')}. "
            f"No histórico total são {d['total_sessions']}.")


def _sessao(s):
    dur = f", duração de {s['duration_minutes'] // 60}h{s['duration_minutes'] % 60:02d}" if s["duration_minutes"] is not None else ""
    return (f"#{s['id']} em {s['started_at']:%d/%m/%Y %H:%M} no {s['charger']}{dur}: "
            f"{fmt_kwh(s['kwh'])}, {fmt_brl(s['cost'])}")


def ultima_recarga(d, user):
    if not d["recent"]:
        return "Você ainda não tem recargas encerradas."
    return f"Sua última recarga foi a {_sessao(d['recent'][0])}."


def custo_ultima_sessao(d, user):
    if not d["recent"]:
        return "Você ainda não tem recargas encerradas."
    s = d["recent"][0]
    return (f"Sua última recarga (#{s['id']}, {s['started_at']:%d/%m/%Y}) consumiu {fmt_kwh(s['kwh'])} e custou "
            f"{fmt_brl(s['cost'])}.\nCálculo: {fmt_kwh(s['kwh'])} × {fmt_brl(s['tariff_per_kwh'])}/kWh "
            f"(tarifa aplicada na época da recarga).")


def historico(d, user):
    if not d["recent"]:
        return "Você ainda não tem recargas encerradas."
    return "Suas últimas recargas:\n" + "\n".join(f"- {_sessao(s)}" for s in d["recent"])


def carregadores_disponiveis(d, user):
    av = d["available"]
    if not av:
        return f"No momento nenhum carregador está disponível ({len(d['in_use'])} em uso)."
    lista = "\n".join(f"- {c['code']} ({c['location'] or 'sem local'}, {fmt_num(c['power_kw'])} kW)" for c in av)
    extra = f"\nEm uso: {len(d['in_use'])}. Fora de operação: {len(d['down'])}."
    return f"Carregadores disponíveis agora ({len(av)} de {d['total']}):\n{lista}{extra}\n(Dados simulados.)"


def como_calcula(d, user):
    t = d["tariff_per_kwh"]
    ex = f" Exemplo: 20 kWh × {fmt_brl(t)}/kWh = {fmt_brl(20 * t)}." if t else ""
    taxa = (f"\nHá também uma taxa fixa de infraestrutura de {fmt_brl(d['fixed_fee'])} por fatura, sempre listada "
            "como item separado." if d["fixed_fee"] else "")
    return ("A cobrança usa o consumo individual em kWh como base:\n"
            f"custo de energia = kWh consumidos × tarifa por kWh (atual: {fmt_brl(t)}/kWh).{ex}{taxa}\n"
            "A tarifa de cada recarga fica registrada no momento da sessão, então mudanças futuras não alteram "
            "faturas antigas. Custos compartilhados, se existirem, são rateados proporcionalmente ao seu consumo "
            "e aparecem em itens próprios.")


def reduzir_consumo(d, user):
    base = ("Dicas gerais (o sistema cobra por kWh consumido, com tarifa única, sem preço diferente por horário):\n"
            "- Carregue apenas o necessário para os seus trajetos: cada kWh a menos reduz o custo de energia.\n"
            "- Acompanhe o painel de consumo para perceber aumentos cedo.\n"
            "- A taxa fixa, se houver, não varia com o consumo.")
    if d["sessions"]:
        base = (f"Neste mês você fez {d['sessions']} {_s(d['sessions'], 'recarga', 'recargas')} com média de "
                f"{fmt_kwh(d['avg_kwh_session'])} por recarga ({fmt_pct(d['change_pct'])} no consumo, {d['comparison_basis']}).\n") + base
    return base


# ------------------------------------------------------------------------------------ síndico
def consumo_condominio(d, user):
    c, ch = d["consumption"], d["chargers"]
    return (f"Em {d['period']['label']} o condomínio consumiu {fmt_kwh(c['kwh'])} em {c['sessions']} recargas, "
            f"com custo de energia de {fmt_brl(c['cost'])}.\n"
            f"Média por morador ativo ({d['residents']['total']}): {fmt_kwh(c['avg_kwh_per_resident'])}.\n"
            f"Comparação ({c['comparison_basis']}): {fmt_kwh(c['previous_kwh'])} → {fmt_pct(c['kwh_change_pct'])}.\n"
            f"Carregadores: {ch['available']} disponíveis, {ch['in_use']} em uso, {ch['maintenance']} em manutenção.")


def maiores_consumidores(d, user):
    if not d["ranking"]:
        return f"Não há recargas encerradas em {d['period_label']} até agora."
    linhas = [f"{i}. {r['name']} (unid. {r['unit']}): {fmt_kwh(r['kwh'])}, {fmt_brl(r['cost'])}, {r['sessions']} recargas"
              for i, r in enumerate(d["ranking"], 1)]
    return f"Maiores consumos em {d['period_label']}:\n" + "\n".join(linhas)


def faturas_vencidas(d, user):
    if not d["overdue_count"]:
        return "Não há faturas vencidas no momento."
    linhas = [f"- {r['resident']} (unid. {r['unit']}), {r['period_label']}: {fmt_brl(r['balance'])}, venceu em {fmt_date(r['due_date'])}"
              for r in d["overdue"]]
    return (f"Há {d['overdue_count']} {_s(d['overdue_count'], 'fatura vencida', 'faturas vencidas')}, somando "
            f"{fmt_brl(d['overdue_amount'])} em aberto:\n" + "\n".join(linhas))


def valor_pendente(d, user):
    return (f"O valor total em aberto é {fmt_brl(d['open_amount'])} em {d['open_count']} faturas "
            f"(das quais {d['overdue_count']} vencidas, {fmt_brl(d['overdue_amount'])}).")


def carregadores_mais_usados(d, user):
    if not d["by_charger"]:
        return "Não há recargas no período."
    linhas = [f"{i}. {c['code']}: {fmt_kwh(c['kwh'])} ({fmt_num(c['share_pct'])}% do consumo), {c['sessions']} recargas"
              for i, c in enumerate(d["by_charger"], 1)]
    return f"Uso dos carregadores nos {d['window']}:\n" + "\n".join(linhas)


def carregadores_indisponiveis(d, user):
    if not d["down"]:
        return "Todos os carregadores estão operacionais."
    return "Carregadores fora de operação:\n" + "\n".join(
        f"- {c['code']} ({c['location'] or 'sem local'}): {STATUS_PT[c['status']]}" for c in d["down"])


def horario_pico(d, user):
    if not d["total_sessions"]:
        return "Não há recargas no período."
    linhas = [f"- {h['label']}: {h['sessions']} recargas ({fmt_num(h['share_pct'])}%)" for h in d["top_hours"]]
    return f"Horários de maior utilização nos {d['window']} (início das recargas):\n" + "\n".join(linhas)


def evolucao_custos(d, user):
    linhas = [f"- {m['label']}: {fmt_kwh(m['kwh'])}, energia {fmt_brl(m['energy_cost'])}, faturado {fmt_brl(m['billed'])}"
              for m in d["months"]]
    return ("Evolução nos últimos meses (o faturado inclui taxas e só existe para meses já faturados):\n" + "\n".join(linhas))


def moradores_aumento(d, user):
    if not d["alerts"]:
        return "Não identifiquei moradores com aumento significativo de consumo nos últimos 30 dias."
    return "Aumentos de consumo que merecem análise:\n" + "\n".join(f"- {a['message']}" for a in d["alerts"])


def anomalias(d, user):
    a, p = d["anomalies"], d["profiles"]
    if a["method"] == "nenhum":
        return a["notes"][0]
    metodo = "Isolation Forest" if a["method"] == "isolation_forest" else "método estatístico (IQR)"
    linhas = [f"Análise com {metodo} sobre {a['n_sessions']} sessões: {a['count']} merecem análise."]
    for it in a["top"]:
        linhas.append(f"- Sessão #{it['session_id']} ({it['resident_name']}, {fmt_num(it['energy_kwh'])} kWh): {it['reasons'][0]}")
    if a["count"] > len(a["top"]):
        linhas.append(f"(Mostrando as {len(a['top'])} mais relevantes; veja a lista completa na tela de análises.)")
    linhas.append("Obs.: são sinais estatísticos, não confirmam erro nem irregularidade.")
    if p["clusters"]:
        grupos = "; ".join(f"{c['label']}: {c['residents']} moradores (~{fmt_num(c['avg_monthly_kwh'], 0)} kWh/mês)" for c in p["clusters"])
        linhas.append(f"Perfis de consumo ({'K-Means' if p['method'] == 'kmeans' else 'tercis'}): {grupos}.")
    return "\n".join(linhas)


def previsao(d, user):
    if d["forecast_kwh"] is None:
        return d["notes"][0]
    lo, hi = d["range_kwh"]
    metodo = {"regressão_linear": "tendência linear", "média_3_meses": "média dos últimos 3 meses",
              "média_simples": "média simples"}[d["method"]]
    linhas = [f"Previsão para {d['next_month_label']}: cerca de {fmt_kwh(d['forecast_kwh'])} "
              f"(faixa indicativa {fmt_kwh(lo)} a {fmt_kwh(hi)}), custo de energia estimado em {fmt_brl(d['forecast_cost'])}.",
              f"Método: {metodo} sobre {len(d['history'])} meses completos; custo = kWh previstos × {fmt_brl(d['tariff_per_kwh'])}/kWh."]
    cm = d.get("current_month")
    if cm:
        linhas.append(f"Ritmo atual de {cm['label']}: {fmt_kwh(cm['kwh_so_far'])} até agora (projeção linear de {fmt_kwh(cm['projection_kwh'])} no mês).")
    if d.get("backtest"):
        b = d["backtest"]
        linhas.append(f"Retroteste: erro médio de {fmt_num(b['mae_media_3m_kwh'], 0)} kWh (média 3 meses) contra {fmt_num(b['mae_linear_kwh'], 0)} kWh (tendência linear).")
    linhas.append("É uma estimativa baseada em dados simulados, não uma garantia.")
    return "\n".join(linhas)


RESPONDERS = {name: fn for name, fn in globals().items() if callable(fn) and not name.startswith("_") and name not in (
    "fmt_brl", "fmt_date", "fmt_kwh", "fmt_pct", "fmt_num")}
