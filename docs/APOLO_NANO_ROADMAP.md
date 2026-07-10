# 🧬 APOLO-NANO — Roadmap da LLM Própria

> Plano vivo da construção da LLM 100% do Leo — **do zero, sem usar nada de ninguém**: sem PyTorch, sem HuggingFace, sem autograd, sem pesos pré-treinados. Cadência igual ao `JARVIS_ROADMAP.md`: **1 incremento por dia**, testado, commitado e mergeado no `main`, com README e memória atualizados. Sem regressões.

**Início:** 2026-07-08 · **Alvo v1 integrada:** 2026-10 · **Alvo do ciclo:** 2027-01 · **Dono:** Leo · **Copiloto:** Claude Code

> 📄 **Fecho do 1º ciclo (2026-07-09):** o "paper caseiro" [`APOLO_NANO.md`](APOLO_NANO.md) consolida arquitetura, dados, treino e resultados **medidos**. Fases A e B (motor + corpus + treino v1 + KV cache + integração) entregues e testadas. M4 (tarefas) confirmou empiricamente o teto 🔒 HW: um modelo de 3,4M no CPU gera PT plausível mas não executa tarefas ancoradas — a qualidade em tarefa precisa de GPU. O pipeline soberano está completo e pronto para reescalar.

---

## 1. Visão — o que é "Apolo-Nano pronto"

Um modelo de linguagem **inteiramente do Leo** — tokenizer, arquitetura, pesos, dados e pipeline de treino — que:

1. **Nasce e vive na sua máquina.** Treina no Ryzen (CPU-only), gera offline, zero nuvem.
2. **É produto, não brinquedo de gaveta.** Integrado ao Apolo AI como backend/ferramenta para tarefas leves reais (títulos de conversa, autocomplete, classificação) — o 14B continua sendo o cérebro do chat.
3. **Aprende com o que o Apolo aprendeu.** O corpus vem primeiro do conhecimento que o próprio Apolo acumulou (sínteses, episódios, docs) — soberania até nos dados.
4. **Cresce com o hardware.** A arquitetura e o pipeline já estão prontos para escalar (7M → 30M → 100M+ params) no dia em que houver GPU.

**O teto honesto, dito sem rodeio:** um modelo treinável nesse CPU (~7M params, dezenas de milhões de tokens) gera português coerente em frases curtas e aprende padrões do SEU domínio — ele **não** conversa como o Qwen 14B e nunca vai, nesta máquina. O valor está em três coisas: soberania real (pesos seus), laboratório de fundamentos (você entende cada peça), e utilidade em tarefas pequenas onde um modelo minúsculo e instantâneo ganha de um gigante lento.

---

## 2. Princípios que guiam o projeto

1. **Do zero de verdade.** Nenhuma lib de ML, nenhum peso alheio, nenhum autograd. NumPy + Python puro. Se uma otimização exigir dependência nova, ela é marcada e decidida explicitamente (nada entra em silêncio).
2. **Realismo de CPU.** Todo épico tem orçamento de tokens/segundo medido, não chutado. Medições atuais: ~700 tok/s (preset `nano` 0.9M), a validar no `small` 7M. Treinos longos SEMPRE resumíveis (`--resume`) — a máquina é sua e você a usa para outras coisas.
3. **Corretude provada, não presumida.** O backprop tem gradient checking numérico; toda peça nova do motor entra com prova equivalente. A loss caindo não basta — o gradiente tem que estar matematicamente certo.
4. **Avaliação antes de ambição.** Não se escala o que não se mede. Perplexity de validação + amostras fixas + relatório reproduzível vêm ANTES do treino longo.
5. **Dados com procedência.** Corpus soberano primeiro (o que o Apolo sabe + docs do Leo). Dado externo (ex.: Wikipedia-PT) só com decisão explícita do Leo, documentada aqui.
6. **Honestidade sobre o teto.** Itens que exigem GPU ficam `🔒 HW`. Não fingimos que dá para treinar um chatbot em CPU.

