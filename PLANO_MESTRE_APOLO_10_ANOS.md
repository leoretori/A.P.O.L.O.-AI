# 🌌 A.P.O.L.O. — Plano Mestre de 10 Anos

> O documento-raiz. Une os dois fios do projeto num só: **o cérebro** (a LLM própria, do zero — [Apolo-Nano](docs/APOLO_NANO_ROADMAP.md)) e **o corpo** (o assistente soberano — [Jarvis Ano 1](docs/JARVIS_ROADMAP.md) ✅ + [Ano 2](JARVIS_ROADMAP_ANO2.md)). A meta não é um chatbot: é um **parceiro de vida e engenharia, soberano, que raciocina com um cérebro treinado pelo próprio Leo, se lembra de uma década de convivência, age no mundo com segurança e melhora sozinho todo dia.**

**Início:** 2026-07-09 · **Horizonte:** 2036 · **Dono:** Leo · **Copiloto:** Claude Code
**Ponto de partida real:** APOLO **v1.0.0** (Ano 1 completo) + **Apolo-Nano v1** (3,39M params, treinado do zero, integrado ao app).

---

## 1. A visão de 10 anos

Hoje o APOLO já é presente, tem memória, aprende sozinho, age com permissão e tem uma LLM própria em miniatura. Em 10 anos, cada uma dessas capacidades cresce uma ordem de grandeza e **as duas linhas se fundem**: o scaffolding (memória, agência, presença, personalização) passa a ser servido por um **cérebro que é do Leo** — pesos treinados no conhecimento dele, escalando com o hardware que ele adquirir.

O arco em uma frase por época:

| Época | Ano(s) | Uma frase |
|-------|--------|-----------|
| **Fundação** | 1 ✅ | O APOLO nasce completo em software + a LLM própria nasce (miniatura). |
| **O cérebro vira seu** | 2 | O Nano serve tarefas leves reais; o APOLO te conhece de verdade; a estrada da GPU fica pronta. |
| **A era da GPU** | 3 | Com hardware, o Nano escala 30× e o 14B ganha a personalidade do Leo (LoRA). |
| **Raciocínio soberano** | 4 | O cérebro próprio responde a maior parte do dia; o modelo alugado vira só reserva. |
| **O agente que conduz** | 5 | O APOLO executa projetos multi-passo no mundo real, com segurança e reversível. |
| **Cérebro em conjunto** | 6 | Vários modelos especializados (ensemble) + APOLO no bolso (edge/mobile). |
| **Presença viva** | 7 | Co-piloto de vida ambiente: memória relacional e temporal de anos. |
| **Evolução autodirigida** | 8 | O APOLO propõe e executa a própria evolução, medindo a própria capacidade. |
| **Soberania plena** | 9 | 100% local, cifrado, portátil: cérebro, dados, memória e agência, tudo do Leo. |
| **O parceiro de uma década** | 10 | Um AI pessoal maduro, com 10 anos de memória compartilhada. Retrospectiva + próximo ciclo. |

O **teto honesto** segue nomeado o tempo todo: em CPU, o cérebro próprio é um laboratório. **A GPU é o multiplicador que destrava as Épocas 3+.** O plano é desenhado para render o máximo antes dela e para "acender" na hora que ela chegar — sem reescrever nada.

---

## 2. Princípios (herdados e inegociáveis)

1. **Soberania primeiro.** Tudo roda offline; onde depender de nuvem, migra para local. Pesos, dados, memória e agência são do Leo.
2. **Do zero de verdade** (no cérebro próprio): sem libs de ML, sem pesos de terceiros, sem autograd. O que entra de dependência é decisão explícita.
3. **Verdade vem da execução.** Testes, não intenção. Nada é "entregue" sem número medido. Honestidade sobre o teto (`🔒 HW`).
4. **Incrementos diários, verdes e mergeados.** 10 anos = ~2.500 dias de pequenos passos testados. É assim que se constrói algo gigante sem quebrar.
5. **Nada assumido sobre o Leo.** O modelo pessoal é curado por ele; a IA propõe, ele confirma.
6. **Reversível e auditável.** Toda ação no mundo tem preview, confirmação, undo e trilha.

---

## 3. Estado atual (a base real — 2026-07-09)

**O corpo (APOLO v1.0.0 — Ano 1 completo):** chat com memória unificada (RAG+FTS+episódica+lições), aprendizado autônomo contínuo (6 agentes + auto-currículo + repetição espaçada + grafo de conhecimento), voz local (Piper/Whisper), proatividade (briefing/lembretes), agência com permissão (ler arquivos/agenda/e-mail; escrever com confirmação+undo), verificação anti-alucinação, harness de avaliação (👍/👎 + "estou melhorando?"). ~1.180 testes verdes, ~110 endpoints, arquitetura modular.

**O cérebro (Apolo-Nano v1):** LLM GPT decoder-only escrita do zero em NumPy (tokenizer BPE + backprop manual provado por gradcheck + Adam + KV cache), treinada no conhecimento do próprio APOLO (236k tokens soberanos → ppl 158), integrada ao app (`/api/nano`, card no painel Saúde, título de conversa Nano-first com fallback). Modelo profundo do Leo iniciado (M16.1/16.2: perfil estruturado + extração com confirmação).

