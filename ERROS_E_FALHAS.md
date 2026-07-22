# ERROS E FALHAS — Auditoria completa (2026-07-22)

> Auditoria feita com a suíte inteira rodando (**1731 testes, todos verdes**) e, principalmente,
> **executando o código de verdade** além do que os testes cobrem — inclusive com o checkpoint
> vivo (`data/nanollm/ckpt_v1`) e os ledgers reais de produção. Todos os erros "CONFIRMADO"
> foram reproduzidos por execução; os "ALTA CONFIANÇA" foram verificados por inspeção do
> caminho de código real.
>
> Este documento é a lista de trabalho: cada item tem checkbox. Marcar só depois do fix + teste
> de regressão. Ordenado por gravidade.

---

## 🔴 CRÍTICOS (quebram o ciclo de evolução da LLM)

### E1 — Flywheel de título crasha TODA noite em que finalmente tiver pares — `float(dict)` ✅ CONFIRMADO
- [x] corrigido
- **Onde:** [src/nanollm/flywheel.py:148-149](src/nanollm/flywheel.py) + [src/nanollm/flywheel.py:56-58](src/nanollm/flywheel.py) (`_default_eval`)
- **O quê:** `_default_eval` retorna o `report` inteiro de `evaluate()` ([src/nanollm/eval.py:108-126](src/nanollm/eval.py)), onde `report["val"]` é um **dict** `{"nll":…, "ppl":…}`. O flywheel faz `float(ev(...)["val"])` → **TypeError**.
- **Prova:** `float({'nll':1.0,'ppl':2.72})` → `TypeError: float() argument must be a string or a real number, not 'dict'`.
- **Sequência real:** destila → **treina o candidato por 400 passos (CPU queimada)** → crasha na medição → `app.py` engole como `"[flywheel] ciclo falhou"`. Nunca promove nem rejeita. **Nunca disparou em produção só porque o portão "poucos pares (2 < 5)" segurou** (ledger `data/nano/flywheel/flywheel_log.jsonl`); na primeira noite com ≥5 pares, explode.
- **Por que os testes não pegam:** os testes injetam `eval_fn` fake que retorna `{"val": <número>}`.
- **Fix:** `_default_eval` retornar `{"val": report["val"]["ppl"]}` (ou o flywheel ler `["val"]["ppl"]`); + teste de integração que usa o `_default_eval` real com um mini-checkpoint.

### E1b — Mesmo com E1 consertado, a medição de ppl crasha com dataset pequeno
- [x] corrigido
- **Onde:** [src/nanollm/eval.py:57-59](src/nanollm/eval.py) (`perplexity`) — exige `val` com ≥ `block_size+1` = **257 tokens**.
- **O quê:** com `FLYWHEEL_MIN_PAIRS=5` (env do app; a lib usa 12) e `val_fraction=0.1`, o val destilado tem ~1 par (~60-100 tokens) → `ValueError: val com N tokens < janela de 257`. O ciclo morre do mesmo jeito.
- **Fix:** `perplexity` aceitar janela menor quando o corpus é curto (janela = min(block, len-1)), ou o flywheel exigir `val_tokens >= block+1` antes de treinar.

### E2 — Prompt ≥ block_size (256 tokens ≈ ~700 chars) → completion **vazia e silenciosa** ✅ CONFIRMADO NO CHECKPOINT VIVO
- [x] corrigido
- **Onde:** [src/nanollm/model.py:176-187](src/nanollm/model.py) (`generate_fast`) + [src/nanollm/engine.py:90](src/nanollm/engine.py) + [src/nanollm/generate.py:45](src/nanollm/generate.py)
- **O quê:** `generate_fast` trunca o prompt para `block_size-1` e **para no teto do cache** (gera no máx. 1 token). O chamador fatia `out[0, len(ids):]` com o `len` do prompt **original** (maior que o out inteiro) → **lista vazia**. Zero erro, zero aviso.
- **Prova (checkpoint real):** prompt curto → 50 tokens; prompt de ~1300 chars → **0 tokens, texto `''`**.
- **Impacto real:** `/api/nano/complete` aceita até **4000 chars** ([routers/nano.py](routers/nano.py)) — acima de ~700 chars devolve vazio; no blind-eval, perguntas longas fazem o Nano "responder" vazio e perder injustamente; qualquer futuro chat-próprio herda isso.
- **Fix:** (a) fatiar pelo tamanho REAL pós-truncagem (devolver `prompt_tokens_used` do `generate_fast`); (b) janela deslizante de verdade: quando o cache enche, re-prefill com a janela recente (custo O(T) a cada `block_size` tokens) em vez de `break`.

