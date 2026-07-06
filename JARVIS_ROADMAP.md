# 🛰️ J.A.R.V.I.S. — Roadmap de 1 Ano (Apolo AI)

> Plano vivo de melhorias diárias. Cadência: **1 incremento por dia**, testado, commitado no branch e mergeado no `main`, com o README e a memória atualizados. Sem regressões (a suíte tem que ficar verde). Este documento é atualizado conforme avançamos.

**Início:** 2026-07-05 · **Alvo:** 2027-07 · **Dono:** Leo · **Copiloto:** Claude Code

---

## 1. Visão — o que é "Jarvis pronto"

Um assistente pessoal **soberano** (100% local), **presente** (fala e ouve, está sempre ali), que **te conhece de verdade** (memória de longo prazo do Leo, seus projetos, hábitos e objetivos), **age no seu mundo** (arquivos, apps, agenda, navegador — com permissão) e **melhora sozinho todo dia** (aprende, se testa, conduz os próprios projetos). Não é um chatbot: é um copiloto de vida e de engenharia que roda na sua máquina, sem depender de nuvem.

O teto honesto: o **cérebro** (os pesos do modelo local) não vai igualar um modelo de fronteira enquanto a máquina for CPU-only. Então a estratégia do ano é **maximizar o scaffolding** (memória, ferramentas, verificação, presença) — que é onde 80% da experiência "Jarvis" mora — e deixar o upgrade de hardware como o multiplicador que destrava a última milha.

---

## 2. Princípios que guiam o ano

1. **Soberania primeiro.** Cada feature nova deve rodar offline. Onde hoje dependemos de nuvem (TTS via edge-tts), migramos para local. Sem exceções silenciosas.
2. **Realismo de CPU.** Ryzen 5 4600G, 16 GB, sem GPU. Teto ~14B. Toda feature respeita esse orçamento: modelo leve por padrão, o 14b só onde vale, nada que trave a máquina.
3. **Incrementos diários testáveis.** Nada de "big bang". Cada dia entrega algo pequeno, verde e mergeado. É assim que 250 dias viram um sistema grande sem quebrar.
4. **Verdade vem da execução.** Testes, não intenção. A guarda de regressão protege o projeto de mim.
5. **Honestidade sobre o teto.** Itens que exigem GPU/hardware ficam marcados `🔒 HW`. Não fingimos que dá para fazer tudo agora.

---

## 3. Estado atual (mapa real — 2026-07-05)

**Tamanho:** ~12.100 linhas Python (`app.py` 3.213 + `src/` 8.940) · frontend `static/index.html` 5.401 linhas · **507 testes** em 40 arquivos · ~110 endpoints.

### O que já existe e funciona
- **Chat** com streaming SSE, memória de sessão, Modo Agente (ReAct: código + web + base), Modo Pesquisa Profunda (`src/research.py`), Code Review (`src/reviewer.py`).
- **Aprendizado autônomo contínuo** (`src/learner.py` 851 linhas): 6 fetchers (GitHub, Docs, WebSearch multissetorial, Trends, Enciclopédia, Livros) + summarizer + síntese cross-domain + auto-currículo. RAG/ChromaDB (`src/rag.py`), SQLite (`src/storage.py` 851 linhas), LocalKnowledge FTS5 (`src/local_knowledge.py`).
- **Coder** ("Claude Code interno", `src/coder.py` 673 linhas): workspace isolado, diff/undo, guarda de regressão, sandbox de automelhoria, memória de lições (`src/lessons.py`), e a pirâmide de conhecimento recém-fechada: `LER/BUSCAR` (workspace) → `CONSULTAR` (RAG) → `BUSCAR_WEB` (web) → `learn_from_web` (o que pesquisa vira memória permanente).
- **Ingestão** (PDF/docx/URL/pasta, `src/ingest.py`), **indexador de repositório** (`src/repo_indexer.py`), **grafo de conhecimento + insights**, **curador de duplicatas** (`src/curator.py`), **export Obsidian** (`src/obsidian.py`), **benchmark/analytics**, **perfil do usuário** (`src/profile.py`), **memória de projeto** (`src/project_memory.py`).
- **Voz (parcial):** STT `faster-whisper` (opcional, **desligado por padrão**), TTS `edge-tts`.
- **PWA**, notificações, agendamentos (`/api/schedules`), Supabase opcional (fallback SQLite).

