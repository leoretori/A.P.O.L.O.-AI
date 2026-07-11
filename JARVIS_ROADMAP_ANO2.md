# 🛰️ JARVIS — Roadmap do Ano 2 (Apolo AI)

> Continuação do [JARVIS_ROADMAP.md](docs/JARVIS_ROADMAP.md) (Ano 1, M1–M12, **v1.0.0** ✅). Mesma cadência: **1 incremento por dia**, testado, commitado no branch e mergeado no `main`, com README e memória atualizados. Sem regressões (a suíte fica verde). Documento vivo.

**Início:** 2026-07-09 · **Alvo:** 2027-07 · **Dono:** Leo · **Copiloto:** Claude Code · **Milestones:** M13–M24

---

## 1. Onde chegamos (Ano 1) — o ponto de partida

Em 12 meses construímos **todo o scaffolding do Jarvis** e chegamos ao **v1.0.0**: arquitetura modular + observabilidade, tecido de memória unificado + episódica, voz local, proatividade/briefing, wake word, ler o mundo com permissão, roteamento + verificação anti-alucinação, aprendizado que entende (repetição espaçada + grafo), harness de avaliação, ação no mundo com undo + rotinas + web sandbox, criptografia + acesso remoto + embeddings locais, e automelhoria supervisionada + retrospectiva falada. Suíte **>1080 verde**.

A aposta do Ano 1 se confirmou: **80% da experiência "Jarvis" é scaffolding — e está de pé.** O que ficou para trás foi, quase inteiramente, o **cérebro** (os pesos do modelo) e o que depende de **hardware**. O Ano 2 ataca exatamente essa fronteira — e agora temos uma arma nova que o Ano 1 não tinha: o **[Apolo-Nano](docs/APOLO_NANO_ROADMAP.md)**, a LLM própria em construção.

---

## 2. A tese do Ano 2

> **O scaffolding está pronto. Agora enchemos ele de profundidade e damos ao Apolo um cérebro que é dele.**

Três eixos, costurados pelo Apolo-Nano:

1. **O cérebro se torna seu.** Integrar o Apolo-Nano ao app como backend real para tarefas leves, criar o **roteamento híbrido** (Nano instantâneo + 14B pesado) e fechar o **flywheel**: o Apolo aprende → o corpus alimenta o Nano → o Nano treina → serve as tarefas leves do Apolo → libera o 14B. Soberania que sai do disco (dados) e chega ao raciocínio (pesos).
2. **Conhecer o Leo de verdade.** O Ano 1 deu memória; falta o **modelo profundo** — metas, hábitos, pessoas, projetos, contexto de vida — e a personalização que adapta o comportamento a você.
3. **Agência que conduz.** O Ano 1 leu e escreveu o mundo (com undo); o Ano 2 faz o Apolo **executar** os projetos que ele mesmo propõe (12.1), operar um **navegador interativo** e **apps nativos** — sempre com confirmação e trilha reversível.

**A honestidade de sempre — agora como engenharia de restrição, não espera:** não fingimos que um Ryzen faz GPT-4. Mas o cérebro soberano **começa a ser desenvolvido AGORA no hardware atual** (destilação de tarefa estreita, escala incremental do Nano de madrugada, iGPU via Vulkan) em vez de esperar a GPU. A GPU dedicada acelera tudo — vira **upside, não pré-requisito** (§6 e §10/Ano 3).

---

## 3. O que ainda falta (limitações no fim do Ano 1)

| # | Limitação | Impacto | Onde |
|---|-----------|---------|------|
| Y1 | **Cérebro "alugado".** O chat depende do Qwen (local, sim, mas não é *seu*). O Apolo-Nano existe mas **não serve nada** no app ainda. | Fundamental | app ↔ nanollm |
| Y2 | **Modelo raso do Leo.** A memória guarda fatos, mas não o **contexto de vida**: metas, hábitos, relações, projetos, valores. `profile.py` ainda é fino. | Alto | `src/profile.py` |
| Y3 | **Agência que lê/escreve mas não CONDUZ.** O 12.1 *propõe* projetos e para aí; sem navegador interativo, sem apps nativos, sem execução supervisionada multi-passo. | Alto | agência |
| Y4 | **Aprendizado não vira capacidade.** O Apolo acumula conhecimento, mas não treina o **próprio cérebro** com ele — o flywheel está desconectado (o corpus já é exportável, falta o loop). | Alto | app ↔ nanollm |
| Y5 | **Multimodal raso.** Visão existe mas é subutilizada; tela, câmera e documentos não são entrada rica de contexto. | Médio-alto | visão |
| Y6 | **Presença intermitente.** Responde e faz briefing, mas não é um ambiente contínuo que acompanha o seu dia. | Médio | presença |
| Y7 | **Prova de melhora só pontual.** O M9 mede num instante; falta o **loop fechado** (medir → agir → re-medir automático) que prove evolução no longo prazo. | Médio | qualidade |
| ⚙️ | **Hardware modesto (não mais trava).** Ryzen 5 4600G + iGPU Vega + 16GB. GPU dedicada acelera, mas o cérebro próprio se desenvolve no que temos: iGPU/Vulkan, destilação, escala incremental. | Oportunidade | máquina |

---

## 4. Os pilares do Ano 2