### E3 — `--resume` + `--freeze-blocks`: retomada quebra com KeyError ✅ CONFIRMADO
- [ ] corrigido
- **Onde:** [src/nanollm/train.py:142-146](src/nanollm/train.py) + [src/nanollm/optim.py:77-82](src/nanollm/optim.py)
- **O quê:** o `optim.npz` só guarda estado dos params **treináveis**. Retomar um run congelado sem repassar exatamente o mesmo `--freeze-blocks` (ou vice-versa) → `KeyError: 'm::wte.w is not a file in the archive'`.
- **Prova:** reproduzido em sonda (Adam com freeze=1 salvo, load com freeze=0 → KeyError).
- **Fix:** gravar `freeze_blocks` no `state.json` e usá-lo no resume (com aviso se a flag divergir); `Adam.load` tolerar chaves ausentes (estado zerado) com warning.

### E4 — Blind-eval do flywheel de resposta compara **respostas vazias** do Nano — `split` antes do `strip` ✅ CONFIRMADO (indireto)
- [x] corrigido
- **Onde:** [src/nanollm/flywheel.py:228](src/nanollm/flywheel.py) (`_default_answer_blind_eval`): `out.split("\n\n")[0].strip()`
- **O quê:** o Nano, com prompt `"Pergunta: X\n\nResposta:"`, frequentemente **começa a completion com `\n\n`** (verificado no checkpoint vivo: `'\n\nUm engenheiro sênior…'`). `split("\n\n")[0]` pega o trecho **antes** do primeiro `\n\n` → string vazia → o juiz recebe resposta vazia do Nano.
- **Impacto:** o portão que decide promoção do flywheel de resposta mede candidato e titular com respostas mutiladas — o win-rate registrado (26,7% / 46,7%) está contaminado.
- **Fix:** `out.strip().split("\n\n")[0]`. Teste: completion iniciando com `\n\n` não pode virar resposta vazia.

### E5 — Portão do flywheel de resposta decide com **n=15 e margem de 5pp = ruído puro**
- [x] corrigido
- **Onde:** [src/nanollm/flywheel.py:248-252](src/nanollm/flywheel.py) (`min_questions=15`, `margin=5.0`) + `data/nano/blind_eval_questions.json` congelado com 15
- **O quê:** com n=15, o desvio-padrão binomial de um win-rate ~40% é ~12,6pp (IC 95% ≈ ±25pp). **Medido em produção:** o MESMO checkpoint titular marcou 33,3% (17/07) e 46,7% (19/07) sem mudar um peso. Margem de 5pp não distingue nada; promoção/rejeição vira cara-ou-coroa.
- **Agravantes:** (a) o professor re-gera respostas a cada rodada (temp 0,3) — candidato e titular são comparados contra **gabaritos diferentes**; (b) juiz LLM tem viés de posição não neutralizado.
- **Fix:** congelar 60-100 perguntas; **cachear as respostas do professor** (mesmo gabarito p/ todos); julgar cada par 2× com posições trocadas e só contar vereditos consistentes; promover só se o IC binomial do delta não cruzar zero.

### E6 — Flywheel de título ainda promove por **perplexidade**, o critério que o próprio projeto já mediu como enganoso
- [x] corrigido
- **Onde:** [src/nanollm/flywheel.py:146-159](src/nanollm/flywheel.py) (`margin=0.0`)
- **O quê:** o comentário no próprio arquivo (linhas 186-192) documenta o achado: *"ppl melhorou mas o BLIND-EVAL mostrou piora nos três [experimentos]"*. Mesmo assim, `run_nightly_flywheel` segue com portão de ppl **e margem 0.0** — o candidato treina na MESMA distribuição do val destilado, então quase sempre "ganha" no ppl; uma vez com pares suficientes (pós-E1), ele vai promover fine-tunes noturnos destrutivos para o checkpoint que também serve título/setor/chat.
- **Fix:** portão do título medir a **tarefa** (taxa de aceitação `title_ok`+`title_relevant` num conjunto held-out congelado, como o `gate_accept` do M26), não ppl; margem > 0.

---

## 🟠 GRAVES (custo/risco alto, não derrubam sozinhos)