### Forças
- Base de aprendizado autônomo madura e resiliente (sobrevive a Ollama fora).
- Coder com autonomia real e salvaguardas sérias.
- Cobertura de testes alta (507) — dá para refatorar com rede.
- Persistência redundante e local-first.

---

## 4. Limitações honestas (priorizadas)

| # | Limitação | Impacto | Onde |
|---|-----------|---------|------|
| L1 | **Voz não é "Jarvis".** TTS é **nuvem** (edge-tts → Microsoft; o comentário em `src/tts.py` que diz "offline" está errado). STT desligado. Sem wake word, sem escuta contínua, sem barge-in. | Alto — é a experiência-assinatura de um Jarvis | `src/tts.py`, `src/whisper_stt.py` |
| L2 | **Sem proatividade.** É request-response + estudo em background. Não inicia conversa, não te lembra de nada, não faz briefing. | Alto | — |
| L3 | **Sem agência no mundo real.** Não lê seus arquivos do sistema, agenda, e-mail, navegador; não controla apps. Age só no workspace isolado. | Alto | — |
| L4 | **Memória fragmentada.** RAG + SQLite + FTS + lessons.db + profile.json + project_memory, sem "tecido de memória" unificado. Não há memória autobiográfica das suas conversas ao longo do tempo, nem consolidação ("o que fizemos mês passado"). | Alto | vários stores |
| L5 | **Modelo raso do usuário.** `profile.py` (69 linhas) é fino. O Jarvis não te conhece profundamente (metas, hábitos, relações, contexto de vida). | Médio-alto | `src/profile.py` |
| L6 | **Aprendizado acumula, mas não "entende".** Fetch+summarize. Sem recall ativo, sem repetição espaçada, sem verificação de correção, sem auto-teste do que aprendeu. | Médio | `src/learner.py` |
| L7 | **Sem avaliação de progresso.** `benchmark.py` existe, mas não mede se o assistente está te ajudando **melhor** com o tempo. Sem loop de feedback da sua satisfação. | Médio | `src/benchmark.py` |
| L8 | **Qualidade de raciocínio no CPU.** Modelo pequeno alucina. Só o Coder tem verificação (guarda de regressão); o chat não tem cadeia de verificação/self-consistency. | Médio | chat/agent |
| L9 | **Monólito.** `app.py` 3.213 linhas e `index.html` 5.401 linhas. Difícil evoluir e testar. Risco crescente. | Médio (estrutural) | `app.py`, `static/index.html` |
| L10 | **Sem acesso remoto/mobile real.** É localhost. Um Jarvis devia estar no seu bolso. | Médio | infra |
| L11 | **Privacidade em repouso.** Dados pessoais em SQLite/JSON sem criptografia; sem log de auditoria do que a IA fez sozinha. | Médio | infra |
| L12 | **Teto de hardware.** CPU-only limita o cérebro, a latência da voz e fecha fine-tuning. `🔒 HW` | Fundamental | máquina |

---

## 5. Os 6 pilares do ano

- **P1 · Voz & Presença** — falar/ouvir local, wake word, loop conversacional, barge-in. *(ataca L1)*
- **P2 · Memória & Personalização** — tecido de memória unificado, memória autobiográfica, modelo profundo do Leo, consolidação. *(L4, L5)*
- **P3 · Proatividade & Autonomia** — briefings, lembretes inteligentes, projetos autodirigidos, digest ativo. *(L2)*
- **P4 · Agência & Ferramentas** — agir no ambiente real (arquivos, agenda, e-mail, navegador, apps) com permissão e sandbox. *(L3)*
- **P5 · Cérebro & Qualidade** — roteamento, verificação anti-alucinação, aprendizado que entende, harness de avaliação. *(L6, L7, L8)*
- **P6 · Arquitetura & Soberania** — quebrar o monólito, observabilidade, criptografia em repouso, acesso remoto, TTS/STT 100% local. *(L9, L10, L11)*

---

## 6. Calendário de 12 meses

> Cada mês tem 3–5 épicos; cada épico vira ~15–20 incrementos diários. Abaixo listo os épicos e **exemplos** de tarefas-dia (não todas). "DoD" = Definition of Done.