- **P7 · Cérebro Híbrido & Soberano** — Nano integrado, roteamento híbrido, flywheel aprender→treinar→servir, estrada pronta para a GPU. *(Y1, Y4)*
- **P8 · Modelo Profundo do Leo** — metas, hábitos, relações, projetos, valores; personalização que adapta. *(Y2)*
- **P9 · Agência que Conduz** — execução supervisionada de projetos, navegador interativo, apps nativos. *(Y3)*
- **P10 · Multimodal & Presença** — visão útil, tela/documentos/câmera, presença ambiente. *(Y5, Y6)*
- **P11 · Qualidade Comprovada** — loop fechado de automelhoria; evals que dirigem ações. *(Y7)*
- **P6 · Soberania** (herdado) — segue como princípio transversal: cada feature roda offline; o cérebro migra de alugado para próprio.

---

## 5. Calendário de 12 meses (M13–M24)

> Cada mês tem 3 épicos; cada épico vira ~15–20 incrementos diários pequenos, testados e verdes. "DoD" = Definition of Done. O padrão que funcionou o Ano 1 continua: **determinístico primeiro + dependências injetáveis** (fake nos testes), verificação no preview, suíte cheia, merge, push.

### 🗓️ Q1 (Y2) — O CÉREBRO SE TORNA SEU *(P7)* — costura com o [Apolo-Nano](docs/APOLO_NANO_ROADMAP.md)

#### **Mês 13 — Ponte Nano ↔ Apolo**
- Épico 13.1 — **Engine do Nano no app:** `src/nanollm/engine.py` carrega um checkpoint 1× e gera thread-safe; `POST /api/nano/complete`; card **🧬 Apolo-Nano** no painel Saúde (`nano_ready`, params, ppl do checkpoint). É o lado-app do D6/M3 do roadmap do Nano.
- Épico 13.2 — **Gate de recursos:** o Nano NUNCA infere durante o 14B (reusa o `GpuGate`/serialização do learner — a lição do thrash 14b+3b vale aqui). Fila e prioridade do usuário preservadas.
- Épico 13.3 — **Observabilidade do Nano:** latência, tokens/s, taxa de fallback, no painel + auditoria. Sem número, sem promoção.
- **DoD M13:** o app carrega e serve o Nano por um endpoint, com gate que não trava a máquina.

#### **Mês 14 — Roteamento híbrido**
- Épico 14.1 — **O roteador aprende o Nano:** `route_task` (M7) ganha a rota **nano** para tarefas leves e tolerantes (título de conversa, tags, classificação de setor, autocomplete curto). Conservador: só o que o Nano provou fazer.
- Épico 14.2 — **Primeira tarefa em produção com fallback:** título automático de conversa servido pelo Nano; se falhar/vier ruim, cai para o modelo grande. Medir latência e qualidade às cegas (Nano vs 14B).
- Épico 14.3 — **Economia visível:** painel mostra **% das tarefas leves servidas pelo Nano** e o 14B poupado — a soberania do cérebro subindo em número.
- **DoD M14:** ≥1 feature real do Apolo rodando no Nano em produção, latência <1s, fallback seguro, economia medida.

#### **Mês 15 — O flywheel: aprender → treinar → servir**
- Épico 15.1 — **Corpus vivo:** o `corpus_export` do Nano roda periodicamente (o Apolo estuda todo dia → o corpus cresce sozinho); agendado pelas **rotinas do M10**, sem competir com o 14B.
- Épico 15.2 — **Promoção com gate de qualidade:** um novo checkpoint só substitui o ativo se o **harness de eval do Nano** melhorar (ppl/amostras-sonda) — nada de "atualizei e piorou em silêncio". Trilha reversível (undo do M10).
- Épico 15.3 — **Fine-tune no hardware atual:** em vez de esperar LoRA do 14B na GPU, **destilar o Nano** dos dados do Leo (dataset gerado localmente pelo Qwen) e treinar de madrugada; explorar LoRA de modelos **pequenos** (0,5–1,5B) no CPU/iGPU. A estrada da GPU continua pronta (liga mais rápido no dia), mas **não é pré-requisito**.
- **DoD M15:** um comando (ou rotina) fecha o ciclo "o Apolo estudou → o Nano re-treinou → só sobe se melhorou".

### 🗓️ Q2 (Y2) — CONHECER O LEO DE VERDADE *(P8)*

#### **Mês 16 — Modelo profundo do Leo**
- Épico 16.1 — **Schema rico:** substitui o `profile.py` raso por um modelo com **metas** (curto/longo prazo), **hábitos/rotinas**, **pessoas** (quem é quem na sua vida), **projetos ativos**, **preferências e valores** — tudo com consentimento e editável.
- Épico 16.2 — **Extração das conversas:** deriva candidatos ao modelo a partir de episódios/conversas (determinístico + LLM leve), sempre com **você confirmando** antes de gravar (nada assumido).
- Épico 16.3 — **Painel "Quem eu acho que você é":** o Apolo mostra o que entendeu de você, você corrige — o modelo fica transparente e seu.
- **DoD M16:** o Apolo mantém um perfil profundo, curado por você, que alimenta as respostas.

