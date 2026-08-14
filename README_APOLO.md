# ☀️ A.P.O.L.O.

**Assistente pessoal de IA que roda 100% na sua máquina — incluindo uma LLM escrita do zero em NumPy.**

Sem custo por token. Sem limite de uso. Sem enviar dado para terceiro. Ele aprende sozinho todo dia e fica mais inteligente com o uso.

`Python 3.11` · `FastAPI` · `Ollama` · `ChromaDB` · `SQLite` · `NumPy` · **1680+ testes**

---

## O que ele faz

| | |
|---|---|
| 🧠 **Aprende sozinho** | 7 mini-agentes em paralelo (docs oficiais, web, GitHub trending, Wikipédia, livros, tendências) alimentam uma base de conhecimento permanente. A cada 6 itens ele sintetiza, identifica as próprias lacunas e **gera o próprio currículo de estudo**. |
| 💬 **Chat com memória real** | Toda resposta puxa recall semântico (ChromaDB) + busca full-text em paralelo e cita as fontes `[n]`. Conversas longas ganham resumo rolante. |
| 🔬 **Pesquisa Profunda** | Decompõe a pergunta em sub-frentes, investiga memória + web em paralelo, reranqueia as fontes e sintetiza com citações numeradas — transmitindo o raciocínio ao vivo. |
| 💻 **A.P.O.L.O. Coder** | Agente ReAct que edita código de verdade num workspace confinado: `LER / EDITAR / RODAR / BUSCAR / CONSULTAR base / BUSCAR_WEB`, com diff colorido, undo por arquivo e guarda de regressão que reverte sozinha se os testes quebrarem. |
| 🔍 **Code Review** | Revisão por severidade (🔴 crítico / 🟡 importante / 🟢 sugestão) ancorada nas boas práticas que ele mesmo estudou. |
| 🔐 **Agência com permissão** | Ler arquivos, agenda (`.ics`) e e-mail (IMAP read-only) — cada capacidade é uma ferramenta com escopo que você autoriza, e toda invocação fica em log de auditoria. |
| 🛠️ **Ações reversíveis** | Toda ação que modifica algo passa por **prévia → confirmação → desfazer**, registrada num ledger. Nunca um clique cego. |
| 🧬 **Apolo-Nano** | Uma LLM própria, treinada do zero. Detalhes abaixo. |

---

## 🧬 Apolo-Nano — LLM do zero, em NumPy puro

O diferencial do projeto. `src/nanollm/` é um motor de LLM completo **sem PyTorch, sem HuggingFace, sem autograd e sem pesos de terceiros**:

- **Tokenizer BPE byte-level** treinado sobre o corpus do próprio A.P.O.L.O.
- **Transformer GPT decoder-only** com atenção causal multi-head, LayerNorm e GELU — **forward e backward escritos à mão**, com a matemática do backprop validada por *gradient checking* numérico nos testes
- **Adam + warmup/cosine + grad clip** implementados do zero, com estado persistente
- **Geração com KV cache** — 7,7× mais rápida, equivalência com o caminho lento provada em teste
- **v1 medido:** 3,39M params · val ppl **158** (baseline 388) · 605 tok/s em CPU

**Promoção honesta:** o ciclo noturno destila do modelo professor, treina um candidato e só troca o checkpoint vivo se ele vencer **na tarefa** (held-out congelado), com teste de sinais pareado (α = 0,05). A perplexidade virou diagnóstico, não critério — em 3 experimentos o candidato "ganhava" no ppl enquanto piorava de verdade.

```bash
python -m src.nanollm.data     --corpus data/nanollm/corpus --out data/nanollm
python -m src.nanollm.train    --data data/nanollm --preset small --steps 10000
python -m src.nanollm.generate --ckpt data/nanollm/ckpt --prompt "O Apolo é"
python -m src.nanollm.title_eval --ckpt data/nanollm/ckpt   # o portão de promoção
```

---

## Arquitetura

```
┌──────────────────────────────────────────────────────────────┐
│  Interface — FastAPI + SSE streaming + PWA                   │
├──────────────────────────────────────────────────────────────┤
│  Roteador de tarefa  →  agência (grátis) | leve (3b) | 14b   │
├──────────────────────────────────────────────────────────────┤
│  Mini-agentes (paralelo)          │  Provedor de LLM         │
│  📚 Docs  🌐 Web  📡 Trends       │  Ollama ⇄ llama.cpp      │
│  🐙 GitHub  📖 Livros  🧠 Síntese │  (trocável por env)      │
│  🎯 Auto-currículo (fecha o loop) │  🧬 Apolo-Nano           │
├──────────────────────────────────────────────────────────────┤
│  MemoryFabric — uma porta para toda a memória                │
│  ChromaDB (RAG) · SQLite (sessões, episódios) · FTS5/Supabase│
└──────────────────────────────────────────────────────────────┘
```

