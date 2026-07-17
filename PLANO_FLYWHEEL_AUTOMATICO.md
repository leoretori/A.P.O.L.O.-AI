# Plano — o flywheel de resposta fecha o loop sozinho

> Continuação direta de [docs/PLANO_CORPUS_DIVERSO.md](docs/PLANO_CORPUS_DIVERSO.md) — três tentativas
> de fine-tune (estreito, diverso, parcial) deram todas piores que o baseline sem fine-tune. Conclusão
> daquele ciclo: o gargalo é volume de dado real, não técnica. Este plano ataca isso diretamente —
> automatizando o que hoje só rodou manualmente (CLI, na mão, nos últimos dois ciclos), pra que o
> corpus de resposta cresça sozinho todo dia, do mesmo jeito que o flywheel de título já cresce.

**Início:** 2026-07-17 · **Dono:** Leo · **Copiloto:** Claude Code

Legenda: 🔲 pendente · 🔨 em andamento · 🏁 concluído (com número medido) · ⏭️ adiado/descartado (com motivo)

---

## 1. Agendar a destilação de conhecimento como ciclo noturno

Hoje `run_knowledge_distillation` (Q&A ancorado, com a amostragem estratificada por setor do ciclo
anterior) só roda via CLI manual — eu mesmo rodei na mão duas vezes nos últimos dois ciclos. O
`learned_topics` cresce sozinho todo dia (aprendizado autônomo 24/7) — o corpus de destilação deveria
acompanhar, sem depender de alguém lembrar de rodar o comando.

- 🔲 **1.1** — `_run_knowledge_distill_cycle()` em `app.py`, mesmo padrão dos ciclos já existentes
  (flywheel/dedup/qualidade/recall-gate): roda 1x/dia via `_maybe_run_daily`, chama
  `run_knowledge_distillation` com `max_per_sector` (evita o desbalanceamento medido no ciclo
  anterior), grava em `data/nano/distill_answers` (sobrescreve o dataset — sempre o mais atual).
- 🔲 **1.2** — Verificar ao vivo que o ciclo dispara e não derruba o scheduler se o professor falhar
  (mesma disciplina de isolamento do item 5 do PLANO_CEREBRO_ASSUME.md).

**DoD:** ciclo noturno registrado e testado (com professor fake), isolado dos demais.

---

## 2. Re-treino automático com portão de qualidade

O flywheel de título (M25.3) já treina e só promove se medir melhora. O de resposta nunca teve essa
automação — cada tentativa foi manual. Agora que `--patience`/`--freeze-blocks` existem e 3
experimentos já mostraram que fine-tune com pouco dado piora, o ciclo automático deve ser
CONSERVADOR: só treina quando o corpus cresceu o suficiente para valer a pena, e só promove com
medição real, nunca por expectativa.

- 🔲 **2.1** — `_run_answer_flywheel_cycle()`: dispara o fine-tune (com `--patience`) só quando o
  corpus de destilação cresceu por um piso mínimo desde a última tentativa registrada em
  `experiment_log` (reusa o histórico do ciclo anterior — não starta do zero).
- 🔲 **2.2** — Gate de promoção: mede blind-eval no conjunto congelado (n=15) contra o checkpoint
  ATUAL em produção — só troca `NANO_CKPT` se bater com margem real (não empate de ruído).
- 🔲 **2.3** — Registra o resultado em `experiment_log` automaticamente (sucesso OU fracasso) — o
  histórico honesto continua mesmo sem eu acompanhar manualmente.

**DoD:** ciclo que treina, mede e decide sozinho — testado com fakes; verificação ao vivo só dispara
quando o piso de crescimento é atingido (não força um treino toda madrugada sem sentido).

---

## 3. Reações — achado, não bug (fechado por investigação)

Investigado antes de montar o plano: `positive_reaction_pairs()` já converte **100%** dos 👍 em pares
válidos (9 de 9). O "gargalo" de 9 pares não é um bug de captura — é que só houve 24 reações no total
(9👍/15👎) na vida inteira do app. Não construí nenhum incentivo artificial pra inflar esse número
(gamificar métrica não é o objetivo). ⏭️ Fechado como investigação, sem código — a fonte real de
crescimento é o aprendizado autônomo (item 1/2), não as reações manuais.

---

## 4. Painel de progresso do corpus de resposta

- 🔲 **4.1** — Estender `intelligence_dashboard.py` com o tamanho atual do corpus de destilação de
  resposta (pares, distribuição por setor) + uma trend simples (crescimento desde o último fine-tune
  registrado no `experiment_log`).
- 🔲 **4.2** — Sinal honesto no painel: "faltam ~X pares pro próximo piso de tentativa" (não uma
  previsão de sucesso — só visibilidade de progresso, evitando repetir a expectativa vazia do M28).

**DoD:** painel mostra o crescimento real, verificado ao vivo no preview.

---

## Cadência

Um item por vez, ordem 1→4, mesma disciplina dos planos anteriores. Ao fechar, migra pra `docs/`.
