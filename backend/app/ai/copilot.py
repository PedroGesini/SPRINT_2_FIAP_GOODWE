"""Copiloto operacional: consultas restritas por condomínio/perfil e propostas confirmáveis.

Não controla equipamentos físicos. Escritas são feitas somente pelo endpoint de confirmação,
que delega às validações e à auditoria da rota de carregadores.
"""
import re
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.assistant import answer_question
from app.ai.formatting import fmt_brl, fmt_kwh, fmt_num
from app.ai.intents import normalize
from app.ai.providers import ExternalProvider, ProviderError
from app.models import Charger, ChargerStatus, ChargingSession, Role, SessionSource, SessionStatus, User
from app.services import dashboard_service as ds

STAFF = (Role.SYNDIC, Role.PLATFORM_ADMIN)
STATUS_PT = {"available": "disponível", "in_use": "em uso", "maintenance": "em manutenção", "unavailable": "indisponível"}


def _chargers(db: Session, user: User) -> list[Charger]:
    return list(db.scalars(select(Charger).where(Charger.condominium_id == user.condominium_id)
                           .order_by(Charger.code)).all())


def _code_in_message(message: str, chargers: list[Charger]) -> Charger | None:
    msg = normalize(message)
    for charger in sorted(chargers, key=lambda c: len(c.code), reverse=True):
        key = normalize(charger.code)
        # exige o código inteiro para evitar CH-01 confundido com CH-010
        if re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", msg):
            return charger
    return None


def _as_charger(c: Charger) -> dict:
    return {"id": c.id, "code": c.code, "name": c.name, "status": c.status.value,
            "status_label": STATUS_PT[c.status.value], "power_kw": float(c.power_kw),
            "location": c.location or "Local não informado", "parking_spot": c.parking_spot or "—"}


def _base(answer: str, *, mode: str = "local", cards: list | None = None, chart: dict | None = None,
          chargers: list | None = None, proposal: dict | None = None, sources: list | None = None) -> dict:
    return {"answer": answer, "mode": mode, "cards": cards or [], "chart": chart,
            "chargers": chargers or [], "proposal": proposal, "sources": sources or [],
            "simulated": True}


def _rewrite(provider: ExternalProvider | None, message: str, intent: str, data: dict, draft: str) -> tuple[str, str]:
    if not provider:
        return draft, "local"
    try:
        return provider.rewrite(message, intent, data, draft), "externo"
    except ProviderError:
        return draft, "local_fallback"


def _recent_monthly(db: Session, user: User, charger: Charger | None = None, count: int = 6) -> list[dict]:
    t = ds.local_today()
    points = []
    for delta in reversed(range(count)):
        year, month = ds.shift_month(t.year, t.month, -delta)
        rows = ds.completed_sessions(db, user.condominium_id, *ds.month_span(year, month),
                                     resident_id=None if user.role in STAFF else user.id)
        if charger is not None:
            rows = [row for row in rows if row.charger_id == charger.id]
        kwh, cost = ds._totals(rows)
        points.append({"label": ds.month_label(year, month), "kwh": round(float(kwh), 2),
                       "cost": round(float(cost), 2), "sessions": len(rows)})
    return points


def _cards(**items) -> list[dict]:
    return [{"label": k, "value": str(v)} for k, v in items.items()]


def _is_status_request(s: str) -> bool:
    verbs = r"coloque|colocar|coloca|marque|marcar|altere|alterar|mude|mudar|deixe|deixar|defina|definir|ponha|libere|liberar|ative|ativar|desative|desativar|tirar.*manutencao|tire.*manutencao|remover.*manutencao"
    return bool(re.search(verbs, s) and re.search(r"manutencao|indisponivel|disponivel|liberar|libere|ativar|ative|desativar|desative", s))


def _target_status(s: str) -> str | None:
    if re.search(r"indisponivel|\bdesativar\b|\bdesative\b", s):
        return "unavailable"
    if re.search(r"manutencao", s) and not re.search(r"tirar.*manutencao|tire.*manutencao|remover.*manutencao", s):
        return "maintenance"
    if re.search(r"tirar.*manutencao|tire.*manutencao|remover.*manutencao|\bliberar\b|\blibere\b|\bativar\b|\bative\b|\bdisponivel\b", s):
        return "available"
    return None


