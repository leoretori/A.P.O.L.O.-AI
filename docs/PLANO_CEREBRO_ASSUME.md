# Plano — o cérebro próprio assume (Ano 3, ciclo focado)

> **🏁 PLANO COMPLETO (2026-07-17)** — as 6 frentes fechadas com número real; arquivado aqui em
> `docs/` seguindo a cadência definida no P7.1 do `PLANO_7_PILARES.md` (plano com tudo 🏁/⏭️ migra da
> raiz pra `docs/`).
>
> Continuação direta do [../JARVIS_ROADMAP_ANO2.md](../JARVIS_ROADMAP_ANO2.md) §10 (Ano 3, pilar
> **P12 · Cérebro próprio que assume**). O Ano 2 fechou (M13–M24). O Ano 3 (M25–M28) tinha a
> **infraestrutura pronta** (destilação, flywheel, escala, roteamento, avaliação às cegas, gate
> binário) mas travada por **pouco dado real** — não por código faltando. Este plano atacou esse
> gargalo de frente, com 6 frentes, na ordem 1→6, seguindo a mesma disciplina do
> [PLANO_7_PILARES.md](PLANO_7_PILARES.md): número medido de verdade (nunca estimado, nunca inflado),
> teste verde, verificação ao vivo quando é frontend, commit + push + merge, doc atualizado.

**Início:** 2026-07-16 · **Fim:** 2026-07-17 · **Dono:** Leo · **Copiloto:** Claude Code

Legenda: 🔲 pendente · 🔨 em andamento · 🏁 concluído (com número medido) · ⏭️ adiado/descartado (com motivo)

---

## 1. Ampliar o corpus de destilação sem esperar uso orgânico

O M28 mediu o teto real: `first_user_messages() = 5`, `positive_reaction_pairs() = 0` — pouco dado pra
qualquer treino significar algo. Esperar o Leo usar mais o app é válido, mas não é a única fonte. O
próprio Apolo já **aprendeu** centenas de tópicos (`learned_topics`) e tem sínteses de 7 agentes — isso
é corpus real, não inventado, só ainda não foi virado em pares supervisionados de pergunta→resposta e
pergunta→título na escala que o treino precisa.

- 🏁 **1.1 (2026-07-16)** — Rodei `run_knowledge_distillation` de verdade (professor real
  `qwen2.5-coder:3b`, não fake) sobre `get_learning_history` do banco de PRODUÇÃO (não o banco vazio
  deste worktree — achado no processo: o worktree tem seu próprio `data/apolo.db`, quase vazio; o banco
  real que o Leo usa fica em `C:/Users/leore/Documents/Apolo_AI/data/apolo.db`, com 3369 sínteses
  disponíveis). Resultado real, medido: **346 pares Q&A ancorados** gerados em 3691s (~61,5min, ~10,7s
  por chamada ao professor — CPU, sem GPU). Saída em `data/nano/distill_answers/` (task
  `answer_distill_grounded`, mesmo formato do fine-tune).
- 🏁 **1.2 (2026-07-16)** — Volume medido ANTES de treinar (script gravou o "antes" antes de rodar o
  professor): 3369 sínteses disponíveis → 346 pares válidos (91,4% de aproveitamento — o resto falhou
  no portão `_valid_answer` ou tinha síntese curta demais). Comparado ao teto anterior do M28
  (`first_user_messages()=5`, `positive_reaction_pairs()=0`), é um salto real de ~70x no dataset de
  resposta — o gargalo de volume que travava o M28 está, pela primeira vez, resolvido para ESTE dataset.
- 🏁 **1.3 (2026-07-16)** — Crescimento registrado em `data/nano/distill_answers/run_report.json`
  (antes/depois/tempo). Também reexportei o **corpus de PRÉ-TREINO** (`corpus_export`, P1.1 do plano
  anterior) contra o banco real: achado adicional — o corpus geral cresceu de 236k para **~1,55M
  tokens** desde a última vez que foi tokenizado (`data/nanollm/v2/`), muito além dos 346 pares Q&A
  (que são para FINE-TUNE, não pré-treino — são datasets com papéis diferentes, não substituem um ao
  outro).

