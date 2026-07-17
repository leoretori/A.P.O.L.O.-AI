# Plano — corpus diverso, fine-tune melhor, docs em dia

> **🏁 PLANO COMPLETO (2026-07-17)** — as 5 frentes fechadas com número real; arquivado aqui em
> `docs/` seguindo a cadência do P7.1 (plano com tudo 🏁/⏭️ migra da raiz pra `docs/`).
>
> Continuação direta do [PLANO_CEREBRO_ASSUME.md](PLANO_CEREBRO_ASSUME.md) — o addendum de
> 2026-07-17 mediu um fine-tune de resposta que PIOROU o modelo (33,3% → 20,0% de win-rate) porque o
> dataset de 346 pares era topicamente estreito (~80% backend/devops/dados). Este plano atacou essa
> causa raiz, tentou de novo com técnica melhor, e fechou duas pendências antigas (README, security
> review). Mesma disciplina de sempre: número medido de verdade, teste verde, commit + push + merge.
>
> **Resultado honesto do item 2:** diversificar o corpus NÃO resolveu — o fine-tune diversificado deu
> o MESMO win-rate (20,0%) do fine-tune estreito. A hipótese original (item 1) estava incompleta; a
> causa provável real é que full fine-tune num modelo de 3,4M com centenas de pares (mesmo diversos)
> já é destrutivo por si só. Ver seção 2 para o raciocínio completo.

**Início:** 2026-07-17 · **Fim:** 2026-07-17 · **Dono:** Leo · **Copiloto:** Claude Code

Legenda: 🔲 pendente · 🔨 em andamento · 🏁 concluído (com número medido) · ⏭️ adiado/descartado (com motivo)

---

## 1. Diversificar o corpus de destilação por setor

`source_knowledge_grounded_pairs` (item 1 do plano anterior) pegou as primeiras N sínteses de
`get_learning_history` sem controlar a distribuição por setor — resultado: ~80% backend/devops/dados,
quase nada de outros assuntos. É provavelmente a causa raiz do fine-tune ter feito o modelo "esquecer"
prosa geral e derivar pra vocabulário tech em qualquer pergunta.

- 🏁 **1.1 (2026-07-17)** — `_stratify_by_sector(history, max_per_sector)` em `src/nanollm/distill.py`:
  reusa `classify_sector` (já usado no gate binário), aplica o teto ANTES de chamar o professor
  (economiza custo também). `source_knowledge_grounded_pairs`/`run_knowledge_distillation` ganham
  `max_per_sector` (default `None`, compatível); CLI ganha `--max-per-sector`. 4 testes novos.
- 🏁 **1.2 (2026-07-17)** — Rodado de verdade contra o banco de produção (3500 sínteses), `max_per_sector=15`:
  - **Antes:** `backend_apis` 638 · `devops_cloud` 492 · `data_ml` 342 · `outros` 257 · `databases` 248
    · `medicine_health` 232 · `mobile` 170 — os 3 primeiros setores já somam ~42% do total.
  - **Depois da estratificação:** 20 setores, TODOS com exatamente 15 itens (599 no total) — nenhum
    dominando. Setores antes ausentes/raros no dataset agora entram: `psychology`, `arts_creativity`,
    `ai_agents`, `science`, `cs_fundamentals`, `embedded_iot`, `education_pedagogy`, `game_dev`,
    `biotech_genomics`, `design_ux`.
  - Professor real (`llamacpp`, `qwen-1.5b`) rodou sobre os 599 candidatos: **588 pares** válidos
    (98,2% de aproveitamento) em 5077s (~84,6min) → `data/nano/distill_answers_v2/` (32.877 tokens,
    ~1,7x o dataset anterior de 346 pares — E MUITO mais diverso, não só maior).

**DoD:** ✅ batido — nenhum setor passou de 15/599 (2,5%) no dataset novo, contra ~18% de um único
setor (`backend_apis`) no anterior — melhora real e mensurável, não estimada.

---

## 2. Repetir o fine-tune com técnica melhor

- 🏁 **2.1 (2026-07-17)** — Fine-tune a partir de `ckpt_v1` com o dataset estratificado do item 1 (588
  pares), LR **3x menor** (2e-4 vs 6e-4 do v1) e `--patience 5`. Parou sozinho no passo 450/3000
  (melhor val no passo 200, val loss 3,696) — o early-stop funcionou de novo.
