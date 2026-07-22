# PLANO DE MELHORIA GIGANTE — LLM própria + Autoaprendizado (2026-07-22)

> **Objetivo declarado do Leo:** construir "meu próprio Claude" dentro da realidade de
> hardware atual (Ryzen 5 4600G, 16GB, CPU-only; uma GPU modesta no horizonte).
>
> **Leitura honesta da situação, baseada nos números medidos do próprio projeto:**
> - O Apolo-Nano (3,39M params, NumPy puro) é um **laboratório excepcional** — backward manual
>   correto, KV cache correto, tokenizer próprio, flywheel com portões. Isso é raro e valioso.
> - Mas 3 fine-tunes consecutivos PIORARAM o modelo (33,3% → 20% → 20% → 6,7% de win-rate), e a
>   conclusão registrada no experiment_history está certa: **o gargalo não é técnica, é escala
>   (dados × parâmetros)**. Um modelo de 3M nunca vai conversar; ele pode, sim, dominar tarefas
>   estreitas (título, setor, gates binários).
> - Portanto o plano tem **duas trilhas paralelas e explícitas**: a trilha **Nano** (laboratório
>   + takeover de tarefas estreitas, onde dá para VENCER hoje) e a trilha **Cérebro** (o caminho
>   realista para "meu próprio Claude": um modelo aberto pequeno + fine-tune LoRA com os SEUS
>   dados, servido pelo SEU motor). As duas se alimentam do mesmo flywheel de dados.
>
> Pré-requisito de tudo: **os erros críticos E1–E6 do [ERROS_E_FALHAS.md](ERROS_E_FALHAS.md)**
> — sem eles consertados, o flywheel noturno gira em falso.

---

## FASE 0 — Consertar o chão (1ª semana) 🔧

A base do plano é o documento de erros. Ordem sugerida (dependências):

1. **E1 + E1b** — flywheel de título volta a fechar o ciclo (é o único flywheel que roda cedo,
   com poucos dados).
2. **E4** — blind-eval sem respostas vazias (destrava medição honesta de TUDO adiante).
3. **E2 + E20** — geração longa correta no engine (destrava chat-próprio e avaliações longas).
4. **E5** — portão estatisticamente honesto (ver Fase 3, item 3.1 — fazer junto).
5. **E6** — título promovido por métrica de TAREFA, não ppl.
6. **E8** — tasks de background com referência (proteção do learner inteiro).
7. Cada fix entra com **teste de regressão do caminho real** (E28).

**Critério de saída da Fase 0:** uma noite completa roda os 3 ciclos (título, resposta,
destilação) sem exceção engolida, com decisões registradas nos ledgers.

---

## TRILHA NANO — o modelo do zero vira ESPECIALISTA em tarefas estreitas

### FASE 1 — Arquitetura: mais capacidade com os MESMOS FLOPs (1-2 semanas)

**1.1 Weight tying (E15) — o maior ganho grátis do projeto.**
`lm_head.w = wte.wᵀ` libera ~1,05M dos 3,39M params (~31%). Reinvestir em +2 camadas ou
n_embd 320. Todo modelo pequeno sério (GPT-2, Pythia, SmolLM) faz isso.

**1.2 ALiBi como padrão + janela deslizante no `generate_fast` (E11/E2).**
O ALiBi já está implementado e correto (verificado por execução). Torná-lo o default dos
próximos treinos: elimina a tabela `wpe` (menos params), extrapola contexto, e o cache pode
crescer além do block_size de treino.

**1.3 Amostragem decente no `_sample` (E13).**
Repetition penalty + top-p + stop-strings. Custo: ~30 linhas de NumPy. Efeito imediato na
qualidade percebida de TODAS as tarefas do Nano (o loop degenerativo é o modo de falha nº 1
de modelo pequeno).

**1.4 Modernizações baratas de arquitetura (medir uma a uma, com o harness que já existe):**
- **RMSNorm** no lugar de LayerNorm (menos ops, mesmo efeito — padrão Llama).
- **SwiGLU** no MLP (ganho consistente em modelos pequenos; ~mesmos FLOPs com 2/3 do hidden).
- **Init escalado por profundidade** já existe; adicionar **z-loss ou logit soft-cap** se o
  treino de modelos maiores instabilizar.
- Manter float32 (CPU não ganha com fp16 em NumPy).

**1.5 Tokenizer: revisar o custo real do byte-level em PT-BR.**
Medir chars/token do vocab 4096 atual em texto PT (meta.json diz ~2,9). Vocab 8192 com o
corpus maior da Fase 2 deve chegar a ~3,5-3,8 → contexto efetivo +25% de graça. O treino de
tokenizer é rápido; o que muda é re-tokenizar o corpus (barato).

### FASE 2 — Dados: o gargalo confirmado (2-4 semanas, roda em paralelo)

O experiment_history já concluiu: *"o gargalo agora é puramente volume de dado real"*. Corpus
atual = o que o Apolo aprendeu + conversas + docs (poucos MB). Um modelo, mesmo de 10-30M,
precisa de **centenas de MB a GB** de texto PT para ter prosa estável.