**Pipeline de aprendizado:** 4 fetchers em paralelo enchem uma fila de 12 enquanto o sumarizador consome — I/O e CPU sobrepostos, throughput 2-3× maior que o ciclo sequencial anterior. A cada síntese, o A.P.O.L.O. extrai as próprias lacunas como queries e as injeta com prioridade na fila.

---

## Decisões técnicas

**Por que 100% local.** O custo por token é o que mata piloto de IA em empresa pequena, e dado sensível não pode sair da infraestrutura do cliente. Tudo — inferência, embeddings, TTS (Piper), STT (Whisper) — roda offline, com fallback em Python puro para embeddings caso não haja modelo baixado.

**Provedor de LLM abstrato.** Todo o app fala com `src/providers.py`, então o motor por baixo é trocável por variável de ambiente: Ollama ou llama.cpp embutido no processo, sem serviço externo. Chat, Coder, agentes, síntese e review herdaram a troca de graça — junto com retry e circuit breaker.

**Medir a alucinação, não afirmar que ela caiu.** A suíte de evals inclui *tarefas-armadilha* de premissa falsa ("em que ano foi promulgada a Lei de Apolônio de 1987?"). Um assistente ancorado admite que não sabe; um que alucina inventa. A taxa de mordida vira métrica no painel "Estou melhorando?", ao lado de satisfação e acerto do Coder.

**Verificação determinística onde dá.** Ancoragem da resposta nas fontes, checagem de fatos contra a base, self-consistency e o roteador de tarefa são todos determinísticos — sobreposição léxica e parsing, sem gastar inferência. Numa máquina CPU-only, cada chamada de LLM economizada é latência que o usuário não espera.

**Automelhoria com rede de proteção.** Modelo local fraco reescreve módulo inteiro para encaixar uma alucinação — aconteceu. Três travas: baseline de testes que reverte tudo em caso de regressão, bloqueio de sobrescrita catastrófica (arquivo de ≥20 linhas por versão <35% do tamanho) e execução numa cópia isolada do projeto, com revisão de diff antes de aplicar.

**O Coder aprende com o próprio erro.** Cada tarefa concluída gera uma lição persistida; regressões viram lição permanente com o erro real dos testes. No início da tarefa seguinte, as lições relevantes entram no system prompt via recall lexical — sem custo de LLM.

---

## Como rodar

```bash
# Pré-requisitos: Python 3.11+ e Ollama (https://ollama.com)
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5-coder:3b        # chat rápido em CPU
pip install -r requirements.txt
cp .env.example .env                # configure OLLAMA_MODEL, CHAT_MODEL
python app.py                       # http://127.0.0.1:8000
```

Como app de desktop (janela nativa, sem navegador): `pip install pywebview && pythonw desktop.py`

```bash
pytest tests/ -v                    # 1680+ testes
```

> ⚡ **Hardware manda.** Um 14b em CPU leva dezenas de segundos por resposta. Use um 3B no chat (`CHAT_MODEL`) — o A.P.O.L.O. já auto-seleciona o melhor leve instalado e reserva o 14b para Pesquisa Profunda e Code Review.

---

## Estrutura

```
app.py                  FastAPI — orquestração
routers/                rotas por domínio (chat, coder, nano, memory, actions…)
src/
├── nanollm/            🧬 LLM do zero: tokenizer, layers, model, optim, train, flywheel
├── memory/             MemoryFabric (semantic | knowledge | lesson) + episódica
├── agents/             mini-agentes de aprendizado autônomo
├── tools/              agência com permissão (registry + run_tool gated)
├── coder.py            agente ReAct de código (sandbox, diff, undo)
├── research.py         Pesquisa Profunda
├── providers.py        motor de LLM intercambiável
├── rerank.py           reranker híbrido (vetorial + lexical + recência)
├── evals.py            eval contínuo com tarefas-armadilha
└── verify.py           verificação anti-alucinação
static/                 UI (PWA, temas, SSE)
tests/                  1680+ testes — 1 arquivo por módulo
```

---

## Status

**v1.0.0** — os 12 milestones do Ano 1 entregues em software: arquitetura, memória, voz local, proatividade, agência com permissão, verificação anti-alucinação, ação no mundo com undo, soberania (backup cifrado, acesso remoto, embeddings locais) e automelhoria supervisionada.

**Pendências conhecidas:** captura contínua de wake word e driver de navegador interativo (Playwright) são opt-in; fine-tuning LoRA e o salto de escala do Apolo-Nano dependem de GPU.

**Roadmap Ano 2:** integração do Apolo-Nano ao roteamento híbrido, flywheel aprender→treinar→servir, agência que conduz projetos e multimodal.