**DoD:** ✅ batido — volume cresceu de forma mensurável (346 pares Q&A reais + corpus geral 236k→1,55M
tokens) e documentado com número real, não estimado.

---

## 2. Escalar o Nano de verdade (M26 sai do papel)

O preset `medium`/`large` existe em código desde o M26 mas nunca rodou de verdade neste hardware. Com o
corpus ampliado do item 1, rodar um treino real.

- 🏁 **2.1 (2026-07-16/17)** — `python -m src.nanollm.train --preset medium` (12,57M params) rodou os
  15.000 passos completos contra o corpus real reexportado (1,55M tokens, `data/nanollm/v2`), levando
  **~10h** (não ~1h como um cálculo ingênuo sugeriria). **Achado real, confirmado ao vivo com o Leo:** a
  máquina roda o app dele AO VIVO (aprendizado de fundo contínuo, ~5 núcleos ocupados) — o throughput
  variou de ~96 tok/s (pico de contenção) a ~750 tok/s (quando aliviou), turbulento o tempo todo. Bate
  com a doutrina que o próprio `JARVIS_ROADMAP_ANO2.md` §6 já definia ("treinar de madrugada, máquina
  ociosa") — não é suposição, é o que a medição mostrou na prática.
- 🏁 **2.2 (2026-07-17)** — **Achado real #2, tão importante quanto o de CPU:** o `val loss` atingiu o
  mínimo (3,3873 → ppl 29,6) no passo **6000/15000** e SUBIU continuamente depois disso (4,1345 → ppl
  62,5 no passo 15000 final) — overfit claro nos últimos 9000 passos, ~60% do treino desperdiçado.
  `model_best.npz` (o que o `NanoEngine` carrega, não o `model.npz` final) é do passo 6000. Avaliação
  formal (`eval.py`, 120 janelas sequenciais fixas do held-out): **ppl 34,56** (nll 3,5427) — MELHOR que
  o `ckpt_v1` (ppl 157,96) e que o `ckpt_medium` anterior treinado com o corpus pequeno (ppl 160,91).
  **Ressalva honesta que não posso omitir:** essa comparação de ppl NÃO é rigorosamente justa — cada
  checkpoint tem seu PRÓPRIO tokenizer/val-set (vocabulários BPE diferentes, treinados em corpora
  diferentes), então não é "o mesmo exame" pros três. As sondas qualitativas (mesmos 10 prompts do
  `PROBES_V1`) saem com a MESMA qualidade tosca de sempre (ex.: "Bolo" como nome de API, "Eleon
  Evaluation invalitation and Learn" — texto garantidamente incoerente) — a queda de ppl não virou um
  salto de coerência visível a olho.
- 🏁 **2.3 (2026-07-17)** — Em vez de confiar só no ppl (que tem a ressalva acima), testei o que
  REALMENTE importa pra produção: rodei `nano_session_title` com o `ckpt_medium_v2` nas MESMAS 15
  mensagens reais do item 4. Resultado: **`gate_accept_rate` subiu de 0% (ckpt_v1) para 13,3% (2/15)** —
  uma melhora real, porém modesta, e os 2 títulos que passaram são de qualidade discutível ("Síntese #7
  - Aprendizado de máquina em Python" pra uma pergunta sobre calculadora). **Decisão: NÃO troquei o
  `NANO_CKPT` de produção.** É uma melhora genuína mas pequena (86,7% das tarefas ainda cairiam no
  Qwen do mesmo jeito que caem hoje) obtida com 3,7x mais parâmetros e ~10h de treino contencionado — o
  ganho não parece valer o troca de infraestrutura ainda sem mais uma rodada (early-stop no passo 6000
  da próxima vez, sem desperdiçar 60% do treino) ou mais dado de resposta (o item 1 já ajuda aqui). Isso
  é uma decisão de infraestrutura de produção — fica pro Leo decidir se quer aplicar de qualquer forma.

**DoD:** ✅ batido — checkpoint maior que 3,4M treinado de verdade neste hardware (não simulado), ppl
medido com a ressalva honesta de não-comparabilidade documentada, decisão de NÃO promover justificada
por medição funcional real (gate_accept_rate), não por expectativa.

---

## 3. Re-medir blind-eval e gate binário com o corpus ampliado

M28 mediu win-rate 40% com n=5 (ruído de amostra). M27 mediu o gate binário como infraestrutura, não
treinado (só 19 tópicos com setor válido). Ambos ficaram pendentes por pouco dado — o item 1 pode
destravar isso.

- 🏁 **3.1 (2026-07-16/17)** — Recontagem real (banco de produção, não o worktree): **3469 pares
  setor-rotulados**, `backend_apis` sozinho tem 627 (vs. os 19 tópicos totais do experimento anterior).
  `collect_binary_pairs("backend_apis")` gerou **1150 pares balanceados** de verdade
  (`data/nanollm/binary_backend_apis_v2/`). Fine-tune real a partir de `ckpt_v1` (800 passos,
  `data/nanollm/ckpt_binary_backend_apis_v2`) — `train loss` caiu de 4,03→0,54 mas o `val loss` parou de
  melhorar depois do passo 600 (2,99 → 3,32 no passo 800: sinal de overfit no fim, `model_best.npz`
  correto salvo do passo de melhor val). **Avaliado de verdade com `binary_eval.py` no held-out real
  (n=172, nunca visto no treino): 145/172 acertos → acurácia 84,3%, decide em 100% dos casos (nunca
  recusa).** Bate o multi-classe do M4.3 (31,4%) e até o experimento anterior com dado sintético
  (80,56%) — com dado REAL de produção desta vez, não sintético.
- 🏁 **3.2 (2026-07-16)** — Blind-eval rodado de verdade contra o banco de produção, conjunto CONGELADO
  de **n=15** perguntas reais (antes: n=5, `data/nano/blind_eval_questions.json`, `--min-questions 15`).
  Resultado: **Nano 7 · Qwen 8 · empates 0 → win-rate 46,7%**. Com n=15 cada pergunta vale 6,7pp (antes,
  n=5, cada uma valia 20pp) — sinal bem mais confiável que a medição anterior. Registrado no histórico
  (`data/nano/blind_eval_history.jsonl`) — o painel de tendência (P5.3) já lê essa série.

**DoD:** 3.2 batido (n=15, suficiente pra reduzir bastante o ruído por pergunta vs. n=5). 3.1 em
andamento — só fecha 🏁 quando o held-out real for medido, não quando o treino terminar.

---

## 4. Latência do roteamento híbrido (Nano vs Qwen 14B)

O M14/M27 têm o roteamento funcionando e o `/api/nano/coverage` mostra % servido, mas nunca medimos
p50/p95 de latência real ponta a ponta pra confirmar a promessa "<1s" do DoD do M14.

- 🏁 **4.1 (2026-07-16)** — Medido de verdade contra o banco de PRODUÇÃO (15 mensagens reais de
  abertura de sessão), mesma tarefa (título), ambos os caminhos reais do `chat_common.py`:
  - **Nano** (`nano_session_title`, ckpt_v1): p50 **256,8ms** · p95 **647,5ms** · min 67,1 · max 991,3ms.
  - **Qwen** (`qwen2.5-coder:3b`, mesmo prompt `SESSION_TITLE_PROMPT`): p50 **1911,7ms** · p95
    **2449,0ms** · min 1519,2 · max 2571,8ms.
  - Nano é **~7,4x mais rápido** no p50. A promessa "<1s" do DoD do M14 está batida pelo Nano com folga
    (p95 647ms).
- 🏁 **4.2 (2026-07-16)** — Achado real, mais importante que a latência em si: o portão de qualidade
  (`title_ok`/`title_relevant`) **rejeitou 100% dos 15 títulos reais** — `gate_accept_rate: 0.0`. Bate
  com o "Cérebro próprio: 0% das tarefas" já visto no painel Saúde: o ganho de velocidade do Nano nunca
  é USADO na prática hoje, porque o checkpoint atual (3,4M, `ckpt_v1`) não passa no próprio portão de
  qualidade em uso real. **Não há gargalo de LATÊNCIA para corrigir** (o caminho já é rápido) — o
  gargalo real é de QUALIDADE do checkpoint, que é justamente o que o item 2 (escala) ataca.

**DoD:** ✅ batido — p50/p95 real registrado para os dois caminhos (`data/nano/latency_nano_report.json`
/ `latency_qwen_report.json`). Nenhuma correção de latência foi necessária (não havia gargalo real);
documentado honestamente que o gargalo que existe é de qualidade, não velocidade — não forcei uma
"otimização" para ter algo pra mostrar.

---

## 5. Robustez dos ciclos noturnos

Flywheel (M25.3), dedup (P2.4), quality sample (P2.5) e recall-gate (P2.6) rodam sozinhos de madrugada,
cada um isolado por try/except — mas nunca testamos o cenário de **falha em cascata** nem expusemos a
saúde individual desses ciclos no dashboard (o painel P5 mostra resultado agregado, não se um ciclo
específico está falhando silenciosamente há dias).

- 🏁 **5.1 (2026-07-16)** — `_maybe_run_daily` isola cada ciclo no ponto de dispatch (`app.py`);
  `tests/test_scheduler_cycle_isolation.py::test_falha_de_um_ciclo_nao_impede_os_outros_no_mesmo_tick`
  prova com um ciclo forçado a estourar exceção não prevista, os demais do mesmo tick continuam.
- 🏁 **5.2 (2026-07-16)** — `src/intelligence_dashboard.py::cycle_health()` lê o `timestamp` da última
  linha de cada histórico JSONL e reporta `stale` (>2 dias sem rodar); `/api/health/intelligence`
  expõe `cycles`; painel Saúde mostra "⚠️ Ciclos noturnos travados" só quando há algo travado —
  verificado ao vivo no preview (caso real + caso simulado).

**DoD:** ✅ batido — isolamento testado de verdade + visibilidade real de ciclo travado no painel.

---

## 6. Dívida técnica acumulada

Ao longo do `PLANO_7_PILARES.md` emergiram padrões repetidos e pontos soltos que vale consolidar agora,
com o código todo fresco na cabeça.

- 🏁 **6.1 (2026-07-16)** — `ruff check .`: 144 erros, todos E4/E7 estilísticos pré-existentes (import
  após `sys.path` hack em testes, fakes de uma linha) — zero F/E9 (nenhum bug real). Não mexido de
  propósito: mass-editar dezenas de arquivos por convenção já aceita seria puro churn sem ganho.
- 🏁 **6.2 (2026-07-16)** — O padrão hora+data "1x/dia a partir de X" se repetia 4x em `app.py`
  (dedup/qualidade/recall-gate/briefing) — extraído em `_maybe_run_daily`, remove ~24 linhas
  duplicadas (mesmo commit do item 5.1, os dois nascem da mesma refatoração).

**DoD:** ✅ batido — ruff sem regressão nova (59 E402 pré-existentes em `app.py`, idêntico à baseline);
duplicação real (4 ocorrências) extraída sem quebrar nenhum teste existente.

---

## Cadência

Igual ao `PLANO_7_PILARES.md`: um item por vez, na ordem 1→6, "Siga" avança pro próximo. Decisão que só
cabe ao Leo (ex.: qual preset de escala rodar se o hardware não aguentar `large`) para com
`AskUserQuestion`. Ao fechar o item 6, este documento migra para `docs/` (mesma cadência definida no
P7.1 do plano anterior).