---

## 3. Estado atual (mapa real — 2026-07-08)

### O que já existe e funciona (commit `b522444`)
- **Motor completo em `src/nanollm/`** (~1.100 linhas, nenhum arquivo >800):
  - `tokenizer.py` — BPE byte-level treinável em Python puro (contagem incremental de pares; acentos/emoji/código sem `<unk>`); treinou vocab 2048 em 6,7s.
  - `layers.py` + `model.py` — GPT decoder-only pré-LN (atenção causal multi-head, GELU, LayerNorm) com **forward E backward manuais** em NumPy; geração com temperatura/top-k; checkpoints `.npz` com config embutida.
  - `optim.py` — Adam + warmup/cosine + grad clip global, com estado persistente (resume fiel).
  - `data.py` / `train.py` / `generate.py` — CLIs de corpus, treino resumível (presets `nano`/`mini`/`small`) e geração.
- **40 testes** (suíte do repo: 931 verdes), incluindo gradient checking float64 de todas as camadas, teste de causalidade da atenção e overfit determinístico.
- **Smoke real validado no Ryzen:** 0.94M params, 300 passos nos docs do repo, loss 7.6→4.9, val 6.39→5.69, `--resume` sem corromper o Adam, geração com a cara do corpus.

### Forças
- Backprop provado — dá para mexer no motor com rede de segurança.
- Pipeline ponta a ponta já fecha o ciclo (corpus → treino → geração).
- O Apolo já tem a MATÉRIA-PRIMA do corpus: base de conhecimento (FTS/RAG), sínteses, episódios — tudo em SQLite local.

---

## 4. Limitações honestas (priorizadas)

| # | Limitação | Impacto | Onde |
|---|-----------|---------|------|
| N1 | **Corpus minúsculo.** 42k tokens (docs do repo). Um `small` de 7M params pede DEZENAS de milhões de tokens para não decorar. | Fundamental — bloqueia o treino v1 | dados |
| N2 | **Sem harness de avaliação.** Só temos loss/val loss. Sem perplexity comparável entre runs, sem amostras fixas, sem relatório — não dá para saber se um treino foi melhor que outro. | Alto | `src/nanollm/` |
| N3 | **Geração O(T²) sem KV cache.** Cada token novo re-processa a sequência inteira → geração longa é lenta demais para produto. | Alto (bloqueia integração séria) | `model.py` |
| N4 | **Velocidade de treino no CPU.** ~700 tok/s no 0.9M; o `small` 7M será ~3–8× mais lento. Treino decente = dias de máquina. | Alto | `🔒 HW` parcial |
| N5 | **Só modela texto cru.** Base LM puro: completa texto, não segue instrução, não responde pergunta. Utilidade de produto exige formato. | Médio-alto | dados/treino |
| N6 | **Zero integração com o app.** Nenhum endpoint, backend ou ferramenta usa o Nano. | Médio-alto (é o objetivo declarado) | app |
| N7 | **16GB de RAM compartilhados.** Treino + Ollama/llama.cpp + app ao vivo competem; treinar junto com o 14B rodando pode travar a máquina (lição já vivida no learner). | Médio | infra |
| N8 | **Tokenizer treina single-thread.** 6,7s para 123k chars ok; para 100MB+ de corpus vai doer (minutos/horas). | Baixo-médio | `tokenizer.py` |
| N9 | **Sem quantização/otimização de inferência.** float32 sempre; nada de int8, nada de batch de geração. | Baixo (até a integração) | motor |

---

## 5. Os 6 pilares

