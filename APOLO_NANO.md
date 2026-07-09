# 🧬 Apolo-Nano — Uma LLM construída do zero, sem usar nada de ninguém

> O "paper caseiro" do Apolo-Nano. Documenta a LLM própria do Leo: arquitetura, dados, treino, resultados **reais e medidos**, e o teto honesto. Escrito em 2026-07-09, ao fim do primeiro ciclo (Fases A e B do [`APOLO_NANO_ROADMAP.md`](APOLO_NANO_ROADMAP.md)).

---

## 1. O que é

O **Apolo-Nano** é um modelo de linguagem (LLM) escrito **inteiramente do zero** em `src/nanollm/`, sob uma única regra inegociável (pedido do Leo): **do zero, sem usar nada de ninguém**.

- **Sem PyTorch, sem TensorFlow, sem HuggingFace.** Nenhuma biblioteca de machine learning.
- **Sem autograd.** A retropropagação (o cálculo que faz a rede aprender) é escrita à mão, derivada por derivada.
- **Sem pesos pré-treinados.** Nenhum parâmetro veio de outro modelo. Tudo foi aprendido do zero, no conhecimento do próprio Apolo.
- **Só NumPy + Python puro.** Álgebra de matrizes e mais nada.

O tokenizer é do Leo, a arquitetura é do Leo, os pesos são do Leo, os dados são do Leo. Soberania de ponta a ponta.

---

## 2. Arquitetura

Um transformer **GPT decoder-only** no estilo GPT-2, com todas as peças implementadas manualmente:

| Peça | Arquivo | O que é |
|------|---------|---------|
| **Tokenizer BPE byte-level** | `tokenizer.py` | Aprende a fundir bytes UTF-8 do corpus. Qualquer texto (acentos, emoji, código) é representável, sem `<unk>`. |
| **Embeddings de token + posição** | `model.py` | Cada token e cada posição viram um vetor aprendível. |
| **Atenção causal multi-head** | `layers.py` | O mecanismo que deixa cada token "olhar" para os anteriores. Forward **e** backward à mão. |
| **LayerNorm + GELU + MLP** | `layers.py` | Normalização e as camadas densas, com seus gradientes manuais. |
| **Cabeça de linguagem** | `model.py` | Projeta de volta para o vocabulário e prevê o próximo token. |
| **Adam + warmup/cosine + grad clip** | `optim.py` | O otimizador que ajusta os pesos, do zero. |
| **KV cache** | `layers.py` + `model.py` | Geração incremental O(T) por token — 7,7× mais rápida. |

**A prova de que a matemática está certa:** `tests/test_nanollm_grad.py` compara cada gradiente analítico com uma aproximação numérica (diferença finita, float64). Se qualquer derivada de qualquer camada estivesse errada, o teste quebraria. Está verde.

---

## 3. Dados — corpus soberano

O corpus veio **do que o próprio Apolo já sabia** — nada externo. O exportador (`corpus_export.py`) varre os bancos locais em modo somente-leitura e aplica higiene:

- **Fontes:** tópicos aprendidos, memória episódica, base de conhecimento (local + Supabase).
- **Segurança:** linhas com cara de segredo (chave de API, senha, token, JWT) **nunca** saem.
- **Qualidade:** filtro de português, remoção de lixo de scraping (URLs, markdown), dedup por parágrafo.

**Resultado:** 547 documentos ≈ **236 mil tokens** (vocabulário de 4096). Honestamente pequeno — mas 100% soberano e rastreável.

---

## 4. Treino

| | Valor |
|--|--|
| Modelo (v1) | 3,39M parâmetros (preset `mini`) |
| Corpus | 236k tokens, ~50 épocas |
| Hardware | Ryzen 5 4600G, CPU-only, 16GB |
| Velocidade | ~2.100 tokens/s (BLAS em 4 threads, app no ar) |
| Tempo | ~90 minutos |
| Perplexity de validação | **157,96** (baseline sem treino: 388,13 — **2,46× melhor**) |

O treino é **resumível** (`--resume`) e cada run gera um relatório reproduzível (`eval.py`: perplexity determinística + 10 sondas fixas). O modelo gera português com a cara do corpus:

> *"O Apolo é projetado para criar um estudo adequado usando o uso básico de APIs Python..."*

**Um experimento que respondeu uma dúvida real do Leo** ("usar mais a GPU / deixar o PC parado ajuda?"): medimos batch 12→48 e threads 4→12 → ganho de **~5%**. O gargalo do treino é a **banda de memória RAM**, não os núcleos. A GPU integrada (Vega 7) divide essa mesma banda e não tem stack de software viável no Windows. Conclusão medida: reservar o PC não acelera; a única alavanca real é uma **GPU dedicada**.

