"""Exportador de conhecimento A.P.O.L.O. para vault Obsidian.

Gera um arquivo ZIP com:
  _Indice.md              — visao geral com stats e links para todos os setores
  _Mapa de Setores.md     — tabela de todos os setores com contagens
  {Setor}.md              — um arquivo por setor com todos os topicos como secoes,
                            resumos, fontes e [[links]] para topicos relacionados

Os links internos usam a sintaxe [[Nome do Arquivo]] do Obsidian.
Topicos relacionados sao encontrados por sobreposicao de palavras-chave
(sem LLM — rapido e funciona offline).
"""

import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone


# Emojis por setor (fallback: "📌")
_SECTOR_EMOJI = {
    "backend": "⚙️", "frontend": "🎨", "mobile": "📱",
    "data_ml": "🤖", "data_engineering": "🔧", "sistemas": "💻",
    "devops": "🚀", "sre_reliability": "📡", "bancos": "🗄️",
    "segurança": "🔒", "ai_agents": "🧠", "game": "🎮",
    "graphics_xr": "🥽", "embedded_iot": "🔌", "blockchain": "🪙",
    "cs_fundamentals": "📐", "networking_protocols": "🌐",
    "testing_qa": "✅", "quantum_computing": "⚛️",
    "robotics_automation": "🤖",
    "ciência": "🔬", "matemática": "📊", "finanças": "💰",
    "produtividade": "⚡", "comunicação": "💬", "design": "🎨",
    "negócios": "💼", "career_growth": "📈", "law_compliance": "⚖️",
    "saúde": "🏥", "história": "📜", "arts_creativity": "🎭",
    "investing_markets": "📈", "crypto_finance": "🪙",
    "accounting_tax": "🧾", "macroeconomics": "🏛️",
    "pharmacology": "💊", "public_health": "🏥",
    "biotech_genomics": "🧬", "politics_government": "🏛️",
    "languages_learning": "🗣️", "agriculture_food": "🌱",
    "psychology": "🧠", "education_pedagogy": "📚",
    "environment_sustainability": "🌱", "cooking_nutrition": "🍽️",
    "space_astronomy": "🚀", "geography_geopolitics": "🌍",
    "marketing_sales": "📣", "sports_fitness": "💪",
    "engineering_physical": "🔩",
    "web_search": "🔍", "synthesis": "🔀", "outros": "📌",
}

_STOPWORDS = {
    "de","a","o","e","em","do","da","no","na","para","com","que","se","um","uma",
    "os","as","dos","das","por","mais","como","ao","e","é","são","foi","tem","the",
    "is","in","of","to","and","an","for","on","with","this","that","it","how",
    "what","why","when","can","use","using","get","make","vs","via",
}


def _safe_filename(name: str) -> str:
    """Converte nome de setor/topico para nome de arquivo seguro."""
    name = name.strip()
    # Remove caracteres proibidos no Windows/macOS
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:80] or "Sem_Nome"


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"\b[a-zA-ZÀ-ú]{3,}\b", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _related_topics(topic: str, candidates: list[str], top: int = 5) -> list[str]:
    """Retorna os candidatos mais relacionados por sobreposicao de tokens."""
    tokens = _tokenize(topic)
    if not tokens:
        return []
    scored = []
    for c in candidates:
        if c == topic:
            continue
        overlap = len(tokens & _tokenize(c))
        if overlap >= 1:
            scored.append((overlap, c))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _, c in scored[:top]]


def _fmt_date(dt) -> str:
    if not dt:
        return "—"
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(dt)[:10]


def _sector_label(sector: str) -> str:
    """Label legivel para o setor (usa SECTOR_LABELS se disponivel)."""
    try:
        from src.topics import SECTOR_LABELS
        return SECTOR_LABELS.get(sector, sector.replace("_", " ").title())
    except Exception:
        return sector.replace("_", " ").title()


def _sector_filename(sector: str) -> str:
    return _safe_filename(_sector_label(sector))


# ── Geradores de conteudo Markdown ────────────────────────────────────────────

def _build_index(sectors: dict[str, list[dict]], total: int, stamp: str) -> str:
    lines = [
        "# ☀️ A.P.O.L.O. — Base de Conhecimento",
        "",
        f"> Exportado em **{stamp}** | **{total}** tópicos | **{len(sectors)}** setores",
        "",
        "## Setores",
        "",
        "| Setor | Tópicos | Arquivo |",
        "|-------|---------|---------|",
    ]
    for sector, topics in sorted(sectors.items(), key=lambda kv: -len(kv[1])):
        label = _sector_label(sector)
        emoji = _SECTOR_EMOJI.get(sector, "📌")
        fname = _sector_filename(sector)
        lines.append(f"| {emoji} {label} | {len(topics)} | [[{fname}]] |")

    lines += [
        "",
        "## Como navegar",
        "",
        "- Clique em qualquer [[link]] para abrir o arquivo do setor",
        "- Dentro de cada setor, os tópicos têm **Relacionados** que ligam a outros setores",
        "- Use `Ctrl+Shift+F` no Obsidian para buscar por qualquer termo",
        "- O **Grafo** do Obsidian (`Ctrl+G`) mostra a rede de conexões",
        "",
        "## Estatísticas",
        "",
        f"- Total de tópicos aprendidos: **{total}**",
        f"- Setores com conhecimento: **{len(sectors)}**",
        f"- Exportado: {stamp}",
    ]
    return "\n".join(lines)