### E7 — `run_answer_flywheel` treina 2000 passos ANTES de checar se o blind-eval pode rodar
- [x] corrigido
- **Onde:** [src/nanollm/flywheel.py:294-304](src/nanollm/flywheel.py)
- **O quê:** `freeze_questions` (que pode levantar `ValueError` por falta de perguntas) só roda **depois** do treino do candidato. Sem perguntas → horas de CPU jogadas fora, toda noite em que a condição persistir.
- **Fix:** mover `freeze_questions` para antes do `train(...)`.

### E8 — `asyncio.create_task` sem guardar referência no learner — risco real de perda silenciosa
- [x] corrigido
- **Onde:** [src/learner.py:572](src/learner.py) (`_save_and_record` — o caminho do SAVE de cada conhecimento!), [src/learner.py:598](src/learner.py), [src/learner.py:617](src/learner.py), [src/learner.py:667](src/learner.py)
- **O quê:** a doc do asyncio é explícita: o loop guarda só referência fraca; task sem referência forte **pode ser coletada pelo GC no meio da execução**. Além disso, exceção nessas tasks nunca é coletada (aparece, se muito, como "Task exception was never retrieved" no stderr). O projeto já teve a lição do except silencioso — este é o mesmo padrão em outra roupa.
- **Fix:** manter um `set` de tasks (`self._bg_tasks.add(t); t.add_done_callback(...)` que loga exceção e descarta).

### E9 — Faxina/reparo de sínteses "cruas" pode re-sintetizar conteúdo BOM repetidamente
- [ ] corrigido
- **Onde:** [src/learner.py:307-312](src/learner.py) (`_looks_raw`: `len>=300 and "##" not in s`)
- **O quê:** qualquer síntese válida que o modelo tenha escrito **sem** cabeçalhos markdown (acontece com o 1.5B) é tratada como "crua" para sempre: cada rodada de reparo gasta 1 chamada de LLM nela, e se a re-síntese também vier sem `##`, conta como "failed" e será tentada de novo na próxima rodada — moto-perpétuo de custo.
- **Fix:** marcar tentativas de reparo no banco (não re-tentar o mesmo id); heurística adicional (ex.: densidade de linhas de lista/parágrafos) em vez de só `##`.

### E10 — Destilação noturna de conhecimento REGERA o dataset do zero e embaralha o alvo do portão de crescimento
- [ ] corrigido
- **Onde:** [app.py:436-447](app.py) (`_run_knowledge_distill_cycle`) + [src/nanollm/flywheel.py:286-292](src/nanollm/flywheel.py)
- **O quê:** toda noite o corpus `data/nano/distill_answers` é reescrito inteiro (novas chamadas ao professor para os MESMOS resumos → pares diferentes para o mesmo conteúdo, split train/val re-sorteado). O gate `pairs - last_pairs < min_growth_pairs` mede crescimento de um dataset que muda de identidade a cada noite; e paga-se custo de professor re-rotulando o que já foi rotulado.
- **Fix:** dataset **append-only com dedup por pergunta** (cache professor→resposta por hash da síntese); regenerar split só quando treinar.

### E11 — `generate_fast` desperdiça a razão de existir do ALiBi ✅ CONFIRMADO
- [x] corrigido
- **Onde:** [src/nanollm/model.py:176-185](src/nanollm/model.py)
- **O quê:** o ALiBi foi adicionado exatamente para extrapolar além do `block_size` (P1.5), e o caminho lento (`generate`) extrapola de verdade. O caminho rápido trunca e para no teto igual ao learned. Prova: mesmo modelo ALiBi, `generate` devolveu 60 tokens, `generate_fast` devolveu 32.
- **Fix:** com ALiBi, deixar o cache crescer além de `block_size` (o viés é relativo, funciona) — só limitar por um teto de memória explícito.

### E12 — Avaliar o titular sobrescreve o `eval_report.json` do checkpoint vivo
- [x] corrigido
- **Onde:** [src/nanollm/eval.py:121-125](src/nanollm/eval.py) (grava sempre em `<ckpt>/eval_report.json` + `evals.jsonl`)
- **O quê:** o flywheel usa `evaluate()` como medidor puro, mas ele tem efeito colateral: a medição noturna no dataset destilado (número não comparável) sobrescreve o report "oficial" do ckpt vivo que o `/api/nano/status` exibe ([src/nanollm/engine.py:60-67](src/nanollm/engine.py)).
- **Fix:** parâmetro `write_report=False` para uso como medidor.

