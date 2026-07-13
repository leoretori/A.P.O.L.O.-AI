"""Memória episódica/autobiográfica (M2, Épico 2.2).

Cada conversa vira um EPISÓDIO resumido e datado ("2026-07-06: fechamos o Épico
2.1 do MemoryFabric"). Isso dá ao A.P.O.L.O. uma linha do tempo do que ele e o
usuário fizeram — e o recall TEMPORAL que responde "o que a gente fez ontem?".

`EpisodicMemory` orquestra: (1) resumir uma sessão num episódio (via LLM) e
persistir; (2) recuperar episódios por janela de tempo, inclusive traduzindo
frases naturais ("ontem", "semana passada") em intervalos de datas.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("apolo.memory.episodic")

EPISODE_PROMPT = """Você é a memória autobiográfica do A.P.O.L.O. Resuma a conversa
abaixo como UM episódio — o que foi feito/decidido/aprendido, do ponto de vista
de "nós" (você e o usuário trabalhando juntos).

Responda em português, EXATAMENTE neste formato:
TÍTULO: <uma frase curta no passado, ex: "fechamos o painel de auditoria">
RESUMO: <2-3 frases com o que rolou de mais importante>

CONVERSA:
{transcript}
"""

# Mínimo de mensagens para valer um episódio (conversas triviais não viram memória).
MIN_MESSAGES = 4


class EpisodicMemory:
    def __init__(self, db=None, summarize_fn=None):
        """`db` expõe os métodos de episódio (save_episode/get_episodes_between/…).
        `summarize_fn(prompt)->str` gera o resumo; default usa o LLM leve."""
        self.db = db
        self._summarize_fn = summarize_fn

    # ── Escrita ───────────────────────────────────────────────
    def record(self, session_id: str, messages: list[dict],
               occurred_at: datetime | None = None) -> dict | None:
        """Resume as mensagens de uma sessão num episódio datado e persiste.
        Retorna o episódio salvo (dict) ou None se curto demais / sem db."""
        if not self.db or len(messages or []) < MIN_MESSAGES:
            return None
        transcript = _format_transcript(messages)
        title, summary = self._summarize(transcript)
        if not title:
            return None
        ep_id = self.db.save_episode(
            title=title, summary=summary, session_id=session_id,
            occurred_at=occurred_at or datetime.now(),
        )
        logger.info(f"[episodic] episódio salvo: {title[:80]}")
        return {"id": ep_id, "title": title, "summary": summary,
                "session_id": session_id}

    def _summarize(self, transcript: str) -> tuple[str, str]:
        fn = self._summarize_fn or _default_summarize
        try:
            raw = fn(EPISODE_PROMPT.format(transcript=transcript[:4000]))
        except Exception as e:
            logger.warning(f"[episodic] resumo falhou: {e}")
            return "", ""
        return _parse_episode(raw or "")

    # ── Leitura temporal ──────────────────────────────────────
    def recall_between(self, start: datetime, end: datetime, limit: int = 50) -> list[dict]:
        if not self.db:
            return []
        return self.db.get_episodes_between(start, end, limit)

    def recall_phrase(self, phrase: str, limit: int = 50,
                      now: datetime | None = None) -> list[dict] | None:
        """Traduz uma frase temporal ('ontem', 'semana passada') numa janela e
        recupera os episódios dela. Retorna None se a frase não for temporal."""
        window = parse_when(phrase, now or datetime.now())
        if window is None:
            return None
        start, end = window
        return self.recall_between(start, end, limit)

    def recent(self, limit: int = 20) -> list[dict]:
        if not self.db:
            return []
        return self.db.recent_episodes(limit)

    # ── Consolidação ("sono") ─────────────────────────────────
    def consolidate(self, inactive_minutes: int = 180, min_messages: int = 4,
                    max_sessions: int = 10) -> dict:
        """Varre conversas encerradas (inativas há `inactive_minutes`) e ainda sem
        episódio, e as resume automaticamente — o gatilho que faltava no 2.2.
        Inspirado na consolidação de memória do sono: transforma o corriqueiro
        (mensagens soltas) em memória de longo prazo (episódios datados).
        Retorna {'consolidated': n, 'titles': [...]}."""
        if not self.db:
            return {"consolidated": 0, "titles": []}
        from src.storage_models import _now
        cutoff = _now() - timedelta(minutes=inactive_minutes)
        pending = self.db.sessions_pending_episode(cutoff, min_messages, max_sessions)
        titles: list[str] = []
        for p in pending:
            messages = self.db.load_session(p["session_id"])
            occurred = _to_local_naive(p.get("last_active"))
            ep = self.record(p["session_id"], messages, occurred_at=occurred)
            if ep:
                titles.append(ep["title"])
        if titles:
            logger.info(f"[episodic] consolidação: {len(titles)} episódio(s) novo(s)")
        return {"consolidated": len(titles), "titles": titles}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        if not self.db:
            return []
        return self.db.search_episodes(query, limit)


# ── Helpers ───────────────────────────────────────────────────

def _format_transcript(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        who = "Usuário" if m.get("role") == "user" else "A.P.O.L.O."
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{who}: {content[:500]}")
    return "\n".join(lines)


def _parse_episode(raw: str) -> tuple[str, str]:
    title, summary = "", ""
    for line in raw.splitlines():
        low = line.strip()
        if low.upper().startswith("TÍTULO:") or low.upper().startswith("TITULO:"):
            title = line.split(":", 1)[1].strip(" *_-\"'")
        elif low.upper().startswith("RESUMO:"):
            summary = line.split(":", 1)[1].strip(" *_-\"'")
    # Fallback: sem formato → usa a 1ª linha como título.
    if not title:
        first = next((l.strip() for l in raw.splitlines() if l.strip()), "")
        title = first[:200]
    return title[:300], summary[:2000]


def _to_local_naive(value) -> datetime | None:
    """Normaliza um timestamp do banco (datetime aware/naive ou string ISO) para
    hora LOCAL naive — o mesmo referencial que `parse_when` usa (datetime.now()),
    para que 'ontem' caia no dia certo mesmo com mensagens gravadas em UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:                 # naive → assume UTC (como _now grava)
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().replace(tzinfo=None)


