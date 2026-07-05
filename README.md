# ☀️ APOLO AI

---

> ## 🦾 Estamos construindo o JARVIS do Homem de Ferro — mas o meu, que se chama **APOLO**.
>
> *Tony Stark tinha o JARVIS: uma IA pessoal que entendia tudo, aprendia continuamente, executava tarefas, buscava informações e evoluía junto com ele.*
> *O objetivo do Apolo é o mesmo — uma IA pessoal, local, ilimitada, que cresce com o tempo e se torna cada vez mais inteligente.*
> *Não é um produto. É o meu assistente. É o Apolo.*

---

## O que é o Apolo AI

Apolo (deus do sol e do conhecimento) é um **assistente pessoal de engenharia de software** que roda **100% no seu computador**, sem custo por token, sem limite de uso e sem enviar seus dados para terceiros.

Ele aprende com o tempo — cada conversa, cada pesquisa na web e cada sessão de estudo autônomo alimenta sua base de conhecimento permanentemente. Quanto mais você usa, mais inteligente ele fica.

### Por que Apolo é diferente

| | Apolo AI | ChatGPT / Claude API |
|---|---|---|
| Custo | **R$ 0 / mês** | Paga por token |
| Limite de uso | **Ilimitado** | Cotas e rate limits |
| Privacidade | **100% local** | Dados na nuvem |
| Memória | **Permanente** | Sessão por sessão |
| Aprendizado | **Autônomo e contínuo** | Estático |
| Domínio | **100% técnico, seu foco** | Generalista |

---

## Pipeline de Aprendizado Contínuo

```
[Doc Fetcher]  ─────┐
[Web Fetcher]  ─────┤──► fetch_queue(12) ──► [Summarizer/LLM] ──► [Saver] ──► [Síntese a cada 6]
[Trend Fetcher]─────┤         ▲                                                      │
[GitHub Fetcher]────┘         │ (fila sempre cheia = zero tempo ocioso)             │
                              │                                                      ▼
       self_queue ◄──────────┴────────────── [Auto-Currículo] ◄── extrai "🎯 QUERY:" da síntese
   (A.P.O.L.O. decide o que estudar a seguir — loop de autonomia fechado, zero LLM extra)
```

**Antes (ciclos):** fetch → espera 180s → fetch → espera 180s → …  
**Agora (pipeline):** 4 fetchers em paralelo enchem a fila enquanto Ollama summariza → throughput 2-3x maior  
**Autonomia:** a cada síntese, o A.P.O.L.O. identifica seus próprios gaps e gera 6 novas queries de estudo — que entram com **prioridade** na fila. Ele constrói o próprio currículo.

## Arquitetura do J.A.R.V.I.S.

```
┌─────────────────────────────────────────────────────────────┐
│                        APOLO AI                             │
│                                                             │
│  ┌──────────────┐    ┌──────────────────────────────────┐  │
│  │   Interface  │    │        Mini-Agentes              │  │
│  │   Web UI     │    │  📚 DocCrawler  → docs oficiais  │  │
│  │   FastAPI    │    │  🌐 WebSearch   → DuckDuckGo     │  │
│  │   SSE Stream │    │  📡 TrendRadar  → novidades tech │  │
│  └──────┬───────┘    │  🐙 GitHub      → repos trending │  │
│         │            │  🧠 Synthesizer → síntese cross  │  │
│         │            │  🎯 Auto-Currículo → decide só   │  │
│  ┌──────▼───────┐    └──────────────┬───────────────────┘  │
│  │  qwen2.5-   │                   │                       │
│  │  coder:14b  │◄──────────────────┤                       │
│  │  (Ollama)   │   sumarização LLM │                       │
│  └──────┬───────┘                   │                       │
│         │                           │                       │
│  ┌──────▼───────────────────────────▼──────────────────┐  │
│  │                  Camadas de Memória                  │  │
│  │                                                      │  │
│  │  SQLite ──── histórico de sessões + tópicos         │  │
│  │  ChromaDB ── RAG local (embeddings de código)       │  │
│  │  Supabase ── base de conhecimento na nuvem          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Fluxo de Aprendizado Autônomo

```
Web / Docs
    │
    ▼
Buscar conteúdo (DuckDuckGo / crawl direto)
    │
    ▼
Ler e extrair texto relevante (BeautifulSoup)
    │
    ▼
ENTENDER via LLM (qwen2.5-coder summariza em PT-BR estruturado)
    │
    ▼
Salvar síntese → SQLite + Supabase + ChromaDB
    │
    ▼
Usar nas respostas (RAG + knowledge context)
```

---

## 🔬 Modo Pesquisa Profunda (Deep Research)

Para perguntas complexas, em vez de uma única resposta do LLM, o Apolo ativa um **agente de raciocínio multi-etapas** — o tipo de coisa que o J.A.R.V.I.S. faria:

```
Pergunta complexa
      │
      ▼
1. 🧩 PLANEJA   → decompõe em 3 sub-perguntas investigativas
      │
      ▼
2. 🔎 PESQUISA  → para cada frente, em PARALELO:
      │            ├─ recall semântico da memória (o que já estudou, ChromaDB)
      │            └─ busca fresca na web (DuckDuckGo)
      ▼
3. ✍️ SINTETIZA → funde todas as evidências numa resposta única,
                   técnica e com FONTES NUMERADAS [1] [2] [3]...