- **D1 · Dados Soberanos** — exportador do conhecimento do Apolo → corpus; limpeza/dedup; decisão sobre dado externo. *(N1)*
- **D2 · Avaliação** — perplexity comparável, amostras fixas, relatório por run; "está melhorando?" com número. *(N2)*
- **D3 · Motor & Performance** — KV cache, otimizações NumPy/BLAS, quantização de inferência, tokenizer mais rápido. *(N3, N8, N9)*
- **D4 · Treino & Escala** — treinar v1 `small`, disciplina de runs (config/curva/relatório), escalar contexto e params conforme dados/HW. *(N4)*
- **D5 · Capacidades** — do texto cru ao formato útil: fine-tune de tarefa (títulos, classificação) com dados gerados localmente. *(N5)*
- **D6 · Integração & Produto** — backend/ferramenta no app, endpoint, UI, gate de recursos (não competir com o 14B). *(N6, N7)*

---

## 6. Calendário (6 meses, M1–M6)

> Cada mês tem 2–4 épicos; cada épico vira incrementos diários pequenos, testados e verdes. "DoD" = Definition of Done.

### 🗓️ FASE A — DADOS & MEDIÇÃO (Meses 1–2)
*Primeiro a matéria-prima e a régua. Treinar sem corpus e sem métrica é queimar CPU.*

#### **Mês 1 (Jul 2026) — Corpus Soberano & Harness** *(D1 + D2)*
- ✅ Épico 0 — **Motor do zero** (ENTREGUE 2026-07-08, veio antes do plano): tokenizer + GPT + backprop manual + Adam + treino resumível + gradcheck.
- Épico 1.1 — **Exportador de corpus do Apolo:** `python -m src.nanollm.corpus_export` — varre o SQLite (tópicos aprendidos/sínteses, episódios, base de conhecimento FTS) e os docs do Leo (pasta autorizada) → `data/nanollm/corpus/*.txt` com procedência no nome. Filtros: só PT, tamanho mínimo, sem segredos (.env/credenciais NUNCA).
- Épico 1.2 — **Limpeza & dedup:** normalização (espaços, mojibake), dedup por hash de parágrafo (reusar a ideia do `curator.py`), relatório de composição (quantos tokens de cada fonte).
- Épico 1.3 — **Harness de avaliação:** `python -m src.nanollm.eval` — perplexity no val fixo + geração das MESMAS 10 amostras-sonda (prompts fixos versionados) + relatório JSON/markdown por run (config, tokens vistos, ppl, amostras). Comparável entre runs.
- Épico 1.4 — **Decisão de dado externo:** com o corpus soberano medido, Leo decide: fica só com ele (menor, 100% seu) ou soma Wikipedia-PT/domínio público (maior, procedência documentada). O plano segue com qualquer um.
- **DoD M1:** corpus soberano ≥ 2M tokens com relatório de composição + `eval` reproduzível rodando em qualquer checkpoint.

#### **Mês 2 (Ago 2026) — Treino v1 do `small`** *(D4)*
- Épico 2.1 — **Calibração:** medir tok/s real do `small` (7M) na máquina; escolher batch/contexto que caibam em RAM COM o app rodando; definir orçamento (ex.: treinar só de madrugada — integrar com o scheduler do Apolo?).
- Épico 2.2 — **Run v1:** treino longo resumível (dias, em sessões), curva de loss/ppl registrada, checkpoints periódicos; regra de parada honesta (ppl estabilizou = para, não romantiza).
- Épico 2.3 — **Higiene de runs:** cada run tem id, config, seed, corpus-hash e relatório do harness; comparação v1 vs smoke documentada aqui.
- **DoD M2:** **Apolo-Nano v1** — checkpoint `small` com ppl de validação documentada e amostras-sonda gerando frases PT majoritariamente gramaticais.

### 🗓️ FASE B — PRODUTO (Meses 3–4)
*O modelo existe; agora ele trabalha.*