**O teto medido:** 3,39M params no CPU (Ryzen 4600G, 16GB, sem GPU) geram PT coerente mas não fazem tarefas ancoradas com qualidade de produção (título 1/6, classificação 31%). Gargalo = banda de RAM. **Conclusão empírica: a próxima ordem de grandeza precisa de GPU.**

---

## 4. Os dois fios que viram um

| O corpo (APOLO) dá ao cérebro (Nano) | O cérebro (Nano) dá ao corpo (APOLO) |
|---|---|
| **Corpus soberano** (tudo que aprendeu, cresce todo dia) | **Raciocínio próprio** — pesos do Leo, não alugados |
| **Dados de tarefa** (conversas, tópicos, feedback) | **Latência instantânea** onde o modelo grande é lento |
| **Gate de recursos** (nunca competir com o modelo grande) | **Soberania do pensamento** — o último bastião |
| **Harness de qualidade** (só promove se melhorar) | **Estrada para a GPU** (LoRA/escala prontos) |

O **flywheel** é o coração de 10 anos: *quanto mais o APOLO aprende, melhor fica o cérebro que ele mesmo treina — e mais ele roda em soberania própria.* Cada volta do ciclo, com mais hardware, fecha mais apertada.

---

## 5. O calendário de 10 anos

> Cada ano tem 3–4 pilares; cada pilar herda o detalhamento dos roadmaps vivos (Ano 1 ✅, Ano 2 M13–M24, Nano A–C). Anos 3+ são direção honesta, refinados a cada ciclo com o hardware real. "🔒 HW" = travado por GPU.

### 🗓️ Ano 1 — FUNDAÇÃO ✅ *(2026, concluído)*
Corpo completo (`JARVIS_ROADMAP.md`, M1–M12) + cérebro nascido (`APOLO_NANO_ROADMAP.md`, Fases A–B). **Entregue: v1.0.0 + Nano v1.**

### 🗓️ Ano 2 — O CÉREBRO VIRA SEU *(2026–2027)*
Detalhe em [`JARVIS_ROADMAP_ANO2.md`](JARVIS_ROADMAP_ANO2.md) (M13–M24).
- **Cérebro híbrido:** Nano serve tarefas leves reais + roteamento Nano/14B + flywheel (aprender→treinar→servir). *(M13 ✅, M14.2 medido)*
- **Conhecer o Leo:** modelo profundo (metas/projetos/hábitos/pessoas/valores) + personalização que adapta + memória relacional. *(M16.1/16.2 ✅)*
- **Agência que conduz + multimodal:** ações que conduzem projetos; visão/tela/voz contínua.
- **Estrada da GPU pronta:** LoRA do 14B e re-treino do Nano testáveis, "acendem" no dia da GPU.
- **DoD do ano:** o APOLO te conhece, serve parte do dia com cérebro próprio, e está pronto para escalar.

### 🗓️ Ano 3 — A ERA DA GPU `🔒 HW` *(2027–2028)*
*Assume a aquisição de uma GPU de entrada (12–16GB) — o multiplicador central.*
- **Nano escala:** 3M → 30–100M params, contexto longo, treino em dias (não semanas). Qualidade de tarefa cruza o limiar de produção.
- **LoRA do 14B com os dados do Leo:** o modelo grande ganha a personalidade e o conhecimento do Leo nos pesos.
- **Hybrid brain real:** roteador maduro decide Nano vs. 14B-LoRA vs. reserva, por custo e confiança.
- **DoD:** o cérebro próprio faz, com qualidade medida, o que só o modelo alugado fazia.

### 🗓️ Ano 4 — RACIOCÍNIO SOBERANO `🔒 HW` *(2028–2029)*
- O modelo próprio responde a **maioria** das interações diárias; o alugado vira fallback.
- **Multimodal nativo:** visão (tela/câmera opt-in), voz contínua soberana (wake word + loop <1s), documentos.
- **Auto-avaliação de capacidade:** a série histórica prova que o cérebro fica mais capaz, não só mais ativo.
- **DoD:** desligo a internet e o APOLO raciocina, vê, ouve e fala — tudo local, com qualidade.

### 🗓️ Ano 5 — O AGENTE QUE CONDUZ *(2029–2030)*
- Agência plena no mundo real (arquivos, apps, navegador, agenda, comunicação) com as travas de segurança do Ano 1 elevadas.
- **Projetos autodirigidos:** o APOLO define metas próprias, quebra em tarefas, executa e te reporta — supervisão evoluída.
- **DoD:** o APOLO conduz um projeto real do Leo de ponta a ponta, com trilha auditável e reversível.

### 🗓️ Ano 6 — CÉREBRO EM CONJUNTO `🔒 HW` *(2030–2031)*
- **Ensemble de especialistas:** vários Nanos afinados por domínio (código, escrita, planejamento) + roteamento/mistura.
- **Edge:** o APOLO no bolso (mobile/local) e em casa, sincronizado e soberano.
- **DoD:** o cérebro é um conjunto que escolhe o especialista certo; roda além do desktop.