- 🏁 **2.2 (2026-07-17)** — Blind-eval no MESMO conjunto congelado (n=15), MESMO oponente real
  (`llamacpp`/`qwen-1.5b`): **20,0%** de win-rate — **idêntico ao `answer_v1`** (o fine-tune anterior,
  dataset estreito). Diversificar o corpus NÃO mudou o resultado.
- 🏁 **2.3 (2026-07-17)** — **Decisão: NÃO promovido.** 20,0% continua abaixo do baseline (33,3%),
  mesmo com corpus diverso e LR mais conservador.

**Conclusão honesta — a hipótese do item 1 estava incompleta:** diversificar por setor não foi a causa
raiz sozinha. Duas rodadas (`answer_v1` topicamente estreito, `answer_v2` diversificado) deram o MESMO
resultado (20,0%), ambas piores que o baseline sem fine-tune. A explicação mais provável agora: um
FULL fine-tune (todas as camadas) de um modelo de 3,4M com apenas centenas de pares — mesmo
diversificados — já é o suficiente pra derrubar a capacidade geral que o pré-treino (corpus de ~1,55M
tokens) deu ao modelo. O problema não é "que tipo de dado", é "quanto dado E como se ajusta". Próximas
tentativas precisam de MUITO mais volume (milhares de pares, não centenas) OU uma técnica que preserve
capacidade geral (congelar a maioria das camadas, LR ainda menor, ou misturar o corpus geral dentro do
próprio fine-tune) — não fine-tune completo ingênuo. Registrado em
`data/nano/experiment_history.jsonl` (item 3) para a próxima tentativa não repetir o mesmo erro sem
saber.

**DoD:** ✅ batido — número comparável ao baseline correto, decisão de promoção justificada por
medição (não bateu, com o motivo provável honesto, incluindo a correção da hipótese original).

---

## 3. Histórico de experimentos de fine-tune

Cada tentativa de fine-tune (título, resposta, binário) hoje vive num diretório solto
(`ckpt_title`, `ckpt_answer_v1`, `ckpt_binary_...`) sem registro central do que foi tentado e o
resultado — a comparação entre tentativas depende de eu (ou o Leo) lembrar/garimpar.

- 🏁 **3.1 (2026-07-17)** — `src/nanollm/experiment_log.py`: `log_experiment`/`read_experiment_history`,
  mesmo padrão JSONL append-only (`src.jsonl_history`) do resto do projeto. 3 testes novos.
- 🏁 **3.2 (2026-07-17)** — Registrados retroativamente `title_4.2` (DoD não batido, 0/6→1/6) e
  `answer_v1` (piorou, 33,3%→20,0%) em `data/nano/experiment_history.jsonl`; `answer_v2` (item 2 deste
  plano) já entrou no histórico ao ser medido, não retroativo.

**DoD:** ✅ batido — histórico consultável de experimentos (3 entradas reais), reusando a infra já
testada (`jsonl_history`), sem duplicar o padrão pela 5ª vez.

---

## 4. Atualizar o README

Pendente desde a consolidação de 2026-07-10 — módulos novos (`jsonl_history`, `intelligence_dashboard`,
`security_audit_log`, `sweep`, `binary_eval`, `experiment_log`) não aparecem na estrutura documentada.

- 🏁 **4.1 (2026-07-17)** — Árvore de estrutura do README atualizada contra o `src/`/`routers/` reais:
  faltava a pasta `routers/` inteira, ~10 arquivos de `nanollm/`, ~15 módulos de `src/` e o contador de
  testes ("17 testes" → 1685 reais).

**DoD:** ✅ batido — README reflete os módulos reais do repo nesta data.

---

## 5. Rodar `/security-review`

Gatilho definido em `[[feedback_security_review_gatilho]]` (>10 arquivos ou routers/`app.py`/auth/CORS
tocados antes de um merge grande) bateu nos dois ciclos anteriores sem eu lembrar o Leo de rodar.

- 🏁 **5.1 (2026-07-17)** — Lembrete entregue ao Leo no fechamento deste plano: dois ciclos grandes
  (`PLANO_CEREBRO_ASSUME.md` + este) tocaram `app.py`, vários `routers/*.py` e módulos novos sem uma
  auditoria de segurança formal desde a de 15/07. Decisão de rodar (e quando) é do Leo.

**DoD:** ✅ batido — lembrete entregue; decisão do Leo se/quando rodar.

---

## Cadência

Um item por vez, ordem 1→5, mesma disciplina dos planos anteriores. Ao fechar o item 5, este documento
migra para `docs/` (mesma cadência do P7.1).
