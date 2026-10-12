<div align="center">

# EV ChargeOps e soluções sustentáveis

### Transparência energética, gestão consciente e caminhos para uma operação mais eficiente

[![Energia](https://img.shields.io/badge/Energia-Medição%20e%20transparência-1D3850)](#contribuições-atuais) [![ODS](https://img.shields.io/badge/ODS-Alinhamento%20potencial-1F5449)](#alinhamento-com-os-ods) [![Estado](https://img.shields.io/badge/Impacto%20ambiental-Ainda%20não%20quantificado-70323F)](#o-que-ainda-não-é-possível-afirmar)

[← README principal](../README.md) · [Documentação OCPP](OCPP.md)

</div>

<img src="assets/12-sustentabilidade.svg" alt="Infográfico ilustrativo sobre medir, entender, planejar e evoluir a gestão de recargas" width="100%" />

## Por que sustentabilidade faz parte deste projeto?

A expansão dos veículos elétricos aumenta a importância de **infraestrutura de recarga confiável e bem gerida**. Em condomínios, saber *quem utiliza*, *quanto consome*, *em qual equipamento* e *em que momento* é uma base prática para planejar capacidade, custos e manutenção.

O **EV ChargeOps** atua como camada de **informação operacional**: coleta/organiza dados de consumo, oferece históricos e estimativas e ajuda a identificar comportamentos que merecem investigação. Isso **pode apoiar** medidas de eficiência — mas o software, por si só, **não demonstra redução de emissões ou consumo**.

## Contribuições atuais

| Recurso do projeto | Relevância potencial para gestão energética | O que está efetivamente implementado |
|---|---|---|
| Consumo em kWh por sessão | Torna o uso mensurável, ajuda a entender demanda | Registro de sessões e medição; OCPP quando conectado |
| Histórico e custos | Apoia prestação de contas e visibilidade por período | APIs, painéis, exportação e faturas demonstrativas |
| Status dos equipamentos | Ajuda a identificar indisponibilidade e melhorar operação | Status centralizado, SSE e atualização via OCPP |
| Previsão estatística | Ajuda a antecipar tendência de demanda | Previsão indicativa baseada no histórico mensal |
| Agrupamentos e anomalias | Sinaliza padrões que merecem revisão técnica | Clustering e detecção de ocorrências fora do padrão |
| Perfil de síndico e morador | Permite ao usuário entender seu próprio consumo | Controle de acesso e painéis autorizados |

**Leituras reais dependem de equipamento conectado e homologado.** Os dados do seed e a maior parte da demonstração local são simulados.

## Melhorias sustentáveis propostas

### 1. Carregamento com decisão por horário

**Ideia:** permitir que o usuário escolha horários e que a administração conheça os picos de demanda para incentivar o uso em horários mais adequados.

- Integrar tarifa horária, se aplicável à instalação.
- Exibir custo estimado por janela de carregamento.
- Sugerir períodos alternativos de menor demanda.
- Estudar perfis e limitação de potência com comandos OCPP apropriados.

**Situação:** proposta. O projeto atual **não implementa Smart Charging OCPP (`SetChargingProfile`)** nem programação automática de carga.

### 2. Integração com geração fotovoltaica

**Ideia:** cruzar energia produzida por sistema fotovoltaico com demanda dos carregadores e consumo da instalação.

- Medir separadamente a geração solar e a energia fornecida aos veículos.
- Registrar parcela de energia de fontes renováveis com metodologia documentada.
- Visualizar oferta solar versus demanda de carregamento.
- Projetar integração de API/inversor/medidor compatível em uma fase futura.

**Situação:** proposta. **Não existe integração fotovoltaica comprovada nesta versão do repositório.**

### 3. Indicadores de desempenho energético

**Ideia:** adicionar métricas históricas, por exemplo:

| Indicador futuro | Fórmula ou regra conceitual | Dados necessários |
|---|---|---|
| Energia carregada (kWh) | Soma do consumo das sessões válidas | Medições finais/iniciais e reconciliadas |
| Pico de uso | Maior potência simultânea em período | Leituras temporais de potência das estações |
| Taxa de ocupação | Tempo ocupado / tempo disponível | Linha do tempo confiável de estados por conector |
| Fator de utilização | Energia transferida / capacidade teórica no período | Potência nominal e período operacional |
| Participação renovável | Energia renovável atribuída / energia total | Medição de geração e regra de alocação |
| Emissões estimadas | Consumo elegível × fator de emissão aplicável | Fatores oficiais, fronteiras e método documentado |

**Atenção:** não somar emissões evitadas sem estabelecer linha de base, matriz energética, origem da energia e método de comparação; um número isolado de kWh não permite concluir o quanto de CO₂ foi reduzido.

### 4. Transparência e comportamento de consumo

**Ideia:** apresentar ao morador gráficos simples de evolução, alertas de desvios e comparações consigo mesmo, respeitando a privacidade. O objetivo é incentivar escolhas conscientes — **sem expor o consumo de outros moradores**.

## Possível jornada de evolução

```mermaid
flowchart LR
    A[Medir consumo<br/>por sessão] --> B[Consolidar dados<br/>de cada estação]
    B --> C[Identificar demanda<br/>e padrões]
    C --> D[Simular cenários<br/>de operação]
    D --> E[Integrar tarifa<br/>e energia renovável]
    E --> F[Avaliar resultados<br/>com metodologia]
```

Os três primeiros estágios já possuem suporte parcial ou direto no projeto atual, dependendo da fonte de dados. Os últimos são **oportunidades de desenvolvimento**, não benefícios mensurados.

## Alinhamento com os ODS

A proposta pode ser relacionada, **conceitualmente**, a objetivos da Agenda 2030, sem afirmar certificação ou alcance de metas:

- **ODS 7 — Energia limpa e acessível:** transparência e possível integração futura com renováveis.
- **ODS 9 — Indústria, inovação e infraestrutura:** software e interoperabilidade de infraestrutura de recarga.
- **ODS 11 — Cidades e comunidades sustentáveis:** apoio ao planejamento de pontos de recarga em condomínios.
- **ODS 12 — Consumo e produção responsáveis:** informação e rastreabilidade de consumo.
- **ODS 13 — Ação climática:** possibilidade de mensurar indicadores futuros, ainda não apurados nesta etapa.

## O que ainda não é possível afirmar

> [!WARNING]
> **Não há evidência no código apresentado para divulgar** redução de emissões de CO₂, economia de energia obtida, percentual de energia renovável, carregamento automático fora do pico, controle inteligente de demanda ou desempenho real de hardware GoodWe.

Esses resultados exigem coleta real, comparação antes/depois, validação de qualidade dos dados e metodologia transparente.

## Como isso valoriza o projeto

A melhoria sustentável mais concreta deste estágio é transformar **consumo elétrico em informação acessível**. O projeto aproxima operação, transparência e inteligência analítica; oferece uma base técnica para próximos passos de eficiência energética, sem confundir **potencial futuro** com **impacto já comprovado**.

---

[← Voltar ao README principal](../README.md)