#### **Mês 3 (Set 2026) — Geração rápida & Integração** *(D3 + D6)*
- Épico 3.1 — **KV cache:** geração incremental (cache de K/V por camada) — de O(T²) para O(T) por token; teste de equivalência exata com o caminho sem cache (mesma seed → mesmos tokens).
- Épico 3.2 — **Backend no app:** `src/nanollm/engine.py` (carrega checkpoint 1x, gera thread-safe) + endpoint `POST /api/nano/complete` + entrada no painel Saúde (`nano_ready`, params, ppl do checkpoint). Gate de recursos: Nano NUNCA roda durante inferência do 14B (reusar o padrão do GpuGate/serialização do learner).
- Épico 3.3 — **Primeira tarefa real:** uma função do app servida pelo Nano em produção — candidata nº1: **título automático de conversa** (curto, tolerante a imperfeição, hoje gasta o modelo grande). Fallback para o LLM grande se o Nano falhar.
- **DoD M3:** uma feature real do Apolo roda no Nano, com latência <1s e fallback seguro.

#### **Mês 4 (Out 2026) — Capacidade dirigida** *(D5)*
- Épico 4.1 — **Dataset de tarefa:** gerar pares (entrada→saída) LOCALMENTE para as tarefas-alvo (título, classificação de setor, tags) — o próprio app tem os dados históricos (conversas + títulos, tópicos + setores do `topics.py`).
- Épico 4.2 — **Fine-tune de tarefa:** continuar o treino do v1 nos dados de tarefa (formato com separadores especiais no tokenizer); avaliar contra baseline (o título do Nano vs o título do 14B, julgado às cegas).
- Épico 4.3 — **Segunda tarefa no app** (a que a avaliação disser que está madura).
- **DoD M4:** Nano executa 2 tarefas reais com qualidade medida ≥ "aceitável às cegas" em 70% dos casos.

### 🗓️ FASE C — ESCALA & RETRO (Meses 5–6)
*Crescer o que provou valor.*

#### **Mês 5 (Nov 2026) — Performance & corpus 2.0** *(D3 + D1)*
- Épico 5.1 — **Otimização de treino:** perfis de CPU (onde o tempo vai), threads do BLAS, micro-otimizações NumPy; meta: +30% tok/s sem dependência nova (qualquer proposta de dependência = decisão explícita do Leo).
- Épico 5.2 — **Quantização de inferência int8** (pesos quantizados na carga, matmul float com dequant) — checkpoint 4× menor, inferência mais leve; teste de degradação de ppl (<2%).
- Épico 5.3 — **Corpus 2.0:** o Apolo aprende todo dia → o corpus cresce sozinho; re-export periódico + re-treino incremental (continuar do checkpoint com dados novos).
- **DoD M5:** pipeline de "o Apolo estuda → o Nano re-treina" rodando com um comando.

#### **Mês 6 (Dez 2026) — Escala honesta & retrospectiva** *(D4)*
- Épico 6.1 — **Experimento de escala:** com tudo medido, treinar o MAIOR modelo que a máquina aguenta de verdade (mini-médio ~15–30M? só o harness dirá se vale) OU dobrar contexto — decidir pelo dado, não pelo ego. `🔒 HW` além disso.
- Épico 6.2 — **Retrospectiva:** o que o Nano aprendeu a fazer, ppl inicial→final, custo real em horas de CPU; decisão de GPU informada por números do SEU caso.
- Épico 6.3 — **Documentação completa** (o "paper caseiro" do Apolo-Nano: arquitetura, dados, treino, resultados).
- **DoD M6:** relatório final v1→v2 e plano do próximo ciclo (com ou sem GPU).

---

## 7. Estratégias no hardware atual — **DESTRAVADO** (Leo, 2026-07-10)

Doutrina nova: em vez de listar o que a GPU destravaria, listamos **o que fazemos AGORA** para o cérebro próprio assumir, aceitando as restrições como engenharia:

- **Destilação de tarefa estreita (o caminho principal):** o modelo pequeno não faz chat geral, mas **imita o Qwen** em tarefas de alta frequência do Leo (título, tags, setor, roteamento, autocomplete, gates). Geramos rótulos com o Qwen → treino supervisionado → o Nano assume aquela fatia. Um modelo de 3–30M **crava tarefa estreita**; é aí que a soberania começa.
- **Escala incremental de madrugada:** crescer 3,4M → 10–30M treinando com a máquina ociosa (rotinas do M10 + gate de recursos). Lento e de graça; cada salto amplia a cobertura. Multi-época de corpus grande fica para a GPU, mas o corpus destilado é enxuto.
- **iGPU via Vulkan (para o MOTOR, não o treino NumPy):** o `llama.cpp` compilado com `-DGGML_VULKAN=ON` **usa a Vega 7** para acelerar a inferência do Qwen (offload de camadas). Não acelera o treino NumPy do Nano (isso segue CPU), mas tira carga do motor que serve o chat hoje.
- **Contexto:** mantém-se curto (256–512) por enquanto; atenção O(T²) é cara em CPU. Estende quando houver folga/GPU.

**A iGPU para TREINO NumPy segue descartada (medido 2026-07-09):** o gargalo é banda de RAM DDR4 (threads 4→12 e batch 12→48 mudam ~5%); a Vega divide a mesma banda, e usá-la exigiria ROCm/DirectML/OpenCL (contra o princípio 1 ou semanas de trabalho). Por isso o treino é CPU e o caminho é **destilação enxuta**, não modelos gigantes. A Vega entra só via Vulkan no **motor** (llama.cpp), não no treino.

**A GPU dedicada continua sendo o acelerador** (100M+ params em dias, LoRA de modelos maiores) — mas agora **acelera** o que já andamos, em vez de dar a partida.

---

## 8. Métricas de sucesso

- **Soberania:** zero dependência de ML adicionada; pesos, tokenizer e dados com procedência 100% rastreável.
- **Corretude:** gradcheck verde em toda mudança do motor; KV cache bit-idêntico ao caminho lento.
- **Aprendizado:** perplexity de validação CAINDO entre runs (registrada na tabela de progresso).
- **Produto:** ≥2 features reais do Apolo servidas pelo Nano com fallback, latência <1s, sem travar a máquina.
- **Processo:** todo run tem relatório; nenhum treino "perdido" (tudo resumível e documentado).

---

## 9. Cadência de trabalho

Igual ao plano-mãe (`JARVIS_ROADMAP.md` §9): incremento diário pequeno → testes verdes → README/memória → commit no branch → fast-forward no `main` → push. Regra extra deste projeto: **treino longo nunca bloqueia incremento** — o treino roda em background/madrugada com `--resume`; o incremento do dia é sempre código/dados/avaliação.

---

## 10. Progresso