> **Progresso — Épico 16.1 ENTREGUE (2026-07-09):** `src/profile.py` deixou de ser lista rasa e virou modelo ESTRUTURADO por categoria (metas c/ horizonte curto/longo, projetos, hábitos, pessoas, preferências, valores; `CATEGORIES`/`normalize_category`). API antiga preservada 100% (add/list/remove/as_context) + `by_category`/`update`; perfis antigos migram sozinhos (entrada sem categoria → "fato"). `as_context` injeta AGRUPADO por seção no system prompt. Router: POST aceita `category`/`horizon`, novo `PATCH /api/profile/{id}` (edição), GET expõe `by_category`+rótulos; **bug corrigido**: DELETE não invalidava o cache do system prompt. 16 testes novos.
>
> **Progresso — Épico 16.2 ENTREGUE (2026-07-09):** extração com CONFIRMAÇÃO — "nada assumido". `src/profile_extract.py` `extract_candidates(msg)` DETERMINÍSTICO (regex categorizado, sem LLM): detecta metas/projetos/hábitos/preferências/valores + horizonte da meta; nega "não quero", corta na pontuação, no máx. 1 por categoria. Fila pendente no `UserProfile` (arquivo irmão `*_candidates.json`): `propose` (dedup contra fatos/pendentes/recusados), `pending`, `confirm` (move p/ perfil, com edição opcional), `reject` (recusa e não re-propõe na sessão). **Mudança-chave:** o `_maybe_extract_fact` do chat agora PROPÕE (determinístico 1º; LLM leve só como rede, também vira candidato) em vez de gravar `source=auto` direto. Endpoints: `GET /api/profile/candidates`, `POST .../{id}/confirm|reject`. 34 testes novos.
>
> **🏁 Épico 16.3 ENTREGUE — M16 COMPLETO (2026-07-09):** o painel "Sobre mim" virou o "Quem eu acho que você é". `loadProfile` (app.js) mostra o modelo AGRUPADO por seção (16.1) + os CANDIDATOS pendentes com ✓/✕ (16.2) + **editor inline** (16.3): cada entrada tem ✎ que troca por input de texto + `<select>` de categoria + horizonte, salvando via `PATCH /api/profile/{id}` (`editFactUI`/`saveFactEdit`, data-* levam os valores sem inliná-los no onclick). VERIFICADO AO VIVO (porta 8125): add "Apolo AI" como fato → PATCH editou o texto E recategorizou p/ project → `by_category` refletiu. Testes de contrato em test_frontend_assets. **DoD do M16 batida:** perfil profundo, curado por você (add/confirmar/editar/recategorizar/esquecer), que alimenta o system prompt agrupado. **PRÓXIMO: M17 (personalização que adapta) — briefing/proatividade ranqueiam pelas suas metas/projetos.**

#### **Mês 17 — Personalização que adapta**
- Épico 17.1 — **Priorização pessoal:** briefing, sugestões e proatividade passam a ranquear pelo que importa PARA VOCÊ (metas/projetos ativos), não genérico.
- Épico 17.2 — **Ritmo & tom:** o Apolo aprende seu horário, seu estilo (direto vs detalhado) e ajusta quando/quanto fala — mensurável, reversível.
- Épico 17.3 — **Antecipação útil:** conecta metas + agenda + hábitos para lembrar/sugerir no momento certo ("você queria retomar X, tem uma janela amanhã").
- **DoD M17:** a experiência muda de forma perceptível e mensurável conforme o modelo do Leo.

> **Progresso — Épico 17.1 ENTREGUE (2026-07-09):** o modelo profundo (M16) começa a MUDAR o comportamento. `src/briefing.py` ganhou `_focus_items(profile)` (metas+projetos ativos do perfil) e `relevant_learned(learned, focus)` — casa o que o Apolo aprendeu com o que o Leo está tocando via `src.graph` (Jaccard de conceitos + `shared_concepts`), no máx. 1 destaque por foco, acima do limiar (sem ruído). `build_briefing(profile=...)` PRIORIZA: o texto falado passa a dizer "isso conecta com seu projeto/sua meta 'X': [tópico]" logo após o resumo. Retrocompatível (sem profile = briefing genérico de antes). Wiring: `rt.profile` passado no scheduler (app.py) e no `GET /api/briefing`. VERIFICADO AO VIVO: entre "asyncio streaming" e "história romana", destacou só o primeiro (conecta com o projeto), ignorou o romano. 6 testes novos.
>
> **Progresso — Épico 17.2 (tom) ENTREGUE (2026-07-09):** o Apolo ajusta QUANTO fala pelo estilo do Leo. `src/style.py` `derive_tone(profile)` DETERMINÍSTICO: lê as preferências/valores do perfil (M16), placar de palavras-sinal → **direto / detalhado / equilibrado** (empate ou sem sinal = equilibrado, não impõe estilo). `style_directive(tone)` injeta a diretriz no system prompt do chat (só quando há sinal claro; cache por sessão já cobre — depende do mesmo `profile_facts`). `GET /api/style` expõe o tom (transparente/reversível: muda a preferência → muda o tom). VERIFICADO AO VIVO: "prefiro respostas diretas"→direct, "explicações detalhadas"→detailed, "futebol"→balanced. 10 testes.
>
> **🏁 Épico 17.3 ENTREGUE — M17 COMPLETO (2026-07-09):** antecipação útil + o "quando" que faltava do 17.2. `src/anticipation.py` `suggest_anticipations(profile, recent_texts)` DETERMINÍSTICO: acha metas/projetos ativos que a atividade recente (episódios + aprendizado) NÃO tocou (inverso do 17.1, via `src.graph.strength` < limiar = negligenciado) e propõe retomá-los, ancorados no HÁBITO (`habit_period`: "de manhã/à tarde/à noite" → o "quando"). Projetos antes de metas, com limite. Integrado ao `build_briefing` (usa episódios+aprendizado que ele já coleta) → o texto falado ganha "Você não avança sua meta 'X' ultimamente. Você costuma se dedicar de manhã — que tal retomar?" + `GET /api/anticipations`. VERIFICADO AO VIVO: o briefing conectou o asyncio ao projeto Apolo AI (17.1) E sugeriu retomar a meta "Rust" esquecida no horário do hábito (17.3), SEM cobrar o projeto já tocado. 10 testes. **DoD do M17 batido: a experiência muda de forma perceptível conforme o modelo do Leo** (prioriza o que importa, adapta o tom, antecipa o esquecido). 🏁 **M16 + M17 = pilar P8 "Conhecer o Leo de verdade" avançado.** PRÓXIMO: M18 (memória relacional & temporal profunda).

