# EV ChargeOps — Etapa 6: sincronização + OCPP 1.6J

Este pacote amplia o **projeto existente** sem eliminar perfis, dados ou o ChargeAI. O backend FastAPI continua sendo a única fonte de verdade; os dashboards de síndico e morador consultam a mesma base SQL.

## Funcionalidades implementadas

**Sincronização entre perfis**

- Alterações bem-sucedidas nas APIs autenticadas notificam os navegadores conectados ao **mesmo condomínio** usando SSE (`GET /api/events` com JWT).
- O frontend abre o stream com `fetch` + header `Authorization: Bearer`, reconsulta suas rotas ao receber `update`, e faz fallback periódico a cada 15 segundos e ao retornar à aba.
- O evento não contém dados pessoais. **A autorização permanece nas APIs** (morador consulta as próprias sessões/faturas; síndico gerencia o condomínio).
- Estados recebidos via OCPP também publicam eventos. Isso sincroniza dados dos equipamentos, recargas, métricas, gráficos e faturas atualizadas, conforme suas APIs.

**OCPP 1.6 JSON sobre WebSocket** — ponto central em `/ocpp/{ocpp_id}` (não confundir com `/api/ocpp/...`).

Suporte a:

| Mensagem OCPP | Suporte |
|---|---|
| BootNotification | Registra fabricante, modelo, firmware e retorna Accepted/interval |
| Heartbeat | Atualiza último contato e retorna hora UTC |
| StatusNotification | Atualiza estado do conector e painel |
| Authorize | Valida morador ativo por RFID provisionado (ou idTag lógico `U{id}` somente em development/test) |
| StartTransaction | Inicia sessão **INTEGRATION**, atribuída ao morador autenticado no ponto |
| MeterValues | Grava leituras cumulativas Wh/kWh, consumo parcial |
| StopTransaction | Finaliza sessão a partir das leituras reais, calcula kWh e custo conforme tarifa ativa |
| ChangeAvailability | Síndico solicita comando remoto **Operative/Inoperative**, requer equipamento conectado e confirmação. O estado muda quando chega StatusNotification |

**Não implementados:** OCPP 2.0.1, Smart Charging (`SetChargingProfile`), `RemoteStartTransaction` / `RemoteStopTransaction`, reservas, atualização de firmware, certificados por dispositivo e roaming OCPI. **OCPP é um protocolo e não garante compatibilidade com qualquer modelo GoodWe**. Confirme a versão OCPP, subprotocolo, Basic Auth e suporte a comandos no manual do firmware antes de conectar hardware real.

## Atualização sem perder os dados

1. **Feche backend e frontend** (`Ctrl+C`). Faça cópia da pasta atual, especialmente `backend/chargeops_dev.db` e `backend/.env`.
2. Extraia o ZIP **Somente Atualização** na pasta `C:\Users\Info Mania\Desktop\projeto_goodwe`, mesclando os arquivos sob `goodwe-build/`. Não apague os arquivos antigos.
3. Execute os comandos na pasta `backend`, **não** na raiz do projeto:

```powershell
cd "C:\Users\Info Mania\Desktop\projeto_goodwe\goodwe-build\backend"
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

4. Em **outro terminal**:

```powershell
cd "C:\Users\Info Mania\Desktop\projeto_goodwe\goodwe-build\frontend"
npm install
npm run build
npm run dev
```

5. Acesse `http://localhost:5173`. Faça login com as contas que **já existem em seu banco**. Não rode `app.seed --reset` nem scripts que recriem senhas.

**Banco**: em `ENVIRONMENT=development`, o SQLAlchemy cria **apenas as novas tabelas** `ocpp_devices`, `ocpp_meter_readings`, `ocpp_tags` ao iniciar. Ele não recria tabelas existentes. Para **produção**, é necessário aplicar essas alterações com uma migração Alembic revisada. A criação automática não está habilitada em produção.

## Como conectar um carregador

