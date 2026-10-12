"""ChargeAI: orquestra identificação de perfil -> intenção -> ferramenta autorizada -> resposta.

Fluxo: (1) perfil vem do usuário autenticado; (2) a pergunta vira uma intenção; (3) a ferramenta é executada
somente se o perfil tiver permissão; (4) a resposta é montada a partir dos dados reais (modo local) e,
se houver chave de API configurada, reescrita por um modelo de linguagem usando apenas esses dados.
"""
from sqlalchemy.orm import Session

from app.ai import responders
from app.ai.intents import classify
from app.ai.providers import ExternalProvider, ProviderError
from app.ai.tools import TOOLS, ToolPermissionError, is_allowed, run_tool
from app.models import Role, User

SUGGESTIONS = {
    Role.RESIDENT: ["Quanto eu consumi neste mês?", "Qual é o valor da minha fatura atual?",
                    "Por que minha fatura ficou mais cara?", "Qual foi minha última recarga?",
                    "Quais carregadores estão disponíveis?", "Como o sistema calcula o valor que devo pagar?",
                    "Como posso reduzir meus gastos?"],
    Role.SYNDIC: ["Qual foi o consumo total do condomínio neste mês?", "Quais moradores tiveram maior consumo?",
                  "Quais faturas estão vencidas?", "Qual é o valor total pendente?",
                  "Existem padrões de consumo anormais?", "Qual é o horário de maior utilização?",
                  "Qual é a previsão de consumo para o próximo mês?"],
}
SUGGESTIONS[Role.PLATFORM_ADMIN] = SUGGESTIONS[Role.SYNDIC]

MODE_LABELS = {"local": "Modo local: respostas calculadas por consultas ao banco de dados do sistema",
               "externo": "Modelo de linguagem externo reescrevendo dados consultados pelo sistema",
               "local_fallback": "Modo local (o modelo externo não respondeu; resposta calculada pelo sistema)"}


def suggestions_for(user: User) -> list[str]:
    return SUGGESTIONS[user.role]


def _refusal(user: User) -> str:
    if user.role == Role.RESIDENT:
        return ("Essa informação é restrita ao síndico. Posso ajudar com os seus dados: consumo, faturas, "
                "recargas, carregadores disponíveis e como o valor é calculado.")
    return ("Consultas pessoais de morador (como 'minha fatura') não se aplicam ao perfil de síndico. "
            "Pergunte sobre consumo do condomínio, faturas pendentes, anomalias, carregadores ou previsão.")


def _reply(answer, intent, tools, mode, user, data=None):
    return {"answer": answer, "intent": intent, "tools_used": tools, "mode": mode,
            "mode_label": MODE_LABELS[mode], "suggestions": suggestions_for(user)[:4], "data": data}


def answer_question(db: Session, user: User, message: str,
                    provider: ExternalProvider | None = None) -> dict:
    intent, params = classify(message)
    if intent is None:
        return _reply("Não consegui identificar a sua pergunta. Tente uma das sugestões abaixo; "
                      "só respondo com dados reais do sistema e não invento valores.", "desconhecida", [], "local", user)
    if intent.name == "bloqueado":
        return _reply("Não executo comandos SQL nem altero dados. Posso consultar informações do sistema "
                      "por meio de perguntas em linguagem natural.", "bloqueado", [], "local", user)
    if intent.name == "ajuda":
        return _reply("Sou a ChargeAI. Respondo com base nos dados reais do EV ChargeOps e nas suas permissões. "
                      "Veja algumas perguntas possíveis nas sugestões.", "ajuda", [], "local", user)

    tools_used: list[str] = []
    needed = [intent.tool]
    if intent.name == "reduzir_consumo":
        needed = ["consultar_consumo_morador"]
    if not all(is_allowed(t, user) for t in needed):
        return _reply(_refusal(user), intent.name, [], "local", user)
    try:
        data = run_tool(intent.tool, db, user, **params)
    except ToolPermissionError:
        return _reply(_refusal(user), intent.name, [], "local", user)
    tools_used.append(intent.tool)
    draft = responders.RESPONDERS[intent.name](data, user)

    mode, answer = "local", draft
    if provider is not None:
        try:
            answer, mode = provider.rewrite(message, intent.name, data, draft), "externo"
        except ProviderError:
            mode, answer = "local_fallback", draft
    return _reply(answer, intent.name, tools_used, mode, user, data=None)