#### **Mês 18 — Memória relacional & temporal profunda**
- Épico 18.1 — **Linha do tempo da vida:** episódios (M2) conectados a metas, pessoas e projetos — "o que estava rolando quando fizemos X".
- Épico 18.2 — **Pessoas & contexto:** um grafo leve de quem-é-quem, ligado às conversas e compromissos.
- Épico 18.3 — **Recall que entende relações:** "o que o [fulano] me pediu?", "onde parei no projeto Y?" respondidos pela memória relacional.
- **DoD M18:** perguntas relacionais/temporais complexas retornam respostas certas e datadas.

> **Progresso — Épico 18.1 ENTREGUE (2026-07-10):** a linha do tempo da vida. `src/timeline.py` liga os episódios datados (M2) às ENTIDADES do modelo do Leo (M16 — pessoa/projeto/meta): cada episódio deixa de ser texto solto e passa a saber QUEM/O QUÊ/QUANDO tocou. Casamento determinístico por nome próprio (âncoras capitalizadas) OU conceitos em comum acima do limiar (reusa `src.graph`, o mesmo do 17.1/17.3), sem LLM. `link_event` anota `refs {person/project/goal}`; `timeline()` ordena (o DB entrega recente→antigo) e filtra por entidade — a base de "o que estava rolando em torno de X". `GET /api/timeline?entity=&when=` (`when` aceita frase temporal via `episodic.recall_phrase`). 11 testes.
>
> **Progresso — Épico 18.2 ENTREGUE (2026-07-10):** quem-é-quem. `people_overview()` deriva da linha do tempo, para cada pessoa do modelo, QUANDO foi vista por último, em que PROJETOS/METAS apareceu e com QUEM coaparece (o grafo leve de relações). Pessoas que o Apolo conhece mas que nunca surgiram num episódio vêm com `mentions:0` (útil: "você me falou dela, mas não voltamos ao assunto"). `GET /api/people`. +4 testes.
>
> **🏁 Épico 18.3 ENTREGUE — M18 COMPLETO (2026-07-10):** recall que entende relações. `parse_relational_question()` reconhece as perguntas (asked / where_stopped / about) e `answer_relational()` responde pela linha do tempo, SEMPRE datado — acha o episódio mais recente que menciona a entidade e devolve com dd/mm/aaaa (determinístico, sem LLM). Integrado ao chat: `_do_relational()` roda em paralelo ao recall semântico + FTS; se a pergunta é relacional e casou um episódio real, entra como `RELATIONAL_SECTION` — fonte de verdade datada que o modelo usa sem inventar. Também em `GET /api/recall?q=`. Front: painel **📜 Linha do tempo** (`openTimeline`/`loadTimeline`/`loadPeople`/`askRecall`, abas linha-do-tempo/pessoas, chips de entidade). **DoD do M18 batido: perguntas relacionais/temporais complexas retornam respostas certas e datadas.** +11 testes (suite 1204→1230, +26 no M18). PRÓXIMO: M19 (execução supervisionada de projetos — Q3, pilar P9 "agência que conduz").

### 🗓️ Q3 (Y2) — AGÊNCIA QUE CONDUZ *(P9)*

#### **Mês 19 — Execução supervisionada de projetos**
- Épico 19.1 — **Do propor ao fazer:** os projetos do **12.1** deixam de só ser propostos — o Apolo **executa os passos** usando as ações do M10 + o Coder, sempre com **preview → confirmação → undo** por passo.
- Épico 19.2 — **Plano multi-passo verificável:** cada projeto vira um plano com checkpoints; o Apolo reporta progresso e para para confirmar nos pontos sensíveis.
- Épico 19.3 — **Fecha o loop "propõe → faz → mede":** ao concluir um projeto, o Apolo re-mede a métrica que o motivou (o eval do M9) e mostra se melhorou de verdade.
- **DoD M19:** o Apolo conduz um projeto de melhoria multi-passo real, do começo ao fim, reversível e medido.

