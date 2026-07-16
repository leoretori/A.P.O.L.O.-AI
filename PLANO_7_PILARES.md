# Plano — 7 Pilares (LLM, Aprendizado & mais)

> Documento vivo. Criado em 2026-07-15, a partir de uma auditoria honesta do estado real do
> Apolo-Nano (`JARVIS_ROADMAP_ANO2.md` §10, `docs/APOLO_NANO.md`) e do pipeline de Aprendizado
> (`src/learner.py` e afins). Não é um plano de "grandes saltos" — é uma lista ordenada de
> melhorias concretas, cada uma com linha de base medida (não estimada) e critério de pronto.
>
> **Ordem de execução:** 1 → 7, um pilar por vez, sem pular. Cada item segue a mesma disciplina
> do Ano 1/Ano 2: incremento pequeno → testes verdes → preview verificado quando aplicável →
> commit → push → fast-forward no `main` → atualizar este doc com o resultado REAL medido
> (nunca estimado, nunca inflado — inclusive quando o resultado é nulo/negativo).
>
> Prefixo de cada item: `P{pilar}.{item}`. Status: 🔲 pendente · 🔨 em andamento · 🏁 concluído
> (com número medido) · ⏭️ adiado (com motivo).

---

## Ordem dos pilares

| # | Pilar | Por quê nessa posição |
|---|---|---|
| 1 | [LLM — Apolo-Nano](#pilar-1--llm-apolo-nano) | O motor; tudo depende de dado e de medição confiável |
| 2 | [Modo Aprendizado](#pilar-2--modo-aprendizado) | A fonte do dado que alimenta o pilar 1 |
| 3 | [Uso real / dogfooding](#pilar-3--uso-real--dogfooding) | Sem isso, 1 e 2 continuam bloqueados por volume |
| 4 | [Cadência de auditoria de segurança](#pilar-4--cadência-de-auditoria-de-segurança) | Formalizar o que já provou valor (4 vulns achadas em 15/07) |
| 5 | [Dashboard único de saúde da inteligência](#pilar-5--dashboard-único-de-saúde-da-inteligência) | Torna 1–4 visíveis num só lugar, sem caçar métrica espalhada |
| 6 | [Fechar ou descartar M20.3](#pilar-6--fechar-ou-descartar-m203-automação-de-navegador) | Débito de roadmap parado — decidir antes de acumular mais |
| 7 | [Consolidação periódica de docs](#pilar-7--consolidação-periódica-de-docs) | Manutenção; faz mais sentido depois que os docs cresceram com 1–6 |

---

## Pilar 1 — LLM (Apolo-Nano)

**Linha de base medida (2026-07-15):** 3,39M parâmetros, contexto de 192 tokens, corpus de
236.221 tokens (meta original era ≥2M, nunca atingida), ppl val 157,96. Título passa a porta de
qualidade em ~1/6 casos (fallback quase sempre). Setor mede 31,4% (código morto, não integrado).
Portão binário (M27) só tem infraestrutura, sem treino — 19 exemplos válidos no banco real, longe
do mínimo. Flywheel roda toda noite desde 13/07 e **nunca disparou** (sempre "poucos pares").
Blind-eval Nano-vs-Qwen só mediu com n=5 (ruído).

- 🏁 **P1.1 — Motor de dados antes de motor de modelo (2026-07-15, medido).** `corpus_export.py`
  ganhou duas fontes que faltavam: `fetch_conversations` (conversas Leo↔Apolo inteiras — antes só
  o título virava par, agora o turno inteiro entra no corpus de pré-treino, crescendo sozinho
  conforme o Pilar 3 avançar) e `fetch_project_docs` (os próprios `.md` do projeto — README,
  roadmaps — via novo parâmetro `--repo-root`). Rodado de verdade contra o banco principal
  (2026-07-15): **1.304.589 tokens estimados** (era 236k) — **DoD numérico batido**. Honestidade
  necessária: a maior parte do salto (`apolo_topics`, ~1,19M tokens) é **crescimento orgânico do
  aprendizado autônomo rodando desde então**, não deste código. A contribuição REAL de hoje foram
  as duas fontes novas: conversas (33.674 chars, ainda pequeno — só 15 turnos reais existem) +
  docs do projeto (271.081 chars, ~93k tokens). O ganho maior de `apolo_conversations` ainda
  depende do Pilar 3 (uso real). 19 testes novos/ajustados em `tests/test_nanollm_corpus.py`.
  ⏭️ **Distillation sintética (2ª metade do item) ainda não feita** — o corpus já bateu a meta
  numérica sem precisar dela; fica registrada como opção futura se o corpus voltar a estagnar.
- 🏁 **P1.2 — Sweep de scaling-law compute-matched (2026-07-16, medido).** Novo `src/nanollm/sweep.py`:
  em vez de passos fixos por preset (o viés do `medium`/M6.1 — mesmo nº de passos, mas cada
  preset tem batch/block diferentes, então tokens vistos diferentes), os passos agora vêm de um
  orçamento **tokens-por-parâmetro constante** (`steps_for_budget`) — um preset com mais
  parâmetros treina por mais passos, proporcionalmente. Rodado de verdade contra o corpus
  atualizado (1.055.664 tokens, `data/nanollm/sweep_dataset`), orçamento pequeno de propósito
  (`tokens_per_param=0.15`, bem abaixo do ideal — é um sweep direcional, não a curva final):

  | preset | params | passos | tokens vistos | val loss | ppl | tempo |
  |---|---|---|---|---|---|---|
  | nano | 1,47M | 107 | 219.136 | 7,1772 | **1309,21** | 86,8s |
  | mini | 3,39M | 220 | 506.880 | 6,4150 | **610,91** | 246,9s |
  | small | 6,91M | 505 | 1.034.240 | 5,4564 | **234,25** | 969,7s |

  **DoD numérico batido** (tabela com 3 pontos, decisão apoiada nela). **Leitura honesta:** sob
  comparação justa (passos proporcionais), ppl melhora MONOTONICAMENTE com o tamanho — o oposto
  do que o experimento `medium` sugeria. Isso não prova que "maior é sempre melhor" em geral; prova
  que a comparação anterior estava **contaminada pelo viés de passos fixos**, não que os modelos
  maiores são estruturalmente piores. Nenhum dos 3 pontos está perto de convergência (orçamento
  0,15 tokens/param é muito abaixo do que a literatura considera saudável, ~15-20) — os ppl
  absolutos aqui são bem piores que o `ckpt_v1` de produção (158), que treinou por muito mais
  passos. **Decisão apoiada na tabela:** manter a aposta em escalar o Nano (`medium`/`large`) para
  o próximo treino real, agora sabendo que dar mais passos ao modelo maior é necessário, não
  opcional. 10 testes novos em `tests/test_nanollm_sweep.py` (sintéticos, determinísticos).
  **Efeito colateral corrigido:** o sweep real esbarrou num bug bloqueante nos 11 entry points
  `python -m src.nanollm.*` — `UnicodeEncodeError` no console cp1252 do Windows sempre que um
  print usava "→" (não era só cosmético, derrubava o processo no meio do treino). Corrigido com
  `sys.stdout.reconfigure(encoding="utf-8")` em todos os `if __name__ == "__main__":`.
- 🏁 **P1.3 — Uma tarefa até passar o DoD (2026-07-16, medido, DoD batido).** O bloqueio do M27
  (só 19 exemplos com setor válido, 2026-07-15) sumiu sozinho: o aprendizado autônomo rodou e o
  banco principal tem hoje **3.220 tópicos** com resumo (367 `backend_apis`). Construído
  `src/nanollm/binary_eval.py` (`load_held_out` reproduz o MESMO split determinístico que
  `taskdata._write_tokenized` usou, pra medir só no que o modelo NUNCA viu; `evaluate_binary_gate`
  mede acurácia geral, acurácia-quando-decide e taxa de decisão separadas — um portão que só
  recusa não deve parecer bom por omissão). Dataset real: `collect_binary_pairs(db, "backend_apis")`
  → 964 pares balanceados (482 sim/482 não). Fine-tune de verdade (warm-start de `ckpt_v1`, preset
  `mini`, lr 3e-4, 1200 passos): **overfitting claro e visível** — loss de treino caiu de 5,47 a
  0,61 enquanto o val nunca melhorou depois do passo 300 (val mínimo 2,9975); `model_best.npz`
  guardou automaticamente esse ponto (o mecanismo de "só promove por qualidade" do M25.3 funcionou
  como desenhado, sem precisar de intervenção). **Avaliação real no held-out val (144 pares nunca
  vistos): 80,56% de acurácia, 100% de taxa de decisão, 0 recusas — DoD (≥70%) batido de verdade.**
  Confirma a aposta do M27: framing binário generaliza MUITO melhor que os 31,4% do multi-classe
  de 9 classes na mesma fonte de dado. Ressalvas honestas: (1) medido só para o setor `backend_apis`
  — não presume que outros setores generalizem igual sem medir; (2) o modelo overfita rápido com
  964 pares (mais dado real ajudaria, não é urgente); (3) **este item mede se o gate PASSA o DoD,
  não wireia produção** — ligar `nano_binary_classify` no roteamento (`routing.py`/`NANO_TASKS`)
  fica registrado como próximo passo natural (não feito aqui, para não misturar medição com
  decisão de promover). 4 testes novos em `tests/test_nanollm_binary_eval.py` (fake determinístico).
- 🔨 **P1.4 — Blind-eval com rigor estatístico (2026-07-16, infra pronta, DoD ainda não).**
  `blind_eval.py` ganhou `freeze_questions` (congela o conjunto na 1ª vez, IDEMPOTENTE — rodar de
  novo não re-sorteia, mesmo que o banco tenha crescido; ataca a causa exata do ruído medido no
  M28 em 2026-07-15, onde 20%→40% era só amostra nova de n=5, não melhora real), `append_history`/
  `read_history` (JSONL append-only, nunca reescreve o passado) e `run_tracked_blind_eval`
  (congela + roda + registra em 1 chamada). `run_blind_eval` ganhou o parâmetro `questions` pra
  aceitar o conjunto congelado em vez de sempre reamostrar. CLI atualizado (`--questions`,
  `--history`, `--min-questions`). 9 testes novos (fakes determinísticos).
  **DoD ainda NÃO batido:** medido de verdade contra o banco principal — só **14 perguntas reais**
  existem (`db.first_user_messages`), abaixo do mínimo de 30 que o próprio item exige. Confirmei
  que o gate recusa corretamente em vez de forçar (`ValueError: poucas perguntas reais...`,
  testado ao vivo via CLI). Mesmo padrão do M27 antes do banco crescer: infraestrutura pronta e
  testada, medição real adiada até o Pilar 3 (uso real) produzir volume suficiente — não é tarefa
  de código pendente, é dado que ainda não existe.
- 🏁 **P1.5 — ALiBi medido e vence nos dois eixos (2026-07-16).** `layers.py`/`model.py` ganham
  `pos_encoding: "learned" | "alibi"` em `GPTConfig` — ALiBi (Press et al.) é um viés relativo
  SOMADO aos scores de atenção, sem parâmetro treinável (`wpe` some do modelo inteiro quando
  ativado); como não tem tabela de posição, o mesmo checkpoint aceita qualquer T, inclusive além
  do `block_size` de treino (o "contexto maior" do item, de graça). Backward não muda: viés
  constante não altera o gradiente dos scores — provado por checagem numérica (gradcheck) igual
  ao caminho `learned`. 8 testes novos em `test_nanollm_grad.py` (gradcheck completo, sem-wpe,
  causalidade, extrapolação além do block_size, `pos_encoding` inválido barrado).

  **Experimento real compute-matched** (preset `mini`, ~437-441 passos, mesmo dataset de
  1.034.551 tokens do P1.2, mesma semente): usei o harness de PPL do `eval.py` em vez do
  blind-eval do P1.4 (seu DoD ainda não foi batido — só 14 perguntas reais, ver P1.4).

  | pos_encoding | ppl @ 192 (treinado) | ppl @ 384 (2× extrapolado) |
  |---|---|---|
  | `learned` | 293,03 | ❌ quebra (erro de broadcast — não processa) |
  | `alibi` | **233,12** | **235,24** (só +0,9% de perda) |

  ALiBi venceu nos dois eixos ao mesmo tempo: ppl in-distribution melhor (233 vs 293, não é
  empate) **e** extrapola pra 2× o contexto treinado quase sem degradar. Passa a regra do próprio
  item ("só entra se medir melhora") sem ressalva. Ressalva honesta: 1 rodada compute-matched, não
  múltiplas sementes — direcional, não estatisticamente blindado; ALiBi treinou ~1,7× mais lento
  no CPU nesta rodada (1505s vs 878s, poss. ruído de máquina, não perfilado a fundo). **Decisão
  registrada, não executada aqui:** candidato forte pra virar o padrão no próximo treino de
  produção real (ckpt_v1 e o portão binário do P1.3 continuam em `learned` por ora — trocar o
  checkpoint vivo é uma decisão de promoção separada, mesmo espírito do P1.3).

**Referência:** este pilar continua o trabalho já registrado em `JARVIS_ROADMAP_ANO2.md` §10
(M25–M28); os itens acima começam em cima daquilo, não o duplicam. GPU dedicada continua sendo
upside, não pré-requisito (ver `docs/APOLO_NANO_ROADMAP.md` e memória `project_hardware`).

---

## Pilar 2 — Modo Aprendizado

**Linha de base medida (2026-07-15):** 6 agentes buscam sobre uma lista majoritariamente FIXA de
~180 tópicos (`src/topics.py`). Auto-currículo existe mas é raso (pede 6–12 tópicos à LLM quando a
rotação esgota) e mostrou deriva pro genérico nos logs reais ("Otimização de infraestruturas
urbanas inteligentes com Machine Learning"). A porta de qualidade antes de salvar é **só
estrutural** (tamanho, formato, anti-injeção) — **não existe verificação factual em nenhum ponto
do pipeline**. Dedup existe mas é majoritariamente manual (ação de curador). O único mecanismo
parecido com "revalidação" é um diff de drift que só roda quando um tópico é re-estudado 21 dias
depois.

- 🏁 **P2.1 — Camada de validação factual, ligada de ponta a ponta (2026-07-16).** O buraco era
  real: nada checava se um resumo era fiel à fonte, só forma (tamanho/markdown/anti-injeção).
  Agora existe uma amostra real:
  - `src/factcheck.py` ganha `GROUNDEDNESS_PROMPT` + `parse_groundedness()` (juiz LLM sim/não,
    puro e testável sem motor de verdade — mesmo padrão do `blind_eval`/`nano_binary_classify`).
  - `learner.py::_process_item` audita **1 em cada `VERIFY_SAMPLE_EVERY` (10) resumos salvos**
    contra a fonte crua (`item.content`, que só existe em memória nesta sessão — é agora ou nunca)
    via `_verify_summary` (mesmo lock/gate/timeout do `_summarize`, nunca derruba o pipeline em
    erro). Contador determinístico, não aleatório — reproduzível.
  - Schema: `learned_topics.verified` (nova coluna, migração automática — `_COLUMN_MIGRATIONS` em
    `storage.py`, testada contra um banco "legado" simulado sem a coluna). `None` = não sorteado
    (a maioria — não é "reprovado"), `"verified"`/`"failed"` = resultado real da auditoria.
  - `_persist` propaga pro SQLite E pro metadata do RAG (Chroma) — `"unchecked"` quando `None`.
  - `rag.py::recall()` passa `verified` pro candidato; `rerank()` ganha `w_verified` — "failed"
    penaliza, "verified" bonifica de leve, "unchecked" (maioria) fica neutro — não afirma nada
    sobre o que nunca foi checado.
  - `storage_learning.py::get_verification_stats()` novo — quantos % já foram amostrados e quantos
    passaram, pronto pro dashboard do Pilar 5.
  **DoD batido nos 3 critérios:** campo existe no schema (✓ migração testada), é populado
  automaticamente (✓ 1/10 resumos reais, não simulado), influencia o rerank (✓ `w_verified`
  testado isolando o efeito). 19 testes novos entre `test_factcheck.py`, `test_storage.py`,
  `test_storage_learning.py`, `test_learner_dedup.py`, `test_rerank.py`, `test_recall_recency.py`.
- 🔲 **P2.2 — Currículo dirigido por necessidade, não só por novidade.** Ligar a geração de
  tópicos do auto-currículo ao perfil/metas/projetos ativos (a infraestrutura de grafo + perfil já
  existe em `src/graph.py`/`src/profile.py`, só não está conectada aqui). Dar peso maior a
  `_user_queue` (perguntas reais que você fez) sobre `_self_queue` (autogerado).
- 🔲 **P2.3 — Filtro de deriva do currículo.** Antes de enfileirar um tópico autogerado, pontuar
  relevância contra seus interesses/perfil conhecidos; descartar ou reformular o que pontuar
  baixo, em vez de estudar qualquer coisa que a LLM sugerir.
- 🔲 **P2.4 — Automatizar dedup.** `dedup_learned_topics()` e `RAGManager.dedup_exact()` hoje só
  rodam por ação manual de curador; agendar como rotina noturna (mesmo padrão do M10/flywheel).
- 🔲 **P2.5 — Métrica de qualidade real, não só estrutural.** Substituir/estender
  `get_summary_quality()` (hoje só checa se tem cabeçalho markdown) por uma amostragem com
  LLM-juiz avaliando precisão/utilidade/não-genericidade, rastreada como indicador no tempo.
- 🔲 **P2.6 — Formalizar `recall_calibration.py`.** Hoje é ferramenta manual; virar gate de
  qualidade agendado testando recall contra um conjunto fixo de perguntas com resposta conhecida,
  pra pegar regressão de RAG antes que você perceba no uso real.
- 🔲 **P2.7 — Re-verificação priorizada.** Tópicos ligados a projetos/metas ativas devem
  re-verificar mais cedo que os 21 dias padrão; tópicos de áreas voláteis (tech) mais cedo que
  áreas estáveis (ciência básica).

---

## Pilar 3 — Uso real / dogfooding

**Por quê:** quase tudo que trava o Pilar 1 (flywheel, portão binário, blind-eval significativo)
está bloqueado por volume real de uso — medição de 15/07: 5 primeiras-mensagens, 0 reações 👍
dadas até agora. Isso não é código, é processo.

- 🔲 **P3.1 — Ritual de uso diário.** Usar o chat normalmente no dia a dia (não só para testar
  features) e dar 👍/👎 quando fizer sentido — os dois flywheels (título e reações) já rodam
  sozinhos de madrugada assim que houver volume suficiente.
- 🔲 **P3.2 — Painel de progresso do volume.** Expor no dashboard (ver Pilar 5) uma barra clara
  "faltam X conversas/reações para o próximo treino automático disparar", pra tornar o gargalo
  visível em vez de descoberto via log.

---

## Pilar 4 — Cadência de auditoria de segurança

**Por quê:** a auditoria de 15/07 achou 4 vulnerabilidades reais e exploráveis (CSRF, SSRF via
redirect, bypass de undo, vazamento de conteúdo) num código que já tinha passado por revisão
normal. Isso não deve ser ad-hoc.

- 🔲 **P4.1 — Definir gatilho de recorrência.** Rodar `/security-review` antes de todo merge
  "grande" no `main` (critério objetivo a definir: ex. >10 arquivos ou qualquer mudança em
  rotas/`routers/`, `src/actions.py`, `src/webtask.py`, auth/CORS).
  crontab? Definir junto com o Leo se é manual-lembrado ou automatizado via rotina.
- 🔲 **P4.2 — Registro histórico de auditorias.** Um arquivo/tabela simples com data, achados,
  status de correção — pra não perder o histórico de "o que já foi auditado e quando".

---

## Pilar 5 — Dashboard único de saúde da inteligência

**Por quê:** hoje as métricas (Nano, qualidade do aprendizado, hit-rate do RAG, canário de
alucinação) estão espalhadas entre `/api/health`, `/api/nano/coverage`, `/api/retrospective2`,
logs e commits. Não existe um lugar só pra ver "como o cérebro está indo".

- 🔲 **P5.1 — Levantar as fontes existentes.** Mapear todo endpoint/métrica já existente
  (`/api/health`, `/api/nano/coverage`, canário `src/evals.py`, `get_summary_quality()`,
  `recall_calibration.py`) antes de construir qualquer UI nova.
- 🔲 **P5.2 — Painel consolidado.** Um card/seção único agregando: % cobertura Nano, ppl atual,
  win-rate blind-eval mais recente, qualidade do aprendizado (P2.5), progresso de volume (P3.2).
- 🔲 **P5.3 — Série histórica, não só snapshot.** Guardar essas métricas ao longo do tempo (não
  só o valor atual) pra enxergar tendência, não só ponto isolado.

---

## Pilar 6 — Fechar ou descartar M20.3 (automação de navegador)

**Por quê:** `JARVIS_ROADMAP_ANO2.md` Épico 20.3 está "PENDENTE DO LEO" há um tempo — infra pronta
(`src/webtask.py`, Playwright instalado), mas sem tarefa real definida. Débito de roadmap
esquecido é pior que decisão explícita de abandonar.

- 🔲 **P6.1 — Decisão explícita.** Ou (a) escolher a tarefa semanal real a automatizar e fechar o
  épico, ou (b) marcar como ⏭️ adiado/descartado no roadmap com motivo, liberando o item da lista
  de pendências ativas.

---

## Pilar 7 — Consolidação periódica de docs

**Por quê:** os roadmaps estão crescendo (`JARVIS_ROADMAP_ANO2.md` já é longo, múltiplos `.md` na
raiz). Manutenção, não urgência — por isso é o último da fila.

- 🔲 **P7.1 — Definir cadência.** Ex.: a cada Ano fechado (como já aconteceu Ano1→Ano2), revisar
  se algum doc pode migrar pra `docs/` como histórico, igual já foi feito uma vez.
- 🔲 **P7.2 — Aplicar aos docs deste próprio plano.** Quando os pilares 1–6 avançarem o
  suficiente, revisar se este arquivo (`PLANO_7_PILARES.md`) deve virar seção de um roadmap maior
  ou continuar solo.

---

*Este documento não estima prazo — cada pilar avança em "siga"s como o resto do projeto. Nenhum
item aqui deve ser marcado 🏁 sem um número medido de verdade (o mesmo padrão que já vale para
todo o resto do roadmap).*
