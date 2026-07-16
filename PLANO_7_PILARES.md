# Plano — 7 Pilares (LLM, Aprendizado & mais)

> Documento vivo. Criado em 2026-07-15, a partir de uma auditoria honesta do estado real do
> Apolo-Nano (`JARVIS_ROADMAP_ANO2.md` §10, `docs/APOLO_NANO.md`) e do pipeline de Aprendizado
> (`src/learner.py` e afins). Não é um plano de "grandes saltos" — é uma lista ordenada de
> melhorias concretas, cada uma com linha de base medida (não estimada) e critério de pronto.
>
> **Ordem de execução:** 1 → 7, um pilar por vez, sem pular. Cada item segue a mesma disciplina
> do Ano 1/Ano 2: incremento pequeno → testes verdes → preview verificado quando aplicável →
> commit → push → fast-forward no `main` → atualizar este doc com o resultado REAL medido
> (nunca estimado, nunca inflado — inclusive quando o resultado é nulo/negativo).
>
> Prefixo de cada item: `P{pilar}.{item}`. Status: 🔲 pendente · 🔨 em andamento · 🏁 concluído
> (com número medido) · ⏭️ adiado (com motivo).

---

## Ordem dos pilares

| # | Pilar | Por quê nessa posição |
|---|---|---|
| 1 | [LLM — Apolo-Nano](#pilar-1--llm-apolo-nano) | O motor; tudo depende de dado e de medição confiável |
| 2 | [Modo Aprendizado](#pilar-2--modo-aprendizado) | A fonte do dado que alimenta o pilar 1 |
| 3 | [Uso real / dogfooding](#pilar-3--uso-real--dogfooding) | Sem isso, 1 e 2 continuam bloqueados por volume |
| 4 | [Cadência de auditoria de segurança](#pilar-4--cadência-de-auditoria-de-segurança) | Formalizar o que já provou valor (4 vulns achadas em 15/07) |
| 5 | [Dashboard único de saúde da inteligência](#pilar-5--dashboard-único-de-saúde-da-inteligência) | Torna 1–4 visíveis num só lugar, sem caçar métrica espalhada |
| 6 | [Fechar ou descartar M20.3](#pilar-6--fechar-ou-descartar-m203-automação-de-navegador) | Débito de roadmap parado — decidir antes de acumular mais |
| 7 | [Consolidação periódica de docs](#pilar-7--consolidação-periódica-de-docs) | Manutenção; faz mais sentido depois que os docs cresceram com 1–6 |

---

## Pilar 1 — LLM (Apolo-Nano)

**Linha de base medida (2026-07-15):** 3,39M parâmetros, contexto de 192 tokens, corpus de
236.221 tokens (meta original era ≥2M, nunca atingida), ppl val 157,96. Título passa a porta de
qualidade em ~1/6 casos (fallback quase sempre). Setor mede 31,4% (código morto, não integrado).
Portão binário (M27) só tem infraestrutura, sem treino — 19 exemplos válidos no banco real, longe
do mínimo. Flywheel roda toda noite desde 13/07 e **nunca disparou** (sempre "poucos pares").
Blind-eval Nano-vs-Qwen só mediu com n=5 (ruído).

- 🏁 **P1.1 — Motor de dados antes de motor de modelo (2026-07-15, medido).** `corpus_export.py`
  ganhou duas fontes que faltavam: `fetch_conversations` (conversas Leo↔Apolo inteiras — antes só
  o título virava par, agora o turno inteiro entra no corpus de pré-treino, crescendo sozinho
  conforme o Pilar 3 avançar) e `fetch_project_docs` (os próprios `.md` do projeto — README,
  roadmaps — via novo parâmetro `--repo-root`). Rodado de verdade contra o banco principal
  (2026-07-15): **1.304.589 tokens estimados** (era 236k) — **DoD numérico batido**. Honestidade
  necessária: a maior parte do salto (`apolo_topics`, ~1,19M tokens) é **crescimento orgânico do
  aprendizado autônomo rodando desde então**, não deste código. A contribuição REAL de hoje foram
  as duas fontes novas: conversas (33.674 chars, ainda pequeno — só 15 turnos reais existem) +
  docs do projeto (271.081 chars, ~93k tokens). O ganho maior de `apolo_conversations` ainda
  depende do Pilar 3 (uso real). 19 testes novos/ajustados em `tests/test_nanollm_corpus.py`.
  ⏭️ **Distillation sintética (2ª metade do item) ainda não feita** — o corpus já bateu a meta
  numérica sem precisar dela; fica registrada como opção futura se o corpus voltar a estagnar.
- 🏁 **P1.2 — Sweep de scaling-law compute-matched (2026-07-16, medido).** Novo `src/nanollm/sweep.py`:
  em vez de passos fixos por preset (o viés do `medium`/M6.1 — mesmo nº de passos, mas cada
  preset tem batch/block diferentes, então tokens vistos diferentes), os passos agora vêm de um
  orçamento **tokens-por-parâmetro constante** (`steps_for_budget`) — um preset com mais
  parâmetros treina por mais passos, proporcionalmente. Rodado de verdade contra o corpus
  atualizado (1.055.664 tokens, `data/nanollm/sweep_dataset`), orçamento pequeno de propósito
  (`tokens_per_param=0.15`, bem abaixo do ideal — é um sweep direcional, não a curva final):

  | preset | params | passos | tokens vistos | val loss | ppl | tempo |
  |---|---|---|---|---|---|---|
  | nano | 1,47M | 107 | 219.136 | 7,1772 | **1309,21** | 86,8s |
  | mini | 3,39M | 220 | 506.880 | 6,4150 | **610,91** | 246,9s |
  | small | 6,91M | 505 | 1.034.240 | 5,4564 | **234,25** | 969,7s |

  **DoD numérico batido** (tabela com 3 pontos, decisão apoiada nela). **Leitura honesta:** sob
  comparação justa (passos proporcionais), ppl melhora MONOTONICAMENTE com o tamanho — o oposto
  do que o experimento `medium` sugeria. Isso não prova que "maior é sempre melhor" em geral; prova
  que a comparação anterior estava **contaminada pelo viés de passos fixos**, não que os modelos
  maiores são estruturalmente piores. Nenhum dos 3 pontos está perto de convergência (orçamento
  0,15 tokens/param é muito abaixo do que a literatura considera saudável, ~15-20) — os ppl
  absolutos aqui são bem piores que o `ckpt_v1` de produção (158), que treinou por muito mais
  passos. **Decisão apoiada na tabela:** manter a aposta em escalar o Nano (`medium`/`large`) para
  o próximo treino real, agora sabendo que dar mais passos ao modelo maior é necessário, não
  opcional. 10 testes novos em `tests/test_nanollm_sweep.py` (sintéticos, determinísticos).
  **Efeito colateral corrigido:** o sweep real esbarrou num bug bloqueante nos 11 entry points
  `python -m src.nanollm.*` — `UnicodeEncodeError` no console cp1252 do Windows sempre que um
  print usava "→" (não era só cosmético, derrubava o processo no meio do treino). Corrigido com
  `sys.stdout.reconfigure(encoding="utf-8")` em todos os `if __name__ == "__main__":`.
- 🏁 **P1.3 — Uma tarefa até passar o DoD (2026-07-16, medido, DoD batido).** O bloqueio do M27
  (só 19 exemplos com setor válido, 2026-07-15) sumiu sozinho: o aprendizado autônomo rodou e o
  banco principal tem hoje **3.220 tópicos** com resumo (367 `backend_apis`). Construído
  `src/nanollm/binary_eval.py` (`load_held_out` reproduz o MESMO split determinístico que
  `taskdata._write_tokenized` usou, pra medir só no que o modelo NUNCA viu; `evaluate_binary_gate`
  mede acurácia geral, acurácia-quando-decide e taxa de decisão separadas — um portão que só
  recusa não deve parecer bom por omissão). Dataset real: `collect_binary_pairs(db, "backend_apis")`
  → 964 pares balanceados (482 sim/482 não). Fine-tune de verdade (warm-start de `ckpt_v1`, preset
  `mini`, lr 3e-4, 1200 passos): **overfitting claro e visível** — loss de treino caiu de 5,47 a
  0,61 enquanto o val nunca melhorou depois do passo 300 (val mínimo 2,9975); `model_best.npz`
  guardou automaticamente esse ponto (o mecanismo de "só promove por qualidade" do M25.3 funcionou
  como desenhado, sem precisar de intervenção). **Avaliação real no held-out val (144 pares nunca
  vistos): 80,56% de acurácia, 100% de taxa de decisão, 0 recusas — DoD (≥70%) batido de verdade.**
  Confirma a aposta do M27: framing binário generaliza MUITO melhor que os 31,4% do multi-classe
  de 9 classes na mesma fonte de dado. Ressalvas honestas: (1) medido só para o setor `backend_apis`
  — não presume que outros setores generalizem igual sem medir; (2) o modelo overfita rápido com
  964 pares (mais dado real ajudaria, não é urgente); (3) **este item mede se o gate PASSA o DoD,
  não wireia produção** — ligar `nano_binary_classify` no roteamento (`routing.py`/`NANO_TASKS`)
  fica registrado como próximo passo natural (não feito aqui, para não misturar medição com
  decisão de promover). 4 testes novos em `tests/test_nanollm_binary_eval.py` (fake determinístico).
- 🔨 **P1.4 — Blind-eval com rigor estatístico (2026-07-16, infra pronta, DoD ainda não).**
  `blind_eval.py` ganhou `freeze_questions` (congela o conjunto na 1ª vez, IDEMPOTENTE — rodar de
  novo não re-sorteia, mesmo que o banco tenha crescido; ataca a causa exata do ruído medido no
  M28 em 2026-07-15, onde 20%→40% era só amostra nova de n=5, não melhora real), `append_history`/
  `read_history` (JSONL append-only, nunca reescreve o passado) e `run_tracked_blind_eval`
  (congela + roda + registra em 1 chamada). `run_blind_eval` ganhou o parâmetro `questions` pra
  aceitar o conjunto congelado em vez de sempre reamostrar. CLI atualizado (`--questions`,
  `--history`, `--min-questions`). 9 testes novos (fakes determinísticos).
  **DoD ainda NÃO batido:** medido de verdade contra o banco principal — só **14 perguntas reais**
  existem (`db.first_user_messages`), abaixo do mínimo de 30 que o próprio item exige. Confirmei
  que o gate recusa corretamente em vez de forçar (`ValueError: poucas perguntas reais...`,
  testado ao vivo via CLI). Mesmo padrão do M27 antes do banco crescer: infraestrutura pronta e
  testada, medição real adiada até o Pilar 3 (uso real) produzir volume suficiente — não é tarefa
  de código pendente, é dado que ainda não existe.
- 🏁 **P1.5 — ALiBi medido e vence nos dois eixos (2026-07-16).** `layers.py`/`model.py` ganham
  `pos_encoding: "learned" | "alibi"` em `GPTConfig` — ALiBi (Press et al.) é um viés relativo
  SOMADO aos scores de atenção, sem parâmetro treinável (`wpe` some do modelo inteiro quando
  ativado); como não tem tabela de posição, o mesmo checkpoint aceita qualquer T, inclusive além
  do `block_size` de treino (o "contexto maior" do item, de graça). Backward não muda: viés
  constante não altera o gradiente dos scores — provado por checagem numérica (gradcheck) igual
  ao caminho `learned`. 8 testes novos em `test_nanollm_grad.py` (gradcheck completo, sem-wpe,
  causalidade, extrapolação além do block_size, `pos_encoding` inválido barrado).

  **Experimento real compute-matched** (preset `mini`, ~437-441 passos, mesmo dataset de
  1.034.551 tokens do P1.2, mesma semente): usei o harness de PPL do `eval.py` em vez do
  blind-eval do P1.4 (seu DoD ainda não foi batido — só 14 perguntas reais, ver P1.4).

  | pos_encoding | ppl @ 192 (treinado) | ppl @ 384 (2× extrapolado) |
  |---|---|---|
  | `learned` | 293,03 | ❌ quebra (erro de broadcast — não processa) |
  | `alibi` | **233,12** | **235,24** (só +0,9% de perda) |

  ALiBi venceu nos dois eixos ao mesmo tempo: ppl in-distribution melhor (233 vs 293, não é
  empate) **e** extrapola pra 2× o contexto treinado quase sem degradar. Passa a regra do próprio
  item ("só entra se medir melhora") sem ressalva. Ressalva honesta: 1 rodada compute-matched, não
  múltiplas sementes — direcional, não estatisticamente blindado; ALiBi treinou ~1,7× mais lento
  no CPU nesta rodada (1505s vs 878s, poss. ruído de máquina, não perfilado a fundo). **Decisão
  registrada, não executada aqui:** candidato forte pra virar o padrão no próximo treino de
  produção real (ckpt_v1 e o portão binário do P1.3 continuam em `learned` por ora — trocar o
  checkpoint vivo é uma decisão de promoção separada, mesmo espírito do P1.3).

**Referência:** este pilar continua o trabalho já registrado em `JARVIS_ROADMAP_ANO2.md` §10
(M25–M28); os itens acima começam em cima daquilo, não o duplicam. GPU dedicada continua sendo
upside, não pré-requisito (ver `docs/APOLO_NANO_ROADMAP.md` e memória `project_hardware`).

---

## Pilar 2 — Modo Aprendizado

**Linha de base medida (2026-07-15):** 6 agentes buscam sobre uma lista majoritariamente FIXA de
~180 tópicos (`src/topics.py`). Auto-currículo existe mas é raso (pede 6–12 tópicos à LLM quando a
rotação esgota) e mostrou deriva pro genérico nos logs reais ("Otimização de infraestruturas
urbanas inteligentes com Machine Learning"). A porta de qualidade antes de salvar é **só
estrutural** (tamanho, formato, anti-injeção) — **não existe verificação factual em nenhum ponto
do pipeline**. Dedup existe mas é majoritariamente manual (ação de curador). O único mecanismo
parecido com "revalidação" é um diff de drift que só roda quando um tópico é re-estudado 21 dias
depois.

- 🏁 **P2.1 — Camada de validação factual, ligada de ponta a ponta (2026-07-16).** O buraco era
  real: nada checava se um resumo era fiel à fonte, só forma (tamanho/markdown/anti-injeção).
  Agora existe uma amostra real:
  - `src/factcheck.py` ganha `GROUNDEDNESS_PROMPT` + `parse_groundedness()` (juiz LLM sim/não,
    puro e testável sem motor de verdade — mesmo padrão do `blind_eval`/`nano_binary_classify`).
  - `learner.py::_process_item` audita **1 em cada `VERIFY_SAMPLE_EVERY` (10) resumos salvos**
    contra a fonte crua (`item.content`, que só existe em memória nesta sessão — é agora ou nunca)
    via `_verify_summary` (mesmo lock/gate/timeout do `_summarize`, nunca derruba o pipeline em
    erro). Contador determinístico, não aleatório — reproduzível.
  - Schema: `learned_topics.verified` (nova coluna, migração automática — `_COLUMN_MIGRATIONS` em
    `storage.py`, testada contra um banco "legado" simulado sem a coluna). `None` = não sorteado
    (a maioria — não é "reprovado"), `"verified"`/`"failed"` = resultado real da auditoria.
  - `_persist` propaga pro SQLite E pro metadata do RAG (Chroma) — `"unchecked"` quando `None`.
  - `rag.py::recall()` passa `verified` pro candidato; `rerank()` ganha `w_verified` — "failed"
    penaliza, "verified" bonifica de leve, "unchecked" (maioria) fica neutro — não afirma nada
    sobre o que nunca foi checado.
  - `storage_learning.py::get_verification_stats()` novo — quantos % já foram amostrados e quantos
    passaram, pronto pro dashboard do Pilar 5.
  **DoD batido nos 3 critérios:** campo existe no schema (✓ migração testada), é populado
  automaticamente (✓ 1/10 resumos reais, não simulado), influencia o rerank (✓ `w_verified`
  testado isolando o efeito). 19 testes novos entre `test_factcheck.py`, `test_storage.py`,
  `test_storage_learning.py`, `test_learner_dedup.py`, `test_rerank.py`, `test_recall_recency.py`.
- 🏁 **P2.2 — Currículo dirigido por necessidade (2026-07-16).** `LearningEngine` ganha
  `profile=None` (opcional — sem perfil, comportamento antigo intacto). Novo
  `_active_needs_context()` lê `goal`+`project` de `src/profile.py` (não `habit`/`person`/etc —
  só o que é acionável como tópico de estudo). `_replenish_curriculum` injeta esse contexto no
  prompt do LLM com instrução explícita de **PRIORIZAR** tópicos que ajudem essas metas/projetos,
  mantendo exploração geral como complemento (não substituição). `app.py`: `profile` passou a ser
  criado ANTES do `learner` e injetado nele. Verificação à parte (não era mudança de código, já
  existia): `_fetcher` já prioriza `_user_queue` sobre `_self_queue` estruturalmente
  (`src/learner.py:376-384` — checa a fila do usuário primeiro, sempre) — conferido por leitura,
  não precisou de correção. 6 testes novos em `test_learner_logic.py` (contexto vazio/com
  dados/perfil quebrado sem derrubar, prompt com e sem metas ativas).
- 🏁 **P2.3 — Filtro de deriva do currículo (2026-07-16).** `_enqueue_self_studies` (ponto único
  usado tanto por `_replenish_curriculum` quanto pela síntese cruzada — os dois caminhos que geram
  tópico via LLM) ganha 2 filtros antes de enfileirar:
  1. **`_curriculum_too_verbose`** (sempre ativo, determinístico): tópicos com mais de
     `CURRICULUM_MAX_WORDS` (6) palavras são descartados. Calibrado contra os exemplos REAIS de
     deriva vistos em produção (2026-07-15) — "Otimização de infraestruturas urbanas inteligentes
     com Machine Learning" (8 palavras) e pior, "Desenvolvimento e implementação da IA aplicada à
     gestão das águas potáveis urbanas resilientes" (12) — contra tópicos legítimos medidos
     ("Filosofia estoica", "Sistemas distribuídos", 2 palavras cada): folga grande entre os grupos.
  2. **`_curriculum_relevance`** (só ativo quando o perfil tem metas/projetos/preferências/valores
     preenchidos): pontua sobreposição lexical contra esse corpus; abaixo de
     `CURRICULUM_RELEVANCE_MIN` (0,12) descarta.

  **Achado honesto no caminho — 1ª tentativa descartada, não escondida:** a ideia original (do
  próprio texto deste item) incluía o HISTÓRICO de tópicos já estudados no corpus de relevância.
  Implementei, testei, e o teste REAL revelou o problema: "Filosofia estoica" era reprovado só por
  não compartilhar palavra com "Docker"/"Redis" recém-estudados — rejeitando diversidade
  LEGÍTIMA, contra o próprio objetivo do currículo (que É diversidade, não repetição temática).
  Removido do corpus; só o perfil CURADO (sinal explícito, não incidental) entra na relevância
  agora. Um teste (`test_interest_corpus_ignora_historico_de_proposito`) trava essa decisão.

  8 testes novos em `test_learner_logic.py`.
- 🏁 **P2.4 — Dedup automático noturno (2026-07-16).** `app.py::_run_dedup_cycle()` roda
  `rag.dedup_exact()` + `db.dedup_learned_topics()` 1×/dia a partir de `DEDUP_HOUR` (padrão 4h),
  mesmo padrão exato do backup/flywheel (`_last_dedup_date`, marca a data ANTES de rodar,
  `-1` desliga). Diferente do flywheel, não exige ocioso/learner parado — é leve (comparação de
  texto exato, sem IA). Os dois destinos são independentes: um falhar não impede o outro (testado).
  O caminho manual do Curador (`MemoryCurator.apply`) continua existindo do jeito que era — isto
  soma, não substitui. 4 testes novos em `tests/test_dedup_scheduler.py`.
- 🏁 **P2.5 — Métrica de qualidade real, rastreada no tempo (2026-07-16).** Novo
  `src/quality_sampler.py` — separado de `get_summary_quality()` (que continua existindo, mede só
  forma). `factcheck.py` ganha `QUALITY_PROMPT`+`parse_quality_verdict` (juiz LLM: preciso, útil,
  específico — mira o mesmo padrão de chavão vazio já visto na deriva do currículo, P2.3).
  `storage_learning.py::sample_topics_for_quality(n)` puxa amostra ALEATÓRIA (não os mais
  recentes) de tópicos já salvos — diferente do P2.1 (precisa da fonte crua, só roda na hora do
  save), este roda depois, sobre a base inteira, de qualquer época. `app.py::_run_quality_sample_cycle`
  agendado 1×/dia (`QUALITY_SAMPLE_HOUR`, padrão 5h) — mesmo padrão do flywheel/dedup — grava
  `data/learner/quality_history.jsonl` (append-only, mesmo desenho do `blind_eval_history` do P1.4).
  21 testes novos entre `test_factcheck.py`, `test_storage_learning.py`, `test_quality_sampler.py`,
  `test_quality_scheduler.py`.
- 🏁 **P2.6 — Gate de regressão do recall agendado (2026-07-16).** `recall_calibration.py`
  (antes só `calibrate()`, ferramenta manual) ganha `freeze_ground_truth` + `evaluate_recall_gate`
  + `run_tracked_recall_gate`: congela N títulos de tópicos JÁ ESTUDADOS (idempotente, mesmo
  padrão do `freeze_questions` do P1.4) e testa — teste de ida-e-volta — se buscar pelo próprio
  título ainda traz o próprio tópico de volta no recall. Cair é regressão REAL de índice/embedding,
  não hipótese. `app.py::_run_recall_gate_cycle` agendado 1×/dia (`RECALL_GATE_HOUR`, padrão 6h) —
  mesmo padrão do flywheel/dedup/qualidade — grava `recall_gate_history.jsonl` e **notifica** se o
  hit-rate cair abaixo de 70%.
  **Refactor de bônus, não escondido:** essa é a 3ª cópia quase idêntica do padrão "placar JSONL
  append-only" (depois de `blind_eval` P1.4 e `quality_sampler` P2.5) — extraído `src/jsonl_history.py`
  compartilhado; os dois módulos antigos foram refatorados pra usá-lo por dentro, API pública
  intacta (testes antigos continuam passando sem alteração). 17 testes novos entre
  `test_jsonl_history.py`, `test_recall_calibration.py`, `test_recall_gate_scheduler.py`.
- 🏁 **P2.7 — Re-verificação priorizada (2026-07-16, fecha o Pilar 2).** `topics.py::relearn_window_days(topic, base)`
  encurta a janela de `RELEARN_DAYS` (21→10) pra setores VOLÁTEIS (tech que muda rápido —
  `VOLATILE_SECTORS`: backend, frontend, mobile, data/ML, devops, segurança, IoT... 16 setores);
  áreas estáveis (ciência, matemática, história) mantêm o padrão — nunca sobe acima do `base`
  passado, e `base<=0` (RELEARN_DAYS desligado) nunca é "reativado" por engano.
  `LearningEngine._effective_relearn_days` combina isso com o P2.2/P2.3: se o tópico conecta com
  uma meta/projeto ATIVO do perfil (reusa `_curriculum_relevance`), a janela corta pela metade de
  novo — piso de 3 dias. `_already_known` (o choke point único de anti-duplicação, já usado desde
  o M8) passa essa janela efetiva pro `is_topic_studied`/`is_url_studied`, que ganham o parâmetro
  opcional `relearn_days` (backward-compatible: `None` = comportamento de sempre, todo outro
  chamador do projeto segue igual). 12 testes novos entre `test_topics.py`,
  `test_storage_learning.py`, `test_learner_logic.py` (mais 2 fixes de fakes existentes que
  precisavam do novo parâmetro opcional).

**Pilar 2 (Modo Aprendizado) fechado: P2.1–P2.7 todos 🏁.**

---

## Pilar 3 — Uso real / dogfooding

**Por quê:** quase tudo que trava o Pilar 1 (flywheel, portão binário, blind-eval significativo)
está bloqueado por volume real de uso — medição de 15/07: 5 primeiras-mensagens, 0 reações 👍
dadas até agora. Isso não é código, é processo.

- ⏭️ **P3.1 — Ritual de uso diário.** Não é código — é usar o chat normalmente no dia a dia e dar
  👍/👎 quando fizer sentido. Só o Leo pode fazer isso; registrado aqui como lembrete, não como
  tarefa de engenharia (não marco 🏁 em algo que não fiz).
- 🏁 **P3.2 — Painel de progresso do volume (2026-07-16).** `/api/nano/flywheel/diagnose` ganha
  `min_pairs`/`faltam_titulo`/`faltam_reacoes` (contra `FLYWHEEL_MIN_PAIRS`, nunca negativo). O
  painel "Cérebro Próprio" (já existente) ganha 2 barras de progresso reaproveitando o
  `.brain-bar-fill` que já animava a Soberania — "faltam X" fica visível sem precisar ler log.
  **Verificado ao vivo** no preview (não só teste): rodei o app de verdade e o funil mostrou
  "🗨️ Pares de título (limiar 5) → pronto para o próximo treino automático" (5/5) e "👍 Pares de
  reação (limiar 5) → faltam 5" (0/5) — exatamente o esperado. Bônus não planejado: essa mesma
  rodada confirmou ao vivo que os ciclos noturnos dos P2.4/P2.5/P2.6 (dedup, qualidade, gate de
  recall) já estão rodando de verdade em produção — "[quality] amostra noturna: 15/15 passaram",
  "[recall-gate] 19/19 tópicos achados". 2 testes novos em `test_routers_nano.py`.

---

## Pilar 4 — Cadência de auditoria de segurança

**Por quê:** a auditoria de 15/07 achou 4 vulnerabilidades reais e exploráveis (CSRF, SSRF via
redirect, bypass de undo, vazamento de conteúdo) num código que já tinha passado por revisão
normal. Isso não deve ser ad-hoc.

- 🏁 **P4.1 — Gatilho definido (2026-07-16, decisão do Leo).** Lembrete manual, não automação
  nova: antes de todo merge "grande" no `main`, EU (Claude) verifico o critério objetivo e aviso
  o Leo pra rodar `/security-review` (o skill é billado — não dispara sozinho). **Critério
  objetivo:** >10 arquivos tocados NO MERGE, OU qualquer mudança em `routers/`, `src/actions.py`,
  `src/webtask.py`, autenticação/CORS/permissões — qualquer um dos dois já dispara o lembrete.
  Sem tabela/cron novo — é uma checagem que entra na minha rotina de "antes do merge grande",
  registrada como memória de longo prazo (`feedback_security_review_gatilho`) pra valer em
  sessões futuras, não só nesta.
- 🏁 **P4.2 — Registro histórico de auditorias (2026-07-16).** Novo `src/security_audit_log.py`
  (`log_audit`/`read_audit_history`) — mesmo padrão JSONL append-only do resto do projeto
  (`src.jsonl_history`, P1.4/P2.5/P2.6). Cada entrada: data, gatilho (`manual`/`pre-merge-large`),
  lista de achados (categoria/severidade/arquivo/resumo/status) e contagem corrigidos/total.
  **Populado retroativamente com a auditoria real de 15/07** (não deixei vazio): os 4 achados
  reais (CSRF em `routers/vision.py`, SSRF em `src/webtask.py`, bypass de undo em
  `src/actions.py`, vazamento de conteúdo em `routers/actions.py`) — todos `fixed` no mesmo dia
  (commit `ffda7be`). Copiado pro `data/` da instância principal também, não só do worktree.
  4 testes novos em `test_security_audit_log.py`.

---

## Pilar 5 — Dashboard único de saúde da inteligência

**Por quê:** hoje as métricas (Nano, qualidade do aprendizado, hit-rate do RAG, canário de
alucinação) estão espalhadas entre `/api/health`, `/api/nano/coverage`, `/api/retrospective2`,
logs e commits. Não existe um lugar só pra ver "como o cérebro está indo".

- 🏁 **P5.1 — Fontes mapeadas (2026-07-16, sem código).** `/api/health`, `/api/nano/coverage`,
  `/api/nano/flywheel/diagnose` (P3.2), `src/evals.py` (canário), `get_summary_quality()`
  (estrutural), `quality_sampler`/`recall_calibration` (P2.5/P2.6). **Achado real no mapeamento:**
  o blind-eval tinha DOIS caminhos de registro — `data/nano/blind_eval_last.json` (só o último
  resultado, escrito pelo endpoint `/api/nano/blind-eval/run`) E `blind_eval_history.jsonl` (a
  série completa do P1.4, escrita pelo CLI). Decisão: o painel novo usa o histórico JSONL (fonte
  de tendência de verdade), não o arquivo solto — sem "consertar" o endpoint antigo agora (fora
  do escopo deste item), só registrado aqui pra não se perder.
- 🏁 **P5.2 + P5.3 — Painel consolidado com tendência (2026-07-16).** Novo
  `src/intelligence_dashboard.py::build_snapshot()` — agrega os 5 números exatos que o item pede
  (cobertura Nano via `db.nano_coverage()`, ppl via `nano_engine.info()`, win-rate blind-eval,
  qualidade P2.5, volume P3.2) reaproveitando os históricos JSONL do P1.4/P2.5/P2.6 — cada bloco
  já vem com `latest` E uma janela de `trend` (não só o valor atual). Cada fonte falha
  independente (banco fora não derruba o resto). Novo `GET /api/health/intelligence`
  (`routers/health.py`). Card "🧠 Saúde da inteligência" no painel de Saúde existente, reaproveitando
  os mesmos helpers `card`/`line` já usados pelos outros cartões. **Verificado AO VIVO no
  preview** (não só teste): abri o painel de verdade e o card mostrou os números reais da
  instância — qualidade 100% (15/15), gate de recall 100% (19/19), "faltam 5 reações". 13 testes
  novos entre `test_intelligence_dashboard.py` e `test_routers_health.py` + 1 teste existente
  ajustado (`test_frontend_assets.py` fazia match textual exato na linha de montagem do painel).

---

## Pilar 6 — Fechar ou descartar M20.3 (automação de navegador)

**Por quê:** `JARVIS_ROADMAP_ANO2.md` Épico 20.3 está "PENDENTE DO LEO" há um tempo — infra pronta
(`src/webtask.py`, Playwright instalado), mas sem tarefa real definida. Débito de roadmap
esquecido é pior que decisão explícita de abandonar.

- 🔲 **P6.1 — Decisão explícita.** Ou (a) escolher a tarefa semanal real a automatizar e fechar o
  épico, ou (b) marcar como ⏭️ adiado/descartado no roadmap com motivo, liberando o item da lista
  de pendências ativas.

---

## Pilar 7 — Consolidação periódica de docs

**Por quê:** os roadmaps estão crescendo (`JARVIS_ROADMAP_ANO2.md` já é longo, múltiplos `.md` na
raiz). Manutenção, não urgência — por isso é o último da fila.

- 🔲 **P7.1 — Definir cadência.** Ex.: a cada Ano fechado (como já aconteceu Ano1→Ano2), revisar
  se algum doc pode migrar pra `docs/` como histórico, igual já foi feito uma vez.
- 🔲 **P7.2 — Aplicar aos docs deste próprio plano.** Quando os pilares 1–6 avançarem o
  suficiente, revisar se este arquivo (`PLANO_7_PILARES.md`) deve virar seção de um roadmap maior
  ou continuar solo.

---

*Este documento não estima prazo — cada pilar avança em "siga"s como o resto do projeto. Nenhum
item aqui deve ser marcado 🏁 sem um número medido de verdade (o mesmo padrão que já vale para
todo o resto do roadmap).*