def _charger_details(db: Session, user: User, message: str, charger: Charger,
                     provider: ExternalProvider | None = None) -> dict:
    item = _as_charger(charger)
    cards = _cards(Status=item["status_label"].capitalize(), Potência=f"{fmt_num(item['power_kw'])} kW",
                   Local=item["location"], Vaga=item["parking_spot"])
    chart = None
    extra = ""
    if user.role in STAFF:
        cutoff = ds.local_today() - timedelta(days=30)
        # Só sessões encerradas; o período acompanha o início de cada recarga.
        sessions = db.scalars(select(ChargingSession).where(
            ChargingSession.condominium_id == user.condominium_id,
            ChargingSession.charger_id == charger.id,
            ChargingSession.status == SessionStatus.COMPLETED,
            ChargingSession.started_at >= ds.bounds(cutoff, ds.local_today())[0]
        )).all()
        energy = sum((Decimal(str(r.energy_kwh or 0)) for r in sessions), Decimal(0))
        cost = sum((Decimal(str(r.energy_cost or 0)) for r in sessions), Decimal(0))
        cards += _cards(**{"Consumo 30 dias": fmt_kwh(energy), "Custo 30 dias": fmt_brl(cost),
                           "Recargas 30 dias": len(sessions)})
        extra = f" Nos últimos 30 dias houve {len(sessions)} recargas encerradas, somando {fmt_kwh(energy)} e {fmt_brl(cost)}."
        chart = {"title": f"Histórico do {charger.code}", "data": _recent_monthly(db, user, charger)}
    if user.role not in STAFF:
        extra = " O consumo agregado do equipamento não é exibido para moradores, para preservar a privacidade."
    draft = (f"O {charger.code} ({charger.name}) está {item['status_label']}. Local: {item['location']}, "
             f"vaga {item['parking_spot']}, potência nominal de {fmt_num(item['power_kw'])} kW.{extra} "
             "Os dados podem combinar simulações e sessões OCPP, quando o equipamento está integrado.")
    answer, mode = _rewrite(provider, message, "carregador_individual", {"charger": item, "cards": cards}, draft)
    return _base(answer, mode=mode, cards=cards, chart=chart, chargers=[item],
                 sources=["Cadastro de carregadores", "Sessões encerradas"])


def _charger_overview(db: Session, user: User, message: str, rows: list[Charger],
                      provider: ExternalProvider | None = None) -> dict:
    counts = {k: sum(c.status.value == k for c in rows) for k in STATUS_PT}
    display = [_as_charger(c) for c in rows]
    cards = _cards(**{"Total": len(rows), "Disponíveis": counts['available'],
                     "Em uso": counts['in_use'], "Em manutenção": counts['maintenance']})
    subset = display
    s = normalize(message)
    if re.search(r"livre|disponiveis|disponivel", s) and not re.search(r"manutencao|todos|status|situacao", s):
        subset = [c for c in display if c['status'] == 'available']
    elif re.search(r"manutencao|fora de operacao|indisponiveis|quebrad", s):
        subset = [c for c in display if c['status'] in ('maintenance', 'unavailable')]
    consumption_chart = None
    usage_summary = ""
    if user.role in STAFF:
        from app.services import dashboard_service as ds2
        end = ds2.local_today()
        start = end - timedelta(days=29)
        recent_sessions = ds2.completed_sessions(db, user.condominium_id, start, end)
        totals = {c.id: {"kwh": 0.0, "cost": 0.0, "sessions": 0} for c in rows}
        for session in recent_sessions:
            if session.charger_id in totals:
                target = totals[session.charger_id]
                target["kwh"] += float(session.energy_kwh or 0)
                target["cost"] += float(session.energy_cost or 0)
                target["sessions"] += 1
        consumption_chart = {"title": "Consumo por carregador · 30 dias", "data": [
            {"label": c.code, "kwh": round(totals[c.id]["kwh"], 2),
             "cost": round(totals[c.id]["cost"], 2), "sessions": totals[c.id]["sessions"]}
            for c in rows]}
        total_kwh = sum(v["kwh"] for v in totals.values())
        total_cost = sum(v["cost"] for v in totals.values())
        cards += _cards(**{"Consumo 30 dias": fmt_kwh(total_kwh), "Custo 30 dias": fmt_brl(total_cost)})
        usage_summary = (f" Nos últimos 30 dias: {fmt_kwh(total_kwh)} e {fmt_brl(total_cost)} "
                         "em sessões encerradas. O gráfico detalha os carregadores.")
    summary = (f"Há {len(rows)} {'carregador cadastrado' if len(rows)==1 else 'carregadores cadastrados'}: {counts['available']} disponíveis, "
               f"{counts['in_use']} em uso, {counts['maintenance']} em manutenção e "
               f"{counts['unavailable']} indisponíveis. "
               f"Veja abaixo o status e a localização.{usage_summary} Os dados podem incluir simulações e medições OCPP.")
    answer, mode = _rewrite(provider, message, "carregadores_visao_geral", {"chargers": subset,"counts": counts}, summary)
    return _base(answer, mode=mode, cards=cards, chart=consumption_chart, chargers=subset, sources=["Cadastro de carregadores", "Sessões encerradas"] if consumption_chart else ["Cadastro de carregadores"])