---

## 🟡 MÉDIOS

### E13 — `NanoEngine` gera sem penalidade de repetição nem top-p nem stop-strings
- [ ] corrigido
- **Onde:** [src/nanollm/model.py:189-199](src/nanollm/model.py) (`_sample`: só temperatura + top-k)
- **O quê:** modelo pequeno degenera em loop (o próprio projeto mediu: "gcloud components install ×132" no llama.cpp; a amostra real do Nano repetiu "engenheiro sênior" 2× em 50 tokens). O motor llama.cpp ganhou `repeat_penalty` configurável; o Nano, que é MENOR e degenera MAIS, não tem nada.
- **Fix:** repetition penalty simples no `_sample` (dividir logits dos tokens já gerados), top-p, e stop-sequences por string (ex.: parar em `"Pergunta:"`).

### E14 — Split de validação do pré-treino é a CAUDA do corpus em ordem alfabética de arquivo
- [ ] corrigido
- **Onde:** [src/nanollm/data.py:80-82](src/nanollm/data.py) + [src/nanollm/data.py:34](src/nanollm/data.py) (`sorted(root.rglob)`)
- **O quê:** o val é os últimos 2% dos tokens = o fim do último arquivo em ordem alfabética (uma fonte só, distribuição diferente do treino). O `best_val`/early-stop otimizam contra um val enviesado. O sample do tokenizer também é "os primeiros 2M chars" da mesma ordenação.
- **Fix:** split por DOCUMENTO sorteado com semente fixa; sample do tokenizer também amostrado por documento.

### E15 — ~62% dos parâmetros do Nano são embedding+head duplicados (sem weight tying)
- [ ] corrigido
- **Onde:** [src/nanollm/model.py:44-52](src/nanollm/model.py)
- **O quê:** no ckpt de 3,39M: `wte` 4096×256 = 1,05M **e** `lm_head` 256×4096 = 1,05M. GPT-2 e todos os modelos pequenos modernos amarram os dois (mesma matriz). Sem tying, um terço dos parâmetros é redundante — num modelo em que cada parâmetro conta.
- **Fix:** `lm_head.w = wte.w.T` (compartilhar o buffer; backward acumula nos dois papéis). Ganha ~31% de parâmetros de graça para camadas/contexto.

### E16 — `run_nightly_flywheel` ignora `min_pairs` divergente entre app (5) e lib (12)
- [ ] corrigido
- **Onde:** [app.py:158](app.py) (`FLYWHEEL_MIN_PAIRS=5`) vs [src/nanollm/flywheel.py:89](src/nanollm/flywheel.py) (`min_pairs=12`)
- **O quê:** o scheduler noturno roda com 5 — treino de 400 passos com 5 pares é overfit garantido e alimenta o E1b (val minúsculo). CLI e rota usam 12/5 conforme o caminho.
- **Fix:** um único default (sugerido ≥ 50), documentado.

### E17 — `first_user_messages`/`diagnose_pair_sourcing` carregam TODAS as mensagens de usuário na memória
- [ ] corrigido
- **Onde:** [src/storage_conversations.py:93-110](src/storage_conversations.py)
- **O quê:** `query(...).all()` sem limite, chamado por flywheel/diagnóstico/blind-eval. Cresce linearmente com o uso do app para sempre.
- **Fix:** window function (`ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY timestamp)`) ou subquery `MIN(id)` por sessão, com `LIMIT`.

### E18 — Fontes destiladas incluem as "Síntese #N" como se fossem tópicos
- [ ] corrigido
- **Onde:** [src/nanollm/distill.py:247-256](src/nanollm/distill.py) (`source_knowledge_grounded_pairs` ← `get_learning_history`, sem filtro de categoria) — a clusterização do learner já filtra (`learner_synthesis.py:60`), a destilação não.
- **O quê:** resumos meta ("Síntese #12", cruzamentos de domínios) viram pares Q&A "ancorados" com perguntas artificiais sobre um documento interno; também entram no prompt do auto-currículo via `_replenish_curriculum`.
- **Fix:** filtrar `category == "synthesis"` (e `topic` iniciando com "Síntese") nas fontes de destilação e do replenish.

