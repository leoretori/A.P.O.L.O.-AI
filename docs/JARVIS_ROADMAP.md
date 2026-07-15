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
| Q4 | M12 | Polimento & documentação (12.3) — FECHA O ANO | 🔨 **fecha o M12 e o ANO 1** — versão bumpada para **1.0.0** (`build_info.APP_VERSION`, marca os 12 milestones em software), README e JARVIS_ROADMAP revisados e completos (todas as features documentadas, marcos 🏁 de M1–M12), memória atualizada. DoD do M12 batido (12.2 já apresenta por voz o que fez no ano + o que sugere pro próximo). **M12 software concluído** (12.1 projetos, 12.2 retrospectiva, 12.3 polimento). 🎉 **Ano 1 completo; pendências restantes são 🔒 HW / setup do Leo.** |
| Q4 | M12 | Retrospectiva do ano (12.2) | 🔨 — o DoD do M12: o A.P.O.L.O. olha para trás e para frente. `src/retrospective.py` (determinístico, sem LLM): `compose_retrospective_text(data)` monta uma narrativa PT-BR FALÁVEL dos números do ano (tópicos aprendidos, dias ativos, tarefas do Coder + acerto, nota/alucinação do eval, 👍/👎, projetos concluídos); `year_two_themes(signals)` propõe os focos do ano 2 = metas concretas das métricas de hoje (reusa `propose_goals` do 12.1) + temas estratégicos (GPU/cérebro maior, mais agência, memória mais profunda). `GET /api/retrospective` coleta os dados reais. UI: seção **📜 Retrospectiva do ano** no topo do painel 🎯 Projetos, com botão **🔊 Ouvir** (fala via `speak()` — apresenta POR VOZ, como o DoD pede). Verificado ao vivo: texto falável + focos do ano 2. ~9 testes. Falta 12.3 (polimento & documentação) p/ fechar o M12 e o ANO |
| Q4 | M12 | O Jarvis conduz projetos (12.1) | 🔨 — automelhoria SUPERVISIONADA: `src/projects.py` (determinístico) olha os PRÓPRIOS sinais de saúde e propõe metas — `propose_goals(signals)` cai de limiares (sínteses cruas, alucinação do eval, acerto do Coder, lacunas, duplicatas, 👎, queda do eval), ordenadas por prioridade; `break_into_tasks(goal)` dá passos concretos por tipo; `project_progress` mede %. NADA roda o Coder sozinho (lição do 3B destruidor) — ele PROPÕE, o Leo aprova/executa. Tabela `self_projects` + `ProjectsMixin` (save/list/get/set_task→conclui ao 100%/set_status/delete/has_active_project). `GET /api/projects/suggest` (coleta sinais reais + omite metas já adotadas), `POST /api/projects/adopt`, `/task`, `/status`, `DELETE`. UI: painel **🎯 Projetos** (sugestões com porquê+passos → adotar; adotados com checklist + barra de progresso). Verificado ao vivo: adotar→3 passos→marcar 1→33%; sem problemas → "nada urgente". 19 testes. Falta 12.2 (retrospectiva do ano) e 12.3 (polimento) p/ fechar o M12 e o ANO |
| Q4 | M11 | Embeddings locais (11.1) — DoD | 🔨 **fecha o M11** — o recall JÁ era local (default `all-MiniLM-L6-v2` ONNX na CPU, ou Ollama `nomic-embed-text`) — sem API externa. Este épico fecha a soberania: `src/embeddings.py` (determinístico) traz um **fallback 100% Python** (`HashingEmbeddingFunction`, feature hashing de palavras+trigramas, L2-normalizado) — sem ONNX, sem Ollama, sem baixar modelo, sem internet: garante recall mesmo com a máquina 100% offline (opt-in `EMBED_MODEL=hashing`, ligado no `_make_embed_fn` do rag). `backend_info()` reporta backend + localidade. `GET /api/embeddings/info` + `POST /api/embeddings/selftest` (prova que textos parecidos ficam mais próximos que diferentes, offline). UI: card **🔡 Embeddings (soberania)** no painel Saúde. Verificado ao vivo: backend onnx-minilm local/offline; selftest 0.59 (parecidos) vs -0.04 (diferentes). Qualidade PT-BR melhor (modelo maior) segue 🔒 HW. ~15 testes. **M11 software concluído** (11.1 embeddings, 11.2 cripto+backup, 11.3 remoto) |
| Q4 | M11 | Acesso remoto seguro (11.3) | 🔨 — o Jarvis alcançável do celular na sua rede, **sem expor tudo**. `src/remote_access.py` (determinístico): `authorize(client_host, expected, provided)` — sem `REMOTE_TOKEN` tudo passa (inalterado); loopback (dono) passa sempre; de fora exige o token (`token_matches` em tempo constante via `hmac.compare_digest`). `lan_ip()` (truque do socket UDP), `access_url`/`url_with_token`. Middleware `_remote_gate_middleware` (registrado por último → outermost, bloqueia antes de tudo): cobre a UI INTEIRA (não só escritas como o `X-API-Token` antigo) via cookie que o celular ganha ao abrir `http://ip-lan:porta/?token=…`. `GET /api/remote/info` (URL da LAN + link com token + dicas honestas do que falta: HOST=0.0.0.0, REMOTE_TOKEN). UI: modal **📱 Acesso remoto** (ícone no header: link copiável + status bind/token). Túnel HTTPS p/ fora da LAN fica 🔒 setup do Leo. Verificado ao vivo: IP da LAN detectado (192.168.x), gate bloqueia de fora sem token (401) e passa com token. ~17 testes. Falta 11.1 (embeddings locais 🔒 HW) p/ fechar o M11 |
| Q4 | M11 | Criptografia em repouso + backup (11.2) | 🔨 — ataca a L11 (dados pessoais sem cifra). `src/crypto.py` (determinístico): chave por **scrypt** (senha+salt, ~16MB, lento p/ força bruta) + **Fernet** (AES-128-CBC+HMAC, AUTENTICADO). Envelope autodescritivo `MAGIC(8)+salt(16)+token` → o arquivo carrega o salt; a **senha nunca é gravada**. `encrypt/decrypt_bytes\|json`; salt novo a cada cifragem. `src/backup_service.py`: `write_encrypted`/`read_encrypted`/`list_backups`/`prune_backups` (.apolobak local). Endpoints `POST /api/backup/encrypted\|restore` + `GET /api/backup/status`; restore confinado à pasta de backups (sem path traversal), senha errada/adulteração FALHAM sem tocar o banco. Reusa `export_all`/`import_all` (helpers `_gather_backup_data`/`_apply_import`). Auto-backup diário no `_scheduler_loop` se `BACKUP_PASSPHRASE` no `.env` (BACKUP_HOUR, poda os antigos). UI: modal **🔒 Backup criptografado** (ícone no header: criar com senha + lista + restaurar). ~18 testes (round-trip, senha errada, adulteração detectada, salt novo, path traversal). Falta 11.1 (embeddings locais 🔒 HW) e 11.3 (acesso remoto seguro) |
| Q4 | M10 | Controle de navegador em sandbox (10.3) — DoD | 🔨 **DoD do M10 batida** — "controle de navegador" para tarefas repetitivas, à maneira soberana: `src/webtask.py` roda uma RECEITA de passos (`open`→`extract`→`follow`) contra um DRIVER injetável; o `HttpDriver` embutido usa só httpx+BeautifulSoup (sem browser pesado, roda no CPU). Duas travas como no M6: **opt-in** por escopo `browser.control` e **sandbox** por allowlist de DOMÍNIOS (a `note` do grant), checada na validação E em runtime (cada `open`/`follow`). READ-ONLY (só GET) → não modifica nada. `validate`/`run`/`parse_page`/`domain_allowed` determinísticos (driver fake nos testes). Tool `browser.run` reusa o portão do M6 (`run_tool` → consentimento + auditoria). Endpoints `GET /api/webtask/example`, `POST /api/webtask/plan` (prévia: valida a sandbox sem navegar) e `/run`. UI: console **🌐 Automação web** no painel 🛠️ Ações (receita JSON → 👁️ Prévia → 🌐 Executar). Verificado ao vivo: fetch REAL a example.com extraiu título/texto; `evil.com` barrado. Driver interativo (clique/digitação em sites JS via Playwright) fica 🔒 opt-in. 18 testes. **M10 software concluído** (10.1 ações+undo, 10.2 rotinas, 10.3 web sandbox) |
| Q4 | M10 | Automação de rotinas (10.2) | 🔨 — casa o agendador com as ações reversíveis do 10.1: uma ROTINA roda sozinha no horário combinado e **cada execução passa por `apply_action`** → entra no ledger de undo + auditoria (autônoma, mas reversível e inspecionável). `src/routines.py` (determinístico): `is_due(routine, now)` decide o disparo (daily/weekly/monthly, 1×/período, sem repetir, sem retroativo), `build_weekly_digest_md` monta o resumo da semana a partir do banco (aprendidos por setor + episódios, SEM LLM), `run_routine` despacha pelo builder → ação. Tipo `weekly_digest` fecha **"toda sexta, gere o resumo da semana e salve"**. Tabela `routines` + mixin (save/list/get/toggle/delete/mark_run). `_scheduler_loop` dispara as vencidas (builders sem LLM → não disputam o Ollama). Endpoints CRUD + `POST /api/routines/{id}/run` (rodar agora). UI: seção **⏰ Rotinas** no painel 🛠️ Ações (criar/pausar/rodar-agora/remover). Verificado ao vivo: criar→rodar (escreve o resumo)→ledger→desfazer→pausar→remover. 23 testes. Falta 10.3 (controle de navegador/app sandbox) p/ o DoD do M10 |
| Q4 | M10 | Ações com confirmação + undo (10.1) | 🔨 — o A.P.O.L.O. passa a MODIFICAR o mundo, mas nunca num clique só: `src/actions.py` (motor determinístico) impõe o ciclo **preview → confirm → undo** com o mesmo portão do M6 (consentimento por escopo + auditoria). 1ª ação: `files.write` (`src/tools/files_write.py`) — escrita/criação de arquivo CONFINADA à allowlist (reusa `_within`: `resolve()` mata `..`/symlink; teto 1 MB), `preview_write` mostra criar-vs-sobrescrever + trecho antigo/novo SEM tocar o disco, `apply_write` grava e captura o undo (conteúdo antigo ou "não existia"), `undo_write` restaura/apaga. Escopo novo `files.write`. Tabela `undo_log` + `ActionsMixin` (save_undo/get_undo/list_undo/mark_undone). Endpoints `POST /api/actions/preview\|confirm\|undo` + `GET /api/actions/undo` (ledger) + `GET /api/actions`. UI: painel **🛠️ Ações reversíveis** (form escrever→👁️ Prévia→✓ Confirmar só habilita após a prévia; histórico com ↩️ Desfazer). Verificado ao vivo: grant→prévia (não escreve)→confirmar (cria)→ledger→desfazer (remove)→revoke. 42 testes |
| Q3 | M9 | Painel "Estou melhorando?" (9.3) — DoD | 🔨 **DoD do M9 batida** — `evals.improvement_report(eval_trend, feedback_trend, coder_stats)` (determinístico) funde as frentes num veredito **melhorando/piorando/estável/sem_dados**: cada eixo tem um delta onde >0 = melhora (queda de alucinação já chega normalizada como positivo). `GET /api/improving` devolve o veredito + placar canário mais recente + série de notas p/ o gráfico. UI: card **📈 "Estou melhorando?"** no topo do painel Analytics (veredito colorido, eixos com setas ▲/▼, **sparkline SVG** das notas, último placar) + botão **▶ Rodar avaliação** (`/api/evals/run`) — carregamento isolado (falha não quebra o painel). Verificado ao vivo (veredito, eixos e sparkline renderizam). 8 testes. **Fecha o M9 E o DoD do M7** (alucinação agora é medida e acompanhada no tempo) |
| Q3 | M9 | Loop de feedback do Leo (9.2) | 🔨 — o 👍/👎 vira dado ACIONÁVEL: `Reaction` ganhou `reason`/`question`/`answer` (migração de coluna p/ bancos antigos). No 👎 o front pede o **"por quê"** (`window.prompt`) e manda pergunta+resposta+motivo — congelando a pergunta que gerou AQUELA resposta (não a última digitada depois). `save_reaction` estendida (compat posicional preservada); `negative_feedback(limit)` lista o que o Leo achou ruim **e por quê** (matéria-prima de melhoria/memória); `feedback_trend(window)` mede a satisfação (👍/total) recente vs anterior. `GET /api/reactions/negative`. 12 testes. Falta 9.3 (painel "estou melhorando?" — DoD do M9 + fecha o do M7) |
| Q3 | M9 | Eval contínuo — tarefas-canário (9.1) | 🔨 — `src/evals.py` (correção 100% determinística): suíte CANÁRIO fixa cobrindo `chat`/`coder`/`recall` **+ `trap`** (pergunta de PREMISSA FALSA — só passa admitindo que não sabe). `grade` pontua por presença de termos (ignora acento/caixa, `forbid` zera), `aggregate` dá o placar + **`hallucination_rate`** (fração das armadilhas mordidas — o número que faltava p/ provar a queda do M7). `run_canary(runner)` com runner INJETÁVEL. Tabela `eval_runs` + `EvalsMixin` (`save_eval_run`/`get_eval_history`/`latest_eval`/`eval_trend`). `POST /api/evals/run` (dispara o LLM: pega o `llm_lock` do learner + `gpu_gate` → **não reintroduz o thrash 14b+3b**) e `GET /api/evals/history` (histórico + tendência). Runner desacoplado do chat → não interfere no aprendizado. 24 testes |
| Q1 | M1 | Modularizar app.py | ✅ **completo (DoD: nenhum .py > 800)** — 22 routers (+`chat`), 0 rotas @app no app.py (só bootstrap/lifespan/scheduler/middleware). app.py 3.213→**485** (–85%). `storage.py` 927→27 (fachada de mixins: models/conversations/learning/analytics) e `learner.py` 851→687 (extraídos `learner_types`/`learner_synthesis`). Maior .py agora: 686 |
| Q1 | M1 | Modularizar frontend | ✅ **CSS + JS extraídos** — `<style>` → `static/css/app.css` (795); os 2 `<script>` → `static/js/app.js` (3.400) + `static/js/enhancements.js` (556). **index.html 5.401→647 (–88%)**, zero código inline. Bônus: a modularização expôs e corrigiu um bug latente de boot (app.js chamava `_initTabs()`/`startLearnSSE()` de enhancements.js antes dele carregar → boot abortava; reordenado). Verificado no preview: tema, tabs, SSE e notificações voltaram a funcionar |
| Q1 | M1 | Observabilidade/auditoria | ✅ **completo** — (1) painel "🕒 Atividade (24h)" (`/api/audit`) com feed unificado; (2) **logging estruturado** (`src/logging_setup.py`, `LOG_FORMAT=json` → 1 linha JSON/evento c/ campos extra); (3) **`/api/health` com build** (versão/git-sha/uptime via `src/build_info.py`), exibido no rodapé do painel Saúde. Robustez: JS/CSS agora `Cache-Control: no-cache` (middleware) + SW network-first — senão o usuário via UI/código velho após updates (sw.js mantém `no-store`) |
| Q1 | M2 | MemoryFabric | ✅ **fachada + recall semântico unificado** — `src/memory/` (MemoryFabric) une RAG (semantic) + base FTS/Supabase (knowledge) + lições (lesson) atrás de `remember(text, kind, tags)` / `recall(query, kind?)` → `MemoryHit`; `/api/memory/recall` expõe a porta; injetado no runtime. Todo recall semântico passa pelo fabric: `agent_recall` (Modo Agente + CONSULTAR do Coder) e o recall do chat (com enrichment/cache/filtro preservados), ambos com fallback sobre rt.rag. (O bloco de lições do Coder segue via `LessonMemory.format_section` de propósito — é formatação específica, não recall genérico.) Verificado no preview + testes de ponta a ponta |
| Q1 | M2 | Memória episódica | ✅ — tabela `episodes` + `EpisodicMemory` (`src/memory/episodic.py`): resume sessão em episódio (LLM) e recall por janela de tempo, traduzindo "ontem"/"semana passada"/"últimos N dias" (`parse_when`). Fabric: `recall_when(frase)` + kind `episode`; endpoints `GET/POST /api/memory/episodes`. **DoD batida**: "o que fizemos ontem?" retorna episódio correto e datado |
| Q1 | M2 | Consolidação noturna | ✅ **gatilho automático ("sono")** — `EpisodicMemory.consolidate()` varre conversas ENCERRADAS (inativas há N min) e ainda sem episódio e as resume sozinho (`db.sessions_pending_episode`); idempotente. Roda no `_scheduler_loop` a cada ~30 min (pausa se o aprendizado de fundo estiver usando o LLM). Endpoint `POST /api/memory/consolidate` p/ sob demanda. `_to_local_naive` alinha o fuso p/ "ontem" cair no dia certo. Fecha o M2 |
| Q1 | M3 | TTS local (Piper) | 🔨 **engine soberano + honestidade** — TTS virou fachada (`src/tts.py`) que prefere **Piper (100% local, CPU)** sobre edge-tts (nuvem): `active_engine()`/`is_local()`/`media_type()`, `TTS_ENGINE` força um. `src/tts_piper.py` (novo engine, WAV) + `src/tts_edge.py` (nuvem, MP3, fallback). `/api/tts` manda `X-TTS-Engine`/`X-TTS-Local`; `/api/health` reporta `tts_engine`+`tts_local` (fim da mentira L1: o código dizia edge="local"). Verificado: fallback p/ edge funciona e se declara nuvem. Falta p/ fechar: usuário instalar `piper-tts` + modelo PT-BR e medir latência no CPU (🔒 HW) |
| Q1 | M3 | STT sempre pronto | ✅ — Whisper (`src/whisper_stt.py`) ganhou `warmup()` + `is_ready()`; o boot pré-carrega o modelo (task atrasada 12s, `STT_WARMUP=0` desliga) → a 1ª ditada não paga o cold-start (~15s de load, medido). `/api/health` e `/api/boot` reportam `stt_ready`. Verificado no preview: modelo `base` pré-carregado no boot, `stt_ready` vira true. (Boot/health também passaram a reportar o `tts_engine`/`tts_local` reais via fachada.) |
| Q1 | M3 | Loop conversacional | ✅ — o modo mãos-livres (VAD → `/api/stt` → `/api/chat` → TTS → volta a ouvir, em `enhancements.js`) foi integrado ao stack de voz soberano: usa o TTS do servidor para QUALQUER engine ≠ browser (corrige o bug que só reconhecia edge-tts e IGNORAVA o Piper local); envia o rótulo da voz (a fachada mapeia por engine); avisa se o STT ainda está aquecendo (`stt_ready`). Verificado no preview (decisão de engine + contrato `/api/health`). Loop 100% local quando Piper instalado |
| Q2 | M4 | Briefing diário | ✅ — `src/briefing.py` compõe um resumo FALÁVEL (o que aprendi na janela + o que fizemos/episódios + agenda de estudos + lembretes + pendências) num `text` PT-BR determinístico; `GET /api/briefing?hours=`. Proativo: o `_scheduler_loop` envia o briefing como notificação uma vez por manhã (`BRIEFING_HOUR`, padrão 8h; -1 desliga). Frontend: botão 📻 no topo → busca e FALA o briefing. Verificado no preview (endpoint + botão + toast) |
| Q2 | M4 | Lembretes/follow-ups | ✅ — `src/reminders.py` detecta "me lembra de X" / "lembrete: X" / "não me deixa esquecer de Y" nas conversas (regex DETERMINÍSTICO, sem LLM), extrai o quê e um vencimento relativo ("amanhã"/"em N dias"/"semana que vem"). Persistido (tabela `reminders`, dedup de pendentes); o chat anota em background (`_maybe_extract_reminder`, espelha o `_maybe_extract_fact`); o `_scheduler_loop` resurfaceia os vencidos como notificação; entram no briefing. Endpoints `/api/reminders` (GET/POST) e `/api/reminders/{id}/done`. Verificado no preview (ciclo criar→listar→briefing→concluir) |
| Q2 | M4 | Notificações que importam | ✅ — `src/notifications.py`: prioridade por tipo (reminder/briefing=3 … study=0) e COLAPSO dos avisos de baixa prioridade (5 "estudei X" → 1 "📚 Estudei 5 tópicos", com `count`). `add_notification` colapsa study não-lido na janela; `list_notifications(min_priority=)` esconde o ruído ("só o que importa"); a UI ganhou borda de destaque + ×N. Migração automática (`_migrate` adiciona colunas priority/count em bancos antigos — `create_all` não faz ALTER). DoD M4 batida: aborda no momento certo, sem virar ruído. Verificado no preview |
| Q2 | M6 | Ferramentas com permissão (6.1) | ✅ **framework de agência** — `src/tools/registry.py`: toda ação que toca o mundo é uma `Tool` com `scope`; `run_tool` é o ÚNICO caminho e SEMPRE checa consentimento → audita → executa/nega. Storage: `Permission` (grants por escopo) + `ToolAudit` (log de tudo). Escopos declarados (`files.read`/`calendar.read`/`email.read`) + ferramenta segura embutida `clock` (sem escopo). Endpoints `/api/permissions` (grant/revoke), `/api/tools` (+run), `/api/tools/audit`. UI: painel 🔐 Permissões (tela de consentimento, grant/revoke por escopo). Verificado no preview (negado→grant→permitido→revoke; tudo auditado) |
| Q2 | M6 | Ler arquivos (6.2) | ✅ — `src/tools/files.py`: `files.search`/`files.read` (scope `files.read`), read-only e CONFINADAS às pastas autorizadas (a `note` do grant é a **allowlist**; `resolve()` neutraliza `..`/symlink de fuga; fora da pasta = negado+auditado mesmo com grant). `registry` ganhou `ToolContext` + `_invoke` (introspecção de assinatura → handlers antigos de 1 arg seguem funcionando). UI: autorizar pede a pasta (caminho vai na `note`, não inlinado no onclick por causa do `\` do Windows). 13 testes (traversal/symlink/fora-da-pasta) |
| Q2 | M6 | Agenda & e-mail (6.3) | ✅ **DoD batida** — `calendar.events` (scope `calendar.read`): parser `.ics` próprio e determinístico + janelas hoje/amanhã/semana (`note`=caminho do .ics). `email.recent` (scope `email.read`): IMAP **read-only por construção** (EXAMINE nunca marca \Seen/apaga), credenciais SÓ do `.env` (nunca no banco). Ponte NL→ferramenta `src/tools/intent.py` + `POST /api/agency/ask`: **"resuma meus e-mails de hoje"** e **"o que tenho na agenda amanhã"** funcionam com permissão explícita (desacoplado do chat → não interfere no aprendizado). 25 testes |
| Q3 | M7 | Roteador de tarefa (7.1) | 🔨 — `routing.route_task(text)` decide a ROTA sem desperdiçar CPU: **tool** (comando de agência CURTO e não-complexo → `run_tool`, sem LLM), **heavy** (14b) ou **light**; marca `factual`. Conservador: pergunta longa que por acaso casa um regex de intenção NÃO vira comando (guarda de nº de palavras + regex `clock` com lookahead). `POST /api/route`. UI: `sendMessage` desvia comando curto para `/api/agency/ask` (ex.: digitar "que horas são?" responde na hora, sem 14b) — verificado ao vivo. 6 testes |
| Q3 | M7 | Verificação anti-alucinação (7.2) | 🔨 **cadeia de verificação** — `src/verify.py` (determinístico, sem LLM): `is_factual_question` separa pergunta de fato de pedido criativo/código/opinião; `grounding_score` mede a sobreposição léxica entre os termos da resposta e as FONTES da base (RAG); `verdict` decide alta/media/baixa/sem_fonte e devolve um aviso de incerteza quando a resposta factual NÃO tem lastro. `POST /api/verify` recupera fontes (MemoryFabric/RAG) e avalia. UI: respostas factuais sem ancoragem ganham um `.verify-chip` ("⚠️ Não encontrei isso na minha base…") — sem poluir quando há lastro. Verificado ao vivo. 12 testes |
| Q3 | M8 | Conexões no grafo (8.3) — DoD | 🔨 **DoD do M8 batida** — `src/graph.py` (determinístico): `shared_concepts`/`strength` (conceitos em comum entre 2 sínteses), `explain` (direto ou via PONTE de 2 saltos), `parse_connect_question` ("como X se conecta com Y?"/"relação entre X e Y"). Tabela `topic_edges` (não-direcionada, canônica) + mixin (`add_edge`/`neighbors`/`get_edge`/`find_bridge`/`count_edges`). Learner: ao aprender, `_link_related` liga o tópico novo aos 5 recentes com mais conceitos em comum (arestas do grafo, sem LLM). `GET /api/graph/connect?a=&b=` (ou `q=`) + `/api/graph/neighbors`. Roteador (7.1) reconhece a pergunta → chat responde **"como X se conecta com Y?"** sem gastar LLM (verificado ao vivo). 20 testes. **M8 software concluído** (8.1+8.2+8.3) |
| Q3 | M8 | Verificação de fatos (8.2) | 🔨 — `src/factcheck.py` (determinístico): `extract_facts` ancora em FATOS objetivos (anos + quantidades c/ unidade); `corroboration(nova, base)` = fração dos fatos novos que já aparecem na base (baixa + sem apoio → sinaliza); `numeric_drift(velha, nova)` detecta uma DATA que mudou sobre o mesmo tópico (candidata a contradição). `POST /api/factcheck`. Learner: ao re-estudar um tópico, compara a síntese anterior com a nova e, se uma data mudou, AVISA ("⚠️ Fato mudou em X"). 10 testes. Falta 8.3 (conexões no grafo — DoD do M8) |
| Q3 | M8 | Recall ativo + repetição espaçada (8.1) | 🔨 — `src/spaced.py` (SM-2 determinístico): intervalos crescentes (1d→6d→~15d…), esquecer reseta e conta lapso; `quality_from_recall` deriva a nota da FORÇA do recall (sem LLM). Tabela `review_schedule` + mixin (`upsert_review`/`due_reviews`/`get_review`/`count_reviews`). Learner: ao salvar agenda a revisão; a cada ~10 min `_run_active_recall` se AUTO-TESTA nos tópicos vencidos (força do recall no RAG), reprograma via SM-2 e **re-enfileira o que esqueceu** (self_directed ignora o RELEARN_DAYS) — sem LLM, não concorre com o summarizer. `GET /api/learning/reviews`. 18 testes. Falta 8.2 (verificação de fatos) e 8.3 (conexões no grafo) |
| P6 | Extra | **Apolo-Nano — LLM própria do zero** (plano próprio: [`APOLO_NANO_ROADMAP.md`](APOLO_NANO_ROADMAP.md)) | 🔨 **motor completo entregue** — `src/nanollm/`: LLM construída DO ZERO, sem PyTorch/HF/autograd/pesos de terceiros (pedido do Leo: "do zero sem usar nada de ninguém"). Tokenizer BPE byte-level treinável (Python puro, contagem incremental de pares), GPT decoder-only (atenção causal multi-head, pré-LN, GELU) com **forward E backward manuais** em NumPy, Adam+warmup/cosine+grad-clip do zero, treino resumível com checkpoints `.npz` e CLIs (`data`/`train`/`generate`). Backprop PROVADO por gradient checking numérico (float64, todas as camadas) + teste de causalidade + overfit. Presets p/ CPU: nano ~0.9M / mini ~3M / small ~7M params. Smoke real: treinado nos docs do próprio repo. Escala honesta: laboratório de soberania (~7M params gera PT coerente), NÃO substitui o 14B. Próximo: corpus PT-BR de verdade + treinar `small` + integrar ao app |
| Q3 | M7 | Self-consistency barata (7.3) | 🔨 — `src/consistency.py`: amostra 2–3 respostas e **reconcilia** (concordância = sobreposição léxica entre amostras, `pairwise_agreement`/`reconcile`/`_medoid`); se divergem a cada tentativa → sinal de alucinação → aviso de baixa confiança. `self_consistent_answer(question, sampler, n)` com sampler INJETÁVEL (fake nos testes, modelo leve com temperatura=0.9 em produção). `POST /api/consistency` (sob demanda — N inferências). 8 testes. **M7 software concluído** (7.1+7.2+7.3); DoD "medir queda de alucinação" depende do harness de eval do M9 |
| Q2 | M5 | Wake word + conversa contínua | ✅ **código concluído** — 5.1 wake word local/determinística (`src/wake.py`: normaliza, tolera preâmbulo e erro de transcrição edit-distance ≤1, casa no início, extrai o comando; `GET /api/wake/config` + `POST /api/wake/detect`); intenção `clock` fecha **"Apolo, que horas são?"** (verificado ponta-a-ponta). 5.2 **barge-in** (`onspeechstart` corta a fala do assistente ao você falar). 5.3 **VAD** já existente no loop mãos-livres (energia + silêncio → `/api/stt` Whisper local). Botão 👂 + escuta contínua → detect → `/api/agency/ask` → fala. **Pendência 🔒 HW (lado do Leo, como o Piper no M3):** captura contínua 100% SOBERANA (a Web Speech é nuvem Google) via openWakeWord/Whisper-loop + medir latência <1s no CPU. 16 testes |

> **🏁 M1 (Arquitetura & Observabilidade) — 100% concluído (2026-07-06).** Monólitos quebrados (backend em routers+mixins, frontend em CSS/JS externos), observabilidade e auditoria no ar, e a DoD batida: nenhum arquivo Python > 800 linhas; suíte verde (630); UI idêntica ao usuário.
>
> **🏁 M2 (Tecido de Memória Unificado) — 100% concluído (2026-07-06).** MemoryFabric é a porta única sobre RAG + base + lições + episódios; todo recall semântico do app passa por ela; memória episódica/autobiográfica com recall temporal ("o que fizemos ontem?") e consolidação automática ("sono") que transforma conversas em episódios sozinha. DoD batida.
>
> **🏁 M3 (Voz Local de Verdade) — código concluído (2026-07-06).** TTS soberano (fachada que prefere Piper local sobre edge nuvem, com reporte honesto de `tts_local`); STT sempre pronto (Whisper pré-carregado no boot, sem cold-start na 1ª ditada); loop conversacional mãos-livres integrado ao stack de voz (usa o TTS do servidor p/ qualquer engine). **Pendência do usuário para 100% soberano:** `pip install piper-tts` + baixar um modelo PT-BR e medir a latência no CPU (🔒 HW). Fecha o Q1 (Fundação).
>
> **🏁 M4 (Proatividade) — 100% concluído (2026-07-06).** O Jarvis deixa de só esperar: briefing diário falável (o que aprendi/fizemos + agenda + lembretes + pendências), lembretes/follow-ups detectados nas conversas ("me lembra de X") que resurfacem no momento certo, e notificações com prioridade + colapso anti-ruído. DoD batida: aborda primeiro, no momento certo, sem virar ruído.
>
> **🏁 M6 (Ler o Mundo com Permissão) — 100% concluído (2026-07-06).** Agência com consentimento: framework de tools onde `run_tool` sempre checa permissão → audita → executa/nega (6.1); leitura de arquivos confinada a pastas autorizadas, à prova de `..`/symlink (6.2); agenda `.ics` (parser próprio) e e-mail IMAP read-only com credenciais só no `.env` (6.3); ponte linguagem-natural `POST /api/agency/ask` fazendo **"resuma meus e-mails de hoje"** e **"o que tenho na agenda amanhã"** funcionarem com permissão explícita. DoD batida. Restante do Q2: **M5 — Wake Word & Conversa Contínua** (🔒 HW latência).
>
> **🏁 M5 (Wake Word & Conversa Contínua) — código concluído (2026-07-07).** Palavra de ativação local e determinística ("Apolo"/"Jarvis") com "Apolo, que horas são?" ponta-a-ponta (5.1); barge-in — falar corta a fala do assistente (5.2); VAD do loop mãos-livres detecta fim de fala (5.3). **Pendência do usuário p/ 100% soberano:** captura contínua sem nuvem (openWakeWord/Whisper-loop) + latência <1s no CPU (🔒 HW), no mesmo espírito do Piper no M3. **Fecha o Q2 (Presença & Agência).**
>
> **🏁 M7 (Raciocínio Confiável) — software concluído (2026-07-07).** Roteador de tarefa (7.1: comando curto → porteira sem LLM; pergunta complexa → 14b), verificação anti-alucinação (7.2: resposta factual sem lastro na base ganha aviso de incerteza) e self-consistency barata (7.3: divergência entre amostras = sinal de chute). O DoD "medir a queda de alucinação" ficou pendente do harness do M9.
>
> **🏁 M8 (Aprendizado que Entende) — software concluído (2026-07-07).** O A.P.O.L.O. não só acumula: se auto-testa com repetição espaçada SM-2 e re-enfileira o que esquece (8.1), cruza fatos (datas/quantidades) e sinaliza contradições ao re-estudar (8.2) e liga os tópicos num grafo de conhecimento, respondendo "como X se conecta com Y?" pelos conceitos em comum — ou por uma ponte — sem gastar LLM (8.3, DoD). Tudo determinístico e testável.
>
> **🏁 M9 (Harness de Avaliação) — software concluído (2026-07-08). FECHA O Q3 (Cérebro & Qualidade).** Tarefas-canário fixas (chat/coder/recall + **armadilhas** de premissa falsa) rodam sob demanda e viram placar histórico; a fração de armadilhas mordidas é a **taxa de alucinação** (9.1). O 👍/👎 do Leo virou dado acionável com o "por quê" + pergunta/resposta (9.2). E o painel **"Estou melhorando?"** funde qualidade, alucinação, satisfação e acerto do Coder num veredito com setas e sparkline (9.3). **Fecha o DoD do M9 e do M7**: a queda de alucinação agora é medida e acompanhada no tempo, não afirmada. O runner do eval pega o `llm_lock` do learner → não reintroduz o freeze 14b+3b.
>
> **🏁 M10 (Agência: Ação no Mundo) — software concluído (2026-07-08).** O A.P.O.L.O. deixa de só LER o mundo e passa a AGIR nele, sempre com controle: ações com prévia → confirmação → desfazer, sobre um ledger reversível e auditado (10.1); rotinas que rodam sozinhas no horário combinado, cada execução reversível ("toda sexta, resumo da semana", 10.2); e automação web em sandbox — opt-in por escopo + allowlist de domínios, read-only, soberana no CPU (10.3, DoD). O DoD foi batido: uma rotina multi-passo real, com trilha de auditoria e reversível. Driver de navegador interativo (Playwright) e ações que tocam apps nativos ficam 🔒 opt-in.
>
> **🏁 M11 (Soberania Total) — software concluído (2026-07-09).** As duas travas estruturais que faltavam caíram: **criptografia em repouso** (backup local cifrado com scrypt+Fernet autenticado; a senha nunca é gravada; auto-backup diário opcional; 11.2) e **acesso remoto seguro** (gate por token que cobre a UI inteira para clientes de fora da máquina, com o dono livre no localhost; URL da LAN para o celular; 11.3). E os **embeddings do recall são 100% locais** — default ONNX na CPU, ou um fallback Python que roda sem nada instalado nem internet (11.1). DoD do M11 essencialmente batido: dados criptografados, alcançável do celular na rede, recall funciona offline. Pendências 🔒 do Leo: `HOST=0.0.0.0`+`REMOTE_TOKEN`/túnel HTTPS para acesso externo; modelo de embedding PT-BR maior (GPU).
>
> **🏁 M12 (Projetos Autodirigidos & Retrospectiva) — software concluído (2026-07-09).** O A.P.O.L.O. passa a conduzir a própria evolução: lê as próprias métricas e propõe metas de melhoria priorizadas, com passos concretos, que o Leo adota e acompanha (automelhoria supervisionada — nada roda o Coder sozinho; 12.1). E fecha o ciclo com a **retrospectiva do ano falada** — um balanço dos números do ano + a proposta dos focos do ano 2, apresentada por voz (12.2). Polimento e documentação: versão **1.0.0**, README e roadmap completos (12.3).
>
> **🎉 ANO 1 DO ROADMAP JARVIS — COMPLETO (2026-07-09, v1.0.0).** Os 12 milestones entregues em software: fundação (arquitetura, memória unificada, voz local), presença & agência (proatividade, wake word, ler o mundo com permissão), cérebro & qualidade (roteamento, anti-alucinação, aprendizado que entende, harness de avaliação) e autonomia & soberania (ação no mundo com undo, cripto/remoto/embeddings locais, projetos autodirigidos + retrospectiva). Suíte >1060 verde. Pendências abertas são de HARDWARE (`🔒 HW`: GPU para cérebro maior, fine-tuning e latência de voz tempo-real) e de SETUP do Leo (Piper PT-BR, `HOST=0.0.0.0`+`REMOTE_TOKEN`/túnel HTTPS, captura de voz contínua soberana). O ano 2 começa pelos focos que o próprio A.P.O.L.O. propõe na retrospectiva.
>
> **🐛 Correções críticas de aprendizado (2026-07-06/07):** (1) **não aprendia** (`buscados:0`) — `fetch_page_text` usava `headers` indefinido (regressão de perf 2200f13), NameError engolido por `except+logger.debug`. (2) **painel congelado** — SSE chamava `applyLearnStatus` inexistente sob `catch {}`. (3) botões 🕒/🔐 brancos (IDs fora da regra CSS). (4) **"estudou 45 e travou"** — escritas no Supabase sem timeout (default 120s × retry) esgotavam o pool de threads compartilhado com o summarizer → congelamento; fix: `ClientOptions(timeout)`, `_persist` com teto, workers do pipeline BLINDADOS contra exceção (worker morto = fila lota = freeze), e **detecção de stall** que grita a causa provável em vez de morrer em silêncio. (5) **"estudou muito e travou de vez"** (todo tópico com `timeout`, `[synthesizer] Erro:` vazio) — a síntese (14b) e o replenish rodavam LLM EM PARALELO com o summarizer (3b) via `create_task`, violando a invariante "único consumidor do Ollama"; numa 16GB CPU-only os dois modelos inferindo juntos travam tudo. Fix: `asyncio.Lock` serializa TODA inferência do learner (summarize+síntese+replenish) — uma de cada vez, cada uma a plena velocidade. Todos com teste de regressão.

---

*Documento vivo. Última atualização: 2026-07-09 — 🎉 Ano 1 completo (v1.0.0).*