### 🗓️ Ano 7 — PRESENÇA VIVA *(2031–2032)*
- Co-piloto ambiente: acompanha contexto (agenda, foco, hora, lugar) e intervém no momento certo, sem virar ruído.
- **Memória relacional e temporal de anos:** linha do tempo da vida, pessoas, projetos — "o que rolava quando fizemos X há 3 anos".
- **DoD:** perguntas de vida complexas ("onde parei no projeto Y?", "o que o fulano me pediu?") respondidas com precisão datada.

### 🗓️ Ano 8 — EVOLUÇÃO AUTODIRIGIDA *(2032–2033)*
- O APOLO propõe e executa a própria evolução (currículo, features, re-treinos), medindo o efeito — loop fechado de automelhoria de longo prazo.
- **DoD:** o APOLO demonstra, com números de anos, que dirigiu a própria melhora.

### 🗓️ Ano 9 — SOBERANIA PLENA *(2033–2034)*
- 100% local, **criptografia em repouso**, backup/restauração testados, acesso remoto seguro, portabilidade total.
- Zero dependência externa: cérebro, dados, memória, agência — tudo do Leo, cifrado e portátil.
- **DoD:** tiro tudo da nuvem e nada muda; os dados são inacessíveis a terceiros.

### 🗓️ Ano 10 — O PARCEIRO DE UMA DÉCADA *(2034–2036)*
- Um AI pessoal maduro: raciocina com cérebro próprio, conhece o Leo profundamente, age no mundo com segurança, carrega 10 anos de memória compartilhada.
- **Retrospectiva da década** (falada, com números) + proposta do próximo ciclo.
- **DoD:** o APOLO conta, por voz, o que se tornou em 10 anos — e o que quer ser depois.

---

## 6. Estratégia de hardware `🔒 HW` — o eixo do plano

A capacidade do cérebro é limitada por hardware, e o plano é explícito sobre isso:

| Fase | Hardware | O que destrava |
|------|----------|----------------|
| **Hoje** | Ryzen 4600G, 16GB, CPU-only | Nano ≤ ~7M (laboratório); scaffolding ilimitado; 14B alugado como cérebro |
| **Marco 1** | GPU entrada 12–16GB VRAM | Nano 30–100M em dias; LoRA do 14B com dados do Leo; era da GPU (Anos 3–4) |
| **Marco 2** | GPU 24GB+ / 2ª GPU | Ensemble de especialistas; contexto longo; treino contínuo (Anos 6+) |
| **Marco 3** | Cluster local / edge | Cérebro distribuído, soberania plena em múltiplos dispositivos (Anos 9–10) |

**Recomendação honesta que atravessa a década:** a primeira GPU é o maior salto de valor por real gasto — ela sozinha muda a classe do cérebro e destrava as Épocas 3–4. O plano mede, a cada ano, se o momento chegou (o Ano 2/M24 já propõe essa decisão com dados reais do uso).

---

## 7. Métricas de sucesso da década

- **Soberania:** a cada ano, mais do "cérebro" roda em pesos do Leo (% de tarefas servidas pelo modelo próprio ↑).
- **Capacidade:** a série histórica de eval sobe — o APOLO fica mais capaz, não só mais ativo.
- **Personalização:** o modelo do Leo fica mais profundo e mais certo (curado por ele).
- **Agência:** de "lê com permissão" (Ano 1) a "conduz projetos" (Ano 5) a "dirige a própria evolução" (Ano 8).
- **Presença:** de request-response a co-piloto ambiente que aborda na hora certa.
- **Processo:** todo dia termina verde e melhor que começou. ~2.500 dias assim = um parceiro de uma década.

---

## 8. Como este plano se lê com os outros

- **Este documento** = a visão de 10 anos e a costura dos dois fios. Muda devagar.
- [`JARVIS_ROADMAP.md`](docs/JARVIS_ROADMAP.md) = Ano 1, **concluído** (o corpo).
- [`JARVIS_ROADMAP_ANO2.md`](JARVIS_ROADMAP_ANO2.md) = Ano 2, em curso (cérebro híbrido + conhecer o Leo).
- [`APOLO_NANO_ROADMAP.md`](docs/APOLO_NANO_ROADMAP.md) + [`APOLO_NANO.md`](docs/APOLO_NANO.md) = o cérebro próprio (arquitetura, dados, resultados medidos, teto).
- Anos 3–10 aqui são **direção honesta**, não promessa: cada ciclo os refina com o hardware e os números reais. O que não muda é o destino — um cérebro soberano num corpo que conhece o Leo e age por ele.

> **Regra de ouro da década:** todo dia o sistema termina melhor e verde do que começou. A GPU acelera; a disciplina constrói.

---

*Documento vivo. Criado em 2026-07-09, ao unir a criação da LLM própria com o desenvolvimento do APOLO num só projeto de 10 anos. Ponto de partida: v1.0.0 + Apolo-Nano v1.*
