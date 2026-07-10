# 🛰️ JARVIS — Roadmap do Ano 2 (Apolo AI)

> Continuação do [JARVIS_ROADMAP.md](JARVIS_ROADMAP.md) (Ano 1, M1–M12, **v1.0.0** ✅). Mesma cadência: **1 incremento por dia**, testado, commitado no branch e mergeado no `main`, com README e memória atualizados. Sem regressões (a suíte fica verde). Documento vivo.

**Início:** 2026-07-09 · **Alvo:** 2027-07 · **Dono:** Leo · **Copiloto:** Claude Code · **Milestones:** M13–M24

---

## 1. Onde chegamos (Ano 1) — o ponto de partida

Em 12 meses construímos **todo o scaffolding do Jarvis** e chegamos ao **v1.0.0**: arquitetura modular + observabilidade, tecido de memória unificado + episódica, voz local, proatividade/briefing, wake word, ler o mundo com permissão, roteamento + verificação anti-alucinação, aprendizado que entende (repetição espaçada + grafo), harness de avaliação, ação no mundo com undo + rotinas + web sandbox, criptografia + acesso remoto + embeddings locais, e automelhoria supervisionada + retrospectiva falada. Suíte **>1080 verde**.

A aposta do Ano 1 se confirmou: **80% da experiência "Jarvis" é scaffolding — e está de pé.** O que ficou para trás foi, quase inteiramente, o **cérebro** (os pesos do modelo) e o que depende de **hardware**. O Ano 2 ataca exatamente essa fronteira — e agora temos uma arma nova que o Ano 1 não tinha: o **[Apolo-Nano](APOLO_NANO_ROADMAP.md)**, a LLM própria em construção.

---

## 2. A tese do Ano 2

> **O scaffolding está pronto. Agora enchemos ele de profundidade e damos ao Apolo um cérebro que é dele.**

Três eixos, costurados pelo Apolo-Nano:

1. **O cérebro se torna seu.** Integrar o Apolo-Nano ao app como backend real para tarefas leves, criar o **roteamento híbrido** (Nano instantâneo + 14B pesado) e fechar o **flywheel**: o Apolo aprende → o corpus alimenta o Nano → o Nano treina → serve as tarefas leves do Apolo → libera o 14B. Soberania que sai do disco (dados) e chega ao raciocínio (pesos).
2. **Conhecer o Leo de verdade.** O Ano 1 deu memória; falta o **modelo profundo** — metas, hábitos, pessoas, projetos, contexto de vida — e a personalização que adapta o comportamento a você.
3. **Agência que conduz.** O Ano 1 leu e escreveu o mundo (com undo); o Ano 2 faz o Apolo **executar** os projetos que ele mesmo propõe (12.1), operar um **navegador interativo** e **apps nativos** — sempre com confirmação e trilha reversível.

**A honestidade de sempre:** o salto de cérebro grande é `🔒 HW` (GPU). O Ano 2 constrói **todo o software que fica pronto no dia em que a GPU chegar** — e extrai o máximo do CPU agora. Nada de fingir que dá para treinar um chatbot em CPU; muito de deixar a estrada pavimentada.

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
| 🔒 | **Teto de hardware.** GPU é o multiplicador do Ano 2 (cérebro maior, LoRA do 14B, Nano 100M+, latência de voz tempo-real). | Fundamental | máquina |

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

### 🗓️ Q1 (Y2) — O CÉREBRO SE TORNA SEU *(P7)* — costura com o [Apolo-Nano](APOLO_NANO_ROADMAP.md)

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
- Épico 15.3 — **Estrada da GPU:** deixar pronto o caminho de **fine-tune LoRA do 14B** com os dados do Leo (dataset gerado localmente) — desligado por `🔒 HW`, mas testável no fluxo e pronto para ligar no dia da GPU.
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
> **Progresso — Épico 17.2 (tom) ENTREGUE (2026-07-09):** o Apolo ajusta QUANTO fala pelo estilo do Leo. `src/style.py` `derive_tone(profile)` DETERMINÍSTICO: lê as preferências/valores do perfil (M16), placar de palavras-sinal → **direto / detalhado / equilibrado** (empate ou sem sinal = equilibrado, não impõe estilo). `style_directive(tone)` injeta a diretriz no system prompt do chat (só quando há sinal claro; cache por sessão já cobre — depende do mesmo `profile_facts`). `GET /api/style` expõe o tom (transparente/reversível: muda a preferência → muda o tom). VERIFICADO AO VIVO: "prefiro respostas diretas"→direct, "explicações detalhadas"→detailed, "futebol"→balanced. 10 testes. **Nota honesta:** o 17.2 diz "quando/quanto fala"; entreguei o **quanto** (tom/verbosidade). O **quando** (timing/ritmo da proatividade) é temporal e se costura melhor no 17.3 (antecipação útil) — será feito lá. Falta 17.3.

