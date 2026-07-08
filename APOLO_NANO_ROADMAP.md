# 🧬 APOLO-NANO — Roadmap da LLM Própria

> Plano vivo da construção da LLM 100% do Leo — **do zero, sem usar nada de ninguém**: sem PyTorch, sem HuggingFace, sem autograd, sem pesos pré-treinados. Cadência igual ao `JARVIS_ROADMAP.md`: **1 incremento por dia**, testado, commitado e mergeado no `main`, com README e memória atualizados. Sem regressões.

**Início:** 2026-07-08 · **Alvo v1 integrada:** 2026-10 · **Alvo do ciclo:** 2027-01 · **Dono:** Leo · **Copiloto:** Claude Code

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

## 7. Itens travados por hardware `🔒 HW`

Sem GPU, ficam fora do alcance deste ciclo:
- **Modelos >30M params** (treino viraria semanas/meses de CPU).
- **Contexto longo** (>512 tokens de bloco — atenção O(T²) em RAM e tempo).
- **Chat de verdade no Nano** (exigiria centenas de M de params + RLHF-like — nem com GPU de entrada).
- **Treino multi-época de corpus grande** (100M+ tokens).

**O multiplicador:** uma GPU de 12–16GB não só destrava o Jarvis (fine-tuning LoRA do 14B) como muda a classe do Nano: 100M+ params treináveis em dias, e o mesmo código NumPy serve de referência/verificação para uma futura versão acelerada.

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
| A | M1 | 1.1 Exportador de corpus | ⬜ |
| A | M1 | 1.2 Limpeza & dedup | ⬜ |
| A | M1 | 1.3 Harness de avaliação | ⬜ |
| A | M1 | 1.4 Decisão dado externo | ⬜ (decisão do Leo) |
| A | M2 | 2.1 Calibração `small` | ⬜ |
| A | M2 | 2.2 Run v1 | ⬜ |
| A | M2 | 2.3 Higiene de runs | ⬜ |
| B | M3 | 3.1 KV cache | ⬜ |
| B | M3 | 3.2 Backend no app | ⬜ |
| B | M3 | 3.3 Primeira tarefa real | ⬜ |
| B | M4 | 4.1 Dataset de tarefa | ⬜ |
| B | M4 | 4.2 Fine-tune de tarefa | ⬜ |
| B | M4 | 4.3 Segunda tarefa | ⬜ |
| C | M5 | 5.1 Otimização de treino | ⬜ |
| C | M5 | 5.2 Quantização int8 | ⬜ |
| C | M5 | 5.3 Corpus 2.0 (auto-retreino) | ⬜ |
| C | M6 | 6.1 Experimento de escala | ⬜ |
| C | M6 | 6.2 Retrospectiva | ⬜ |
| C | M6 | 6.3 Documentação (paper caseiro) | ⬜ |
