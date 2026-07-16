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

- 🔲 **P1.1 — Motor de dados antes de motor de modelo.** Instrumentar captura passiva de todo
  turno de chat como par de treino candidato (hoje só título vira par). Usar `distill.py` de
  forma mais agressiva para gerar pares sintéticos rotulados pela LLM grande quando dado real
  faltar (rotulado como sintético, nunca misturado sem marca com dado real). **DoD:** corpus
  sobe de 236k para ≥1M tokens de fontes soberanas rastreáveis.
- 🔲 **P1.2 — Sweep de scaling-law compute-matched.** Reproduzir o experimento `medium` (que
  regrediu por undertraining) com passos proporcionais ao tamanho, não passos fixos. **DoD:**
  tabela params × passos × ppl com pelo menos 3 pontos, decisão de tamanho baseada nela.
- 🔲 **P1.3 — Uma tarefa até passar o DoD antes de somar outra.** Priorizar o portão binário
  (M27) — a aposta é que 2 classes generaliza melhor que 9 num modelo de 3M. Só considerar nova
  tarefa depois que essa passar ≥70% na porta de qualidade em produção.
- 🔲 **P1.4 — Blind-eval com rigor estatístico.** Fixar um conjunto de ≥30 perguntas reais do
  banco (não amostra nova a cada rodada) e rodar `blind_eval` nele, virando isso um placar
  histórico rastreável (`data/nano/blind_eval_history.jsonl` ou similar) em vez de números soltos
  em commit messages.
- 🔲 **P1.5 — Contexto e arquitetura baratos em CPU.** Avaliar RoPE/ALiBi para contexto maior que
  192 tokens, tying embedding/unembedding, vocabulário do tokenizer. Cada mudança validada pelo
  harness de eval do P1.4 antes/depois — só entra se medir melhora.

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

- 🔲 **P2.1 — Camada de validação factual (o maior buraco hoje).** Passe amostral (ex.: 10% dos
  resumos salvos) onde a LLM grande audita o resumo contra as fontes já buscadas na mesma sessão,
  marcando `verificado`/`não verificado`. Conteúdo não verificado rankeia mais baixo no RAG.
  **DoD:** campo de verificação existe no schema, é populado automaticamente, e influencia o
  rerank em `rag.py`.
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
