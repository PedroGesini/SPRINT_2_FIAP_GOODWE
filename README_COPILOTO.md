# EV ChargeOps — Copiloto ChargeAI

## Implementação

O botão **Copiloto inteligente** abre o chat lateral (React + TypeScript) ligado à API FastAPI.

O copiloto funciona sem API de LLM, em **modo local** com intenções e consultas determinísticas ao banco. Nesse modo, responde somente às perguntas suportadas: consumo próprio / do condomínio, gastos, recargas, faturas, previsão, análises, disponibilidade, status, detalhes, localização, potência e uso de carregadores. Uma chave de **API Anthropic opcional** permite reescrever as respostas com linguagem mais natural, sempre depois de recuperar os dados autorizados. No modo local, perguntas fora do escopo recebem orientação; não são respondidas livremente por um modelo generativo.

### Visualizações no chat

- Indicadores de consumo (kWh), custo e quantidade de recargas;
- Gráficos do histórico de consumo;
- Lista de carregadores com status e localização;
- Consulta por código, por exemplo `CH-01`, com indicadores detalhados para síndico;
- Respostas e sugestões adaptadas ao tipo de usuário.

### Ações com confirmação explícita

- Síndico: solicitar alteração simulada de status para **disponível**, **em manutenção** ou **indisponível**.
- Morador: solicitar início de recarga simulada em carregador livre.
- Morador e síndico: solicitar encerramento de uma sessão simulada em andamento dentro do escopo permitido.
- O copiloto primeiro gera uma **proposta**. Nenhum pedido em linguagem natural altera o sistema antes de o usuário clicar em **Confirmar alteração**.
- O endpoint da ação valida novamente identidade, condomínio, propriedade da sessão e estado. Reaproveita serviços/rotas existentes com auditoria.
- **Atualização Etapa 6:** OCPP 1.6J foi adicionado. Há provisionamento, autenticação de tags, eventos, medições e comando remoto `ChangeAvailability` sujeito a confirmação e autorização. Consulte [README_SYNC_OCPP.md](README_SYNC_OCPP.md). Início/encerramento via copiloto continuam simulados; sessões OCPP são controladas pelo equipamento, e pagamentos continuam simulados.

### Rodar no Windows (PowerShell)

Backend, no primeiro terminal:

```powershell
cd "C:\Users\Info Mania\Desktop\projeto_goodwe\goodwe-build\backend"
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Frontend, em outro terminal:

```powershell
cd "C:\Users\Info Mania\Desktop\projeto_goodwe\goodwe-build\frontend"
npm install
npm run dev
```

Abra **http://localhost:5173** e clique no ícone de chat ou em **Abrir copiloto** no menu lateral.

A API fica em http://127.0.0.1:8000/docs.

### Modelo de linguagem opcional

Para usar a API da Anthropic, configure o arquivo `.env` **somente no backend**. Por exemplo:

```dotenv
AI_API_KEY=sua_chave_privada
AI_MODEL=nome_de_um_modelo_disponivel_na_sua_conta
```

O provedor atual reescreve respostas baseadas em consultas autorizadas; não recebe acesso direto ao banco, não executa SQL e não dispara ações. Sem chave de API, o modo local continua funcional.

> As chaves devem ficar exclusivamente no servidor. Nunca coloque a chave de API no código React ou no repositório.

### Rotas adicionadas

`POST /api/ai/copilot/chat` com `{ "message": "Quanto consumi?", "conversation_id": null }`

`POST /api/ai/copilot/execute` com `{ "action": "set_charger_status", "charger_id": 5, "status": "available" }`

Outras ações suportadas neste endpoint são `start_session` (com `status: "in_progress"`) e `end_session` (com `session_id` e `status: "completed"`). Todas requerem autenticação JWT; operações indisponíveis ao perfil recebem HTTP 403.

### Atualização sem perder dados

Substitua a pasta de código do frontend e as alterações em `backend/app/` e `backend/tests/`; **não apague** seu arquivo de banco SQLite nem arquivos `.env` de um projeto existente.

Não é necessário usar `python -m app.seed --reset`. Não rode `--reset`, pois ele apaga os dados. O banco SQLite usa como padrão um caminho relativo à pasta backend (`sqlite:///./chargeops_dev.db`). Execute o backend sempre a partir dessa pasta.

## Arquivos alterados/adicionados

- `frontend/src/Copilot.tsx` — novo painel interativo e visual
- `frontend/src/main.tsx` — integração com painel existente
- `frontend/src/index.css` — estilo dark premium do copiloto
- `backend/app/ai/copilot.py` — orquestração autorizada
- `backend/app/api/routes/ai.py` — API de conversa estruturada e ações confirmadas
- `backend/tests/test_ai.py` — testes de novas rotas/permissões
