"""DatabaseManager — aprendizado: tópicos estudados, diário do Coder, feed de
atividade/auditoria, qualidade de sínteses e estatísticas. Mixin."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src.storage_models import (
    _now, RELEARN_DAYS, Execution, Notification,
    LearnedTopic, CoderTask, BenchmarkRun, ReviewSchedule, TopicEdge,
)


def _canon(a: str, b: str) -> tuple[str, str]:
    """Ordena o par para guardar a aresta 1× (grafo não-direcionado)."""
    a, b = (a or "").strip(), (b or "").strip()
    return (a, b) if a <= b else (b, a)


def _edge_dict(r) -> dict:
    return {"a": r.a, "b": r.b, "weight": r.weight,
            "shared": [c for c in (r.shared or "").split(";") if c]}


def _review_dict(r) -> dict:
    return {"topic": r.topic, "ease": r.ease, "interval": r.interval,
            "reps": r.reps, "lapses": r.lapses,
            "due_at": r.due_at.isoformat() if r.due_at else None,
            "last_reviewed": r.last_reviewed.isoformat() if r.last_reviewed else None}


class LearningMixin:
    # ── Tópicos aprendidos ────────────────────────────────────
    def save_learned_topic(self, topic: str, url: str, summary: str, category: str = "web",
                           verified: str | None = None) -> None:
        with Session(self.engine) as s:
            s.add(LearnedTopic(topic=topic, url=url, summary=summary, category=category,
                               verified=verified))
            s.commit()

    # ── Repetição espaçada (M8 8.1) ───────────────────────────
    def upsert_review(self, topic: str, ease: float, interval: int, reps: int,
                      lapses: int, due_at: datetime, last_reviewed: datetime | None = None) -> None:
        """Grava/atualiza a agenda de revisão SM-2 de um tópico (chave = topic)."""
        topic = (topic or "").strip()
        if not topic:
            return
        with Session(self.engine) as s:
            row = s.get(ReviewSchedule, topic)
            if not row:
                row = ReviewSchedule(topic=topic)
                s.add(row)
            row.ease, row.interval, row.reps, row.lapses = ease, interval, reps, lapses
            row.due_at, row.last_reviewed = due_at, last_reviewed
            s.commit()

    def get_review(self, topic: str) -> dict | None:
        with Session(self.engine) as s:
            row = s.get(ReviewSchedule, (topic or "").strip())
            return _review_dict(row) if row else None

    def due_reviews(self, now: datetime | None = None, limit: int = 20) -> list[dict]:
        """Tópicos vencidos para auto-teste, mais atrasados primeiro."""
        now = now or _now()
        with Session(self.engine) as s:
            rows = (s.query(ReviewSchedule)
                    .filter(ReviewSchedule.due_at <= now)
                    .order_by(ReviewSchedule.due_at.asc()).limit(limit).all())
            return [_review_dict(r) for r in rows]

    def count_reviews(self) -> int:
        with Session(self.engine) as s:
            return s.query(ReviewSchedule).count()

    # ── Grafo de conhecimento (M8 8.3) ────────────────────────
    def add_edge(self, a: str, b: str, weight: float, shared: list[str]) -> None:
        """Cria/atualiza a aresta entre dois tópicos (ordem canônica). Ignora
        laço trivial (a == b) ou peso zero."""
        a, b = _canon(a, b)
        if not a or not b or a == b:
            return
        with Session(self.engine) as s:
            row = s.get(TopicEdge, (a, b))
            if not row:
                row = TopicEdge(a=a, b=b)
                s.add(row)
            row.weight = round(float(weight), 3)
            row.shared = ";".join(dict.fromkeys(shared or []))[:800]
            row.updated_at = _now()
            s.commit()

    def get_edge(self, a: str, b: str) -> dict | None:
        a, b = _canon(a, b)
        with Session(self.engine) as s:
            row = s.get(TopicEdge, (a, b))
            return _edge_dict(row) if row else None

    def neighbors(self, topic: str, limit: int = 12) -> list[dict]:
        """Tópicos ligados a `topic`, mais fortes primeiro. Cada item:
        {topic, weight, shared}."""
        topic = (topic or "").strip()
        with Session(self.engine) as s:
            rows = (s.query(TopicEdge)
                    .filter((TopicEdge.a == topic) | (TopicEdge.b == topic))
                    .order_by(TopicEdge.weight.desc()).limit(limit).all())
            out = []
            for r in rows:
                other = r.b if r.a == topic else r.a
                out.append({"topic": other, "weight": r.weight,
                            "shared": [c for c in (r.shared or "").split(";") if c]})
            return out

    def find_bridge(self, a: str, b: str) -> dict | None:
        """Ponte de 2 saltos: um tópico ligado A AMBOS. Retorna
        {bridge, a_shared, b_shared} do melhor (maior peso somado) ou None."""
        na = {n["topic"]: n for n in self.neighbors(a, 50)}
        nb = {n["topic"]: n for n in self.neighbors(b, 50)}
        commons = set(na) & set(nb) - {a, b}
        if not commons:
            return None
        best = max(commons, key=lambda z: na[z]["weight"] + nb[z]["weight"])
        return {"bridge": best, "a_shared": na[best]["shared"],
                "b_shared": nb[best]["shared"]}

    def count_edges(self) -> int:
        with Session(self.engine) as s:
            return s.query(TopicEdge).count()

    def get_topic_summary(self, topic: str) -> str | None:
        """Síntese mais recente já salva para o tópico (M8 8.2: comparar fatos ao
        re-estudar). None se nunca estudado."""
        with Session(self.engine) as s:
            row = (s.query(LearnedTopic)
                   .filter(LearnedTopic.topic == topic)
                   .order_by(LearnedTopic.studied_at.desc()).first())
            return row.summary if row else None

    def is_url_studied(self, url: str) -> bool:
        """Evita re-estudar a mesma URL — mas libera após RELEARN_DAYS (refresh)."""
        with Session(self.engine) as s:
            q = s.query(LearnedTopic).filter(LearnedTopic.url == url)
            if RELEARN_DAYS > 0:
                q = q.filter(LearnedTopic.studied_at >= _now() - timedelta(days=RELEARN_DAYS))
            return q.count() > 0

    def is_topic_studied(self, topic: str) -> bool:
        """Anti-duplicação na rotação dos agentes — mas libera após RELEARN_DAYS (refresh)."""
        if not topic:
            return False
        with Session(self.engine) as s:
            q = s.query(LearnedTopic).filter(LearnedTopic.topic == topic)
            if RELEARN_DAYS > 0:
                q = q.filter(LearnedTopic.studied_at >= _now() - timedelta(days=RELEARN_DAYS))
            return q.first() is not None

    def delete_learned_topic(self, topic_id: int) -> dict | None:
        """Remove um conhecimento (e todos os re-estudos do mesmo tópico) do log.
        Retorna {topic, url} para o caller propagar a remoção a Supabase/RAG."""
        with Session(self.engine) as s:
            row = s.get(LearnedTopic, topic_id)
            if not row:
                return None
            topic, url = row.topic, row.url
            (s.query(LearnedTopic).filter(LearnedTopic.topic == topic)
             .delete(synchronize_session=False))
            s.commit()
            return {"topic": topic, "url": url}

    def count_topic_duplicates(self) -> int:
        """Quantos registros são re-estudos do mesmo tópico (excedentes)."""
        with Session(self.engine) as s:
            total = s.query(LearnedTopic).count()
            from sqlalchemy import func, distinct
            uniq = s.query(func.count(distinct(LearnedTopic.topic))).scalar() or 0
        return max(0, total - uniq)

    def dedup_learned_topics(self) -> int:
        """Remove re-estudos repetidos do log, mantendo o registro mais recente de cada
        tópico. Retorna quantos foram removidos."""
        with Session(self.engine) as s:
            rows = (s.query(LearnedTopic.id, LearnedTopic.topic)
                    .order_by(LearnedTopic.studied_at.desc()).all())
            seen: set[str] = set()
            to_del: list[int] = []
            for rid, topic in rows:
                key = (topic or "").strip().lower()
                if key in seen:
                    to_del.append(rid)
                else:
                    seen.add(key)
            for i in range(0, len(to_del), 500):
                (s.query(LearnedTopic)
                 .filter(LearnedTopic.id.in_(to_del[i:i + 500]))
                 .delete(synchronize_session=False))
            if to_del:
                s.commit()
        return len(to_del)

    def get_learning_history(self, limit: int = 30) -> list[dict]:
        """Tópicos aprendidos, SEM repetir o mesmo tópico (mostra o mais recente de cada).
        Evita a sensação de 'repetindo muito' no dashboard."""
        with Session(self.engine) as s:
            rows = (s.query(LearnedTopic)
                    .order_by(LearnedTopic.studied_at.desc())
                    .limit(limit * 6).all())
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            key = (r.topic or "").strip().lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"id": r.id, "topic": r.topic, "url": r.url,
                        "summary": r.summary, "category": r.category,
                        "studied_at": r.studied_at.isoformat(), "verified": r.verified})
            if len(out) >= limit:
                break
        return out

    # ── Diário de tarefas do Coder ────────────────────────────
    def save_coder_task(self, task: str, model: str = "", steps: int = 0,
                        wrote: bool = False, ran: bool = False, reverted: bool = False,
                        duration_s: float = 0.0, summary: str = "") -> int:
        with Session(self.engine) as s:
            row = CoderTask(task=task[:500], model=model, steps=steps, wrote=wrote,
                            ran=ran, reverted=reverted, duration_s=round(duration_s, 1),
                            summary=(summary or "")[:400])
            s.add(row); s.commit()
            return row.id

    def get_coder_tasks(self, limit: int = 20) -> list[dict]:
        with Session(self.engine) as s:
            rows = (s.query(CoderTask)
                    .order_by(CoderTask.id.desc()).limit(limit).all())
            return [{"id": r.id, "created_at": r.created_at.isoformat(),
                     "task": r.task, "model": r.model, "steps": r.steps,
                     "wrote": r.wrote, "ran": r.ran, "reverted": r.reverted,
                     "duration_s": r.duration_s, "summary": r.summary} for r in rows]

    def get_coder_stats(self, window: int = 10) -> dict:
        """Taxa de sucesso do Coder + TENDÊNCIA: compara a janela recente com a
        anterior (medir → melhorar → provar — as lições estão funcionando?)."""
        from sqlalchemy import func
        with Session(self.engine) as s:
            total = s.query(func.count(CoderTask.id)).scalar() or 0
            reverted = (s.query(func.count(CoderTask.id))
                        .filter(CoderTask.reverted == True).scalar() or 0)
            flags = [r.reverted for r in
                     s.query(CoderTask.reverted)
                      .order_by(CoderTask.id.desc()).limit(window * 2).all()]

        def _rate(fs: list) -> int | None:
            return round(100 * sum(1 for f in fs if not f) / len(fs)) if fs else None

        recent_rate = _rate(flags[:window])
        prev_rate = _rate(flags[window:window * 2])
        trend = (recent_rate - prev_rate
                 if recent_rate is not None and prev_rate is not None else None)
        return {"total": total, "reverted": reverted,
                "success_rate": round(100 * (total - reverted) / total) if total else None,
                "recent_rate": recent_rate, "prev_rate": prev_rate, "trend": trend}

    def get_activity_since(self, hours: int = 24, limit: int = 100) -> list[dict]:
        """Feed unificado de auditoria — 'o que a IA fez nas últimas `hours` horas'.
        Junta as fontes de atividade autônoma/assistida (aprendizado, tarefas do
        Coder, execuções de código, notificações e benchmarks) num só fluxo
        ordenado por tempo (mais recente primeiro). Cada evento tem a forma
        {ts, kind, icon, title, detail} para o painel de observabilidade."""
        cutoff = _now() - timedelta(hours=hours)
        events: list[dict] = []

        def _iso(dt) -> str:
            return dt.isoformat() if dt else ""

        with Session(self.engine) as s:
            for r in (s.query(LearnedTopic)
                      .filter(LearnedTopic.studied_at >= cutoff)
                      .order_by(LearnedTopic.studied_at.desc()).limit(limit).all()):
                events.append({"ts": _iso(r.studied_at), "kind": "learn", "icon": "📚",
                               "title": f"Aprendeu: {r.topic}",
                               "detail": (r.summary or "")[:200], "url": r.url})

            for r in (s.query(CoderTask)
                      .filter(CoderTask.created_at >= cutoff)
                      .order_by(CoderTask.created_at.desc()).limit(limit).all()):
                bits = []
                if r.wrote: bits.append("escreveu")
                if r.ran: bits.append("rodou")
                if r.reverted: bits.append("revertido")
                events.append({"ts": _iso(r.created_at), "kind": "coder", "icon": "💻",
                               "title": f"Coder: {r.task}",
                               "detail": f"{r.steps} passos · {', '.join(bits) or 'sem alterações'}"
                                         f" · {r.duration_s}s", "reverted": r.reverted})

            for r in (s.query(Execution)
                      .filter(Execution.timestamp >= cutoff, Execution.deleted == False)
                      .order_by(Execution.timestamp.desc()).limit(limit).all()):
                events.append({"ts": _iso(r.timestamp), "kind": "exec", "icon": "⚙️",
                               "title": f"Executou código ({r.status})",
                               "detail": (r.request or "")[:200]})

            for r in (s.query(Notification)
                      .filter(Notification.created_at >= cutoff)
                      .order_by(Notification.created_at.desc()).limit(limit).all()):
                events.append({"ts": _iso(r.created_at), "kind": "notif", "icon": "🔔",
                               "title": r.message, "detail": r.kind, "url": r.link})

            for r in (s.query(BenchmarkRun)
                      .filter(BenchmarkRun.ran_at >= cutoff)
                      .order_by(BenchmarkRun.ran_at.desc()).limit(limit).all()):
                events.append({"ts": _iso(r.ran_at), "kind": "benchmark", "icon": "🎯",
                               "title": f"Autoavaliação: {r.avg_score} de nota",
                               "detail": f"{r.questions} perguntas · {r.avg_latency_ms}ms médios"})

        events.sort(key=lambda e: e["ts"], reverse=True)
        return events[:limit]

    def activity_summary(self, hours: int = 24) -> dict:
        """Contagens por tipo de atividade nas últimas `hours` horas — cabeçalho
        do painel de auditoria ('hoje: 12 estudos, 3 tarefas do Coder…')."""
        from sqlalchemy import func
        cutoff = _now() - timedelta(hours=hours)
        with Session(self.engine) as s:
            return {
                "hours": hours,
                "learned": s.query(func.count(LearnedTopic.id))
                            .filter(LearnedTopic.studied_at >= cutoff).scalar() or 0,
                "coder_tasks": s.query(func.count(CoderTask.id))
                                .filter(CoderTask.created_at >= cutoff).scalar() or 0,
                "executions": s.query(func.count(Execution.id))
                               .filter(Execution.timestamp >= cutoff,
                                       Execution.deleted == False).scalar() or 0,
                "notifications": s.query(func.count(Notification.id))
                                  .filter(Notification.created_at >= cutoff).scalar() or 0,
                "benchmarks": s.query(func.count(BenchmarkRun.id))
                               .filter(BenchmarkRun.ran_at >= cutoff).scalar() or 0,
            }

    def update_topic_summary(self, topic_id: int, summary: str) -> bool:
        """Substitui a síntese de um tópico aprendido (reparo in-place —
        não cria linha nova no log)."""
        with Session(self.engine) as s:
            row = s.get(LearnedTopic, topic_id)
            if not row:
                return False
            row.summary = summary[:2000]
            s.commit()
            return True

    def get_summary_quality(self) -> dict:
        """Qualidade da base de aprendizado: sínteses estruturadas (têm seções
        '##') vs cruas (texto corrido ≥300 chars — lixo de timeouts antigos)
        vs curtas. Alimenta o cartão de qualidade do painel Saúde."""
        from sqlalchemy import func
        with Session(self.engine) as s:
            total = s.query(func.count(LearnedTopic.id)).scalar() or 0
            structured = (s.query(func.count(LearnedTopic.id))
                          .filter(LearnedTopic.summary.like("%##%")).scalar() or 0)
            raw = (s.query(func.count(LearnedTopic.id))
                   .filter(~LearnedTopic.summary.like("%##%"),
                           func.length(LearnedTopic.summary) >= 300).scalar() or 0)
        return {"total": total, "structured": structured, "raw": raw,
                "short": total - structured - raw,
                "pct_structured": round(100 * structured / total) if total else None}

    def get_verification_stats(self) -> dict:
        """P2.1: quantos resumos já foram auditados contra a fonte (amostra de
        ~10%) e quantos passaram. A maioria fica `None` de propósito — não é
        'não verificado ainda' = 'ruim', é 'não sorteado'."""
        from sqlalchemy import func
        with Session(self.engine) as s:
            total = s.query(func.count(LearnedTopic.id)).scalar() or 0
            verified = (s.query(func.count(LearnedTopic.id))
                       .filter(LearnedTopic.verified == "verified").scalar() or 0)
            failed = (s.query(func.count(LearnedTopic.id))
                     .filter(LearnedTopic.verified == "failed").scalar() or 0)
        sampled = verified + failed
        return {"total": total, "sampled": sampled, "verified": verified, "failed": failed,
                "pct_sampled": round(100 * sampled / total) if total else None,
                "pct_faithful_of_sampled": round(100 * verified / sampled) if sampled else None}

    def sample_topics_for_quality(self, n: int = 15) -> list[dict]:
        """P2.5: amostra ALEATÓRIA de tópicos já salvos (com resumo) pro juiz de
        qualidade avaliar — diferente de `_verify_summary` (P2.1, precisa da
        fonte crua, só roda na hora do save), este roda depois, sobre o que já
        está gravado, então pode amostrar de qualquer época."""
        from sqlalchemy import func
        with Session(self.engine) as s:
            rows = (s.query(LearnedTopic.id, LearnedTopic.topic, LearnedTopic.summary)
                    .filter(LearnedTopic.summary.isnot(None), LearnedTopic.summary != "")
                    .order_by(func.random()).limit(n).all())
        return [{"id": rid, "topic": topic, "summary": summary} for rid, topic, summary in rows]

    def get_learning_stats(self) -> dict:
        from sqlalchemy import func, distinct
        today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        with Session(self.engine) as s:
            # Conta tópicos ÚNICOS (não cada re-estudo) — número real de conhecimentos.
            total = s.query(func.count(distinct(LearnedTopic.topic))).scalar() or 0
            today_count = (s.query(func.count(distinct(LearnedTopic.topic)))
                           .filter(LearnedTopic.studied_at >= today).scalar() or 0)
            return {"total": total, "today": today_count}

    def get_learned_since(self, hours: int = 24, limit: int = 1000) -> list[dict]:
        """Tópicos ÚNICOS aprendidos nas últimas `hours` horas — base do digest diário."""
        from datetime import timedelta
        cutoff = _now() - timedelta(hours=hours)
        with Session(self.engine) as s:
            rows = (s.query(LearnedTopic)
                    .filter(LearnedTopic.studied_at >= cutoff)
                    .order_by(LearnedTopic.studied_at.desc())
                    .limit(limit * 3).all())
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            key = (r.topic or "").strip().lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"topic": r.topic, "url": r.url, "category": r.category,
                        "studied_at": r.studied_at.isoformat()})
            if len(out) >= limit:
                break
        return out

    def get_learning_timeline(self, days: int = 14) -> list[dict]:
        """Tópicos ÚNICOS aprendidos por dia nos últimos N dias (não conta re-estudos)."""
        from datetime import timedelta
        start = (_now() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        with Session(self.engine) as s:
            rows = (s.query(LearnedTopic.studied_at, LearnedTopic.topic)
                    .filter(LearnedTopic.studied_at >= start).all())
        per_day: dict[str, set] = {}
        for dt, topic in rows:
            d = dt.strftime("%Y-%m-%d")
            per_day.setdefault(d, set()).add((topic or "").strip().lower())
        return [
            {"date": (start + timedelta(days=i)).strftime("%Y-%m-%d"),
             "count": len(per_day.get((start + timedelta(days=i)).strftime("%Y-%m-%d"), set()))}
            for i in range(days)
        ]