def _consumption_overview(db: Session, user: User, message: str,
                          provider: ExternalProvider | None = None) -> dict:
    period = "previous" if re.search(r"mes passado|mes anterior|ultimo mes", normalize(message)) else "current"
    t = ds.local_today()
    y, m = ds.shift_month(t.year, t.month, -1) if period == 'previous' else (t.year, t.month)
    rows = ds.completed_sessions(db, user.condominium_id, *ds.month_span(y, m),
                                 resident_id=None if user.role in STAFF else user.id)
    kwh, cost = ds._totals(rows)
    subject = "O condomínio" if user.role in STAFF else "Você"
    draft = (f"{subject} consumiu {fmt_kwh(kwh)} em {len(rows)} {'recarga encerrada' if len(rows)==1 else 'recargas encerradas'} em "
             f"{ds.month_label(y, m)}, com custo de energia de {fmt_brl(cost)}. "
             "O valor considera somente sessões encerradas, incluindo medições OCPP quando disponíveis.")
    data = {"period": ds.month_label(y,m), "kwh": float(kwh), "cost": float(cost), "sessions":len(rows)}
    answer, mode = _rewrite(provider, message, "resumo_consumo", data, draft)
    return _base(answer, mode=mode, cards=_cards(**{"Consumo": fmt_kwh(kwh),
                  "Custo de energia": fmt_brl(cost), "Recargas": len(rows)}),
                 chart={"title":"Evolução de consumo (kWh)", "data":_recent_monthly(db, user)},
                 sources=["Sessões encerradas"])


def _simulate_session_proposal(db: Session, user: User, s: str, charger: Charger | None) -> dict | None:
    start = bool(re.search(r"\b(inicie|iniciar|comece|comecar|abrir|abra)\b.*\b(recarga|sessao|carregamento)\b", s))
    end = bool(re.search(r"\b(encerre|encerrar|finalize|finalizar|termine|terminar|pare|parar)\b.*\b(recarga|sessao|carregamento)\b", s))
    if not (start or end):
        return None
    if start:
        if user.role in STAFF:
            return _base("Para iniciar uma recarga de outro morador, use o formulário Recargas > Nova recarga. "
                         "O copiloto não escolhe automaticamente o proprietário da sessão.")
        if charger is None:
            return _base("Informe o código do carregador: por exemplo, 'Inicie uma recarga no CH-01'.")
        if charger.status != ChargerStatus.AVAILABLE:
            return _base(f"O {charger.code} está {STATUS_PT[charger.status.value]} e não pode iniciar uma recarga agora.")
        return _base(f"Posso iniciar uma sessão simulada no {charger.code} para sua conta. "
                     "Ela será registrada na plataforma, não acionará um carregador físico. Confirme abaixo.",
                     proposal={"action":"start_session", "charger_id":charger.id, "charger_code":charger.code,
                               "status":"in_progress", "status_label":"iniciar recarga simulada"},
                     chargers=[_as_charger(charger)])
    stmt = select(ChargingSession).where(
        ChargingSession.condominium_id == user.condominium_id,
        ChargingSession.status == SessionStatus.IN_PROGRESS)
    if user.role == Role.RESIDENT:
        stmt = stmt.where(ChargingSession.resident_id == user.id)
    if charger:
        stmt = stmt.where(ChargingSession.charger_id == charger.id)
    active = list(db.scalars(stmt.order_by(ChargingSession.started_at.desc())).all())
    if not active:
        return _base("Não encontrei uma recarga em andamento para encerrar dentro do seu escopo.")
    if len(active) > 1:
        return _base("Há mais de uma recarga em andamento. Informe o código do carregador para identificar qual encerrar.")
    session = active[0]
    if session.source != SessionSource.SIMULATION:
        return _base("Esta sessão não é simulada. Para encerrá-la, utilize a tela de recargas e informe a leitura real.")
    c = db.get(Charger, session.charger_id)
    return _base(f"Encontrei a sessão #{session.id} no {c.code}. Posso encerrá-la com consumo calculado "
                 "pelo simulador, sem qualquer comando enviado ao equipamento físico. Confirme abaixo.",
                 proposal={"action":"end_session", "charger_id":c.id, "charger_code":c.code,
                           "session_id":session.id, "status":"completed", "status_label":"encerrar recarga simulada"})