### 🗓️ Q1 — FUNDAÇÃO (Meses 1–3)
*Primeiro arrumamos a casa e a memória, depois damos voz. Sem fundação, o resto vira dívida.*

#### **Mês 1 — Arquitetura & Observabilidade** *(P6)*
Destrava todo o resto: um monólito de 3.200 linhas não aguenta um ano de features.
- Épico 1.1 — **Modularizar `app.py`** em routers FastAPI (`routers/chat.py`, `routers/coder.py`, `routers/learning.py`, …). Exemplos-dia: extrair endpoints de learning → router; extrair coder → router; mover helpers para `src/`; teste de fumaça por router.
- Épico 1.2 — **Quebrar `index.html`** em componentes/módulos JS + CSS separados (sem framework pesado; ES modules). Um painel por arquivo.
- Épico 1.3 — **Observabilidade:** logging estruturado, `/api/health` expandido, um painel de "o que a IA fez nas últimas 24h" (auditoria).
- **DoD:** nenhum arquivo Python > 800 linhas; suíte verde; a UI idêntica ao usuário.

#### **Mês 2 — Tecido de Memória Unificado** *(P2)*
Uma só porta para toda memória, com memória autobiográfica de verdade.
- Épico 2.1 — **`src/memory/` (MemoryFabric):** fachada única sobre RAG + SQLite + FTS + lessons. `remember(text, kind, tags)` / `recall(query, kind?)`. Migração incremental dos call-sites.
- Épico 2.2 — **Memória episódica/autobiográfica:** cada conversa vira um episódio resumido e datado ("2026-07-05: fechamos a pirâmide do Coder"). Recall temporal ("o que fizemos semana passada").
- Épico 2.3 — **Consolidação (sono):** rotina noturna que resume episódios em memórias de longo prazo e poda ruído (inspirado em consolidação de memória).
- **DoD:** perguntar "o que a gente fez ontem?" retorna resposta correta e datada.

#### **Mês 3 — Voz Local de Verdade** *(P1 + P6)*
O Jarvis passa a falar e ouvir — e 100% local.
- Épico 3.1 — **TTS soberano:** trocar edge-tts por **Piper** (TTS neural local, roda em CPU). Voz PT-BR, streaming. Remover a dependência de nuvem. `🔒 HW` parcial: latência aceitável no CPU, medir.
- Épico 3.2 — **STT sempre pronto:** ligar `faster-whisper` (modelo `base`/`small`) por padrão, com push-to-talk na UI. Medir latência.
- Épico 3.3 — **Loop conversacional:** falar → transcrever → responder → falar, sem clicar. Estado de conversa por voz.
- **DoD:** conversa por voz ida-e-volta, offline, com internet desligada.

### 🗓️ Q2 — PRESENÇA & AGÊNCIA (Meses 4–6)
*Agora ele deixa de esperar você e começa a agir.*

#### **Mês 4 — Proatividade** *(P3)*
- Épico 4.1 — **Briefing diário:** de manhã, um resumo falado (o que aprendeu à noite, pendências, agenda). Reusa o `/api/digest`.
- Épico 4.2 — **Lembretes e follow-ups inteligentes:** "você pediu pra retomar X". Detecção de compromissos em conversas.
- Épico 4.3 — **Notificações que importam:** filtro de relevância (não spammar). Push real via SSE/PWA.
- **DoD:** o Jarvis te aborda primeiro, no momento certo, sem virar ruído.

#### **Mês 5 — Wake Word & Conversa Contínua** *(P1)*
- Épico 5.1 — **Wake word local** ("Apolo"/"Jarvis") via `openWakeWord`/Porcupine local. Escuta contínua de baixo custo.
- Épico 5.2 — **Barge-in:** interromper a fala do assistente falando por cima.
- Épico 5.3 — **VAD** (detecção de voz) para saber quando você terminou de falar.
- **DoD:** "Apolo, que horas são?" funciona do outro lado da sala, sem tocar no PC. `🔒 HW` (latência).