**2.1 Corpus público PT-BR filtrado (o pré-treino de verdade).**
- Wikipedia PT (dump oficial, ~2GB de texto limpo) — licença livre, qualidade alta.
- Ajustar `corpus_export`/`data.py` para corpus em shards (streaming, sem carregar tudo).
- Manter a identidade soberana: o corpus do Apolo entra como **fine-tune de domínio** DEPOIS
  do pré-treino geral — nunca misturado 50/50 (lição do M14.2 sobre distribuições).

**2.2 Split de validação honesto (E14).**
Split por documento sorteado, semente fixa. Sem isso, todo número de val da Fase 1 é suspeito.

**2.3 Replay/mixagem no fine-tune — ataca o esquecimento MEDIDO.**
Toda rodada de fine-tune de tarefa mistura X% do corpus geral (ex.: 30%) no batch. É a
resposta padrão da literatura para exatamente o fenômeno que os 3 experimentos registraram
(fine-tune melhora a tarefa, destrói a prosa). Implementação: `get_batch` com duas fontes e
proporção; ~20 linhas.

**2.4 LoRA manual em NumPy — fine-tune que NÃO destrói o modelo.**
Em vez de tocar em W (congelar ou não congelar — as duas variantes já falharam), treinar
apenas `ΔW = B·A` de rank 4-8 por camada de atenção. Forward: `x@(W + B@A)`. Backward: só
A e B recebem gradiente (as regras já existem no framework). Benefícios:
- o checkpoint base fica intacto (promoção = trocar o adapter, rollback trivial);
- ~1-2% dos params treináveis → menos overfit com centenas de pares;
- adapters POR TAREFA (título, setor, resposta) sobre o MESMO base — resolve o conflito de
  "um checkpoint só para tudo" que hoje faz o flywheel de título ameaçar o de resposta.
É o item de maior alavancagem técnica da trilha Nano inteira.

**2.5 Destilação com soft targets (quando houver GPU/tempo).**
O llama.cpp expõe logprobs; treinar o Nano com KL nos top-k logits do Qwen (não só o texto)
transfere MUITO mais sinal por par. Guardar para quando o custo de gerar logits couber.

### FASE 3 — Medição que não mente (1 semana, junto com Fase 0)

**3.1 Portão estatístico (E5).**
- Conjunto congelado: 60-100 perguntas (o banco já tem sessões suficientes? o
  `diagnose_pair_sourcing` diz — se não, congelar 30 e crescer o arquivo, nunca re-sortear).
- **Gabarito do professor cacheado em disco** por pergunta (mesma referência para candidato,
  titular e rodadas futuras; custo de professor cai pela metade).
- Juiz 2× por par (A/B e B/A); inconsistente = empate.
- Promoção: teste binomial no delta (ex.: scipy não é necessário — normal approx à mão).

**3.2 Suite de tarefas como régua contínua.**
`gate_accept` (título), acurácia de setor, acurácia binária held-out — já existem as peças
(`binary_eval.py`, `evals.py`). Consolidar num `python -m src.nanollm.report` que imprime a
tabela completa de um checkpoint: ppl geral + ppl domínio + gate título + setor + win-rate.
Toda mudança de Fase 1/2 só entra com esse report antes/depois.

**3.3 Curva de escala própria.**
Com corpus da Fase 2 + presets existentes (nano→medium), treinar 3 pontos e plotar
loss×params×tokens. Isso diz — com dados SEUS — quanto vale cada upgrade de hardware, e
substitui achismo por engenharia na decisão da GPU.

### FASE 4 — Takeover de verdade (contínuo)

- **Título:** com E6 + 1.3, meta realista: >50% das sessões tituladas pelo Nano (métrica já
  existe: `nano_coverage`).
- **Setor:** promover o `ckpt_sector`/gate binário com a medição de 3.2 — primeiro takeover
  de classificação.
- **Novas famílias estreitas** (baixo risco, alta frequência): tags de conhecimento,
  julgamento "é degenerado?" (substituindo heurística do content_hygiene), dedup semântico
  barato, "esta pergunta precisa do modelo pesado?" (roteador leve→pesado — hoje resolvido
  por heurística em `model_select`).
- Cada família: dataset destilado isolado + adapter LoRA próprio + gate estatístico.

---

## TRILHA CÉREBRO — o caminho realista para "meu próprio Claude"

> O Nano é o laboratório e o especialista em tarefas. Mas "um Claude do Leo" — que conversa,
> raciocina e usa as suas memórias — no seu hardware, passa por **especializar um modelo
> aberto pequeno**, não por pré-treinar do zero. Isso NÃO é desistir da soberania: o motor é
> seu (llama.cpp), os pesos ficam na sua máquina, o dado de treino é 100% seu.

### FASE 5 — Flywheel de dados apontado para o Cérebro (já pode começar)

Tudo que o autoaprendizado coleta hoje vira o dataset de fine-tune do futuro Cérebro:
- **5.1 Dataset conversacional unificado e append-only (E10):** pares (pergunta real do Leo →
  resposta 👍 OU resposta do professor), Q&A ancorado nas sínteses dos agentes, episódios.
  Formato chat (system/user/assistant) desde já — é o formato que QUALQUER fine-tune futuro
  consome (Nano, Qwen, o que vier). Um `data/cerebro/dataset.jsonl` com dedup e procedência.