def handle_copilot(db: Session, user: User, message: str,
                   provider: ExternalProvider | None = None) -> dict:
    s = normalize(message)
    rows = _chargers(db, user)
    charger = _code_in_message(message, rows)
    session_proposal = _simulate_session_proposal(db, user, s, charger)
    if session_proposal is not None:
        return session_proposal
    if _is_status_request(s):
        if user.role not in STAFF:
            return _base("Somente o síndico pode alterar o status dos carregadores. Você pode consultar a disponibilidade e o seu consumo.")
        if charger is None:
            return _base("Informe o código do carregador, por exemplo: 'Coloque CH-05 em manutenção'.")
        from app.models import OCPPDevice
        if db.scalar(select(OCPPDevice.id).where(OCPPDevice.charger_id == charger.id)):
            return _base(f'O {charger.code} é gerenciado via OCPP. Utilize a seção Carregadores para enviar ChangeAvailability ao equipamento conectado; o estado só muda quando o dispositivo confirmar.')
        state = _target_status(s)
        if state is None:
            return _base("Qual status deseja definir? Disponível, manutenção ou indisponível.")
        if charger.status.value == 'in_use':
            return _base(f"O {charger.code} está em uso. Encerre a sessão antes de solicitar uma alteração de status.")
        if charger.status.value == state:
            return _base(f"O {charger.code} já está {STATUS_PT[state]}.")
        proposal = {"action": "set_charger_status", "charger_id": charger.id, "charger_code": charger.code,
                    "status": state, "status_label": STATUS_PT[state]}
        return _base(f"Posso alterar o status simulado do {charger.code} para {STATUS_PT[state]}. "
                     "Confirme a operação abaixo para aplicar a mudança e registrá-la no histórico de auditoria.",
                     cards=_cards(**{"Carregador": charger.code, "Status atual": STATUS_PT[charger.status.value]}),
                     chargers=[_as_charger(charger)], proposal=proposal)
    if charger is not None:
        return _charger_details(db, user, message, charger, provider)
    if re.search(r"carregador|carregamento|estacao|eletroposto|pontos? de recarga|vaga|potencia", s) and not re.search(r"minha (ultima|recarga|fatura|sessao)|historico|minhas recargas",s):
        # Rankings de carregadores e horários são respondidos pelas ferramentas existentes.
        if re.search(r"mais (usad|utiliz)|ranking|horario|\bpico\b|mais consumo", s) and user.role in STAFF:
            result=answer_question(db,user,message,provider)
            if result['intent'] != 'desconhecida':
                return _base(result['answer'],mode=result['mode'], sources=["Histórico de sessões"])
        return _charger_overview(db, user, message, rows, provider)
    if re.search(r"(quanto|total|resumo|consumo).*(consum|gasto|gastou|energia|kwh)|(consumi|gastei|consumiu|consumo total)",s) and not re.search(r"fatura|conta|tarifa",s):
        return _consumption_overview(db, user, message, provider)
    result=answer_question(db,user,message,provider)
    return _base(result['answer'],mode=result['mode'],sources=["Consultas autorizadas do EV ChargeOps"] if result['tools_used'] else [])
