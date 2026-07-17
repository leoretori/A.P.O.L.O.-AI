# Plano — o cérebro próprio assume (Ano 3, ciclo focado)

> Continuação direta do [JARVIS_ROADMAP_ANO2.md](JARVIS_ROADMAP_ANO2.md) §10 (Ano 3, pilar **P12 · Cérebro
> próprio que assume**). O Ano 2 fechou (M13–M24). O Ano 3 (M25–M28) tem a **infraestrutura pronta**
> (destilação, flywheel, escala, roteamento, avaliação às cegas, gate binário) mas travada por **pouco
> dado real** — não por código faltando. Este plano ataca esse gargalo de frente, com 6 frentes, na
> ordem 1→6, seguindo a mesma disciplina do [docs/PLANO_7_PILARES.md](docs/PLANO_7_PILARES.md): número
> medido de verdade (nunca estimado, nunca inflado), teste verde, verificação ao vivo quando é
> frontend, commit + push + merge, doc atualizado.

**Início:** 2026-07-16 · **Dono:** Leo · **Copiloto:** Claude Code

Legenda: 🔲 pendente · 🔨 em andamento · 🏁 concluído (com número medido) · ⏭️ adiado/descartado (com motivo)

---

## 1. Ampliar o corpus de destilação sem esperar uso orgânico

O M28 mediu o teto real: `first_user_messages() = 5`, `positive_reaction_pairs() = 0` — pouco dado pra
qualquer treino significar algo. Esperar o Leo usar mais o app é válido, mas não é a única fonte. O
próprio Apolo já **aprendeu** centenas de tópicos (`learned_topics`) e tem sínteses de 7 agentes — isso
é corpus real, não inventado, só ainda não foi virado em pares supervisionados de pergunta→resposta e
pergunta→título na escala que o treino precisa.

- 🔲 **1.1** — Gerar pares título e resposta a partir do `learned_topics` existente (o professor Qwen já
  sabe fazer isso via `distill.py`; falta rodar em volume sobre o que já foi aprendido, não só sobre
  `first_user_messages`).
- 🔲 **1.2** — Medir o volume resultante antes de treinar (mesma disciplina do M28: nunca treinar com
  dado insuficiente só pra fechar uma caixinha).
- 🔲 **1.3** — Registrar o crescimento do corpus (antes → depois) no histórico, honesto.

**DoD:** volume de pares de treino (título + resposta) cresce de forma mensurável e documentada; se o
volume ainda não bastar para um treino significativo, isso também é reportado como resultado (não
escondido).

---

## 2. Escalar o Nano de verdade (M26 sai do papel)

O preset `medium`/`large` existe em código desde o M26 mas nunca rodou de verdade neste hardware. Com o
corpus ampliado do item 1, rodar um treino real.

- 🔲 **2.1** — Rodar `python -m src.nanollm.train --preset medium` (ou o preset que o corpus disponível
  sustentar) até convergência razoável, medindo tempo real de treino no CPU.
- 🔲 **2.2** — Comparar ppl do checkpoint novo contra o `ckpt_v1` (3,4M) no mesmo conjunto de validação.
- 🔲 **2.3** — Promover só se medir melhora (reusa o portão de qualidade do M25.3); se não melhorar,
  reportar isso também.

**DoD:** um checkpoint maior que 3,4M treinado de verdade neste hardware, com ppl medido e decisão de
promoção justificada por número, não por expectativa.

---

## 3. Re-medir blind-eval e gate binário com o corpus ampliado

M28 mediu win-rate 40% com n=5 (ruído de amostra). M27 mediu o gate binário como infraestrutura, não
treinado (só 19 tópicos com setor válido). Ambos ficaram pendentes por pouco dado — o item 1 pode
destravar isso.

- 🔲 **3.1** — Recontar tópicos com setor válido; se cruzar o mínimo do `collect_binary_pairs`, treinar
  o gate binário de verdade e medir acurácia real (compara contra os 80,56% do experimento anterior
  com dado sintético).
- 🔲 **3.2** — Rodar blind-eval com `n` maior que 5 (o corpus ampliado do item 1 permite mais perguntas
  reais na amostra), win-rate honesto registrado no histórico.

**DoD:** cada medição roda com `n` suficiente para o número significar algo — ou, se ainda não bastar,
isso é reportado explicitamente em vez de reciclar o resultado antigo.

---

## 4. Latência do roteamento híbrido (Nano vs Qwen 14B)

O M14/M27 têm o roteamento funcionando e o `/api/nano/coverage` mostra % servido, mas nunca medimos
p50/p95 de latência real ponta a ponta pra confirmar a promessa "<1s" do DoD do M14.

- 🔲 **4.1** — Instrumentar/medir latência real do caminho Nano (`NanoEngine.complete`) e do caminho
  Qwen (14B via llama.cpp) para a mesma tarefa (título de conversa), várias amostras.
- 🔲 **4.2** — Se houver gargalo real (não hipotético), corrigir; senão, documentar o número medido
  como baseline.

**DoD:** p50/p95 real registrado para os dois caminhos, com correção aplicada se houver problema
concreto encontrado (não otimização especulativa).

---

## 5. Robustez dos ciclos noturnos

Flywheel (M25.3), dedup (P2.4), quality sample (P2.5) e recall-gate (P2.6) rodam sozinhos de madrugada,
cada um isolado por try/except — mas nunca testamos o cenário de **falha em cascata** nem expusemos a
saúde individual desses ciclos no dashboard (o painel P5 mostra resultado agregado, não se um ciclo
específico está falhando silenciosamente há dias).

- 🔲 **5.1** — Teste de falha isolada: um ciclo lançando exceção não deve impedir os outros de rodar
  na mesma madrugada (validar o que já deveria ser verdade, com teste real).
- 🔲 **5.2** — Expor no dashboard/health quando um ciclo noturno não roda há mais que N dias (sinal de
  problema silencioso, não só "não há dado ainda").

**DoD:** garantia testada de isolamento de falha entre ciclos + visibilidade real de ciclo travado.

---

## 6. Dívida técnica acumulada

Ao longo do `PLANO_7_PILARES.md` emergiram padrões repetidos e pontos soltos que vale consolidar agora,
com o código todo fresco na cabeça.

- 🔲 **6.1** — Rodar `ruff` no repo inteiro, comparar contra a baseline conhecida, corrigir o que for
  novo (não reabrir debate sobre avisos pré-existentes aceitos).
- 🔲 **6.2** — Varrer `src/nanollm/` e `src/*.py` tocados neste ciclo grande por duplicação óbvia
  (regra dos 3) que ainda não foi extraída.

**DoD:** ruff sem regressão nova, duplicações reais (3+ ocorrências) extraídas sem quebrar API pública.

---

## Cadência

Igual ao `PLANO_7_PILARES.md`: um item por vez, na ordem 1→6, "Siga" avança pro próximo. Decisão que só
cabe ao Leo (ex.: qual preset de escala rodar se o hardware não aguentar `large`) para com
`AskUserQuestion`. Ao fechar o item 6, este documento migra para `docs/` (mesma cadência definida no
P7.1 do plano anterior).