> **Progresso — Épico 19.1 ENTREGUE (2026-07-10):** do propor ao FAZER. `src/project_exec.py` dá um EXECUTOR aos passos dos projetos autodirigidos (M12): registro de `StepOp {preview (sem efeito), run (aplica + re-mede)}`, cada um embrulhando uma função que JÁ existe e é testada — `get_summary_quality`/`count_topic_duplicates` (medir), `dedup_learned_topics`/`rag.dedup_exact(dry_run)` (o dry_run vira a prévia natural). `plan_for(projeto)` mapeia o tipo → passos executáveis; tipos sem plano seguem 100% manuais (nada roda escondido). Contrato de dois passos do M10 (preview → run). Endpoints: `GET /api/projects/{id}/plan`, `POST steps/{key}/preview|run` (`task_index` marca o item do checklist → a execução avança o projeto). Front: "Passos que posso executar" no painel Projetos. +12 testes.
>
> **Progresso — Épico 19.2 ENTREGUE (2026-07-10):** plano multi-passo verificável. `run_plan(project, ctx, confirm=)` roda a sequência em ordem: executa os passos SEGUROS (medições) sozinho e PARA num checkpoint a cada passo sensível (mutação), reportando progresso. `confirm` autoriza o passo do checkpoint atual; chamar de novo segue ao próximo. IDEMPOTENTE e retomável SEM store novo: uma mutação já aplicada re-mede 0 pendências (preview count 0 = no-op) e é pulada. `POST /api/projects/{id}/plan/run {confirm?}`. Front: "Executar plano (com checkpoints)" mostra o que rodou + a prévia do checkpoint + "Confirmar e continuar". +8 testes.
>
> **🏁 Épico 19.3 ENTREGUE — M19 COMPLETO (2026-07-10):** fecha o loop propõe→faz→MEDE. Cada tipo de projeto tem uma MÉTRICA que o motivou; `capture_baseline` fotografa o valor no `adopt` (nova coluna `self_projects.baseline_json` + migração), e `outcome(project, ctx)` re-mede e compara — `{baseline, current, delta, improved}` respeitando a direção (↑ p/ % estruturadas, ↓ p/ duplicatas). `GET /api/projects/{id}/outcome`. Front: ao concluir o plano (ou no botão "📊 Medir resultado"), o card mostra o antes→depois datado ("📈 melhorou — antes X → agora Y"). **DoD do M19 batido: o Apolo conduz um projeto de melhoria multi-passo real, do começo ao fim, supervisionado e MEDIDO.** +6 testes (suite 1248→1254). **🏁 Início do Q3 / pilar P9 "agência que conduz".** PRÓXIMO: M20 (navegador interativo opt-in em sandbox).

#### **Mês 20 — Navegador interativo (opt-in, sandbox)**
- Épico 20.1 — **Driver interativo:** sobe a automação web do **10.3** de read-only para **clique/preenchimento** (Playwright, `🔒 setup`), mantendo a allowlist de domínios e o preview de cada passo.
- Épico 20.2 — **Trilha reversível na web:** cada ação com efeito (enviar formulário, etc.) registrada e, onde possível, confirmável/reversível; nunca um clique cego.
- Épico 20.3 — **Tarefas repetitivas reais:** uma automação de ponta a ponta que o Leo faz toda semana, feita pelo Apolo.
- **DoD M20:** o Apolo completa uma tarefa web interativa multi-passo, auditada, com você no comando.

> **Progresso — Épico 20.1 ENTREGUE (2026-07-10):** navegador interativo em sandbox. `src/webtask.py` sobe a automação de read-only para INTERATIVA — ops `click`/`fill`/`submit` no núcleo determinístico com driver injetável (fake nos testes). Padrão soberano mantido: o driver real é `PlaywrightDriver` (lazy, 🔒 opt-in, erro claro se faltar o pacote). Segurança reforçada: mesma sandbox de domínios checada em CADA navegação; `preview_interactive()` descreve cada passo e destaca os de EFEITO; a fronteira do efeito (`submit`) NUNCA roda num clique cego — `run_interactive` exige `confirm_effects=True`, senão para com `needs_confirmation`. Novo escopo `browser.interact` + tool (via M6). Endpoints `/api/webtask/interactive/{example,plan,run}`. Front: console "🖱️ Navegador interativo" no painel Ações. +13 testes.
>
> **Progresso — Épico 20.2 ENTREGUE (2026-07-10):** trilha reversível/auditável. Cada ação com EFEITO executada de fato entra numa trilha durável (o handler persiste o ledger via `db.log_tool "web.effect"`). `GET /api/webtask/interactive/trail`; front "🧾 Trilha de efeitos". Honesto: web submits não são auto-reversíveis — a garantia é o registro + o gate de confirmação do 20.1 (nunca um clique cego). +3 testes. Suite → 1269.
>
> **⏳ Épico 20.3 — PENDENTE DO LEO:** o motor está pronto (20.1+20.2); fechar o DoD exige (1) `pip install playwright` + `playwright install chromium` (🔒 opt-in — hoje não instalado) e (2) escolher a tarefa semanal REAL a automatizar ("a definir com você"). Assim que houver os dois, monto a receita ponta-a-ponta e demonstro auditada.

#### **Mês 21 — Apps nativos & sistema**
- Épico 21.1 — **Ações no desktop com permissão:** abrir apps, mover/organizar arquivos **com undo**, automações simples — reusando o framework de consentimento + auditoria do M6/M10.
- Épico 21.2 — **Integrações do seu fluxo:** as ferramentas nativas que o Leo mais usa (a definir com você), sempre opt-in e reversível.
- Épico 21.3 — **Segurança da agência nativa:** sandbox, limites e trilha — a mesma disciplina do resto, aplicada ao sistema.
- **DoD M21:** o Apolo executa uma tarefa de sistema real, com permissão explícita e reversível.

> **Progresso — Épico 21.1 ENTREGUE (2026-07-10):** a primeira ação de SISTEMA (fora do texto) — **mover/organizar arquivos com desfazer**. `src/tools/files_move.py` registra a ação `files.move` reusando integralmente o framework do M10/M6: grant `files.write` + allowlist de pastas (`ctx.note`) + as defesas de `files.py` (`_within` neutraliza `..`/symlink). É a tarefa de sistema mais REVERSÍVEL possível — desfazer = mover de volta (recusa se a origem foi reocupada; nunca sobrescreve destino existente). Ciclo `preview → apply → undo` puro e testável com pastas temporárias; auditado como `files.move:{preview,apply,undo}`. Front: console "📦 Mover / organizar" no painel 🛠️ Ações (preview→confirmar→desfazer, botão só habilita após a prévia). **21.3 (sandbox/limites/trilha) já vem de graça:** a allowlist é a sandbox, o ledger é a trilha, o undo é a reversibilidade. +13 testes (suite 1276→1288). **DoD do M21 batido** para arquivos. Falta o opt-in do Leo p/ "abrir apps" (21.1 estendido) e as integrações do fluxo dele (21.2, "a definir com você").

