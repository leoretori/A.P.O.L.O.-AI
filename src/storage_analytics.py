"""DatabaseManager — analytics de uso, histórico de benchmark e reações. Mixin."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.storage_models import SessionMessage, LearnedTopic, Reaction, BenchmarkRun


class AnalyticsMixin:
    # ── Analytics ─────────────────────────────────────────────

    def analytics_messages_by_day(self, days: int = 30) -> list[dict]:
        """Contagem de mensagens do usuário por dia (últimos N dias)."""
        start = datetime.now(timezone.utc) - timedelta(days=days)
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage.timestamp)
                    .filter(SessionMessage.role == "user",
                            SessionMessage.timestamp >= start)
                    .all())
        counts: dict[str, int] = {}
        for (ts,) in rows:
            d = ts.strftime("%Y-%m-%d") if ts else None
            if d:
                counts[d] = counts.get(d, 0) + 1
        return [
            {"date": (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"),
             "count": counts.get((datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"), 0)}
            for i in range(days)
        ]

    def analytics_messages_by_hour(self) -> list[dict]:
        """Distribuição de mensagens do usuário por hora do dia (0–23)."""
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage.timestamp)
                    .filter(SessionMessage.role == "user")
                    .all())
        counts = [0] * 24
        for (ts,) in rows:
            if ts:
                counts[ts.hour] += 1
        return [{"hour": h, "count": counts[h]} for h in range(24)]

    def analytics_top_topics(self, limit: int = 20) -> list[dict]:
        """Tópicos mais estudados (por frequência de aparecimento no learned_topics)."""
        with Session(self.engine) as s:
            rows = s.query(LearnedTopic.topic, LearnedTopic.category).all()
        freq: dict[str, dict] = {}
        for topic, cat in rows:
            key = (topic or "").strip()
            if len(key) < 3:
                continue
            if key not in freq:
                freq[key] = {"topic": key, "category": cat or "web", "count": 0}
            freq[key]["count"] += 1
        return sorted(freq.values(), key=lambda x: x["count"], reverse=True)[:limit]

    def analytics_top_words(self, limit: int = 15) -> list[dict]:
        """Palavras/termos mais frequentes nas perguntas do usuário (stopwords removidas)."""
        import re
        _STOP = {
            "de","a","o","e","em","do","da","no","na","para","com","que","se","um","uma",
            "os","as","dos","das","por","mais","como","mas","ao","às","este","esta","isso",
            "são","foi","tem","é","não","me","te","se","lhe","você","eu","ele","ela","the",
            "is","in","of","to","and","a","an","for","on","with","this","that","it","be",
            "what","how","why","when","where","can","use","get","make","do","does","using",
        }
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage.content)
                    .filter(SessionMessage.role == "user")
                    .all())
        freq: dict[str, int] = {}
        for (content,) in rows:
            words = re.findall(r"\b[a-záàâãéêíóôõúüçA-Z]{3,}\b", content or "")
            for w in words:
                wl = w.lower()
                if wl not in _STOP:
                    freq[wl] = freq.get(wl, 0) + 1
        return [{"word": w, "count": c}
                for w, c in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:limit]]

    def analytics_usage_summary(self) -> dict:
        """Resumo geral: total mensagens, sessões, tópicos, estimativa de horas."""
        with Session(self.engine) as s:
            total_msgs  = s.query(SessionMessage).filter(SessionMessage.role == "user").count()
            total_sess  = s.query(SessionMessage.session_id).distinct().count()
            total_topics = s.query(LearnedTopic).count()
            # Dias distintos com atividade
            rows = s.query(SessionMessage.timestamp).filter(SessionMessage.role == "user").all()
        days_active = len({ts.strftime("%Y-%m-%d") for (ts,) in rows if ts})
        # Estimativa grosseira: ~2 min por mensagem trocada (ida + volta)
        est_hours = round(total_msgs * 2 / 60, 1)
        return {
            "total_messages": total_msgs,
            "total_sessions": total_sess,
            "total_topics_studied": total_topics,
            "days_active": days_active,
            "est_hours": est_hours,
        }

    # ── Benchmark persistente ──────────────────────────────────

    def save_benchmark_run(self, result: dict) -> int:
        """Persiste um run de benchmark no banco."""
        import json as _json
        with Session(self.engine) as s:
            row = BenchmarkRun(
                model=result.get("model", ""),
                avg_score=result.get("avg_score"),
                avg_latency_ms=result.get("avg_latency_ms"),
                total_ms=result.get("total_ms"),
                questions=result.get("questions"),
                results_json=_json.dumps(result.get("results", []), ensure_ascii=False),
            )
            s.add(row); s.commit()
            return row.id

    def get_benchmark_history(self, limit: int = 20) -> list[dict]:
        """Retorna histórico de benchmark (mais recente primeiro)."""
        import json as _json
        with Session(self.engine) as s:
            rows = (s.query(BenchmarkRun)
                    .order_by(BenchmarkRun.ran_at.desc())
                    .limit(limit).all())
        out = []
        for r in reversed(rows):  # cronológico para gráfico
            out.append({
                "id": r.id,
                "ran_at": r.ran_at.isoformat() if r.ran_at else "",
                "model": r.model,
                "avg_score": r.avg_score,
                "avg_latency_ms": r.avg_latency_ms,
                "total_ms": r.total_ms,
                "questions": r.questions,
                "results": _json.loads(r.results_json or "[]"),
            })
        return out

    # ── Reações (👍👎) ────────────────────────────────────────────

    def save_reaction(self, message_hash: str, reaction: str,
                      session_id: str = "", sources: list | None = None,
                      reason: str = "", question: str = "", answer: str = "") -> None:
        import json as _json
        reason = (reason or "")[:1000]
        question = (question or "")[:1000]
        answer = (answer or "")[:2000]
        with Session(self.engine) as s:
            # Upsert: atualiza se já existe para o mesmo hash
            existing = (s.query(Reaction)
                        .filter(Reaction.message_hash == message_hash).first())
            if existing:
                existing.reaction = reaction
                existing.sources = _json.dumps(sources or [])
                # Só sobrescreve pergunta/resposta/motivo quando vier conteúdo novo
                # (re-clicar o 👍/👎 sem 'por quê' não deve apagar o motivo já dado).
                if reason:
                    existing.reason = reason
                if question:
                    existing.question = question
                if answer:
                    existing.answer = answer
            else:
                s.add(Reaction(
                    message_hash=message_hash,
                    reaction=reaction,
                    session_id=session_id or "",
                    sources=_json.dumps(sources or []),
                    reason=reason, question=question, answer=answer,
                ))
            s.commit()

    def negative_feedback(self, limit: int = 20) -> list[dict]:
        """Os 👎 mais recentes COM o 'por quê' — matéria-prima de melhoria (M9 9.2).
        É o que o Leo achou ruim e por quê: candidato a virar lição/memória."""
        with Session(self.engine) as s:
            rows = (s.query(Reaction)
                    .filter(Reaction.reaction == "down")
                    .order_by(Reaction.created_at.desc()).limit(limit).all())
            return [{"question": (r.question or ""), "answer": (r.answer or ""),
                     "reason": (r.reason or ""),
                     "created_at": r.created_at.isoformat() if r.created_at else None}
                    for r in rows]

    def feedback_trend(self, window: int = 20) -> dict:
        """Taxa de aprovação (👍/total) na janela recente vs a anterior — a
        satisfação do Leo está subindo? Alimenta o painel 'estou melhorando?' (9.3)."""
        with Session(self.engine) as s:
            rows = (s.query(Reaction.reaction)
                    .order_by(Reaction.created_at.desc()).limit(window * 2).all())
        flags = [r[0] == "up" for r in rows]

        def _rate(fs: list) -> float | None:
            return round(sum(1 for f in fs if f) / len(fs), 3) if fs else None

        recent = _rate(flags[:window])
        prev = _rate(flags[window:window * 2])
        trend = round(recent - prev, 3) if recent is not None and prev is not None else None
        return {"samples": len(flags), "recent_rate": recent,
                "prev_rate": prev, "trend": trend}

    def reaction_stats(self) -> dict:
        """Contagem de 👍/👎 e fontes mais polarizadas (para o painel Analytics)."""
        import json as _json
        with Session(self.engine) as s:
            rows = s.query(Reaction).all()
        ups   = sum(1 for r in rows if r.reaction == "up")
        downs = sum(1 for r in rows if r.reaction == "down")
        # Fontes mais negativamente avaliadas
        url_neg: dict[str, int] = {}
        for r in rows:
            if r.reaction == "down":
                for url in (_json.loads(r.sources or "[]") or []):
                    url_neg[url] = url_neg.get(url, 0) + 1
        top_neg = sorted(url_neg.items(), key=lambda x: -x[1])[:5]
        return {
            "total": len(rows), "up": ups, "down": downs,
            "top_negative_sources": [{"url": u, "count": c} for u, c in top_neg],
        }
