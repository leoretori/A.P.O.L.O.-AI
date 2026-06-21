"""Memória episódica — indexa conversas no RAG para recall semântico futuro.

Permite ao A.P.O.L.O. recuperar contexto de chats antigos por semântica:
"lembra que discutimos React na semana passada?" → encontra a conversa certa.
"""

MAX_SESSION_CHARS = 4000
MAX_MSG_CHARS = 300


def _condense(messages: list[dict], max_chars: int = MAX_SESSION_CHARS) -> str:
    """Condensa mensagens em texto compacto para indexação."""
    parts = []
    for m in messages:
        role = "Usuário" if m.get("role") == "user" else "A.P.O.L.O."
        text = (m.get("content") or "")[:MAX_MSG_CHARS]
        parts.append(f"{role}: {text}")
    return "\n".join(parts)[:max_chars]


def make_episodic_doc(
    session_id: str,
    title: str,
    messages: list[dict],
    summary: str = "",
) -> tuple[str, str, dict]:
    """Gera (doc_id, conteúdo, metadata) para indexação no RAG.

    O doc começa com '# Conversa: {título}' para que _parse_learned_doc
    extraia título e corpo corretamente no recall.
    """
    doc_id = f"episodic_{session_id[:24]}"
    title_clean = (title or "Conversa").strip()[:80]
    body = f"# Conversa: {title_clean}\n"
    if summary:
        body += f"Resumo: {summary[:600]}\n\n"
    body += _condense(messages)
    metadata = {
        "session_id": session_id,
        "type": "episodic",
        "title": title_clean,
    }
    return doc_id, body, metadata


def index_session(
    session_id: str,
    title: str,
    messages: list[dict],
    rag,
    summary: str = "",
) -> bool:
    """Indexa a conversa no RAG para recall futuro (upsert).

    Requer no mínimo 4 mensagens (2 trocas) para valer a pena indexar.
    Retorna True se indexou, False se ignorou (sessão muito curta ou erro).
    """
    if not messages or len(messages) < 4:
        return False
    doc_id, content, metadata = make_episodic_doc(session_id, title, messages, summary)
    try:
        rag.add_example(content, doc_id, metadata)
        return True
    except Exception:
        return False
