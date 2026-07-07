"""Tipos e prompts do Learner — itens do pipeline (FetchedItem/LearnedItem),
constantes de configuração e templates de sumarização (código vs. geral)."""

import os
from dataclasses import dataclass, field
from datetime import datetime


# ── Configuração do pipeline ──────────────────────────────────
FETCH_QUEUE_MAX   = 12   # buffer máximo de itens prontos para sumarizar
SYNTHESIS_EVERY   = 6    # dispara síntese a cada N itens salvos
# Ollama fora do ar → o summarizer PAUSA e re-checa a cada N segundos,
# em vez de queimar o currículo inteiro descartando tópico por tópico.
LLM_DOWN_BACKOFF  = float(os.getenv("LLM_DOWN_BACKOFF", 30))
MAX_CONTENT_CHARS = 3500 # limita conteúdo enviado ao LLM (mais rápido)
# Teto para a persistência de UM item (SQLite + Supabase + RAG). Impede que uma
# escrita lenta em rede ruim segure o pipeline (o save roda em background, mas
# sem teto uma pendência acumula threads do pool e pode congelar o aprendizado).
PERSIST_TIMEOUT   = float(os.getenv("PERSIST_TIMEOUT", 45))


@dataclass
class FetchedItem:
    topic: str
    url: str
    content: str
    category: str
    agent_name: str
    retries: int = 0   # tentativas de sumarização já feitas


@dataclass
class LearnedItem:
    topic: str
    url: str
    summary: str
    category: str
    agent_name: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M"))


SUMMARIZE_PROMPT = """Você é A.P.O.L.O., agente de IA de elite em engenharia de software.

Sintetize "{topic}" em português brasileiro:

## Conceitos-chave
[3-4 pontos fundamentais — direto ao ponto]

## Como usar
[Código real ou passos concretos de produção]

## Integração
[Como se conecta com outras tecnologias do ecossistema]

## Insight A.P.O.L.O.
[O ponto mais importante para um engenheiro sênior lembrar]

CONTEÚDO:
{content}

Síntese (técnica, densa, sem enrolação):"""

# Conhecimento GERAL (enciclopédia, livros) não é código: sintetizar "Teoria da
# relatividade" com template de engenharia ("Como usar — código real") produzia
# lixo. Cada categoria usa o template certo.
SUMMARIZE_PROMPT_GERAL = """Você é A.P.O.L.O., mente enciclopédica de elite.

Sintetize "{topic}" em português brasileiro:

## Essência
[O conceito explicado em 2-3 frases claras]

## Pontos-chave
[4-6 fatos ou ideias centrais — os que realmente importam]

## Conexões
[Como este tema se liga a outras áreas do conhecimento]

## Insight A.P.O.L.O.
[A compreensão mais valiosa para reter deste tema]

CONTEÚDO:
{content}

Síntese (clara, densa, fiel ao conteúdo — não invente fatos):"""

# Categorias de conhecimento geral → usam o template enciclopédico.
GENERAL_CATEGORIES = {"encyclopedia", "book"}