---

## 5. Integração ao app

O Nano não ficou na gaveta — virou serviço do Apolo:

- `POST /api/nano/complete` e `GET /api/nano/status` — o modelo próprio servindo texto, com carregamento lazy e gerações serializadas.
- **Gate de recursos:** a geração do Nano marca atividade de usuário no GpuGate — o aprendizado de fundo espera pelo Nano, nunca o contrário.
- **Cartão 🧬 Apolo-Nano** no painel Saúde: status, parâmetros, perplexity, selo de soberania.
- **Título de conversa Nano-first:** o Nano tenta gerar o título primeiro; o LLM grande é fallback garantido, com um portão de qualidade determinístico no meio.

---

## 6. Resultados em tarefas — a parte honesta

O objetivo era o Nano **fazer tarefas reais** do app. Testamos duas, com método (held-out, baselines):

| Tarefa | Resultado | Baseline | Veredito |
|--------|-----------|----------|----------|
| **Título de conversa** (aberta) | 1/6 passam no portão | 0/6 (v1 cru) | Ganhou forma de título, mas não ancora na pergunta |
| **Classificação de setor** (9 classes) | 31,4% de acurácia | 22,9% (classe majoritária) · 11,1% (aleatório) | Bate o aleatório, mal encosta na majoritária |

**A conclusão empírica, sem maquiagem:** um modelo de 3,39M de parâmetros, treinado em ~470 exemplos num CPU, **gera português plausível mas não executa tarefas ancoradas de forma confiável.** Na classificação, ele aprendeu a chutar as classes frequentes (backend, data/ML) e zerou nas raras — decorou a cabeça da distribuição, não aprendeu a mapear.

Isso **não é um bug**. É o teto de hardware que o roadmap marcou como `🔒 HW` desde a primeira linha. A régua funcionou: o portão de qualidade protege a produção (cai no fallback), e a avaliação nos disse a verdade em vez de deixar passar lixo.

---

## 7. O que ficou construído (a conquista durável)

O valor deste projeto nunca foi o tamanho do modelo — foi o **stack inteiro, do zero, testado e soberano**:

- ✅ Tokenizer BPE, transformer, backprop manual **provado por gradiente numérico**
- ✅ Adam, treino resumível, KV cache (7,7×)
- ✅ Harness de avaliação (perplexity + sondas), pipeline de destilação de dados
- ✅ Fine-tune com warm-start, dataset de tarefa a partir do banco
- ✅ Integração ao app (endpoints, painel, título com fallback)
- ✅ **~90 testes novos, suíte verde (1.145), ~16 commits**

O Leo tem uma LLM que entende de ponta a ponta, com pesos que são dele. Nenhuma linha veio de terceiros.

---

## 8. O teto e o caminho à frente

A qualidade em tarefas está limitada por **escala** — e escala, neste projeto, tem um nome: **GPU dedicada**.

- **Hoje (CPU):** modelo ~3M, corpus ~250k tokens, tarefas beiram o baseline.
- **Com GPU de entrada (12–16GB):** modelos 30× maiores em dias, corpus de milhões de tokens, e o mesmo código NumPy vira a referência de verificação de uma versão acelerada. Destrava também o fine-tune LoRA do 14B (o "Apolo com personalidade nos pesos").

O pipeline está pronto para esse dia. Nada aqui precisa ser refeito — só reescalado.

---

## 9. Como usar

```bash
# 1. Exportar o conhecimento do Apolo como corpus (read-only, com higiene)
python -m src.nanollm.corpus_export --supabase-env .env --out data/nanollm/corpus

# 2. Tokenizar
python -m src.nanollm.data --corpus data/nanollm/corpus --out data/nanollm

# 3. Treinar (resumível com --resume)
python -m src.nanollm.train --data data/nanollm --out data/nanollm/ckpt --preset mini --steps 5000

# 4. Avaliar (perplexity + sondas)
python -m src.nanollm.eval --ckpt data/nanollm/ckpt --data data/nanollm

# 5. Gerar texto
python -m src.nanollm.generate --ckpt data/nanollm/ckpt --prompt "O Apolo é"
```

---

*Apolo-Nano é laboratório de soberania e fundamentos — não um substituto do modelo de chat. Foi essa a expectativa desde o início, e é essa a entrega: uma LLM inteiramente própria, honestamente medida.*
