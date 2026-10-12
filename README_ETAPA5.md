# GoodWe ChargeOps — Etapa 5: frontend completo

O pacote mantém o backend Python/FastAPI da etapa 4 e adiciona `frontend/` (React 19 + Vite 6 + TypeScript + Tailwind 3 + Recharts).

## Executar

### 1. Banco e API
O backend usa SQLite por padrão (`sqlite:///./chargeops_dev.db`), na pasta `backend/`, e também pode ser configurado para PostgreSQL via `DATABASE_URL`. Entre em `backend/` e, com Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.seed  # somente se o banco ainda estiver vazio
uvicorn app.main:app --reload --port 8000
```

A inicialização do banco ocorre no modo de desenvolvimento. Execute os comandos de seed depois de garantir que a tabela foi criada (inicie o backend uma vez). Se utilizar banco novo, execute `python -m app.seed` e reinicie o backend se necessário.

### 2. Frontend
Abra OUTRO terminal em `frontend/`:

```powershell
npm install
npm run dev
```

Acesse **http://localhost:5173**. O Vite faz proxy de `/api` para `http://localhost:8000`. Se o backend estiver em outro endereço, crie `frontend/.env` com `VITE_PROXY_TARGET=http://IP:PORTA`.

### 3. Contas de teste (seed)

- Síndico: `sindico@example.com` / `Sindico@2026dev`
- Morador: `ana.souza@example.com` / `Morador@2026dev`

Essas credenciais são apenas para demonstração local; nunca as utilize em produção.

## Páginas
- Login com token JWT no `sessionStorage`
- Visão geral do síndico com KPIs, gráficos, estados e alertas
- Visão geral do morador com consumo, custos, recargas e fatura
- Carregadores: listar, criar e alterar status (permissões da API)
- Moradores: buscar, filtrar, cadastrar e aprovar/rejeitar/desativar/ativar
- Recargas: listar, iniciar e encerrar, exportar CSV
- Faturas: listar, gerar por período, baixar PDF, enviar e registrar pagamentos
- Inteligência: consultar anomalias, perfis, previsão e disparar análise
- Copiloto ChargeAI lateral com indicadores e gráficos integrado a `/api/ai/copilot/chat` e ações confirmadas via `/api/ai/copilot/execute`
- Configurações: dados básicos de usuário

**Observações:** dados e cobranças são simulados. A API da etapa 4 determina quais operações são autorizadas. O painel consome a API existente; não é um mockup estático. Gráficos Recharts e estados de erro/carregamento fazem parte do frontend. Não foi executada verificação final de build neste ambiente porque `npm install` não completou; execute `npm install && npm run build` localmente.


Veja [README_COPILOTO.md](README_COPILOTO.md) para a nova implementação do ChargeAI.


## Atualização Etapa 6 — sincronização / OCPP

O projeto foi ampliado com sincronização SSE entre síndico e moradores e integração inicial OCPP 1.6J, sem alterar o banco existente. Consulte [README_SYNC_OCPP.md](README_SYNC_OCPP.md) para detalhes e limitações de equipamentos físicos.