#### **Mês 6 — Agência: Leitura do Mundo** *(P4)*
Começa lendo (seguro) antes de agir.
- Épico 6.1 — **Sistema de ferramentas com permissão:** framework de tools + tela de consentimento + log de auditoria. Toda ação no mundo passa por aqui.
- Épico 6.2 — **Ler arquivos do sistema** (pastas que você autorizar): buscar, resumir, "onde está aquele documento?".
- Épico 6.3 — **Agenda & e-mail (leitura):** conectar calendário/e-mail locais (ICS, IMAP) — só leitura no início.
- **DoD:** "resuma meus e-mails de hoje" / "o que tenho na agenda amanhã" funciona, com permissão explícita.

### 🗓️ Q3 — CÉREBRO & QUALIDADE (Meses 7–9)
*Menos alucinação, aprendizado que entende, e prova de que está melhorando.*

#### **Mês 7 — Raciocínio Confiável no CPU** *(P5)*
- Épico 7.1 — **Roteador de modelos/tarefas:** classificar a intenção e escolher leve vs 14b vs ferramenta. Menos desperdício de CPU.
- Épico 7.2 — **Cadeia de verificação no chat:** para respostas factuais, checar contra a base (RAG) e sinalizar incerteza. Anti-alucinação.
- Épico 7.3 — **Self-consistency barata:** em perguntas críticas, amostrar 2–3 respostas e reconciliar.
- **DoD:** taxa de alucinação medida cai num conjunto de perguntas-teste.

#### **Mês 8 — Aprendizado que Entende** *(P5)*
- Épico 8.1 — **Recall ativo + repetição espaçada:** o learner se auto-testa sobre o que estudou; o que falha volta pra fila.
- Épico 8.2 — **Verificação de fatos:** cruzar novas sínteses com o que já sabe; marcar contradições.
- Épico 8.3 — **Conexões explícitas:** ligar tópicos novos aos existentes no grafo de conhecimento (não só a síntese periódica).
- **DoD:** o Jarvis responde "como X se conecta com Y?" usando o que aprendeu sozinho.

#### **Mês 9 — Harness de Avaliação** *(P5)*
- Épico 9.1 — **Eval contínuo:** conjunto de tarefas-canário rodando periodicamente (chat, coder, recall) com placar histórico.
- Épico 9.2 — **Loop de feedback do Leo:** 👍/👎 + "por quê" nas respostas, virando dado de melhoria e memória.
- Épico 9.3 — **Painel "Estou melhorando?":** tendência de qualidade ao longo do tempo.
- **DoD:** dá para ver, num gráfico, se o assistente está ficando mais útil mês a mês.

### 🗓️ Q4 — AUTONOMIA & SOBERANIA (Meses 10–12)
*Ele passa a agir no mundo e a se conduzir; e fechamos a soberania.*

#### **Mês 10 — Agência: Ação no Mundo** *(P4)*
- Épico 10.1 — **Ações com confirmação:** escrever arquivos, criar eventos, rascunhar e-mails — sempre com preview + confirmação + undo.
- Épico 10.2 — **Automação de rotinas:** "toda sexta, gere o resumo da semana e salve no Obsidian".
- Épico 10.3 — **Controle de navegador/app** (opt-in, sandbox) para tarefas repetitivas.
- **DoD:** o Jarvis executa uma rotina multi-passo real, com trilha de auditoria e reversível.

#### **Mês 11 — Soberania Total** *(P6)*
- Épico 11.1 — **Embeddings locais** (substituir qualquer dependência externa de embedding). `🔒 HW` parcial.
- Épico 11.2 — **Criptografia em repouso** dos dados pessoais + backup local automático + restauração testada.
- Épico 11.3 — **Acesso remoto seguro** (do celular, via túnel local/HTTPS) — o Jarvis no bolso.
- **DoD:** internet 100% desligada, tudo funciona; dados criptografados; alcançável do celular na sua rede.

#### **Mês 12 — Projetos Autodirigidos & Retrospectiva** *(P3 + P5)*
- Épico 12.1 — **O Jarvis conduz projetos:** define metas de melhoria próprias, quebra em tarefas, executa no Coder, te reporta. (Automelhoria supervisionada evoluída.)
- Épico 12.2 — **Retrospectiva do ano:** o próprio Jarvis analisa o que evoluiu e propõe o roadmap do ano 2.
- Épico 12.3 — **Polimento & documentação** de tudo.
- **DoD:** o Jarvis apresenta, por voz, o que fez no ano e o que sugere para o próximo.