### E19 — `repeat_penalty=1.3` global no motor llama.cpp castiga também o modelo de chat 7B
- [ ] corrigido
- **Onde:** [src/providers.py:93](src/providers.py) e [src/providers.py:159-161](src/providers.py)
- **O quê:** 1.3 é agressivo (default llama.cpp: 1.1); em código/listas/JSON o 7B perde qualidade — penaliza reusar tokens obrigatórios (`{`, `def`, vírgulas). O problema real era o 1.5B degenerar.
- **Fix:** penalidade por MODELO (ex.: 1.3 só p/ o 1.5B; 1.1 p/ o 7B/14B), ou expor por chamada.

### E20 — `NanoCompleteRequest` promete o que o motor não entrega
- [x] corrigido
- **Onde:** [routers/nano.py:26-31](routers/nano.py) (`max_length=4000`, `max_tokens` até 400) vs block_size=256
- **O quê:** contrato da API aceita prompt de 4000 chars e 400 tokens de saída; o motor entrega vazio acima de ~700 chars de prompt (E2) e nunca mais que ~255 tokens de saída. Nenhum campo da resposta indica truncagem.
- **Fix:** após E2, incluir `truncated: true/prompt_tokens_used` na resposta e alinhar os limites do schema.

---

## 🔵 MENORES / OBSERVAÇÕES

- **E21** [src/nanollm/routing.py:46](src/nanollm/routing.py) — `served_by = "nano" if result else "teacher"`: um resultado falsy legítimo (ex.: `False` de um futuro gate binário roteado) seria descartado e recomputado no professor. Hoje só título passa por aqui (truthy sempre); vira bug quando o gate binário for promovido. Usar sentinela `None` explícita.
- **E22** [src/learner.py:786-809](src/learner.py) — `learn_from_web` incrementa `_saved_count` mas não dispara o gatilho de síntese (`% SYNTHESIS_EVERY`) — pode pular um marco de síntese.
- **E23** [src/learner.py:281-305](src/learner.py) — `study_now` não passa pelo dedup in-flight (`_reserve`) nem incrementa `_saved_count`; dois cliques rápidos estudam o mesmo tópico 2×.
- **E24** [src/learner.py:212-222](src/learner.py) — `_already_known`/`is_topic_studied` são chamadas SQLite **síncronas** dentro do event loop (fetchers). Latência pequena, mas é o único lugar do pipeline que fura o padrão `asyncio.to_thread`.
- **E25** [src/nanollm/tokenizer.py:144](src/nanollm/tokenizer.py) — `decode` ignora ids desconhecidos silenciosamente (`b""`). Bom para robustez, ruim para debug: um bug de vocab viraria texto "encolhido" sem sinal. Logar em debug.
- **E26** [src/nanollm/distill.py:41](src/nanollm/distill.py) — `MAX_INPUT_CHARS=300` no treino, mas o blind-eval pergunta com o texto INTEIRO — leve descasamento treino/inferência (o mesmo pecado que o M14.2 diagnosticou).
- **E27** [src/nanollm/data.py:110](src/nanollm/data.py) — `rng.integers(0, len-block-1)` nunca sorteia a última janela válida (off-by-one inofensivo).
- **E28** — a suíte (1731 testes) não cobre NENHUM dos erros críticos acima: todos os caminhos reais (`_default_eval`, `_default_answer_blind_eval`, prompt longo no engine, resume+freeze) são substituídos por fakes nos testes. Cada fix deve entrar com teste que exercite o caminho REAL (mini-checkpoint de verdade, sem LLM).

---

## O que foi testado e está SÓLIDO ✅

Para registro honesto — auditado e aprovado:
- **Backward manual completo** (atenção, LayerNorm, GELU, embedding): conferido contra a matemática; a suíte tem checagem numérica de gradiente.
- **KV cache**: equivalência prefill/step vs forward completo verificada por execução — diff ~1e-8 (learned) e ~1e-10 (ALiBi).
- **Tokenizer BPE**: round-trip perfeito (acentos, emoji, `<|sep|>` literal, vazio); contagem incremental de pares correta; sem injeção de token especial via texto.
- **Quantização int8 por coluna**: matemática correta, `load()` transparente.
- **Higiene de corpus** (segredos, dedup por parágrafo, filtro PT): sólida.
- **`blind_compare`** em si (embaralhamento A/B, parse do veredito com fronteira de palavra): correto — os problemas estão em volta (n, gabarito, split).
- **Pipeline do learner**: locks de LLM, gpu_gate, anti-repetição in-flight, pausa com Ollama fora, detector de stall — desenho maduro, fruto visível das lições anteriores.