1. Entre como síndico, abra **Carregadores > Integração OCPP 1.6J**, clique em **Provisionar** no carregador cadastrado (ex.: `CH-01`).
2. Copie **usuário, senha e ID OCPP**; a senha aparece uma única vez. Cada equipamento possui uma credencial independente.
3. No equipamento, configure `wss://SEU-DOMINIO/ocpp/CH-01`, subprotocolo `ocpp1.6` e autenticação HTTP Basic (`username=CH-01`, senha fornecida). Para **laboratório local isolado**, você pode usar `ws://IP_LOCAL:8000/ocpp/CH-01`; jamais exponha WS sem TLS na internet.
4. Para RFID real, cadastre o cartão em **Cartões RFID** vinculando o ID do cartão ao morador. A autenticação OCPP exige usuário ativo no mesmo condomínio.
5. O carregador deve mandar `BootNotification`, `StatusNotification`, `StartTransaction`, `MeterValues`, `StopTransaction`. Veja o painel OCPP e ambas as telas atualizarem.
6. Para `ChangeAvailability`, use botões **Ativar/Desativar** no painel do síndico. Confirme a operação; `Accepted` é aceitação do pedido, não prova de alteração física. Aguarde o próximo `StatusNotification`.

As operações simuladas de início de sessão são **bloqueadas** em carregadores provisionados em OCPP. O mesmo vale para encerramento simulado de sessões de origem `integration`, evitando dados financeiros incorretos.

### Testar sem equipamento físico

Provisione o dispositivo pelo dashboard e obtenha uma tag lógica de morador em `GET /api/ocpp/my-tag` (JWT do próprio morador), ou vincule um RFID de teste.

```powershell
cd "C:\Users\Info Mania\Desktop\projeto_goodwe\goodwe-build\backend"
python scripts\ocpp_simulator.py --url ws://127.0.0.1:8000/ocpp/CH-01 --tag U2 --hold 60
```

**Substitua `U2` pela idTag autorizada do morador do seu banco**. O prefixo `U{id}` só é aceito em development/test; em produção cadastre uma tag física autorizada. Digite a senha OCPP quando solicitada. O simulador envia um ciclo com leitura inicial 1.000 Wh e final 3.500 Wh (= **2,500 kWh**) sem equipamento físico. O backend armazena sessões reais de protocolo marcadas `integration`, mas esta execução é gerada pelo **simulador**.

### Testes

```powershell
cd "C:\Users\Info Mania\Desktop\projeto_goodwe\goodwe-build\backend"
python -m pytest tests\test_ocpp.py -q
```

Os testes cobrem autenticação do morador, transação, medição, término e custo. Os arquivos TypeScript podem ser validados em `frontend/` com `npm run build`.

## Segurança e operação real

- O endpoint WebSocket rejeita dispositivo não provisionado, senha inválida e conexões sem subprotocolo `ocpp1.6`. Senhas aleatórias só são retornadas no provisionamento/rotação; banco armazena hash SHA-256 de segredo aleatório de 256 bits.
- Use `WSS`/TLS com certificado válido, firewall e **JWT_SECRET** aleatório em produção. Configure tamanho máximo de frames no servidor WebSocket (por exemplo, `uvicorn --ws-max-size 65536`). Não exponha o serviço com credenciais de demonstração.
- O sistema registra solicitações administrativas no histórico de auditoria.
- Eventos SSE e conexões OCPP utilizam **registro em memória no processo**. Para escalar em produção para múltiplos workers/máquinas, use Redis/pub-sub + broker compartilhado para OCPP, e ajuste sessões/distribuição, evitando inconsistência de conexão. Execute um único worker no desenvolvimento.
- Após queda de conexão sem `StopTransaction`, uma sessão real continua em andamento para reconciliação operacional; o sistema **não inventa** um horário, kWh ou valor final.
- Para um parque real de recarga são necessárias homologação dos modelos/firmware, monitoração, retry/reconciliação de mensagens, backups, migrações e política de operação/segurança.

## Rotas adicionadas

`GET /api/events` · `GET /api/ocpp/devices` · `GET /api/ocpp/my-tag` · `GET /api/ocpp/tags` · `POST /api/ocpp/tags` · `DELETE /api/ocpp/tags/{tag_id}` · `POST /api/ocpp/chargers/{id}/provision` · `POST /api/ocpp/chargers/{id}/rotate` · `POST /api/ocpp/chargers/{id}/availability` · `WS /ocpp/{ocpp_id}`.