### 🗓️ Q4 (Y2) — MULTIMODAL, PRESENÇA & PROVA *(P10 + P11)*

#### **Mês 22 — Visão útil**
- Épico 22.1 — **Ler tela e documentos:** screenshots, PDFs e imagens como **entrada rica** — "o que tem nessa tela/imagem/documento?" ligado à memória.
- Épico 22.2 — **Visão + agência:** ver a tela para agir sobre ela (com as travas do Q3).
- Épico 22.3 — **Câmera (opt-in):** entrada visual do mundo real quando fizer sentido, com consentimento.
- **DoD M22:** o Apolo entende e age sobre conteúdo visual real, integrado à memória.

> **Progresso — Épico 22.1 ENTREGUE (2026-07-10):** ler TELA e DOCUMENTOS como entrada rica. `src/vision_read.py` unifica, reusando o que já existe: `capture_screen()` (screenshot local via Pillow, redimensionado p/ payload sensato), `read_document(filename, raw)` roteia por tipo → texto de PDF (`src.ingest.extract_pdf_text`), DOCX, texto puro, ou marca imagem com `needs_vision`; `describe_image()` descreve tela/imagem via o modelo de visão do app (injetável). Núcleo determinístico (captura/decode/roteamento sem LLM). Ligado à MEMÓRIA: `remember` guarda o texto extraído via `Ingestor` (RAG + base). `capabilities()` diz honestamente o que dá agora (tela ✓; visão só com modelo; PDF só com pypdf). Endpoints `GET /api/vision/status`, `POST /api/vision/{screen,document}`. Front: console "👁️ Visão útil" no painel Ações (📸 ler tela / 📄 ler documento + guardar na memória). Verificação leve (testes formais adiados a pedido do Leo): captura 1280×720 ok, leitura de texto/imagem ok, app importa. **Nota:** descrever imagem exige modelo de visão — com o backend soberano text-only (llama.cpp) fica indisponível até um GGUF multimodal ou llava no Ollama.

#### **Mês 23 — Presença ambiente**
- Épico 23.1 — **Contexto contínuo:** o Apolo acompanha agenda + foco + hora e intervém no **momento certo** (evoluindo o briefing do M4), sem virar ruído.
- Épico 23.2 — **Voz contínua soberana:** completar o loop de voz 100% local (openWakeWord/Whisper-loop) **no hardware atual** — Whisper `tiny`/`base` + VAD + quantização, medindo e otimizando a latência (sem esperar GPU). A última milha do M3/M5.
- Épico 23.3 — **Modos de presença:** foco, descanso, trabalho — o Apolo se comporta conforme o momento do seu dia.
- **DoD M23:** o Apolo é um ambiente presente que aborda na hora certa, por voz, sem incomodar.

#### **Mês 24 — Prova de evolução & retrospectiva do Ano 2**
- Épico 24.1 — **Loop fechado de automelhoria:** o eval (M9) mede → um projeto (19) executa → o Apolo re-mede, sozinho, e registra a curva. Prova de melhora no longo prazo, não pontual.
- Épico 24.2 — **Placar de 2 anos:** o painel "estou melhorando?" ganha a série histórica dos dois anos — capacidade, não só atividade.
- Épico 24.3 — **Retrospectiva do Ano 2 + plano do Ano 3:** o Apolo apresenta, por voz, o que **passou a saber fazer** no ano (com números) e propõe o Ano 3 — provavelmente já decidindo sobre a **GPU** com dados do próprio caso.
- **DoD M24:** o Apolo demonstra, com números, que ficou mais **capaz** — e propõe o próximo ciclo.

---

## 6. Estratégias no hardware atual — **DESTRAVADO** (decisão do Leo, 2026-07-10)

> **Mudança de doutrina:** saímos do "esperar a GPU" para **"desenvolver o cérebro próprio AGORA, no hardware que temos"** (Ryzen 5 4600G + iGPU Radeon Vega + 16GB). A GPU dedicada continua sendo o multiplicador — mas deixa de ser um portão. Nada fica `🔒` esperando: cada item ganha uma **estratégia de CPU/iGPU** e entra no plano.

**A honestidade permanece** (não fingimos que um Ryzen faz GPT-4), mas ela vira **engenharia de restrição**, não desculpa:

- **iGPU via Vulkan (usar a placa que temos):** o `llama.cpp` tem backend **Vulkan** que roda no **Radeon Vega integrado**. Compilar com `-DGGML_VULKAN=ON` e descarregar camadas (`LLAMACPP_GPU_LAYERS>0`) tira carga do CPU. Ganho modesto (RAM compartilhada), mas real — e é a nossa "GPU".
- **Cérebro próprio por DESTILAÇÃO de tarefa estreita:** o Nano de 3,4M não faz chat geral, mas **crava tarefas estreitas** se treinado para IMITAR o Qwen nelas (título de conversa, tags, classificação de setor, roteamento de intenção, autocomplete, gates sim/não). Geramos rótulos com o Qwen → treinamos o Nano supervisionado → ele assume aquela fatia. É o **"Nano como cérebro" honesto**: cérebro do que ele já dá conta, expandindo.
- **Escala incremental no CPU:** crescer o Nano de 3,4M → ~10–30M, treinado **de madrugada** (a máquina ociosa vira treino — agendado pelas rotinas do M10). Lento e de graça. Cada salto de tamanho amplia a cobertura.
- **Takeover progressivo (o flywheel ligado):** o roteador manda **mais tarefas** ao Nano conforme ele prova qualidade (portão do 15.2); o Qwen cobre o resto; a **% servida pelo Nano sobe mês a mês**. A métrica de soberania do cérebro vira a estrela-guia.
- **Fine-tune realista:** LoRA do 14B no CPU é inviável — mas **LoRA/full-FT de modelos PEQUENOS** (0,5–1,5B) no CPU/iGPU de madrugada é factível, e a destilação do Nano não precisa de LoRA. Fazemos o que cabe.
- **Voz contínua:** o loop 100% local (openWakeWord + Whisper) é **construído e OTIMIZADO no hardware atual** (modelos `tiny`/`base`, VAD, quantização) — mede-se a latência e melhora-se, sem esperar GPU.

**A recomendação da GPU não some — vira upside, não pré-requisito:** uma GPU de 12–16GB acelera tudo isto de uma vez. Mas o desenvolvimento do cérebro soberano **começa agora**, e o **Ano 3** (§10) é dedicado a isso.

---

## 7. Métricas de sucesso do Ano 2

- **Soberania do cérebro:** % das tarefas leves servidas pelo Apolo-Nano (subindo mês a mês).
- **Profundidade do Leo:** campos do modelo profundo preenchidos e confirmados por você (não assumidos).
- **Agência real:** nº de projetos autodirigidos **executados** (não só propostos), todos reversíveis.
- **Qualidade comprovada:** alucinação (M9) continua caindo na série histórica; o loop fechado (24.1) mostra causa → efeito.
- **Multimodal em uso:** visão/tela/documento usados em tarefas reais.
- **Processo:** cada épico com testes verdes, preview verificado, merge, push, docs — a mesma disciplina do Ano 1.

---

## 8. Cadência de trabalho

Igual ao Ano 1 (`JARVIS_ROADMAP.md` §10) e ao Nano (`APOLO_NANO_ROADMAP.md` §9): incremento diário pequeno → testes verdes → README/memória → commit no branch → fast-forward no `main` → push. Um épico por **"siga"**. Determinístico primeiro; o LLM (e agora o Nano) entra por trás de interfaces injetáveis, testáveis sem depender do modelo.

---

## 9. Como o Ano 2 se conecta com o Apolo-Nano

O Ano 2 e o [Apolo-Nano](docs/APOLO_NANO_ROADMAP.md) são **dois lados do mesmo aperto de mão**:

| O Apolo dá ao Nano | O Nano dá ao Apolo |
|---|---|
| **Corpus soberano** (o que aprendeu — `corpus_export` ✅) | **Backend leve** para tarefas instantâneas (M13–M14) |
| **Dados de tarefa** (conversas→títulos, tópicos→setores) | **Latência <1s** onde o 14B é lento demais |
| **Gate de recursos** (não competir com o 14B) | **Soberania do raciocínio** (pesos do Leo servindo o app) |
| **Harness de qualidade** (só promove se melhorar) | **Estrada para a GPU** (LoRA/escala prontos) |

Os **M13–M15 são o lado-Apolo do pilar D6 (Integração & Produto)** do roadmap do Nano — construídos aqui, no app, onde a integração de fato acontece. O flywheel (M15) é o coração: **quanto mais o Apolo aprende, melhor fica o cérebro que ele mesmo treina** — e mais o Apolo roda em soberania própria.

### Progresso M13–M14 (adiantado no ciclo do Nano — 2026-07-09)

O primeiro ciclo do [Apolo-Nano](docs/APOLO_NANO.md) já entregou o lado-app:

- **🏁 M13 (Ponte Nano ↔ Apolo) — ENTREGUE.** 13.1 `NanoEngine` + `POST /api/nano/complete` + card 🧬 no painel Saúde; 13.2 gate de recursos (`GpuGate.user_enter/exit` na completion — o learner espera pelo Nano); 13.3 params/ppl/latência no `/api/health`. O app carrega e serve o Nano sem travar a máquina.
- **🔨 M14 (Roteamento híbrido) — parcial + teto medido, agora ATACADO.** 14.2 construído: título de conversa Nano-first com fallback garantido (`generate_session_title` + portão de qualidade). A **medição honesta** (título 1/6, classificação de setor 31%) mostrou que um modelo de 3,4M **generalista** no CPU não basta — mas a resposta deixou de ser "esperar GPU": é **destilação de tarefa estreita + escala incremental** (§6/§10). O flywheel (M15) e a promoção por qualidade (15.2) estão prontos; agora **ligam no hardware atual** treinando o Nano para imitar o Qwen nas tarefas que ele consegue. O fallback garante que a produção nunca piora enquanto o Nano cresce.

---

## 10. Ano 3 — **O cérebro soberano assume** (no hardware atual)

> Decisão do Leo (2026-07-10): destravar tudo e desenvolver o **Apolo-Nano como cérebro** com o que temos. O objetivo do Ano 3 é subir a **% de tarefas servidas pelo modelo próprio** de perto de 0 para o máximo que a máquina permitir — cada mês, mais uma fatia sai do Qwen e passa para o Nano. Honestidade mantida: o Qwen (motor próprio llama.cpp) continua cobrindo o chat geral **enquanto** o Nano cresce; ninguém fica sem resposta boa no caminho.