| Fase | Mês | Épico | Status |
|------|-----|-------|--------|
| A | M1 | Épico 0 — Motor do zero | ✅ **entregue 2026-07-08** (`b522444`) — tokenizer BPE + GPT backprop manual + Adam + treino resumível + gradcheck float64; smoke 0.94M no CPU: loss 7.6→4.9, ~700 tok/s, resume e geração validados. Suíte 931 |
| A | M1 | 1.1 Exportador de corpus | ✅ **2026-07-09** — `src/nanollm/corpus_export.py`: varre os bancos do Apolo em modo SOMENTE LEITURA (learned_topics + episodes no apolo.db, knowledge no local_knowledge.db, `--supabase-env` puxa a base da nuvem via cliente do app, `--docs` pastas extras). Um .txt por fonte com registros separados por `DOC_SEPARATOR` (o `data.read_corpus` entende) + `report.json` de composição. 16 testes |
| A | M1 | 1.2 Limpeza & dedup | ✅ **2026-07-09 (junto do 1.1)** — normalização NFC/espaços, **linhas com cara de segredo nunca saem** (api key/senha/token/JWT/DSN/hex longo), filtro PT por razão de stopwords distintivas (`--keep-non-pt` desliga; auditado nos dados reais: os 409 rejeitados eram EN de verdade), dedup GLOBAL por hash de parágrafo. **Números reais do 1º export:** 849 tópicos → 439 PT mantidos; Supabase 832 → 104 (4.337 parágrafos duplicados removidos — a base da nuvem repete as sínteses locais); episódios ~0 (memória episódica recente). **Corpus soberano v0: 547 docs, 889k chars ≈ 236k tokens (vocab 4096, 3.76 chars/token)** — abaixo da DoD de 2M; a decisão do Épico 1.4 (dado externo) ficou mais importante |
| A | M1 | 1.3 Harness de avaliação | ✅ **2026-07-09** — `src/nanollm/eval.py`: (1) **perplexity determinística** em janelas SEQUENCIAIS fixas do val.npy (sem sorteio — mesmo val = mesmo número, comparável entre runs); (2) **10 sondas versionadas** (`PROBES_V1`, seed fixa — nunca editar lista publicada, criar V2); (3) relatório `eval_report.json` + histórico `evals.jsonl` por checkpoint. 7 testes (ppl≈vocab em modelo virgem, ppl cai 3× com treino, determinismo, histórico). **BASELINE OFICIAL: ckpt_real nano 1.47M @ passo 600 → val ppl 388.13** (nll 5.96); sondas já mostram estrutura PT ("O Apolo é uma ferramenta que…") |
| A | M1 | 1.4 Decisão dado externo | ✅ **2026-07-09 (padrão)** — apresentadas as 3 opções (só soberano / Wikipedia-PT / híbrido); Leo respondeu "siga o plano" → vale o princípio nº 5: **só corpus soberano até decisão explícita em contrário**. Consequência: v1 dimensionado pro corpus real (236k tokens), e o corpus cresce com o aprendizado diário do Apolo. Reabrir quando Leo quiser escala |
| A | M2 | 2.1 Calibração | ✅ **2026-07-09** — medido na máquina real (app no ar): `nano` 1,47M ≈ 4–5k tok/s · `mini` 3,39M ≈ 2k tok/s · `small` 6,91M ≈ 930 tok/s. Com 236k tokens, **v1 = `mini`** (small decoraria mais custando 2×). RAM ok nos 3. LIÇÃO de ferramenta: `\| Select-Object -First N` MATA processo nativo no meio (pipe fechado) — calibrações iniciais morreram antes do save por isso, não por bug do trainer |
| A | M2 | 2.2 Run v1 | ✅ **2026-07-09 — APOLO-NANO v1 EXISTE.** `mini` 3,39M params, 5.000 passos (~11,5M tokens ≈ 50 épocas do corpus soberano), ~90 min a ~2,1k tok/s com threads BLAS=4 (app no ar o tempo todo). **val ppl 157,96 (nll 5,06) vs baseline 388,13 — 2,46× melhor.** Curva didática de overfit: val fez fundo ~5,05 no passo ~1.800-2.000 e subiu a 7,09 no fim (train loss 0,32 = decoreba) — `model_best.npz` preservou o melhor ponto e o eval usa ele. Sondas geram frases PT reais ("O Apolo é projetado para criar um estudo adequado usando o uso básico de APIs Python…"). Checkpoint: `data/nanollm/ckpt_v1` |
| A | M2 | 2.3 Higiene de runs | ✅ **2026-07-09 (mecanismo)** — todo run tem: `state.json` (passo/best_val), config embutida no `.npz`, `eval_report.json` + histórico `evals.jsonl` (data/params/passo/ppl por linha), e a comparação documentada AQUI. **EXPERIMENTO máquina-dedicada (pergunta do Leo):** batch 12/threads 4 → 2.113 tok/s; batch 32/12 threads → 2.137; batch 48/12 threads → 2.213 (**+5%**). Conclusão MEDIDA: o gargalo é banda de RAM DDR4, não núcleos — reservar o PC não acelera este modelo; iGPU Vega 7 divide a mesma banda (ver §7). **🏁 M2 FECHADO — DoD batida (v1 com ppl documentada + frases PT)** |
| B | M3 | 3.1 KV cache | ✅ **2026-07-09** — geração incremental O(T)/token: `CausalSelfAttention.step` (query única sobre K/V acumulado, sem máscara), `forward(keep_kv=True)` faz o prefill, `GPT._prefill/_step/generate_fast` orquestram; `_sample` compartilhado entre os 2 caminhos (mesma seed → mesmos sorteios). Sem janela deslizante no caminho rápido (cache tem posição absoluta): para limpo ao encher o block_size. **Equivalência PROVADA em teste**: logits allclose 1e-5 posição a posição + greedy bit-idêntico + gradcheck de regressão (treino intocado). **MEDIDO no v1 real: 79 → 605 tok/s (7,7×), 150 tokens em 0,25s** — meta de <1s do produto batida. generate.py CLI já usa o caminho rápido. 8 testes |
| B | M3 | 3.2 Backend no app | ✅ **2026-07-09** — o Nano virou serviço do Apolo: `src/nanollm/engine.py` (`NanoEngine`: checkpoint lazy na 1ª completion, gerações SERIALIZADAS por lock — o modelo tem caches internos, não é reentrante; `info()` com params/ppl do eval_report; env `NANO_CKPT`, padrão ckpt_v1) + `routers/nano.py` (`GET /api/nano/status`, `POST /api/nano/complete` com validação Pydantic, roda em `to_thread` e marca **atividade de usuário no GpuGate** — o learner espera pelo Nano, nunca o contrário) + wiring em runtime/app.py + bloco `nano` no `/api/health` (`features.nano`). **Verificado AO VIVO** (instância real do app): status 200 com ppl 157.96, completion de 40 tokens em 536ms, health reportando. 12 testes |
| B | M3 | 3.3 Primeira tarefa real | ✅ **2026-07-09 — 🏁 M3 FECHADO.** Título de conversa: **o Nano tenta PRIMEIRO, o LLM grande é fallback garantido** (`generate_session_title` em src/chat_common.py). `src/nanollm/tasks.py`: prompt como continuação "Tópico:" (padrão do corpus — modelo base não segue instrução) + **portão de qualidade determinístico em 2 camadas**: forma (`title_ok`: tamanho/palavras/loop degenerativo/markdown/proporção de letras) E relevância (`title_relevant`: 1+ palavra de conteúdo compartilhada com a mensagem, radical de 4 chars sem acento). HONESTIDADE MEDIDA no v1 real: sem o cheque de relevância, 3/6 títulos passavam BEM-FORMADOS PORÉM ERRADOS ("AWS S3" p/ pergunta de asyncio); com ele, **0/6 passam → 100% fallback hoje**. É o comportamento correto: o portão protege o produto, e a taxa de aprovação vira a MÉTRICA do fine-tune 4.2 (meta: ≥70%). nano_session_title NUNCA levanta exceção. 17 testes (29 c/ regressão do título antigo) |
| B | M4 | 4.1 Dataset de tarefa | ✅ **2026-07-09** — `src/nanollm/taskdata.py`: destilação SOBERANA — os títulos que o LLM grande já produziu no banco viram dataset de fine-tune do Nano. Fonte principal: `learned_topics.summary → .topic` (o 14B destilou o título); + os títulos de conversa reais (`session_meta`). Formato = MESMO template da inferência (`{context}\n\nTópico: {title}`, casado com `tasks.title_prompt` num teste). Higiene decisiva (medida): 1º export deu 288 pares mas com LIXO de scraping no contexto (`**fonte** URL:...`) e títulos em inglês (queries do web_search) — treinar assim ensinaria lixo→título. Adicionados `_prose_context` (tira URL/markdown/separador → prosa, a distribuição real da inferência) e `_looks_english` (barra query inglesa). **Resultado limpo: 201 pares PT ≈ 15k tokens**, reusa o tokenizer do ckpt_v1 (fine-tune não troca vocab), split train/val determinístico, `pairs.jsonl` auditável. 6 testes |
| B | M4 | 4.2 Fine-tune de tarefa | 🔨 **feito, mediu, HONESTO: 0/6 → 1/6 (abaixo da DoD 70%).** `--init-from ckpt_v1` + 201 pares de título, lr 2e-4. Fine-tune FUNCIONA mecanicamente: train loss 2.09→0.11 e os títulos ganharam FORMA de título ("GitHub Actions — Docker Build", "FastAPI — Pandas e Validação" — antes era "AWS S3" solto). Mas só 1/6 ancorou na pergunta → o portão de relevância barra os outros 5 (fazendo o trabalho dele). **Causa-raiz (não é bug, é teto):** (a) descasamento de distribuição — treinei em `prosa enciclopédica → título`, mas a inferência recebe `pergunta → título`; o modelo aprendeu a FORMA, não a ANCORAGEM; (b) 201 pares / 13,7k tokens é pouco e o modelo decora rápido (val subiu 4.67→5.54 já no passo 400 = overfit; model_best pegou o passo 200); (c) 3,39M params é pouco para generalizar ancoragem. Sistema correto: o fallback protege a produção. Melhora real exige mais dados de `pergunta→título` (temos só 4 conversas reais) ou modelo maior (🔒 HW). NÃO promovido a default |
| B | M4 | 4.3 Classificação de setor | 🔨 **feito, medido, HONESTO: 31,4% (marginal, NÃO production-worthy).** Pivô do Leo: classificação FECHADA (9 setores, 471 pares via `build_sector_dataset`/`collect_sector_pairs`, rotulados por `classify_sector`; `tasks.nano_classify_sector` casa a saída por prefixo). Held-out 70 exemplos: **model_best 31,4%** (baseline classe-majoritária 22,9%, aleatório 11,1%), model.npz treinado 17,1% (overfit piorou). Bate o aleatório mas mal encosta na majoritária, e a tabela por classe REVELA o porquê: acerta só as classes frequentes (backend 11/16, data_ml 6/11) e ZERA em frontend/mobile/science/devops → aprendeu a chutar a cabeça da distribuição, não a classificar. **Conclusão empírica (2ª tarefa a confirmar):** 3,39M params + ~470 exemplos + CPU não generalizam mapeamento contexto→rótulo. NÃO integrado (seria pior que o classify_sector determinístico que já existe). DoD do M4 (≥70%) NÃO batida — é o teto 🔒 HW, previsto no §1/§7 |
| C | M5 | 5.1 Otimização de treino | ⬜ |
| C | M5 | 5.2 Quantização int8 | ⬜ |
| C | M5 | 5.3 Corpus 2.0 (auto-retreino) | ⬜ |
| C | M6 | 6.1 Experimento de escala | ⬜ |
| C | M6 | 6.2 Retrospectiva | ✅ **2026-07-09** — o §4/§6/§8 do [`APOLO_NANO.md`](APOLO_NANO.md) É a retrospectiva: ppl inicial→final (388→158), custo real (~90 min CPU), as 2 tarefas medidas e a decisão de GPU informada por números do caso real do Leo. Costurado ao plano-mãe do Ano 2 (M13 entregue, M14.2 medido) |
| C | M6 | 6.3 Documentação (paper caseiro) | ✅ **antecipado 2026-07-09** — [`APOLO_NANO.md`](APOLO_NANO.md): arquitetura, dados soberanos, treino, integração e os resultados MEDIDOS das 2 tarefas + o teto de HW. Fecha o 1º ciclo com honestidade |