def _build_sector_file(sector: str, topics: list[dict],
                       all_topics: list[str]) -> str:
    label = _sector_label(sector)
    emoji = _SECTOR_EMOJI.get(sector, "📌")
    lines = [
        f"# {emoji} {label}",
        "",
        f"> {len(topics)} tópicos aprendidos neste setor",
        "",
        "[[_Indice|← Índice Geral]]",
        "",
        "---",
        "",
    ]

    for t in sorted(topics, key=lambda x: (x.get("topic") or "").lower()):
        topic = (t.get("topic") or "").strip()
        if not topic:
            continue
        url = (t.get("url") or "").strip()
        summary = (t.get("summary") or "").strip()
        date = _fmt_date(t.get("studied_at"))
        cat = (t.get("category") or "").strip()

        lines.append(f"## {topic}")
        lines.append("")

        if date != "—":
            lines.append(f"**Estudado em:** {date}  ")
        if cat:
            lines.append(f"**Categoria:** `{cat}`  ")
        if url:
            # URL curta para exibicao
            domain = re.sub(r"https?://(?:www\.)?", "", url).split("/")[0]
            lines.append(f"**Fonte:** [{domain}]({url})  ")
        lines.append("")

        if summary:
            # Limita o resumo a 800 chars para nao poluir o arquivo
            excerpt = summary.strip()[:800]
            if len(summary) > 800:
                excerpt += "…"
            lines.append(excerpt)
            lines.append("")

        # Links relacionados (sobreposicao de palavras)
        related = _related_topics(topic, all_topics, top=5)
        if related:
            rel_links = " · ".join(f"[[{r}]]" for r in related)
            lines.append(f"**Relacionados:** {rel_links}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _build_map(sectors: dict[str, list[dict]], stamp: str) -> str:
    """Mapa de setores com barras de tamanho proporcional."""
    max_count = max((len(v) for v in sectors.values()), default=1)
    lines = [
        "# 🗺️ Mapa de Setores",
        "",
        f"> {stamp}",
        "",
        "| Setor | Tópicos | Proporção |",
        "|-------|---------|-----------|",
    ]
    for sector, topics in sorted(sectors.items(), key=lambda kv: -len(kv[1])):
        label = _sector_label(sector)
        emoji = _SECTOR_EMOJI.get(sector, "📌")
        count = len(topics)
        bar = "█" * max(1, round(count / max_count * 20))
        lines.append(f"| [[{_sector_filename(sector)}\\|{emoji} {label}]] | {count} | {bar} |")
    return "\n".join(lines)


# ── Ponto de entrada ──────────────────────────────────────────────────────────

def generate_vault(db, knowledge_db=None, limit: int = 5000) -> bytes:
    """Gera o vault Obsidian completo como bytes de um arquivo ZIP.

    Args:
        db: DatabaseManager do A.P.O.L.O. (SQLite).
        knowledge_db: base de conhecimento Supabase/Local (opcional — enriquece).
        limit: maximo de topicos a exportar.

    Returns:
        bytes do arquivo ZIP pronto para download.
    """
    from src.topics import classify_sector

    # ── 1. Coleta dados ───────────────────────────────────────────────────────
    history: list[dict] = db.get_learning_history(limit=limit)

    # Enriquece com artigos da base de conhecimento (se disponivel)
    kb_topics: list[dict] = []
    if knowledge_db:
        try:
            rows = knowledge_db.all_rows(2000)
            for r in rows:
                kb_topics.append({
                    "topic": r.get("title", ""),
                    "url": r.get("url", ""),
                    "summary": (r.get("content") or "")[:600],
                    "category": r.get("category", "web"),
                    "studied_at": r.get("updated_at"),
                })
        except Exception:
            pass

    # Unifica, dedup por topico normalizado
    all_records: list[dict] = list(history)
    seen = {(t.get("topic") or "").strip().lower() for t in history}
    for r in kb_topics:
        key = (r.get("topic") or "").strip().lower()
        if key and key not in seen:
            all_records.append(r)
            seen.add(key)

    # ── 2. Classifica por setor ───────────────────────────────────────────────
    sectors: dict[str, list[dict]] = defaultdict(list)
    for record in all_records:
        topic_text = record.get("topic") or ""
        if not topic_text.strip():
            continue
        sector = classify_sector(f"{topic_text} {record.get('category','')}")
        sectors[sector].append(record)

    # Lista de todos os nomes de topicos para calculo de relacionados
    all_topic_names = [
        (r.get("topic") or "").strip()
        for r in all_records
        if (r.get("topic") or "").strip()
    ]

    total = sum(len(v) for v in sectors.values())
    stamp = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    # ── 3. Gera ZIP em memoria ────────────────────────────────────────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        folder = f"APOLO_{datetime.now().strftime('%Y%m%d')}/"

        # Indice geral
        zf.writestr(
            folder + "_Indice.md",
            _build_index(sectors, total, stamp).encode("utf-8"),
        )

        # Mapa de setores
        zf.writestr(
            folder + "_Mapa de Setores.md",
            _build_map(sectors, stamp).encode("utf-8"),
        )

        # Um arquivo por setor
        for sector, topics in sectors.items():
            content = _build_sector_file(sector, topics, all_topic_names)
            fname = _sector_filename(sector) + ".md"
            zf.writestr(folder + fname, content.encode("utf-8"))

    return buf.getvalue()
