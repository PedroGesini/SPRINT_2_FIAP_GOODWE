"""Interpretação da pergunta -> intenção -> ferramenta (modo local, determinístico)."""
import re
import unicodedata
from dataclasses import dataclass


def normalize(text: str) -> str:
    s = unicodedata.normalize("NFKD", text)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


@dataclass(frozen=True)
class Intent:
    name: str
    tool: str | None
    pattern: str
    params: tuple = ()


I = Intent
STAFF_INTENTS = [
    I("anomalias", "analisar_padroes_consumo", r"anomal|atipic|suspeit|anormal|padroes? de consumo|perfis? de consumo"),
    I("previsao", "prever_consumo", r"previs|projec|estimativa de consumo|proximo mes"),
    I("moradores_aumento", "consultar_aumentos_consumo", r"aument\w*.*consumo|consumo.*aument|aumentaram"),
    I("maiores_consumidores", "consultar_ranking_moradores", r"maior(es)? consum|mais consum|ranking|quais moradores.*consum|quem.*consum"),
    I("faturas_vencidas", "consultar_faturas_pendentes", r"vencid|atrasad|inadimpl", (("kind", "overdue"),)),
    I("valor_pendente", "consultar_faturas_pendentes", r"pendente|em aberto|a receber"),
    I("carregadores_mais_usados", "consultar_uso_carregadores", r"carregador\w*.*mais (utiliz|usad)|mais (utiliz|usad)\w* .*carregador|uso dos carregadores"),
    I("carregadores_indisponiveis", "consultar_carregadores_indisponiveis", r"indisponiv|manutencao|fora de operacao|quebrad"),
    I("horario_pico", "consultar_horarios_uso", r"horario|\bpico\b|hora.*(movimentad|utiliza)"),
    I("evolucao_custos", "consultar_evolucao_custos", r"evolu|ultimos meses|historico de custos"),
    I("consumo_condominio", "consultar_consumo_condominio", r"condominio|consumo total|consumo geral"),
]
RESIDENT_INTENTS = [
    I("fatura_mais_cara", "consultar_faturas_morador", r"(por ?que|porque|motivo).*(fatura|conta).*(cara|maior|subiu|aument)|(fatura|conta).*(mais cara|aument|subiu)"),
    I("custo_ultima_sessao", "consultar_historico_recargas", r"(quanto custou|custo|valor).*(ultima|ultimo).*(recarga|sessao)|(ultima|ultimo).*(recarga|sessao).*(custou|custo|valor)"),
    I("ultima_recarga", "consultar_historico_recargas", r"ultima (recarga|sessao)"),
    I("qtd_recargas", "consultar_historico_recargas", r"quantas (vezes|recargas|sessoes)|numero de recargas"),
    I("consumo_mes_passado", "consultar_consumo_morador", r"(mes passado|mes anterior|ultimo mes).*consum|consum.*(mes passado|mes anterior)|(consumi|gastei).*(mes passado|mes anterior)", (("period", "previous"),)),
    I("como_calcula", "consultar_regras_de_cobranca", r"como.*(calcul|cobr)|formula|rateio|tarifa"),
    I("reduzir_consumo", "consultar_consumo_morador", r"reduz|econom|gastar menos|diminu|baratear"),
    I("consumo_mes", "consultar_consumo_morador", r"consum|gastei"),
    I("fatura_atual", "consultar_faturas_morador", r"fatura|conta de energia|boleto"),
    I("historico", "consultar_historico_recargas", r"historico|minhas recargas|minhas sessoes"),
]
SHARED_INTENTS = [
    I("como_calcula", "consultar_regras_de_cobranca", r"como.*(calcul|cobr)|formula|rateio|tarifa"),
    I("carregadores_disponiveis", "consultar_carregadores_disponiveis", r"carregador|disponiv|livre"),
    I("ajuda", None, r"ajuda|o que voce (faz|pode)|\bhelp\b"),
]
BLOCKED = re.compile(r"\b(select|insert|update|delete|drop|alter|truncate)\b.*\b(from|into|table|set|database)\b")
PERSONAL = re.compile(r"\b(meu|minha|meus|minhas|eu|consumi|gastei|mim)\b")
PREVIOUS = re.compile(r"mes passado|mes anterior|ultimo mes")


def classify(message: str) -> tuple[Intent | None, dict]:
    text = normalize(message)
    if BLOCKED.search(text):
        return Intent("bloqueado", None, ""), {}
    ordered = (RESIDENT_INTENTS + STAFF_INTENTS if PERSONAL.search(text) else STAFF_INTENTS + RESIDENT_INTENTS)
    for intent in ordered + SHARED_INTENTS:
        if re.search(intent.pattern, text):
            params = dict(intent.params)
            if PREVIOUS.search(text) and intent.tool in ("consultar_consumo_condominio", "consultar_ranking_moradores"):
                params["period"] = "previous"
            return intent, params
    return None, {}