def _default_summarize(prompt: str) -> str:
    from src.llm import chat_resilient, KEEP_ALIVE
    from src import runtime as rt
    # A consolidação ("sono") roda em thread de fundo (asyncio.to_thread, tick de
    # 30min) e pode resumir até 10 sessões numa rodada — sem ceder o GpuGate,
    # seguraria o lock do motor e faria o chat do usuário esperar atrás dela
    # (mesma classe de bug corrigida no flywheel/blind_eval do Nano).
    if rt.gpu_gate:
        rt.gpu_gate.wait_for_idle_sync()
    model = rt.get_chat_model() or rt.model
    return chat_resilient(model, [{"role": "user", "content": prompt}],
                          keep_alive=KEEP_ALIVE)


def _day_bounds(d: datetime) -> tuple[datetime, datetime]:
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def parse_when(phrase: str, now: datetime) -> tuple[datetime, datetime] | None:
    """Converte frases temporais em português numa janela [start, end).
    Retorna None se não reconhecer nenhuma expressão de tempo."""
    p = (phrase or "").lower()
    today_start, today_end = _day_bounds(now)

    if "anteontem" in p:
        s, _ = _day_bounds(now - timedelta(days=2))
        return s, s + timedelta(days=1)
    if "ontem" in p:
        s, e = _day_bounds(now - timedelta(days=1))
        return s, e
    if "hoje" in p:
        return today_start, today_end
    if "semana passada" in p:
        # Semana anterior (segunda a domingo).
        this_monday = today_start - timedelta(days=now.weekday())
        last_monday = this_monday - timedelta(days=7)
        return last_monday, this_monday
    if ("essa semana" in p or "esta semana" in p or "nesta semana" in p
            or "última semana" in p or "ultima semana" in p
            or "últimos dias" in p or "ultimos dias" in p):
        this_monday = today_start - timedelta(days=now.weekday())
        return this_monday, today_end
    if "mês passado" in p or "mes passado" in p:
        first_this = today_start.replace(day=1)
        last_month_end = first_this
        prev = first_this - timedelta(days=1)
        first_prev = prev.replace(day=1)
        return first_prev, last_month_end
    if "esse mês" in p or "este mês" in p or "esse mes" in p or "este mes" in p:
        return today_start.replace(day=1), today_end
    # "últimos N dias" / "N dias atrás"
    import re
    m = re.search(r"(\d{1,3})\s*dias", p)
    if m:
        n = int(m.group(1))
        return today_start - timedelta(days=n), today_end
    return None