```

- O **raciocínio é transmitido ao vivo**: você vê o Apolo decompor, investigar e sintetizar em tempo real
- As respostas **citam tanto a memória interna** (📚) **quanto a web** (🌐) — transparência total
- A síntese roda em **thread separada** para não congelar o pipeline de aprendizado autônomo
- Ative pelo botão **🔬 Profundo** na barra de input

> É aqui que o ciclo do J.A.R.V.I.S. se fecha: o Apolo **usa de verdade** tudo que aprendeu sozinho.

---

## 🔍 Code Review Agent

Cole qualquer código no painel **🔍 Revisar Código** (sidebar) e o Apolo faz uma revisão de engenheiro sênior:

- **Detecta a linguagem** automaticamente (Python, TS, JS, Go, Rust, SQL, Bash) ou você escolhe
- **Recupera boas práticas** que ele mesmo estudou (recall semântico do ChromaDB) e usa como base
- Devolve uma revisão **estruturada por severidade**, em streaming:
  - 🎯 Veredito · 🔴 Críticos · 🟡 Importantes · 🟢 Sugestões · ✅ Código revisado
- Cada achado vem com **o problema, o porquê e a correção em código**
- Cita as memórias internas que apoiaram a análise

> Verificado: numa função com SQL injection, `except` nu e conexão não fechada, o Apolo identificou os três e entregou a query parametrizada correta.

---

## Stack Técnica

| Componente | Tecnologia | Função |
|---|---|---|
| LLM | `qwen2.5-coder:14b` via Ollama | Geração, sumarização, raciocínio |
| Web Framework | FastAPI + uvicorn | API REST + SSE streaming |
| RAG local | ChromaDB | Busca semântica em exemplos de código |
| Conhecimento cloud | Supabase (PostgreSQL) | Base de conhecimento persistente |
| Histórico local | SQLite + SQLAlchemy | Sessões, execuções, tópicos aprendidos |
| Busca web | DuckDuckGo (sem API key) | Pesquisa gratuita e autônoma |
| Fetch de páginas | httpx + BeautifulSoup | Extração de conteúdo de documentação |
| Render frontend | marked.js + highlight.js + DOMPurify | Markdown e syntax highlight |

---

## Mini-Agentes de Aprendizado

O Apolo usa **7 mini-agentes especializados** que rodam em paralelo, mais uma **camada de meta-aprendizado** (Auto-Currículo) que decide o que estudar a seguir:

### 🐙 GitHubAgent *(novo)*
- Monitora **repositórios trending** do GitHub (Python, TypeScript, Go, Rust)
- Lê **READMEs de 20 projetos de referência** (FastAPI, Polars, uv, Ruff, LangGraph, Qdrant, Temporal...)
- Aprende com código real de produção, não apenas documentação
- Categoria: `github`

### 📚 DocCrawlerAgent
- Faz crawl direto em **78 URLs de documentação oficial multi-setor**
- Fontes: Python, FastAPI, SQLAlchemy, Pydantic, Docker, Kubernetes, AWS, dbt, Kafka, Terraform + **MDN/JS, React, TypeScript, Tailwind, Rust, Go, Flutter, React Native, PyTorch, scikit-learn, Hugging Face, Polars**
- Detecta URLs já estudadas (deduplicação)
- Categoria: `official_doc`

### 🌐 WebSearchAgent — **estudo em leque (multissetorial)**
- Busca **322 tópicos em 52 setores** no DuckDuckGo, em **rodízio por setor** (`src/topics.py` → `interleave`)
- **Tech (20 setores):** backend/APIs, frontend/web, mobile, data/ML, data engineering, sistemas (Rust/Go/C++), devops/cloud, SRE/confiabilidade, bancos, segurança, agentes de IA, game dev, gráficos/XR, embarcados/IoT, blockchain, fundamentos de CS
- **Conhecimento geral (32 setores):** ciência, matemática, finanças/economia, produtividade/aprendizado, comunicação/idiomas, design/UX, negócios/produto, carreira, direito/compliance (LGPD), saúde/mente, história/filosofia, artes/criatividade, **medicina & saúde, psicologia, educação, meio ambiente, culinária & nutrição, astronomia, geografia & geopolítica, marketing & vendas, esportes & fitness, engenharia (física)**
- Cada estudo consecutivo vem de um setor diferente — ele varre o leque em vez de afundar num só assunto
- Categoria: `web_search`

### 📡 TrendAgent
- Monitora **novidades e tendências tech** (70 queries, multi-setor)
- Rastreia: Python 3.13/3.14, frontend (React 19, signals), mobile (KMP, Flutter), sistemas (Rust, Zig, WASM), segurança (passkeys, pós-quântico), LLMs locais, agentes autônomos, blockchain L2, game engines
- Shuffling aleatório para variedade
- Categoria: `tech_trend`

### 📚 EncyclopediaAgent *(novo — conhecimento geral, fora da tech)*
- Estuda artigos da **Wikipédia em português** sobre ciência, filosofia, história, arte, saúde, sociedade, espaço...
- Usa a **API oficial da Wikimedia** (o scraping de HTML retorna 403) — texto limpo direto
- Deduplica artigos já estudados. Categoria: `encyclopedia`

### 📖 BookAgent *(novo — sabedoria aplicável)*
- Aprende as **ideias centrais de livros de não-ficção influentes** (Hábitos Atômicos, Sapiens, Pense Rápido e Devagar, Mindset, Antifrágil...)
- Cobre psicologia, hábitos, filosofia, negócios, ciência. Categoria: `books`

### 🧠 SynthesisAgent
- Roda **a cada 6 itens** salvos pelos outros agentes
- Pega os últimos 30 tópicos, agrupa por domínio (`_cluster_topics`) e gera uma **síntese estratégica cross-domain**
- Identifica padrões, conexões entre tecnologias, gaps e recomenda próximos estudos
- Categoria: `synthesis`

### 🎯 Auto-Currículo *(novo — núcleo da autonomia)*
- **O A.P.O.L.O. decide sozinho o que estudar a seguir.**
- A cada síntese, ele lista as lacunas do próprio conhecimento como queries `🎯 QUERY: ...`
- O motor extrai essas queries (**sem nenhuma chamada extra de LLM** — parsing puro) e as injeta na `self_queue`
- Essa fila tem **prioridade** sobre a rotação fixa: o que o A.P.O.L.O. decidiu estudar vem primeiro
- Resultado: um **loop de automelhoria fechado** — quanto mais ele aprende, melhor escolhe o próximo estudo
- Categoria: `self_directed`

### Estratégia de Orquestração

```
Fetchers paralelos:  DocCrawler + WebSearch + TrendRadar + GitHub  (enchem a fila)
Summarizer:          consome a fila, 1 LLM por vez (serializado)
A cada 6 itens:      Synthesizer  → gera síntese + currículo auto-dirigido
Prioridade na fila:  1º User question  2º Auto-Currículo  3º rotação dos agentes
```

---

## Capacidades Atuais

- ✅ **Chat com streaming** — respostas token a token via SSE
- ✅ **Execução de código** — roda Python e retorna output
- ✅ **Busca na web** — DuckDuckGo em tempo real durante o chat
- ✅ **RAG local** — busca semântica em exemplos de código (ChromaDB)
- ✅ **Base de conhecimento** — Supabase para conhecimento persistente
- ✅ **Sessões persistentes** — conversas sobrevivem a reinicializações
- ✅ **7 mini-agentes paralelos** — Doc, Web, Trend, GitHub, Enciclopédia, Livros, Synthesizer
- ✅ **Pipeline IO/CPU sobreposto** — 4 fetchers paralelos, fila de 12, zero tempo ocioso
- ✅ **Síntese cross-domain** — clustering por domínio, mapa de integração, gaps identificados
- ✅ **Throughput ao vivo** — painel mostra itens/hora e profundidade da fila
- ✅ **Base de Conhecimento navegável** — busca + filtros + sínteses completas expansíveis
- ✅ **Títulos de sessão automáticos** — LLM nomeia cada conversa
- ✅ **A.P.O.L.O.** — Agente Pessoal de Operações, Lógica e Otimização
- ✅ **LLM local** — qwen2.5-coder:14b, zero custo, zero privacidade comprometida
- ✅ **🧠 Auto-roteamento de raciocínio (chat mais inteligente)** — o chat decide sozinho quando usar o modelo pesado (14b) vs o leve (`src/routing.py`, `is_complex`). A heurística ficou mais esperta: **uma única pista forte** (arquitetura, otimização, trade-off, refatoração, comparação, "passo a passo", "prove"…) numa pergunta com substância já escala para o 14b — antes exigia 2 pistas, então perguntas difíceis como "como otimizar meu banco?" caíam no modelo leve e recebiam respostas piores. Continua conservador em conversa trivial (o 14b é lento em CPU). Coberto por testes (`tests/test_routing.py`).
- ✅ **⚙️ Perfil de performance ("cérebro no pico")** — `src/hardware.py` centraliza quanto da máquina usar, via `APOLO_PERFORMANCE`:
  - `balanced` (padrão) — libera RAM entre tarefas pesadas (bom p/ uso compartilhado).
  - `max` (máquina **dedicada**, CPU-only) — mantém o **modelo pesado quente** (sem recarregar do disco a cada tarefa) e usa **contexto maior** (`APOLO_NUM_CTX`, padrão 8192 — o modelo "enxerga" mais código de uma vez, ficando mais capaz), além de `APOLO_NUM_THREAD` para fixar as threads. As opções são mescladas em **toda** chamada de inferência (o chamador tem prioridade). O painel **Saúde** mostra o perfil ativo, threads/CPUs, contexto e se o modelo está quente. Recomendações no `.env.example`. (Teto realista de uma máquina 16 GB sem GPU: um modelo **14B** — um 32B não cabe.) Coberto por testes (`tests/test_hardware.py`).
- ✅ **🧬 Motor de inferência intercambiável (soberania total)** — o A.P.O.L.O. fala com um **provedor de LLM** abstrato (`src/providers.py`), então o motor por baixo é trocável por variável de ambiente, **sem mexer no resto do código**:
  - `LLM_BACKEND=ollama` (padrão) — usa o Ollama local.
  - `LLM_BACKEND=llamacpp` — usa um **motor próprio embutido** via `llama-cpp-python` (o mesmo llama.cpp que o Ollama embrulha), rodando **dentro do processo**, sem nenhum serviço externo nem o binário do Ollama. Você baixa os **GGUF** (Hugging Face) uma vez e os aponta em `LLAMACPP_MODELS="qwen2.5-coder:3b=models/q3.gguf;qwen2.5-coder:14b=models/q14.gguf"` (configura `LLAMACPP_CTX`, `LLAMACPP_THREADS`, `LLAMACPP_GPU_LAYERS`). Import preguiçoso: o projeto roda sem a lib instalada enquanto o backend for `ollama`.
  - Tanto o streaming (`stream_chat`) quanto as chamadas discretas (`chat_resilient`) passam pelo provedor; ambos herdam o **retry + circuit breaker**. Coberto por testes (`tests/test_providers.py`)
  - **Seleção de modelo agnóstica de backend** — a escolha do modelo leve do chat e do modelo de visão foi extraída para `src/model_select.py` (funções **puras e testadas**: `pick_chat_model`/`pick_vision_model`) e passou a listar modelos pelo **provedor ativo** (`_installed_models`), não mais por `ollama.list()` direto — então funciona igual no motor próprio. Coberto por testes (`tests/test_model_select.py`).
  - **Cobertura total**: *todos* os módulos que usavam `ollama.chat` direto foram migrados para o provedor — **chat, Modo Agente, Coder, aprendizado contínuo (`learner`), mini-agentes, síntese, Pesquisa Profunda e Code Review**. Trocar `LLM_BACKEND` afeta o app **inteiro**, não só o chat. A listagem de modelos (`/api/models`, painel Saúde) também vem do provedor ativo, e o painel **Saúde** mostra qual **backend** está rodando (Ollama ou motor próprio).
- ✅ **Interface JARVIS** — painel de aprendizado ao vivo, start/stop separados, auto-refresh
- ✅ **Tela inicial premium** — hero com título em gradiente e 4 cards clicáveis que lançam Pesquisa Profunda, Code Review, o painel de aprendizado e a Mente do A.P.O.L.O.
- ✅ **🧠 Mente do A.P.O.L.O.** — painel de auto-percepção: mostra tudo que ele já aprendeu (total, **barras por setor** — 52 setores classificados automaticamente —, barras por categoria/agente, principais fontes, próximos estudos do auto-currículo e aprendizados recentes), fundido com o estado vivo do aprendizado
- ⚡ **Varredura de performance (Mente, Mapa, Saúde)** — vários painéis carregavam devagar por varrerem centenas/milhares de linhas e refazerem trabalho a cada abertura. Otimizações, **sem perder nenhuma informação**:
  - **Mente** (`/api/knowledge/insights`) — `insights` **cacheados** (TTL 120 s, invalidado a cada novo conhecimento salvo) + as 3 fontes (insights + aprendizado + linha do tempo) buscadas **em paralelo** (`asyncio.gather`).
  - **`classify_sector` com `lru_cache`** — era o gargalo de CPU (percorria 52 setores × palavras-chave por linha). Função pura chamada milhares de vezes nos painéis e **a cada save** do aprendizado; tópicos repetidos saem de graça (~1000 classificações em <1 ms).
  - **Mapa** (`/api/knowledge/graph`) — cache curto (60 s) para não reconstruir o grafo do zero a cada abertura.
  - **Caches unificados (DRY)** — a lógica `(valor, timestamp)` que estava reimplementada à mão em cada cache virou um utilitário único e testado: `TTLCache` (`src/cache.py`, com `get`/`set`/`peek`/`invalidate`), agora usado pelo cache da Mente (`knowledge.insights`) e pela qualidade do recall (`rag.recall_quality`). Mesmo comportamento, menos duplicação. Coberto por testes (`tests/test_cache.py`).
  - **Saúde** (`/api/health`) — os 4 blocos de I/O de rede (Ollama, banco local, Supabase, qualidade do recall) agora rodam **em paralelo** em vez de em série; a **qualidade do recall** (que fazia ~6 embeddings no Ollama) ganhou cache TTL 90 s (invalidado ao indexar novo exemplo); e `stats()` do Supabase usa `count="exact"` com `limit(1)` (lê só o contador, não baixa todas as linhas).
- ✅ **📊 Telemetria de latência por endpoint** — um middleware mede o tempo de **toda** requisição `/api/*` e acumula, por rota, **média, p95, máximo, contagem e erros** numa janela em memória (`src/telemetry.py`, thread-safe, zero dependências). Exposto em `/api/perf` (e `/api/perf/reset`) e mostrado num cartão **⚡ Latência por endpoint** no painel **Saúde** — cores por faixa (verde <300 ms, amarelo <800 ms, vermelho acima) e botão "Zerar métricas". Serve para **flagrar regressões de performance na hora** (ex.: se a Mente voltar a ficar lenta, aparece aqui). Coberto por testes (`tests/test_performance.py`)
- ✅ **🛡️ Resiliência das chamadas externas (retry + circuit breaker)** — `src/resilience.py` (sem dependências): `retry_call` repete falhas transitórias de rede com **backoff exponencial + jitter**, e o `CircuitBreaker` evita martelar um serviço fora do ar (abre após 5 falhas seguidas, rejeita rápido por 30 s, depois testa em *half-open*). Aplicado aos acessos ao **Supabase** (`save`/`insights`/`stats`): agora um **soluço de rede não descarta mais o conhecimento aprendido** (antes ia direto pra contagem de erros e era perdido) — ele é reenviado; e se o Supabase cair de vez, o A.P.O.L.O. para de travar e degrada graciosamente (a Mente mostra o último cache em vez de vazia). O estado da conexão aparece no cartão **☁️ Supabase** do painel Saúde (**circuit breaker**: fechado/testando/ABERTO). Coberto por testes (`tests/test_resilience.py`)
  - **Ollama também protegido** — `chat_resilient` (em `src/llm.py`) embrulha as chamadas **não-streaming** do Ollama (autocrítica, agente, coder) com retry + um circuit breaker próprio, e o **warmup do boot** agora retenta (o Ollama pode ainda estar subindo). O estado aparece no cartão **🧩 Ollama** da Saúde. O streaming de tokens continua direto (não dá para retentar no meio do fluxo).
  - **Camada de inferência testada** — `stream_chat`, `stream_sync` e `chat_resilient` têm testes diretos (`tests/test_llm.py`) cobrindo streaming, **propagação de erro do worker**, retry de falha transitória e abertura do circuit breaker — com provedor fake, sem depender do Ollama.
- ✅ **🗂️ Breakdown por setor** — cada conhecimento é classificado em 1 dos 52 setores (`classify_sector` em `src/topics.py`): match exato dos tópicos do WebSearch + fallback por palavras-chave para docs/trends/GitHub. Funciona até para o histórico antigo (classificação em tempo de leitura)
- ✅ **⚡ Chat rápido auto-ajustável** — o A.P.O.L.O. escolhe sozinho o melhor modelo leve instalado para o chat (`/api/models`) e o reserva do 14b (que fica para Pesquisa/Review). Se só houver modelos pesados, a interface sugere `ollama pull qwen2.5-coder:3b` e passa a usá-lo automaticamente quando baixado
- ✅ **Síntese inteligente** — Apolo entende o conteúdo, não apenas armazena
- ✅ **🌐 Estudo em leque (multissetorial)** — 322 tópicos em **52 setores** (20 de tech + 32 de conhecimento geral) em rodízio por setor: cada estudo consecutivo vem de uma área diferente, em vez de afundar num só assunto (`src/topics.py`)
- ✅ **Foco em autonomia** — IA autônoma, automelhoria e meta-aprendizado seguem como setor-missão dentro do leque
- ✅ **Aprendizado auto-dirigido** — 🎯 o Apolo gera o próprio currículo a partir dos gaps que identifica (loop fechado, zero LLM extra)
- ✅ **Modelo de sumarização configurável** — `SUMMARIZE_MODEL` permite um modelo menor/mais rápido só para sínteses
- ✅ **🔬 Modo Pesquisa Profunda** — raciocínio multi-etapas: decompõe a pergunta, investiga memória + web em paralelo e sintetiza uma resposta fundamentada e **citada**, transmitindo o raciocínio ao vivo. **Nº de frentes adaptativo** (2 para perguntas simples, até 5 para complexas/longas); as **fontes web são reranqueadas** por relevância à sub-pergunta antes da síntese e entram no dossiê **com trecho**; frentes que vêm vazias disparam um **2º round** com a query simplificada (núcleo de palavras-chave); após a síntese, faz uma **autocrítica que complementa** lacunas (adiciona uma seção `## Complemento` se algo importante faltou — aditivo, nunca reescreve; configurável por `RESEARCH_REFINE`); e ao final ele **guarda a descoberta na memória de longo prazo** (Supabase + RAG, categoria `deep_research`) — desde que a síntese seja substancial e embasada em fontes reais — para que pesquisas futuras já partam do que ele descobriu
- ✅ **🧩 Memória + citações no chat do dia a dia** — TODA resposta do chat puxa o recall semântico do ChromaDB (o que ele estudou e os arquivos que você ensinou) e mostra as **fontes citadas [n]** abaixo da resposta. Antes só a Pesquisa/Review faziam isso; agora o aprendizado autônomo deixa o chat normal mais inteligente
- ✅ **🧠 Grounding em paralelo (mais embasado)** — o chat agora consulta **memória semântica (ChromaDB) E base FTS (Supabase) ao mesmo tempo** (`asyncio.gather`), usando as duas fontes para fundamentar a resposta — sem custo de latência (as buscas não somam)
- ✅ **🧠 Modo Inteligente (toggle)** — botão 🧠 na barra de input troca o modelo leve pelo **14b (raciocínio mais profundo)** só naquela mensagem; o resto do chat segue rápido. A resposta ganha um selo "raciocínio profundo (14b)"
- ✅ **📎 Ingestão de arquivos** — solte um arquivo (texto, código, markdown ou PDF) pelo botão 📎 e o A.P.O.L.O. o fatia, indexa no ChromaDB + Supabase e passa a **responder sobre os SEUS documentos e citá-los**. Categoria `user_doc`. PDF requer `pip install pypdf` (texto/código funcionam sem nada extra)
- ✅ **🧹 Curador de Memória** — encontra conhecimento duplicado e propõe manter o melhor de cada grupo. Limpa os **três armazenamentos**: base (Supabase) + índice de recall (ChromaDB) + log de aprendizado (SQLite). Seguro: scan só leitura, remoção explícita. Botão "🧹 Curar" na Mente
- ✅ **🚫 Anti-duplicação na fonte** — o learner não re-estuda tópicos já aprendidos (`is_topic_studied`), e o índice de recall faz upsert por tópico. O dashboard mostra **tópicos únicos** (sem repetição) e os contadores contam conhecimentos distintos
- ✅ **🔁 Política de refresh** — tópicos voltam a ser estudados após `RELEARN_DAYS` (padrão 21) para manter o conhecimento atual, sem voltar a duplicar (upsert por tópico + dedup no dashboard)
- ✅ **🗂️ Filtro por setor + 📈 analytics** — a Base de Conhecimento filtra pelos 52 setores; a Mente tem gráfico de crescimento (14 dias). Classificação cobre ~100% (balde "outros" praticamente zerado)
- ✅ **📅 Digest "o que aprendi hoje"** — botão na Mente que resume os tópicos novos das últimas 24h agrupados por setor (`/api/digest`)
- ✅ **🧠 Memória de conversa longa** — em diálogos longos (>16 msgs), o A.P.O.L.O. resume as mensagens antigas num resumo rolante (atualizado em background) injetado no contexto, então ele lembra do início da conversa mesmo enviando só as últimas mensagens ao modelo
- ✅ **⌨️ Command palette (Ctrl/Cmd+K)** — atalho global abre um menu de navegação rápida com busca: digite e dê Enter para abrir qualquer painel (Coder, Mente, Mapa, Base, Saúde, Code Review, Agendados, Pesquisa, Notificações…). Setas ↑/↓ navegam, Esc fecha. E **Esc fecha qualquer painel aberto**
- ✅ **📄 Exportar conversa em Markdown** — botão 📄 na barra de Conversas baixa a conversa atual como um `.md` legível (título, turnos com avatar e horário) — `/api/session/{id}/export`. Bom para guardar, compartilhar ou versionar uma sessão
- ✅ **💬 Histórico de chats persistente** — todas as conversas (inclusive **antigas**) aparecem na sidebar, sem limite de janela de dias; apagar um chat também remove o título (sem sessões fantasmas) e os órfãos são limpos no startup. O conteúdo fica no SQLite e é restaurado ao reabrir a sessão
- ✅ **🔎 Busca no histórico de conversas** — caixa de busca na sidebar (acima da lista de chats): digita um termo e o A.P.O.L.O. varre **todas** as conversas (`/api/sessions/search`), mostrando o chat e um trecho com o contexto do acerto; clicar abre a conversa. Debounce de 250ms
- ✅ **⬇️⬆️ Backup / Export / Import** — botão ⬇️ na sidebar baixa um JSON com **tudo** (conhecimento do Supabase + sessões/mensagens + tópicos aprendidos; `/api/export`, nome `apolo_backup_AAAAMMDD_HHMMSS.json`); o botão ⬆️ **restaura** esse backup (`/api/import`) de forma **idempotente** — itens já existentes são ignorados (não duplica), então dá pra migrar de máquina ou recuperar sem medo. Seu segundo cérebro fica portável e à prova de perda
- ✅ **🧪 Camada de dados testada** — a lógica de aprendizado/dados do SQLite (`storage.py`) tem cobertura dedicada (`tests/test_storage_learning.py`): anti-duplicação (`is_url_studied`/`is_topic_studied`), contagem e **dedup** de re-estudos (ignorando caixa/espaços), `get_learning_timeline` (tópicos únicos por dia) e o toggle pausa/ativa de agendamentos. Garante que o segundo cérebro não se engane no que já estudou.
- ✅ **⏰ Estudos agendados** — no painel Mente, botão **⏰ Agendar**: defina "estude *tópico* às *HH:MM*" e o A.P.O.L.O. estuda sozinho todo dia naquele horário (scheduler interno, roda enquanto o servidor está ligado; se você ligar depois da hora, ele faz o estudo ao iniciar — *catch-up*). Cada agendamento pode ser **pausado/ativado** (⏸️/▶️) ou removido, e mostra a data do último estudo. Endpoints `/api/schedules` (CRUD)
- ✅ **🩺 Saúde do Sistema** — painel na sidebar (`/api/health`) que consolida o estado num só lugar: modelos do Ollama (chat/pesado/visão), aprendizado contínuo (status, fila, ritmo/h, lacunas, agentes ativos), banco local (conhecimentos, hoje, conversas, **duplicatas**) e Supabase (total, subidos na sessão, **falhas de upload** + último erro). Cada cartão tem um farol ●verde/●vermelho
- ✅ **🗑️ Esquecer conhecimento** — botão 🗑️ em cada item da Base de Conhecimento remove aquele conhecimento **dos três stores de uma vez** (log SQLite, Supabase e índice RAG/ChromaDB), com confirmação — controle manual sobre a memória, para apagar algo errado ou indesejado. `/api/knowledge/forget`
- ✅ **🎯 Recall com rerank híbrido (memória + base) + recência** — tanto a memória semântica (ChromaDB, `rag.recall`) quanto a base de conhecimento (Supabase FTS, `knowledge.search`) não confiam só no ranking bruto do índice: buscam **4× mais candidatos** e os **reordenam** com um reranker compartilhado (`src/rerank.py`) que combina similaridade vetorial + **sobreposição lexical** com a pergunta + **boost por recência** (conhecimento recém-estudado pesa mais — decaimento com meia-vida de 90 dias, ativo **nas duas memórias**: Supabase via `updated_at` e ChromaDB via `studied_at` carimbado em cada `add_example`), ainda **cortando quase-duplicatas** (mesmo título ou conteúdo quase idêntico via Jaccard). Resultado: chat, Modo Agente e Pesquisa Profunda recebem trechos mais relevantes, atuais e sem repetição. Pesos configuráveis no código
- ✅ **🗺️ Mapa de Conhecimento** — no painel Mente, botão **🗺️ Mapa**: um grafo radial em SVG com o núcleo **☀️ A.P.O.L.O.** no centro, os **setores** que ele mais estudou ao redor (tamanho ∝ volume, cores distintas) e **tópicos de exemplo** como folhas. Clicar num setor abre a Base de Conhecimento já filtrada por ele. Dados de `/api/knowledge/graph` (tópicos agrupados por `classify_sector`)
- ✅ **🔔 Notificações (autonomia visível)** — sino na barra superior da sidebar, com **contador de não-lidas**: o A.P.O.L.O. te avisa o que fez sozinho — **estudo agendado concluído** (📚), **lacuna de conhecimento detectada** no chat (🔍), **nova síntese cross-domain** gerada pelo aprendizado (🧠) etc. Dropdown com tempo relativo ("agora", "2h atrás"), botões de marcar todas como lidas (✓) e limpar (🗑️); atualiza a cada 30s. Persistido no SQLite (`notifications`), endpoints `/api/notifications` (GET/POST read/DELETE)
- ✅ **🩺 Saúde: qualidade do recall** — o painel Saúde ganhou o cartão **🎯 Qualidade do recall**: roda tópicos recentes como consultas de teste e mede **score médio**, **relevância vetorial** e **casamento lexical** médios + nº de docs no índice. Um número objetivo para acompanhar se a recuperação de memória está saudável (farol verde/amarelo)
- ✅ **📊 Telemetria de upload de conhecimento** — `/api/knowledge/stats` mostra total no Supabase, quantos artigos subiram **nesta sessão**, falhas de upload e o último erro; o indicador "Supabase" na sidebar avisa (⚠️) se algum save falhar — você sabe na hora se o conhecimento está subindo de verdade
- ✅ **👁️ Visão (analisar imagens)** — botão 🖼️ na barra de input: anexe um print, diagrama ou foto e o A.P.O.L.O. *enxerga* e responde, usando um modelo de visão local do Ollama. Auto-detecta o modelo instalado; se não houver, orienta `ollama pull llava`. A imagem aparece na sua mensagem e é roteada para o modelo de visão
- ✅ **💻 A.P.O.L.O. Coder (um "Claude Code" interno)** — botão **💻 A.P.O.L.O. Coder** na sidebar: você descreve uma tarefa de código e ele a executa de verdade num **workspace isolado** (`./workspace`, configurável por `APOLO_WORKSPACE`), em loop ReAct, escolhendo a cada passo **uma ação**: 📂 **LISTAR** diretório, 📖 **LER** arquivo, ✍️ **ESCREVER** arquivo (conteúdo completo) e ⚙️ **RODAR** comando de shell — então usa a **saída real** para corrigir e seguir até concluir. **Sandbox seguro**: todo caminho é confinado à raiz (proteção contra path traversal), extensões de escrita restritas a texto/código, e comandos catastróficos (`rm -rf /`, fork bomb, `git push`…) são bloqueados. Se escreveu código e não testou, o A.P.O.L.O. é **forçado a rodar uma verificação** antes de concluir. Painel com o trace das ações + árvore viva do workspace, e um seletor **🧠 Leve / 14b** para escolher entre o modelo rápido (`qwen2.5-coder` leve) e o **14b mais inteligente** para tarefas difíceis. Cada arquivo escrito mostra um **diff colorido** (verde/vermelho, estilo Claude Code) com a contagem `+linhas/-linhas` e se **criou** ou **alterou**.
  - **✏️ Edição cirúrgica (EDITAR)** — além de ESCREVER (arquivo inteiro), o Coder agora tem a ação **EDITAR** — a ferramenta-assinatura do Claude Code: troca um **trecho exato** por outro (marcadores `<<<<<<< / ======= / >>>>>>>`), exigindo que o trecho apareça **uma única vez** (senão erro acionável). É a forma **preferida** de mudar arquivos existentes: reduz drasticamente o risco de destruição (não dá para apagar um arquivo editando 3 linhas) e funciona muito melhor com modelos locais (eles só geram a região alterada, não o arquivo todo). Reversível, com diff colorido. Cobertura em `tests/test_coder_edit.py`.
  - **↩️ Histórico & Desfazer** — toda escrita vira um snapshot; o painel lista as mudanças da sessão e você pode **desfazer por arquivo** ou **descartar tudo** (reverte ao conteúdo anterior; arquivos novos são removidos). É o "aplicar → revisar → descartar" — o agente precisa gravar para rodar os testes, então a confirmação vem na forma de revisão/undo.
  - **📁 Pasta configurável + 📂 navegador de pastas** — por padrão o workspace é isolado (`./workspace`), mas você pode **apontar para uma pasta de projeto real** (com confirmação) para o Coder trabalhar nela; o confinamento e o histórico passam a valer para aquela raiz. Além de digitar o caminho, há um botão **📂 Procurar** que abre um **navegador de pastas do servidor** (`/api/coder/browse`) — você navega entrando nas subpastas e subindo com `.. (voltar)`, vê o caminho atual e clica em **✓ Usar esta pasta**. Esconde ruído (`__pycache__`, `node_modules`, `.git`, `venv`).
  - **🎨 Visual refinado** — o painel do Coder foi limpo: classes CSS dedicadas (`.coder-bar`/`.coder-field`/`.coder-btn`/`.coder-pane`) no lugar de estilos inline, botões com hover e cores por função (verde = executar, azul = VS Code, violeta = automelhoria), campos com foco destacado, cabeçalho com divisória e painéis com títulos em caixa-alta sutil.
  - **🔎 Busca no workspace** — duas ações para o Coder se orientar em projetos grandes antes de editar: **BUSCAR** (grep de conteúdo, retorna `arquivo:linha: trecho`) e **ACHAR** (lista arquivos por nome/caminho). Ignora `.git`, `node_modules`, `__pycache__`, `venv` etc.
  - **📚 CONSULTAR a própria base (RAG) — o ciclo learner→coder fechado** — nova ação do Coder: quando trava num erro, conceito ou API que não conhece, ele **pergunta à base de conhecimento** que a IA já estudou (`CONSULTAR <pergunta>`, ícone 📚) em vez de chutar. Reusa o mesmo recall do chat (`_agent_recall`). E é uma via de mão dupla: se a base **não** tem nada relevante, o Coder registra o assunto como **lacuna de conhecimento** (`note_gap` + fila de estudo prioritária) — o que ele não sabia hoje vira tópico de estudo do aprendizado autônomo. Tolera flexão do verbo (CONSULTE) e o sinônimo LEMBRAR.
  - **🌐 BUSCAR_WEB — o Coder pesquisa na web** — quando nem a base local resolve (fatos atuais, docs de biblioteca, uma mensagem de erro específica), o Coder pesquisa na **web** (`BUSCAR_WEB: <consulta>`, ícone 🌐) com a mesma infra do chat (`web_research` → DuckDuckGo + fetch das top páginas, timeout 20s). Fecha a pirâmide de conhecimento do Coder: **workspace** (LER/BUSCAR) → **memória da IA** (CONSULTAR) → **web** (BUSCAR_WEB). Parser distingue rigorosamente `BUSCAR` (grep local) de `BUSCAR_WEB` (web) — nunca confunde os dois.
  - **⎇ Git integrado** — quando o workspace é um repositório, o painel mostra o **branch, se há alterações pendentes e quantos commits à frente**, com um **diff colorido** (verde/vermelho) num clique (`/api/coder/git`, `/api/coder/git/diff`). Read-only e seguro; commits/push continuam por sua conta no terminal
  - **⌨️ Terminal do workspace** — um campo de comando (`$ …`) executa comandos **direto no workspace** (sem o loop LLM), com saída ao vivo — útil para rodar `python -m pytest`, `ls`, `git status` etc. na hora. Mesmas proteções (confinamento + comandos catastróficos bloqueados). `/api/coder/exec`
  - **👁️ Explorador de arquivos** — a lista de arquivos do workspace é **clicável**: um clique abre um visualizador read-only com o conteúdo (`/api/coder/read`), para inspecionar sem rodar tarefa; do visualizador dá para **apagar** o arquivo (🗑️, reversível)
  - **🗑️ Apagar + ✏️ Renomear + 🔁 Buscar-e-substituir** — apagar arquivos, renomear/mover, e **substituir um texto por outro em TODOS os arquivos** de uma vez (refactor) — tudo **reversível** (cada operação vira um snapshot no histórico). Disponível como ações do agente (`APAGAR`, `MOVER a ==> b`, `SUBSTITUIR x ==> y`) e como ferramentas diretas no painel (`/api/coder/delete`, `/api/coder/move`, `/api/coder/replace`)
  - **⚙️ Saída de comando ao vivo** — comandos longos (`pytest`, `npm install`, build…) transmitem a saída **linha a linha em tempo real** no painel (evento `cmd_line`), com **watchdog de timeout** que mata o processo se travar. Nada de esperar congelado até o fim.
  - **⧉ Abrir no VS Code** — botão **⧉ VS Code** ao lado da pasta abre o workspace inteiro no VS Code, e cada arquivo no visualizador tem um **⧉** que abre aquele arquivo direto na linha certa (`code -g arquivo:linha`). Usa a CLI `code` do VS Code; se ela não estiver no PATH, o A.P.O.L.O. avisa como instalá-la (no VS Code: `Ctrl+Shift+P → Shell Command: Install 'code' command in PATH`). Confinado ao workspace (não abre nada fora da raiz). `/api/coder/vscode`
  - **🛡️ Salvaguardas de automelhoria** — automelhoria autônoma é perigosa com modelos fracos (um 3B chegou a reescrever um módulo inteiro para encaixar uma alucinação). Três redes de proteção: (1) **guarda de regressão** — se o workspace tem suíte de testes, o Coder mede o baseline (verde/vermelho) no início e, ao concluir, **revalida**; se as alterações deixaram a suíte vermelha (estando verde antes), **desfaz tudo automaticamente** (`undo_all`) em vez de "concluir" quebrado; (2) **guarda anti-reescrita catastrófica** — `write_file` **bloqueia** sobrescrever um arquivo não-trivial (≥20 linhas) por uma versão <35% do tamanho, orientando o uso de `SUBSTITUIR` (cobertura em `tests/test_coder_security.py`); (3) o modo **🧬 Auto-melhorar força o modelo 14b** (o leve é proibido aqui). A doutrina também instrui: ImportError = conserte seu teste, não destrua o módulo.
  - **🧪 Automelhoria em cópia segura** — o botão **🧬 Auto-melhorar** agora trabalha numa **cópia isolada** do projeto (`src/sandbox.py`, `/api/coder/sandbox`), não nos arquivos ao vivo. A cópia exclui runtime (`data/`, `logs/`), caches e **o `.env` (segredos nunca são copiados)**. Você roda a automelhoria na cópia (com a guarda de regressão), clica em **🧪 Revisar cópia** para ver a lista de mudanças (🟢 novo / 🟡 alterado / 🔴 removido) e o **diff colorido** de cada arquivo, e então decide **✅ Aplicar ao projeto** ou **🗑️ Descartar**. O servidor ao vivo nunca é tocado por estados intermediários. Endpoints `/api/coder/sandbox[/diff|/file|/apply|/discard]`. Coberto por testes (`tests/test_sandbox.py`).
  - **🧬 Automelhoria direta (A.P.O.L.O. Code)** — `/api/coder/self` ainda aponta o Coder direto para o próprio código (sem cópia) para quem quiser o fluxo antigo. O Coder opera guiado pela **doutrina A.P.O.L.O. Code** (`A.P.O.L.O._Code.md`) — um manual com toda a metodologia de engenharia de elite: ciclo ReAct, leis da boa engenharia, **protocolo de verificação real** (`py_compile`/`node --check`/`pytest`/`TestClient`), autocorreção, o **loop de automelhoria** (mapear → medir → aplicar → provar → atualizar README → iterar) e um mapa mental do codebase. A doutrina condensada é injetada no system prompt do Coder (`CODER_DOCTRINE`), e o manual completo fica no projeto para o Coder `LER` quando precisar. As barreiras de segurança (comandos catastróficos, `git push`, sair do workspace, vazar segredos) permanecem — protegem a máquina, não limitam a engenharia.
  - **🛡️ Sandbox coberto por testes de borda** — o código de segurança do Coder tem testes dedicados (`tests/test_coder_security.py`): **cada** comando catastrófico bloqueado (`rm -rf /` e `~`, fork bomb, `mkfs`, `dd if=`, `shutdown`/`reboot`, `> /dev/sd`, `chmod -R 777 /`, `git push`), os comandos **seguros que não podem ser bloqueados** (sem falsos positivos: `rm arquivo.txt`, `git commit`, `python app.py`, menção em string…) e o confinamento do `open_in_vscode` (traversal barrado, parse de `arquivo:linha`).
  - **🧠 Memória de lições (autoaprendizado do Coder)** — o Coder agora **aprende com a própria experiência**, como o memory do Claude Code (`src/lessons.py`, `data/lessons.db`). Três fontes de lição: (1) **reflexão pós-tarefa** — ao concluir uma tarefa que escreveu código, uma chamada curta ao modelo leve extrai UMA lição genuína ("erro a evitar / verificação que salvou tempo / padrão deste workspace") e a persiste (`CODER_REFLECT=0` desativa); (2) **lição de regressão automática** — se a guarda de regressão reverteu as mudanças, a falha vira uma lição permanente (com o erro real dos testes), e lições de regressão **pesam mais** no recall; (3) dedup automático (re-aprender a mesma lição não duplica) e **poda automática** — acima de `LESSONS_MAX` (padrão 300), as lições menos usadas/mais antigas saem sozinhas (regressões têm proteção extra). No início de **cada tarefa**, as lições relevantes (recall lexical por sobreposição de tokens, sem custo de LLM) são **injetadas no system prompt** — o Coder vê "🧠 Aplicando N lição(ões)" e literalmente não repete o erro que já pagou para aprender. O painel do Coder tem a seção **🧠 Lições aprendidas** (contador, ícone por tipo, tooltip com a tarefa de origem/data/nº de usos, e 🗑️ para esquecer uma lição errada — curadoria manual). Endpoints `GET /api/coder/lessons` e `DELETE /api/coder/lessons/{id}`. Coberto por testes (`tests/test_lessons.py`).
  - **🗜️ Compactação de contexto do loop** — em tarefas longas, o histórico ReAct (arquivos lidos, saídas de comando) estourava a janela de 8192 tokens e o modelo **"esquecia" a tarefa e o plano** (que estão no início da conversa). Agora, acima de `CODER_CTX_CHARS` (padrão 20000 chars), as observações antigas do miolo são truncadas — **head (tarefa + plano) e as últimas mensagens ficam intactos**, mesma estratégia do compact do Claude Code (`compact_messages` em `src/coder.py`, testado).
  - **⚡ Verificação sintática instantânea** — após todo ESCREVER/EDITAR em arquivo `.py`, o Coder roda `py_compile` **automaticamente** (custo ~0, sem LLM): erro de sintaxe é devolvido ao modelo NA HORA ("⚠️ VERIFICAÇÃO AUTOMÁTICA"), em vez de só explodir num RODAR três passos depois.
  - **📚 Loop fechado Coder → Learner** — quando a guarda de regressão reverte uma tarefa, o tema da falha é **enviado ao autoaprendizado** (`note_gap` + fila prioritária do learner): o A.P.O.L.O. estuda o assunto sozinho antes da próxima tentativa. Falhar → aprender → tentar melhor: o ciclo de autonomia completo.
  - **📖 Leitura parcial de arquivos grandes** — `LER caminho:10-80` mostra só a faixa de linhas pedida; e quando uma leitura completa trunca (>6000 chars), a mensagem **ensina o próximo comando exato** ("use LER arquivo:214-334 para continuar"). O Coder navega qualquer tamanho de arquivo sem estourar o contexto.
  - **🔁 Anti-loop + 🩹 resgate de resposta malformada** — repetir a MESMA ação com o MESMO alvo é sinal de modelo travado: na 1ª repetição o Coder recebe um aviso explícito ("tente uma abordagem DIFERENTE"), na 3ª o loop é encerrado e ele conclui com o que tem (não desperdiça os 12 passos). E se o modelo despejar código solto (bloco ``` sem `ESCREVER`/`EDITAR`) ou vier vazio — o que antes encerrava a tarefa "concluída" sem gravar nada — um resgate único devolve o formato correto e pede para refazer.
  - **⚡ Baseline de regressão com cache** — a guarda de regressão rodava a suíte INTEIRA no início de **cada** tarefa (minutos, na CPU). Agora o resultado fica em cache por `CODER_BASELINE_TTL` (padrão 15 min), revalidado no fim de cada tarefa que escreve, e **invalidado automaticamente** por qualquer mudança feita por fora (terminal do workspace, apagar/mover/substituir, undo, troca de pasta, aplicar sandbox). Tarefas em sequência ganham minutos.
  - **📜 Diário de bordo (autonomia visível)** — toda tarefa executada vira um registro persistente no SQLite (`coder_tasks`: passos usados, duração, escreveu/rodou, **revertida pela guarda?**). O painel mostra as tarefas recentes com **taxa de sucesso** (ex.: "12 · 92% ✓") — um número objetivo para acompanhar se o Coder está melhorando com as lições. `GET /api/coder/tasks`.
  - **⏹ Parar tarefa** — durante a execução o botão vira **⏹ Parar**: um clique interrompe a tarefa na hora (AbortController); as alterações já feitas ficam no histórico (dá para desfazer). Essencial com o 14b na CPU, onde uma tarefa pode levar muitos minutos.
  - **✏️ EDITAR com dica do trecho real** — a maior causa de edição falha em modelo local é o trecho BUSCAR diferir do arquivo por um detalhe (indentação, espaço, aspas). Agora, quando o trecho exato não casa, o erro mostra **o bloco REAL mais parecido do arquivo** (difflib, com nº da linha) — o modelo copia dele e acerta na tentativa seguinte, em vez de desistir ou reescrever o arquivo.
  - **📈 Tendência da taxa de sucesso (medir → melhorar → provar)** — o diário de bordo agora compara as **últimas 10 tarefas com as 10 anteriores** e mostra a tendência no painel (↗ verde / ↘ vermelho): um número objetivo para saber se as lições aprendidas e as automelhorias estão de fato tornando o Coder melhor.
  - **🎯 Memória de Projeto no Coder** — se há um projeto memorizado (botão 🎯), a stack e as dependências entram no system prompt do Coder desde o 1º passo — o mesmo contexto que o chat já usava.
  - **💾 Commit assistido** — quando o workspace é um repositório com alterações pendentes, o painel git ganha o link **💾 commit**: o modelo leve gera a mensagem (Conventional Commits, a partir do diff real) e commita. **Confinado ao workspace** via pathspec (`git add/commit/status/diff -- .`): se o workspace for um subdiretório de um repo maior, nada de fora é tocado (bug real pego em teste ao vivo — o commit varria o repo inteiro — e coberto por teste de regressão). **Nunca faz push** — enviar ao remoto é sempre decisão sua. `POST /api/coder/commit` (aceita `message` própria).
  - Endpoints `/api/coder` (SSE, eventos `step`/`diff`/`token`/`done`), `/api/coder/files` (árvore + mudanças), `/api/coder/lessons` (memória de lições), `/api/coder/undo` e `/api/coder/workspace`
- ✅ **🤖 Modo Agente iterativo (ferramentas + memória + autocrítica)** — toggle 🤖 na barra de input. Loop ReAct de verdade onde, a cada passo, o A.P.O.L.O. escolhe **uma ação**:
  - **🔧 Executar código** Python real (sandbox `CodeExecutor`) — para cálculo/lógica/dados, sempre com o **resultado verdadeiro**; se falha, **lê o erro, corrige e re-executa** (até `MAX_AGENT_FIXES`, via `FIX_PROMPT`)
  - **🌐 Buscar na web** (`BUSCAR_WEB: ...`) quando precisa de fatos atuais
  - **📚 Consultar a própria base/memória** (`CONSULTAR_BASE: ...`) — RAG do que já estudou
  - encadeia até `MAX_AGENT_STEPS` passos antes de responder
  - **🧠 Memória de longo prazo**: no início recupera soluções/conhecimento já produzidos (RAG) como apoio e, ao final, **salva a solução** para uso futuro — com salvaguardas anti-envenenamento (cálculo é **sempre recalculado**, nunca copiado da memória)
  - **🔎 Auto-avaliação**: critica e refina a própria resposta num passe extra (✨) — **nunca** reescreve um número vindo de execução (a saída do código é verdade-base), só respostas de texto/web; resposta final passa por limpeza de vazamentos
  - Tudo configurável por env (`MAX_AGENT_STEPS`, `MAX_AGENT_FIXES`, `AGENT_SELF_EVAL`). Confiável mesmo no modelo leve
- ✅ **🔗 Ingestão por link** — `/learn <url>` (ou colar uma URL) busca a página e a aprende como um documento, citável no chat
- ✅ **🛑 Fim do estudo repetido (anti-repetição em 3 camadas)** — bug real: o aprendizado estudou "Teoria da relatividade" 6× seguidas. Causas e correções em `src/learner.py`: (1) **dedup in-flight** — um tópico só vira "estudado" *depois* do save (~2 min), e nesse intervalo o fetcher o re-enfileirava a cada 3s até lotar a fila com cópias; agora um `set` de tópicos em voo garante **nunca duas cópias do mesmo tópico na fila** (normalizado por caixa/espaços, liberado após salvar — refresh futuro continua possível); (2) **checagem "já estudado" para TODOS os agentes de URL** (`_already_known`: tópico OU URL) — antes só o doc_agent checava, e enciclopédia/GitHub/livros repetiam à vontade; (3) **sumarização no modelo leve por padrão** — com o 14b na CPU toda síntese estourava o timeout de 120s (salvava conteúdo cru truncado, e a geração órfã seguia ocupando o Ollama em cascata); agora sem `SUMMARIZE_MODEL` definido o learner usa o modelo leve do chat (síntese real em ~20-40s). Coberto por testes (`tests/test_learner_dedup.py`).
- ✅ **📊 Qualidade da base visível na Saúde** — o cartão 💾 Banco local agora mostra **"Qualidade das sínteses: N% estruturadas"** (verde ≥90%, amarelo ≥60%, vermelho abaixo), contando via SQL quantos conhecimentos têm síntese estruturada (`##`) vs **crus** (lixo de timeouts antigos) vs curtos. Havendo crus, aparece o atalho **"🩹 N cruas"** que abre a Mente e dispara o reparo direto — você vê o número cair a cada rodada de reparo. `get_summary_quality()` em `storage.py`, exposto em `/api/health`.
- ✅ **⏸️ Estudo resiliente a Ollama fora do ar** — bug real: com o Ollama desligado, o pipeline buscou 48 tópicos na web e **descartou um a um** ("falhou 2×") em minutos, queimando o currículo da sessão. Agora o learner distingue **falha de infraestrutura** (conexão recusada/circuito aberto → **pausa** o estudo, devolve o item à fila sem contar tentativa, avisa 1× via 🔔 e re-checa a cada `LLM_DOWN_BACKOFF=30s`) de **falha de conteúdo** (timeout/síntese ruim → aí sim re-tenta e desiste). `llm_down` exposto no status. E quando o app **sobe com o Ollama fora**, o modelo leve do chat caía no 14b para a sessão inteira — agora o scheduler **re-seleciona o modelo leve sozinho** quando o Ollama volta (chat + sumarização, com notificação ✅). Coberto por testes (`tests/test_learner_dedup.py`).
- ✅ **🩹 Reparo de sínteses cruas** — botão **🩹 Reparar** na Mente: encontra conhecimentos salvos **crus** pelos timeouts antigos (texto truncado sem estrutura `##`) e os **re-sintetiza em segundo plano** com o template certo da categoria, atualizando **in-place** (log SQLite + índice de recall por upsert — sem criar duplicatas). O resultado chega nas 🔔 notificações; rodadas sucessivas reparam o restante (8 por vez, `POST /api/learning/repair`). Falhou a re-síntese? O original é preservado. Coberto por testes (`tests/test_learner_dedup.py`).
- ✅ **📖 Qualidade da síntese (template por categoria + sem lixo)** — três melhorias de qualidade no aprendizado: (1) **template de síntese por categoria** — "Teoria da relatividade" era sintetizada com o template de engenharia de software ("Como usar — código real"), produzindo lixo; enciclopédia/livros agora usam um template enciclopédico próprio (Essência / Pontos-chave / Conexões / Insight); (2) **síntese que falha não vira conhecimento** — antes, todo timeout salvava o conteúdo cru truncado na base fingindo ser síntese; agora re-tenta 1× (sem re-fetch) e, na 2ª falha, **desiste do tópico na sessão sem salvar nada**; (3) **enciclopédia com rotação aleatória e lista ampliada (55 assuntos)** — cada sessão começa num ponto diferente da lista, e o refresh avança a rotação (antes travava sempre no 1º assunto). Coberto por testes (`tests/test_learner_dedup.py`).
- ✅ **🧠 Autoaprendizado mais esperto** — duas melhorias no auto-currículo (`src/learner.py`): (1) **bug corrigido** — o filtro anti-repetição usava `is_url_studied` numa *query de tópico* (que nunca casava), então o A.P.O.L.O. **re-estudava o que já sabia**; agora usa `is_topic_studied` (semântico correto) e não desperdiça ciclos; (2) extração de queries com **dedup normalizado** (ignora pontuação/maiúsculas/espaços — "Redis pub/sub" e "redis pub sub?" são o mesmo tema) e normalização de espaços. Coberto por testes (`tests/test_learner_logic.py`).
- ✅ **🎯 Autoestudo de lacunas** — quando o chat não acha memória sobre o tema, o A.P.O.L.O. marca a **lacuna** e a prioriza na fila de estudo; mostra um aviso na resposta e lista as lacunas no painel Mente
- ✅ **⏹ Parar / ↻ Regenerar** — o botão de enviar vira **Parar** durante a geração (cancela na hora via `AbortController`, preservando o texto parcial); cada resposta tem **Regenerar**
- ✅ **👤 Memória pessoal (Sobre mim)** — fatos sobre VOCÊ (projeto, stack, preferências) ficam guardados (`data/user_profile.json`) e entram no system prompt para personalizar as respostas. Painel "Sobre mim" na sidebar + comando `/remember <fato>`
- ✅ **🎤🔊 Voz** — ditar a mensagem por microfone (Web Speech API) e ouvir a resposta em voz alta (TTS **local** do navegador, pt-BR)
- ✅ **🧪 Cobertura de testes** — **495 testes** (pytest): executor, utils, storage (sessões, notificações, agendamentos, export/import, esquecer), `topics`, `ingest`, `curator`, `rerank` (híbrido + recência), `coder` (sandbox/traversal/diff/undo/busca/stream), `lessons` (memória de lições + compactação de contexto), `research` (frentes adaptativas, refino, dossiê) e mais
- ✅ **🔍 Code Review Agent** — cole qualquer código e o Apolo faz uma revisão de elite (corretude, segurança, performance, arquitetura) usando as boas práticas que estudou, com severidade e correções em código
- ✅ **⚡ Otimização de latência** — `keep_alive` mantém o modelo na memória (sem recarga a cada mensagem), warmup no boot, streaming do chat em thread (não trava o event loop) e timeout na busca da base para não atrasar o 1º token
- ✅ **🎚️ Modelo de chat separado (`CHAT_MODEL`)** — chat do dia a dia usa um modelo leve (resposta rápida na CPU), reservando o 14b para Pesquisa Profunda e Code Review; auto-seleciona o melhor modelo leve instalado
- ✅ **🦾 Prioridade de GPU/CPU ao usuário** — quando você pergunta algo, o aprendizado de fundo cede a vez (GpuGate), eliminando a fila atrás das sínteses do learner
- ✅ **📱 PWA sempre atualizado** — o service worker era cache-first para a página: depois de cada atualização do A.P.O.L.O., o navegador continuava mostrando a **UI velha** até limpar o cache na mão. Agora o HTML é **network-first** (servidor local = latência ~0; o cache vira só fallback offline) e o cache foi versionado (`apolo-v3` purga os antigos na ativação). Assets estáticos e CDNs continuam cache-first.

---

## Estrutura do Projeto

```
Apolo_AI/
├── app.py                    # FastAPI — rotas, streaming, orquestração
├── src/
│   ├── agents/               # Mini-agentes especializados
│   │   ├── base.py           # Classe base: fetch → summarize → persist
│   │   ├── doc_agent.py      # DocCrawler — 78 fontes oficiais multi-setor
│   │   ├── search_agent.py   # WebSearch — estudo em leque (usa topics.py)
│   │   ├── trend_agent.py    # TrendRadar — 70 tendências multi-setor
│   │   ├── github_agent.py   # GitHub — trending + READMEs de referência
│   │   ├── encyclopedia_agent.py # 📚 Enciclopédia — Wikipédia (conhecimento geral)
│   │   ├── book_agent.py     # 📖 Livros — ideias de não-ficção influente
│   │   └── synthesis_agent.py# Synthesizer — síntese cross-domain
│   ├── topics.py             # 🌐 Universo de estudo: 52 setores + interleave + classify_sector
│   ├── ingest.py             # 📎 Ingestão de arquivos/URLs do usuário (chunk + index)
│   ├── curator.py            # 🧹 Curador de Memória — dedup do conhecimento
│   ├── profile.py            # 👤 Memória pessoal sobre o usuário (JSON)
│   ├── learner.py            # Pipeline + Auto-Currículo (loop de autonomia)
│   ├── research.py           # 🔬 Pesquisa Profunda (plano adaptativo → pesquisa → síntese citada → autocrítica → persiste)
│   ├── reviewer.py           # 🔍 Code Review Agent (recall + revisão por severidade)
│   ├── coder.py              # 💻 A.P.O.L.O. Coder — workspace isolado (FS+shell), diff, undo, busca, streaming
│   ├── rerank.py             # 🎯 Reranker híbrido compartilhado (vetorial + lexical + recência + dedup)
│   ├── llm.py                # ⚡ Ollama: keep_alive, streaming sem bloquear o loop, warmup
│   ├── gpu_gate.py           # 🦾 Prioridade de GPU ao usuário sobre o aprendizado de fundo
│   ├── storage.py            # SQLite: execuções, sessões, tópicos
│   ├── knowledge.py          # Supabase: base de conhecimento (+ insights p/ a Mente)
│   ├── rag.py                # ChromaDB: RAG local
│   ├── web_search.py         # DuckDuckGo + fetch de páginas
│   ├── executor.py           # Execução segura de Python
│   ├── prompts.py            # System prompt + templates
│   └── utils.py              # Utilitários
├── static/
│   └── index.html            # Interface web completa
├── data/
│   ├── apolo.db              # SQLite local
│   └── chroma_db/            # Vetores ChromaDB
├── supabase/
│   └── schema.sql            # Schema PostgreSQL
├── tests/
│   └── test_storage.py       # 17 testes (todos passando)
├── .env                      # Variáveis de ambiente
└── requirements.txt          # Dependências
```

---

## Como Rodar

### Pré-requisitos

1. **Ollama** instalado e rodando: https://ollama.com
2. **Python 3.11+**
3. **Supabase** (opcional) — para persistência na nuvem

### Instalar modelo

```bash
ollama pull qwen2.5-coder:14b
```

### Instalar dependências

```bash
pip install -r requirements.txt
```

### Configurar `.env`

```env
OLLAMA_MODEL=qwen2.5-coder:14b
# Modelo leve para o chat do dia a dia (resposta rápida na CPU). O 14b fica
# reservado para Pesquisa Profunda / Code Review. Se vazio, o A.P.O.L.O.
# auto-seleciona o melhor modelo leve instalado (3B > 7B > codellama > 14b).
CHAT_MODEL=
# Opcional: modelo menor/mais rápido só para sumarizar o aprendizado (acelera o estudo).
SUMMARIZE_MODEL=
# Mantém o modelo residente na memória entre as mensagens ("30m", "1h", -1 = sempre).
OLLAMA_KEEP_ALIVE=30m
# Tempo máximo esperando a base de conhecimento antes de responder sem ela.
KNOWLEDGE_TIMEOUT=4
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sua-chave-anon
LEARNING_INTERVAL=180
```

> ⚡ **Velocidade x hardware:** o tempo de resposta é dominado pelo seu hardware. Em
> **máquina sem GPU compatível** (ou com pouca VRAM/RAM), um modelo 14b roda **100% na CPU**
> e fica lento (dezenas de segundos por resposta). Soluções, da mais eficaz à menos:
> 1. **Use um modelo leve no chat** — `ollama pull qwen2.5-coder:3b` e o A.P.O.L.O. já o adota
>    automaticamente (ou fixe em `CHAT_MODEL`). Um 3B responde em segundos na CPU.
> 2. **GPU** — com uma GPU NVIDIA que comporte o modelo, o ganho é de ordens de magnitude.
> 3. As otimizações de software (keep_alive, warmup, GpuGate, streaming sem bloqueio) já
>    removem recargas e contenção, mas **não** mudam a velocidade bruta de inferência na CPU.

### Iniciar

Forma simples (sobe o servidor com reload automático):

```bash
python app.py
```

Ou explicitamente via uvicorn:

```bash
python -m uvicorn app:app --reload --port 8000
```

Acesse: **http://127.0.0.1:8000**

> Variáveis opcionais: `PORT` (padrão 8000), `HOST` (padrão 127.0.0.1),
> `APOLO_RELOAD=0` para desligar o auto-reload. No Windows o console é forçado
> para UTF-8 automaticamente (emojis ☀️ nos logs não quebram mais).

### Rodar testes

```bash
pytest tests/ -v
```

---

## Roadmap — Próximas Evoluções do J.A.R.V.I.S.

### ✅ Fase 1 — Memória e Contexto (Jun 2026)
- [x] **Contexto multi-turn** — janela deslizante de 12 turnos + resumo rolante para conversas longas (`SUMMARY_TRIGGER`) ✅
- [x] **Perfil do usuário rico** — `src/profile.py` extrai fatos pessoais automaticamente das mensagens e injeta no system prompt ✅
- [x] **RAG melhorado com chunking + overlap** — `add_chunked()` divide documentos grandes em chunks de 1200 chars com overlap de 200; rerank híbrido (semântico + lexical + recência) ✅
- [x] **Memória episódica** — `src/episodic.py` indexa conversas no ChromaDB; o chat recupera automaticamente contexto de sessões antigas por semântica; botão "💬 Reindexar" no painel Mente reindexar o histórico completo (`POST /api/sessions/reindex`) ✅

### ✅ Fase 2 — Autonomia e Planejamento (Jun 2026)
- [x] **Planejamento explícito no Coder** — antes de tocar qualquer arquivo, o A.P.O.L.O. Coder escreve um `📋 Plano de execução` numerado (via `CODER_PLAN_PROMPT`); o modelo se compromete com o plano antes de agir, reduzindo saltos precipitados e alterações erradas ✅
- [x] **Idle auto-learning** — `IDLE_TRIGGER` (padrão 600s): após N segundos sem requisição do usuário, o aprendizado autônomo inicia sozinho; GpuGate preempta o learner quando o usuário volta ✅
- [x] **Grafo de conhecimento** — `/api/knowledge/graph` + painel 🗺️ Mapa (setores → tópicos, SVG radial interativo) ✅
- [x] **Multi-step tool use** — loop ReAct com MAX_AGENT_STEPS, ferramentas encadeadas (código + web + base) ✅

### Próximas Fases
### ✅ Fase 3 — Percepção e Voz (Jun 2026)
- [x] **Whisper STT local** — `src/whisper_stt.py` + `POST /api/stt`; o botão 🎤 usa Whisper local (faster-whisper) se instalado, Web Speech API como fallback. `/api/health` expõe `stt: true/false` para o frontend detectar. Instalar: `pip install faster-whisper` (modelos: tiny/base/small, via `WHISPER_MODEL`) ✅
- [x] **DOCX support** — `extract_docx_text()` em `src/ingest.py`; parses parágrafos + tabelas (requer `pip install python-docx`). Tratado em `/api/ingest` como base64 binário igual ao PDF ✅
- [x] **Drag-and-drop** — soltar arquivos (docs ou imagens) diretamente no campo de entrada; `#input-wrap` fica verde ao arrastar; imagens vão para visão, documentos para ingestão ✅
- [x] **Multi-arquivo** — botão 📎 aceita múltiplos arquivos de uma vez; ingere sequencialmente e exibe contagem final ✅
- [x] **TTS** — `speechSynthesis` do navegador (Web Speech API, PT-BR) já presente; botão 🔊 em cada resposta ✅
- [x] **Visão** — análise de imagens via modelo llava local (Ollama) já presente ✅
### ✅ Fase 4 — Soberania Total (Jun 2026)
- [x] **Base de conhecimento local (SQLite FTS5)** — `src/local_knowledge.py`: implementa a mesma interface de `SupabaseKnowledge` com SQLite FTS5. Ativado automaticamente quando Supabase não está configurado. Zero dependências externas, busca full-text PT-BR, rerank híbrido, cache de insights. Sidebar mostra `💾 Local SQLite` quando ativo ✅
- [x] **Embeddings locais via Ollama** — `EMBED_MODEL=nomic-embed-text` em `.env` ativa embeddings 100% locais no ChromaDB; usa coleção isolada para evitar incompatibilidade de dimensões. Instalar: `ollama pull nomic-embed-text` ✅
- [x] **LLM_BACKEND=llamacpp** — motor de LLM próprio migrado em toda a app (`src/providers.py`) ✅
- [ ] **Migração Supabase → SQLite** — script de migração para mover dados existentes (pós-disco-disponível)
- [ ] **Fine-tuning LoRA** — requer GPU; roadmap para quando tiver hardware
- [ ] **Fase 4 — Soberania Total** — PostgreSQL local (sem Supabase), embeddings próprios, fine-tuning LoRA
### ✅ Fase 5 — Multi-agente (Jun 2026)
- [x] **Orquestrador de sub-agentes** — `src/orchestrator.py` + `POST /api/orchestrate`; o modelo analisa a tarefa e decide: resposta direta OU delega a especialistas (🔬 Researcher → síntese de conhecimento, 💡 Analyst → trade-offs e estrutura, 💻 Coder → implementação 14b); execução sequencial com streaming de cada agente ao vivo; síntese final coerente. Modo `🤝 Multi` no input bar ✅
- [x] **API LAN** — CORS habilitado (`allow_origins=["*"]`); `API_TOKEN` para proteção; acesse de celular/tablet: `uvicorn app:app --host 0.0.0.0 --port 8000` ✅
- [x] **Benchmark contínuo** — `src/benchmark.py`: 8 perguntas de referência (coding, explanation, devops, database, algorithms, security, ai); score por keyword match + comprimento; latência por questão; `POST /api/benchmark/run` salva histórico, `GET /api/benchmark/diff` compara 2 últimos runs ✅

### Funcionalidades anteriores
- [x] **GitHub Agent** — lê repositórios e aprende com código real ✅
- [x] **Self-improvement Loop** — Apolo identifica gaps na síntese e injeta novos estudos automaticamente (Auto-Currículo) ✅
- [x] **Code Review Agent** — analisa código do usuário e sugere melhorias usando o conhecimento acumulado ✅
- [x] **Resposta que cita o conhecimento** — Modo Pesquisa Profunda referencia memória + web com fontes numeradas ✅
- [x] **Auto-percepção (Mente do A.P.O.L.O.)** — painel que mostra o que ele sabe: total, categorias, fontes e aprendizados recentes ✅
- [x] **Otimização de latência** — keep_alive, warmup, GpuGate, streaming sem bloqueio e modelo de chat leve separado (`CHAT_MODEL`) ✅
- [ ] **SSE push real-time** — eventos de aprendizado chegam ao browser sem polling
- [ ] **Voice interface** — interação por voz (Whisper + TTS local)

---

*"Um homem sem medo é um homem sem imaginação." — Tony Stark*

*O Apolo aprende todo dia. Você usa sem limite. É o seu J.A.R.V.I.S.*