- **5.2 Pares de preferência:** cada 👍/👎 sobre respostas alternativas vira par (chosen,
  rejected) — combustível de DPO futuro. O schema de reações já existe; falta exportador.
- **5.3 Curadoria automática:** o quality_sampler já julga resumos; estender para julgar
  pares do dataset (professor ruim não entra no treino).

### FASE 6 — Quando a GPU chegar (mesmo uma "GPU merda")

Com QUALQUER GPU de 8-12GB (ex.: RTX 3060/4060):
- **6.1 QLoRA no Qwen2.5 1.5B-3B** com o dataset da Fase 5 (milhares de pares reais a essa
  altura). Ferramentas: PyTorch + peft/unsloth — treino de horas, não semanas. Resultado:
  um modelo que fala COMO o Apolo, sabe o contexto do Leo, roda no llama.cpp atual (exportar
  merge → GGUF). **Este é o primeiro artefato que merece o nome "meu próprio Claude v0".**
- **6.2 Nano em PyTorch:** portar o GPT (mantendo o NumPy como referência didática e teste de
  gradiente) → 10-50× de throughput → presets 30M/125M viáveis → a curva da Fase 3.3 diz até
  onde escalar.
- **6.3 DPO com os pares da 5.2** sobre o modelo da 6.1 — o ciclo completo: usar → reagir →
  treinar preferência → servir. Fechado e 100% local.

---

## AUTOAPRENDIZADO — melhorias no learner (paralelo, incremental)

- **A1. Relevância do currículo por embedding, não por overlap lexical.**
  `_curriculum_relevance` usa interseção de palavras — "Filosofia estoica" vs metas em outras
  palavras dá 0. O projeto JÁ tem embeddings (RAG); usar similaridade de cosseno contra o
  perfil dá um filtro de deriva muito melhor que `CURRICULUM_RELEVANCE_MIN` lexical.
- **A2. Recall ativo com pergunta gerada, não com o título.**
  `_recall_strength` consulta o RAG com o próprio tópico (quase sempre acha o doc do próprio
  tópico → score alto → "lembrou"). Auto-teste honesto: gerar 1 pergunta sobre o tópico
  (barato, 1.5B) e medir se o recall acha a resposta. Senão o SM-2 mede a qualidade do
  índice, não a memória.
- **A3. Gap-driven learning de verdade.** `note_gap` hoje só conta/exibe. Fechar o loop:
  lacuna detectada no chat → tópico prioritário → após estudar, notificar "aprendi sobre X
  que você perguntou ontem" (a anticipation já tem o canal).
- **A4. Verificação amostral → verificação dirigida.** Em vez de 1 a cada 10 fixo, verificar
  100% das categorias de risco (trend/github, mais sujeitas a ruído de scraping) e menos as
  estáveis (enciclopédia).
- **A5. Síntese com citação.** A síntese cross-domain gera texto sem fontes; incluir os ids
  dos tópicos usados → o Q&A ancorado da destilação ganha procedência e o painel pode expandir.
- **A6. E22/E23/E24 do doc de erros** (consistência de contadores, dedup no study_now, DB
  async) — higiene.

---

## PRIORIZAÇÃO CONSOLIDADA (impacto × esforço)

| # | Item | Trilha | Esforço | Impacto |
|---|------|--------|---------|---------|
| 1 | Fase 0 (E1–E8) | base | dias | 🔥 destrava tudo |
| 2 | 1.1 weight tying | Nano | horas | 🔥 +31% params grátis |
| 3 | 1.3 sampling decente | Nano | horas | 🔥 qualidade imediata |
| 4 | 3.1 portão estatístico | base | 1-2 dias | 🔥 decisões param de ser ruído |
| 5 | 5.1 dataset unificado append-only | Cérebro | 1-2 dias | 🔥 capitaliza TODO uso diário |
| 6 | 2.3 replay no fine-tune | Nano | horas | alto — mata o esquecimento medido |
| 7 | 2.4 LoRA NumPy | Nano | 2-4 dias | alto — fine-tune seguro + multi-tarefa |
| 8 | 2.1 corpus Wikipedia PT | Nano | 2-3 dias | alto — remove o teto de dados |
| 9 | 3.2 report unificado | base | 1 dia | médio-alto |
| 10 | A1-A3 (learner) | auto | 1-2 dias cada | médio |
| 11 | 1.4/1.5 arquitetura/tokenizer | Nano | 2-3 dias | médio (medir!) |
| 12 | 5.2 pares de preferência | Cérebro | 1 dia | médio agora, 🔥 na Fase 6 |
| 13 | Fase 6 (GPU) | Cérebro | quando vier | 🔥🔥 o salto de verdade |

**Regra de ouro mantida do projeto:** nada é promovido sem medição honesta antes/depois; toda
mudança de treino passa pelo report da Fase 3.2; datasets nunca misturam distribuições sem
decisão explícita.