---

## 7. Itens travados por hardware `🔒 HW`

O maior multiplicador do projeto é uma **GPU**. Sem ela, estes ficam limitados:
- **Fine-tuning LoRA** de um modelo próprio (o "Apolo" com sua personalidade e conhecimento nos pesos) — impossível no CPU.
- **Modelos maiores** (>14B) para raciocínio de fronteira.
- **Latência de voz** tempo-real (wake word + STT + LLM + TTS em <1s).
- **Embeddings locais** de alta dimensão em escala.

**Recomendação honesta:** planejar, em algum ponto do ano, uma GPU de entrada (ex.: usada com 12–16 GB VRAM). Ela sozinha destrava o Q4 inteiro e eleva o teto do cérebro. Até lá, o plano é desenhado para render o máximo no CPU.

---

## 8. Métricas de sucesso (como saber que deu certo)

- **Presença:** consigo conversar por voz, offline, sem tocar no PC.
- **Memória:** ele acerta "o que fizemos semana passada" e me conhece (metas, projetos, preferências).
- **Proatividade:** ele me aborda primeiro, útil, sem virar spam.
- **Agência:** ele executa uma rotina real no meu ambiente, com segurança e undo.
- **Cérebro:** a taxa de alucinação cai e o painel "estou melhorando?" sobe.
- **Soberania:** tiro a internet e nada quebra; dados criptografados; alcanço do celular.

---

## 9. Cadência de trabalho (como rodamos, todo dia)

1. Escolher o próximo incremento do épico atual (o menor passo que entrega valor).
2. Implementar com testes. Suíte tem que ficar verde (guarda de regressão).
3. Verificar ao vivo quando for UI (preview).
4. Atualizar `README.md` e a memória.
5. Commit no branch → fast-forward no `main` (sua instância roda `main`).
6. Push ao GitHub **só com sua confirmação**.

> **Regra de ouro:** todo dia o sistema termina melhor e verde do que começou. 250 dias assim = um Jarvis.

---

## 10. Progresso

| Trimestre | Mês | Épico | Status |
|-----------|-----|-------|--------|
| Q1 | M1 | Modularizar app.py | ✅ **app.py < 800** — 22 routers (+`chat`), 0 rotas @app no app.py (só bootstrap/lifespan/scheduler/middleware). app.py 3.213→**485** (–85%). Falta quebrar learner.py/storage.py (851) p/ fechar o épico |
| Q1 | M1 | Modularizar frontend | ✅ **CSS + JS extraídos** — `<style>` → `static/css/app.css` (795); os 2 `<script>` → `static/js/app.js` (3.400) + `static/js/enhancements.js` (556). **index.html 5.401→647 (–88%)**, zero código inline. Bônus: a modularização expôs e corrigiu um bug latente de boot (app.js chamava `_initTabs()`/`startLearnSSE()` de enhancements.js antes dele carregar → boot abortava; reordenado). Verificado no preview: tema, tabs, SSE e notificações voltaram a funcionar |
| Q1 | M1 | Observabilidade/auditoria | ✅ **completo** — (1) painel "🕒 Atividade (24h)" (`/api/audit`) com feed unificado; (2) **logging estruturado** (`src/logging_setup.py`, `LOG_FORMAT=json` → 1 linha JSON/evento c/ campos extra); (3) **`/api/health` com build** (versão/git-sha/uptime via `src/build_info.py`), exibido no rodapé do painel Saúde. Robustez: JS/CSS agora `Cache-Control: no-cache` (middleware) + SW network-first — senão o usuário via UI/código velho após updates (sw.js mantém `no-store`) |
| Q1 | M2 | MemoryFabric | ⬜ |
| Q1 | M2 | Memória episódica | ⬜ |
| Q1 | M2 | Consolidação noturna | ⬜ |
| Q1 | M3 | TTS local (Piper) | ⬜ |
| Q1 | M3 | STT sempre pronto | ⬜ |
| Q1 | M3 | Loop conversacional | ⬜ |

*(a tabela cresce conforme avançamos; itens viram ✅ com o commit que os entrega)*

---

*Documento vivo. Última atualização: 2026-07-05.*