#### **Mês 18 — Memória relacional & temporal profunda**
- Épico 18.1 — **Linha do tempo da vida:** episódios (M2) conectados a metas, pessoas e projetos — "o que estava rolando quando fizemos X".
- Épico 18.2 — **Pessoas & contexto:** um grafo leve de quem-é-quem, ligado às conversas e compromissos.
- Épico 18.3 — **Recall que entende relações:** "o que o [fulano] me pediu?", "onde parei no projeto Y?" respondidos pela memória relacional.
- **DoD M18:** perguntas relacionais/temporais complexas retornam respostas certas e datadas.

### 🗓️ Q3 (Y2) — AGÊNCIA QUE CONDUZ *(P9)*

#### **Mês 19 — Execução supervisionada de projetos**
- Épico 19.1 — **Do propor ao fazer:** os projetos do **12.1** deixam de só ser propostos — o Apolo **executa os passos** usando as ações do M10 + o Coder, sempre com **preview → confirmação → undo** por passo.
- Épico 19.2 — **Plano multi-passo verificável:** cada projeto vira um plano com checkpoints; o Apolo reporta progresso e para para confirmar nos pontos sensíveis.
- Épico 19.3 — **Fecha o loop "propõe → faz → mede":** ao concluir um projeto, o Apolo re-mede a métrica que o motivou (o eval do M9) e mostra se melhorou de verdade.
- **DoD M19:** o Apolo conduz um projeto de melhoria multi-passo real, do começo ao fim, reversível e medido.

#### **Mês 20 — Navegador interativo (opt-in, sandbox)**
- Épico 20.1 — **Driver interativo:** sobe a automação web do **10.3** de read-only para **clique/preenchimento** (Playwright, `🔒 setup`), mantendo a allowlist de domínios e o preview de cada passo.
- Épico 20.2 — **Trilha reversível na web:** cada ação com efeito (enviar formulário, etc.) registrada e, onde possível, confirmável/reversível; nunca um clique cego.
- Épico 20.3 — **Tarefas repetitivas reais:** uma automação de ponta a ponta que o Leo faz toda semana, feita pelo Apolo.
- **DoD M20:** o Apolo completa uma tarefa web interativa multi-passo, auditada, com você no comando.

#### **Mês 21 — Apps nativos & sistema**
- Épico 21.1 — **Ações no desktop com permissão:** abrir apps, mover/organizar arquivos **com undo**, automações simples — reusando o framework de consentimento + auditoria do M6/M10.
- Épico 21.2 — **Integrações do seu fluxo:** as ferramentas nativas que o Leo mais usa (a definir com você), sempre opt-in e reversível.
- Épico 21.3 — **Segurança da agência nativa:** sandbox, limites e trilha — a mesma disciplina do resto, aplicada ao sistema.
- **DoD M21:** o Apolo executa uma tarefa de sistema real, com permissão explícita e reversível.

### 🗓️ Q4 (Y2) — MULTIMODAL, PRESENÇA & PROVA *(P10 + P11)*

#### **Mês 22 — Visão útil**
- Épico 22.1 — **Ler tela e documentos:** screenshots, PDFs e imagens como **entrada rica** — "o que tem nessa tela/imagem/documento?" ligado à memória.
- Épico 22.2 — **Visão + agência:** ver a tela para agir sobre ela (com as travas do Q3).
- Épico 22.3 — **Câmera (opt-in):** entrada visual do mundo real quando fizer sentido, com consentimento.
- **DoD M22:** o Apolo entende e age sobre conteúdo visual real, integrado à memória.

#### **Mês 23 — Presença ambiente**
- Épico 23.1 — **Contexto contínuo:** o Apolo acompanha agenda + foco + hora e intervém no **momento certo** (evoluindo o briefing do M4), sem virar ruído.
- Épico 23.2 — **Voz contínua soberana:** completar o loop de voz 100% local (openWakeWord/Whisper-loop) quando o `🔒 HW`/latência permitir — a última milha do M3/M5.
- Épico 23.3 — **Modos de presença:** foco, descanso, trabalho — o Apolo se comporta conforme o momento do seu dia.
- **DoD M23:** o Apolo é um ambiente presente que aborda na hora certa, por voz, sem incomodar.

