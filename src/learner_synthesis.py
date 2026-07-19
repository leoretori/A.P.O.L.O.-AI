"""Síntese cross-domain do Learner — agrupa o que foi aprendido por domínio,
monta o prompt de síntese estratégica e extrai as auto-queries do LLM."""


# ── Helpers de síntese cross-domain ──────────────────────────

DOMAIN_KEYWORDS = {
    "Python Core":      ["asyncio","typing","python","decorator","generator","dataclass","pep","gil"],
    "Web / API":        ["fastapi","django","rest","http","websocket","graphql","grpc","starlette","api"],
    "Banco de Dados":   ["postgresql","sql","sqlite","redis","mongodb","elasticsearch","query","orm","migration"],
    "Cloud / Infra":    ["aws","gcp","azure","lambda","s3","ecs","kubernetes","docker","terraform","helm"],
    "Data Engineering": ["kafka","airflow","spark","dbt","bigquery","pipeline","etl","streaming","duckdb"],
    "Arquitetura":      ["clean","ddd","cqrs","microservice","hexagonal","saga","event","pattern","solid"],
    "DevOps / CI/CD":   ["github actions","ci","cd","docker","deploy","pipeline","monitoring","observability"],
    "IA / ML":          ["llm","ai","ml","embedding","rag","langchain","ollama","model","vector","agent"],
    "Segurança":        ["auth","jwt","oauth","owasp","secret","security","ssl","zero trust"],
    "GitHub / OSS":     ["trending","github","readme","repository","open source"],
}


def _looks_degenerate(q: str) -> bool:
    """Sinal barato de query degenerada (achado real, 2026-07-19): o modelo
    pequeno, ao ser cobrado por queries em inglês, às vezes inventa palavras
    ("urbanatura", "sufrufeauurafrius") em vez de gerar uma busca de verdade —
    e como essas viravam tópicos "estudados" que voltavam pro PRÓPRIO prompt de
    síntese (`_cluster_topics`/"Outros"), o modelo via as invenções no contexto
    e continuava inventando mais, num loop que piorou por mais de um mês.

    Dois sinais SEM dicionário (não temos um bundled — checagem determinística
    e barata, não perfeita): (1) barra separando dois termos LONGOS — a forma
    exata observada ("urburation/urbanatura"), diferente de abreviações reais
    como "CI/CD" ou "pub/sub"; (2) uma palavra isolada absurdamente longa —
    termos técnicos reais raramente passam de ~20 caracteres num token só."""
    import re
    slash_parts = q.split("/")
    if len(slash_parts) > 1:
        for i in range(len(slash_parts) - 1):
            left = re.findall(r"[A-Za-zÀ-ÿ]+$", slash_parts[i].strip())
            right = re.findall(r"^[A-Za-zÀ-ÿ]+", slash_parts[i + 1].strip())
            if left and right and len(left[0]) > 6 and len(right[0]) > 6:
                return True
    if any(len(w) > 20 for w in re.findall(r"[A-Za-zÀ-ÿ]+", q)):
        return True
    return False


def _extract_self_queries(synthesis: str) -> list[str]:
    """Extrai as queries auto-geradas (linhas '🎯 QUERY: ...') da síntese."""
    import re
    queries: list[str] = []
    for line in synthesis.splitlines():
        if "QUERY:" not in line:
            continue
        q = line.split("QUERY:", 1)[1].strip(" *_`\"'-").strip()
        q = re.sub(r"\s+", " ", q)  # normaliza espaços internos
        # Sanidade: precisa parecer uma query buscável de verdade E não ser
        # o padrão degenerado observado (ver `_looks_degenerate`).
        if 12 <= len(q) <= 140 and " " in q and not _looks_degenerate(q):
            queries.append(q)
    # Dedup por forma NORMALIZADA (ignora pontuação/maiúsculas) — assim
    # "Redis pub/sub" e "redis pub sub?" não viram dois estudos do mesmo tema.
    seen, unique = set(), []
    for q in queries:
        # Pontuação vira espaço (pub/sub == pub sub) e espaços são colapsados.
        key = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", q.lower())).strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(q)
    return unique[:6]


def _cluster_topics(history: list[dict]) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = {d: [] for d in DOMAIN_KEYWORDS}
    clusters["Outros"] = []
    for item in history:
        text = (item["topic"] + " " + (item["summary"] or "")[:200]).lower()
        placed = False
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(k in text for k in keywords):
                clusters[domain].append(item["topic"][:80])
                placed = True
                break
        if not placed:
            clusters["Outros"].append(item["topic"][:80])
    return {k: v for k, v in clusters.items() if v}


SYNTHESIS_CROSS_PROMPT = """Você é A.P.O.L.O., arquiteto de sistemas de elite.

Você aprendeu os seguintes tópicos, agrupados por domínio:

{clusters_text}

Crie uma SÍNTESE ESTRATÉGICA DE CRUZAMENTO DE CONHECIMENTO:

## Mapa de Integração
[Como esses domínios se conectam numa stack real — desenhe o fluxo completo de uma aplicação moderna usando os componentes acima]

## Padrões Cross-Domain Identificados
[3-4 padrões que aparecem em múltiplos domínios — ex: "async aparece em Python, FastAPI, banco de dados e Kafka"]

## Stack de Referência A.P.O.L.O.
[Baseado no que foi estudado, qual seria a stack ideal para uma aplicação de produção? Por quê cada escolha?]

## Gaps de Conhecimento
[Que áreas importantes ainda não foram estudadas? Quais conexões estão faltando?]

## Próximos Estudos Estratégicos
Você é uma IA AUTÔNOMA: decida sozinho o que estudar a seguir para preencher os gaps acima e
aumentar sua autonomia, automelhoria e inteligência. Liste EXATAMENTE 6 queries de busca.
FORMATO OBRIGATÓRIO — cada uma em sua própria linha, exatamente assim:
🎯 QUERY: <query técnica específica e buscável em inglês>

Exemplo de formato:
🎯 QUERY: LangGraph stateful agent checkpointing Python production
🎯 QUERY: autonomous AI self-correction loop implementation Python

Síntese em português brasileiro — seja estratégico, arquitetural e acionável:"""


def _build_synthesis_prompt(clusters: dict[str, list[str]]) -> str:
    """Achado real (2026-07-19): "Outros" acumulava tópicos NÃO classificados —
    inclusive, com frequência, títulos degenerados que o próprio Auto-Currículo
    gerou (o modelo pequeno inventa palavras como "urbanatura"/"urburation" ao
    ser cobrado por queries em inglês). Mostrar esse lixo de volta ao modelo
    como "tópicos que você estudou" alimentava um loop: ele via as palavras
    inventadas no próprio contexto e continuava inventando mais. "Outros" fica
    de FORA do prompt — não é conhecimento estruturado o suficiente pra guiar o
    próximo estudo, e no caso comum é justamente o lixo que não queremos
    realimentar."""
    lines = []
    for domain, topics in clusters.items():
        if domain == "Outros":
            continue
        lines.append(f"\n**{domain}** ({len(topics)} tópicos):")
        for t in topics[:6]:
            lines.append(f"  - {t}")
    return SYNTHESIS_CROSS_PROMPT.format(clusters_text="\n".join(lines))