**Pilar P12 · Cérebro próprio que assume** — a estrela: soberania do raciocínio subindo, medida.

- **M25 — Flywheel de destilação ligado.** O `corpus_export` + gerador de rótulos (o Qwen rotula tarefas reais do Leo: títulos, tags, setores, roteamento) alimenta um treino do Nano **agendado de madrugada** (rotinas do M10, com o gate de recursos). Promoção só por qualidade (15.2). **DoD:** o Nano re-treina sozinho e melhora numa sonda, sem intervenção.
  - **🔨 M25.1 ENTREGUE (2026-07-10):** o pipeline de destilação. `src/nanollm/distill.py`: `generate_distill_pairs(inputs, teacher_fn)` (o professor=Qwen é injetável, fake nos testes) rotula entradas reais **na distribuição de inferência** (`pergunta→título`, o que faltava no 4.1) + `distill_titles` (valida com `_valid_title`) + `write_distill_dataset` (mesmo formato/tokenizer do fine-tune, o `train.py` consome sem mudança). Ataca a CAUSA-RAIZ do teto medido no M14.2 (descasamento de distribuição + poucos pares). Determinístico, 7 testes com professor fake.
  - **🔨 M25.2 ENTREGUE (2026-07-11):** o professor real. `make_llm_teacher()` liga o Qwen (via `get_provider().complete`, modelo de chat do runtime) como professor; `db.first_user_messages()` (novo em `storage_conversations.py`) puxa a 1ª mensagem de cada sessão = a distribuição de inferência real; `run_distillation(db, tok, out)` faz o ciclo (sourcing→rótulo→dataset) + CLI `python -m src.nanollm.distill`. 4 testes novos (banco+provider fakes).
  - **🔨 M25.3 ENTREGUE (2026-07-11):** o flywheel FECHOU — `src/nanollm/flywheel.py::run_nightly_flywheel` destila → treina um candidato (warm-start do titular) → avalia candidato E titular no **mesmo val destilado** → **promove só se a perplexidade cair** (portão de qualidade, reversível: backup do titular + `revert_promotion`). Ligado no scheduler do `app.py` (`FLYWHEEL_HOUR`, padrão 3h; só ocioso e com o learner parado; treino em thread). Após promover, `NanoEngine.reload()` serve o cérebro novo **sem reiniciar**. Ledger JSONL + `read_flywheel_log`. 6 testes (train/eval/professor fakes, exercitam toda a decisão). **DoD atingido:** o Nano re-treina sozinho de madrugada e só assume se medir melhora. **Falta rodar de verdade:** juntar volume de conversas + deixar 1 noite ligado (M26+ = Vulkan/escala/roteamento).
- **M26 — iGPU & escala incremental.** Compilar o `llama.cpp` com **Vulkan** (usa a Vega integrada) e medir o ganho; crescer o Nano (3,4M → 10–30M) e medir cobertura por tarefa. **DoD:** ≥1 tarefa estreita servida pelo Nano em produção com qualidade ≥ Qwen, e inferência acelerada pela iGPU.
  - **🔨 M26 (código) ENTREGUE (2026-07-11):** (1) **escala** — presets `medium` (~10M) e `large` (~30M) no `train.py` (n_head divide n_embd, batch cai p/ caber na RAM); testes garantem a faixa de params. (2) **iGPU honesta** — `backend_status()` agora reporta `gpu` lendo a API do próprio llama.cpp (`llama_supports_gpu_offload`): diz se o BUILD suporta offload e avisa "recompile com Vulkan" se `gpu_layers>0` num build sem GPU; surface na Saúde → "Aceleração" (verificado ao vivo: "CPU (build sem GPU)"). (3) **receita** `docs/VULKAN_BUILD.md` (Vulkan SDK + recompilar com `-DGGML_VULKAN=ON` mantendo o fix AVX2/no-AVX512 + `LLAMACPP_GPU_LAYERS`). **Falta do Leo (hardware/tempo):** rodar o build Vulkan e treinar um Nano `medium` de madrugada (o flywheel M25.3 pode, é só apontar o preset). Expectativa honesta: ganho da iGPU num 7B é modesto (banda de RAM) — o ganho real do M26 está no Nano maior + roteamento (M27).
- **M27 — Takeover progressivo & medição.** O roteador migra tarefas ao Nano conforme o portão de qualidade libera; painel mostra a **% do cérebro que já é próprio** subindo. **DoD:** uma família de tarefas (ex.: toda a organização de conversas — títulos, tags, setores) 100% no Nano, Qwen só no chat aberto.
- **M28+ — Rumo ao chat próprio.** Distilar um Nano maior para diálogo curto/factual ancorado na memória do Leo; medir contra o Qwen às cegas. Aqui a GPU dedicada, **se e quando vier**, multiplica — mas o caminho já está andando.

**Métrica-mãe do Ano 3:** *% de tarefas do dia servidas pelo cérebro próprio* (Nano), subindo mês a mês — a soberania saindo do disco (dados, ✅) e do motor (llama.cpp, ✅) e chegando aos **pesos que são do Leo**.

---

*Documento vivo. Criado em 2026-07-09, no fechamento do Ano 1 (v1.0.0). Atualizado 2026-07-10: **DESTRAVADO** — o desenvolvimento do cérebro soberano (Apolo-Nano) começa no hardware atual via destilação + escala incremental + iGPU/Vulkan (§6), e o **Ano 3** (§10) é dedicado a isso. A GPU dedicada vira aceleração, não pré-requisito.*