#### **Mês 24 — Prova de evolução & retrospectiva do Ano 2**
- Épico 24.1 — **Loop fechado de automelhoria:** o eval (M9) mede → um projeto (19) executa → o Apolo re-mede, sozinho, e registra a curva. Prova de melhora no longo prazo, não pontual.
- Épico 24.2 — **Placar de 2 anos:** o painel "estou melhorando?" ganha a série histórica dos dois anos — capacidade, não só atividade.
- Épico 24.3 — **Retrospectiva do Ano 2 + plano do Ano 3:** o Apolo apresenta, por voz, o que **passou a saber fazer** no ano (com números) e propõe o Ano 3 — provavelmente já decidindo sobre a **GPU** com dados do próprio caso.
- **DoD M24:** o Apolo demonstra, com números, que ficou mais **capaz** — e propõe o próximo ciclo.

---

## 6. Itens travados por hardware `🔒 HW`

A GPU é o **multiplicador central do Ano 2**. Sem ela ficam fora do alcance (mas com a estrada pronta):
- **Fine-tune LoRA do 14B** com os dados do Leo (o software fica pronto no M15; liga no dia da GPU).
- **Apolo-Nano 100M+ params** e contexto longo (ver [APOLO_NANO_ROADMAP.md](APOLO_NANO_ROADMAP.md) §7).
- **Latência de voz em tempo real** para a presença contínua (M23).
- **Chat de verdade num modelo próprio** — nem com GPU de entrada; segue no Qwen até lá.

**A recomendação honesta segue de pé:** uma GPU de 12–16GB VRAM destrava simultaneamente o cérebro do Jarvis (LoRA) e muda a classe do Nano. O M24 propõe a decisão com números reais do seu uso.

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

O Ano 2 e o [Apolo-Nano](APOLO_NANO_ROADMAP.md) são **dois lados do mesmo aperto de mão**:

| O Apolo dá ao Nano | O Nano dá ao Apolo |
|---|---|
| **Corpus soberano** (o que aprendeu — `corpus_export` ✅) | **Backend leve** para tarefas instantâneas (M13–M14) |
| **Dados de tarefa** (conversas→títulos, tópicos→setores) | **Latência <1s** onde o 14B é lento demais |
| **Gate de recursos** (não competir com o 14B) | **Soberania do raciocínio** (pesos do Leo servindo o app) |
| **Harness de qualidade** (só promove se melhorar) | **Estrada para a GPU** (LoRA/escala prontos) |

Os **M13–M15 são o lado-Apolo do pilar D6 (Integração & Produto)** do roadmap do Nano — construídos aqui, no app, onde a integração de fato acontece. O flywheel (M15) é o coração: **quanto mais o Apolo aprende, melhor fica o cérebro que ele mesmo treina** — e mais o Apolo roda em soberania própria.

### Progresso M13–M14 (adiantado no ciclo do Nano — 2026-07-09)

O primeiro ciclo do [Apolo-Nano](APOLO_NANO.md) já entregou o lado-app:

- **🏁 M13 (Ponte Nano ↔ Apolo) — ENTREGUE.** 13.1 `NanoEngine` + `POST /api/nano/complete` + card 🧬 no painel Saúde; 13.2 gate de recursos (`GpuGate.user_enter/exit` na completion — o learner espera pelo Nano); 13.3 params/ppl/latência no `/api/health`. O app carrega e serve o Nano sem travar a máquina.
- **🔨 M14 (Roteamento híbrido) — parcial + teto medido.** 14.2 construído: título de conversa Nano-first com fallback garantido (`generate_session_title` + portão de qualidade). Mas a **medição honesta** (título 1/6, classificação de setor 31%) confirmou o teto 🔒 HW: um modelo de 3,4M no CPU não faz tarefas ancoradas com qualidade de produção. **O flywheel (M15) e a promoção por qualidade (15.2) estão prontos em infraestrutura; o que falta é ESCALA (GPU)** — não mais código. O fallback garante que a produção nunca piora.

---

*Documento vivo. Criado em 2026-07-09, no fechamento do Ano 1 (v1.0.0). O ciclo do Apolo-Nano adiantou **M13 (completo)** e **M14.2 (medido, teto de HW confirmado)**. Próximo passo real: **M15 (flywheel) quando houver GPU**, ou seguir para **Q2 (M16 — modelo profundo do Leo)**, que é software puro e não depende de hardware.*
