# Plano — corpus diverso, fine-tune melhor, docs em dia

> Continuação direta do [docs/PLANO_CEREBRO_ASSUME.md](docs/PLANO_CEREBRO_ASSUME.md) — o addendum de
> 2026-07-17 mediu um fine-tune de resposta que PIOROU o modelo (33,3% → 20,0% de win-rate) porque o
> dataset de 346 pares era topicamente estreito (~80% backend/devops/dados). Este plano ataca essa
> causa raiz, tenta de novo com técnica melhor, e fecha duas pendências antigas (README, security
> review). Mesma disciplina de sempre: número medido de verdade, teste verde, commit + push + merge.

**Início:** 2026-07-17 · **Dono:** Leo · **Copiloto:** Claude Code

Legenda: 🔲 pendente · 🔨 em andamento · 🏁 concluído (com número medido) · ⏭️ adiado/descartado (com motivo)

---

## 1. Diversificar o corpus de destilação por setor

`source_knowledge_grounded_pairs` (item 1 do plano anterior) pegou as primeiras N sínteses de
`get_learning_history` sem controlar a distribuição por setor — resultado: ~80% backend/devops/dados,
quase nada de outros assuntos. É provavelmente a causa raiz do fine-tune ter feito o modelo "esquecer"
prosa geral e derivar pra vocabulário tech em qualquer pergunta.

- 🔲 **1.1** — Adicionar amostragem ESTRATIFICADA por setor (reusa `classify_sector`, já usado no gate
  binário) em vez de "as primeiras N" — teto por setor pra nenhum dominar o dataset.
- 🔲 **1.2** — Regenerar o dataset de destilação com a amostragem nova, medir a distribuição real
  resultante (não assumir que ficou balanceado — contar de verdade).

**DoD:** dataset novo com distribuição por setor mensuravelmente mais equilibrada que o anterior
(nenhum setor dominando >30-40% dos pares, por exemplo) — número real, comparado ao antes.

---

## 2. Repetir o fine-tune com técnica melhor

- 🔲 **2.1** — Fine-tune novo a partir de `ckpt_v1` com o dataset balanceado do item 1, LR mais baixo
  (menos agressivo que os 6e-4 usados antes) e `--patience` (já existe, do ciclo anterior).
- 🔲 **2.2** — Blind-eval no MESMO conjunto congelado (n=15) contra o MESMO oponente real (`llamacpp`,
  corrigido no ciclo anterior) — comparável de verdade com os 33,3%/20,0%/6,7% já medidos.
- 🔲 **2.3** — Decisão de promoção honesta: só troca `NANO_CKPT` se bater o baseline (33,3%) com
  margem real, não empate dentro do ruído de n=15.

**DoD:** número comparável ao baseline correto; decisão de promoção justificada por medição, incluindo
a possibilidade honesta de "ainda não bateu, eis o motivo provável".

---

## 3. Histórico de experimentos de fine-tune

Cada tentativa de fine-tune (título, resposta, binário) hoje vive num diretório solto
(`ckpt_title`, `ckpt_answer_v1`, `ckpt_binary_...`) sem registro central do que foi tentado e o
resultado — a comparação entre tentativas depende de eu (ou o Leo) lembrar/garimpar.

- 🔲 **3.1** — `src/nanollm/experiment_log.py` (ou extensão de um módulo existente): registra cada
  fine-tune (dataset, hiperparâmetros, resultado do blind-eval/gate) no mesmo padrão JSONL append-only
  (`src.jsonl_history`) do resto do projeto.
- 🔲 **3.2** — Retroativamente, registrar os experimentos já feitos (title 4.2, answer_v1 deste ciclo)
  pra não começar o histórico vazio.

**DoD:** histórico consultável de experimentos, reusando a infra já testada (`jsonl_history`), sem
duplicar o padrão pela 5ª vez.

---

## 4. Atualizar o README

Pendente desde a consolidação de 2026-07-10 — módulos novos (`jsonl_history`, `intelligence_dashboard`,
`security_audit_log`, `sweep`, `binary_eval`, `experiment_log`) não aparecem na estrutura documentada.

- 🔲 **4.1** — Atualizar a seção de estrutura/módulos do README com o que existe de verdade hoje
  (checar contra o `src/` real, não por memória).

**DoD:** README reflete os módulos reais do repo nesta data.

---

## 5. Rodar `/security-review`

Gatilho definido em `[[feedback_security_review_gatilho]]` (>10 arquivos ou routers/`app.py`/auth/CORS
tocados antes de um merge grande) bateu nos dois ciclos anteriores sem eu lembrar o Leo de rodar.

- 🔲 **5.1** — Lembrar o Leo explicitamente de rodar `/code-review ultra` ou `/security-review` antes
  do próximo merge grande — isto é ação DELE (billing/cloud), não algo que eu disparo.

**DoD:** lembrete entregue, decisão do Leo se/quando rodar.

---

## Cadência

Um item por vez, ordem 1→5, mesma disciplina dos planos anteriores. Ao fechar o item 5, este documento
migra para `docs/` (mesma cadência do P7.1).
