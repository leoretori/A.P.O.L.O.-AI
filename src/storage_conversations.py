"""DatabaseManager — CRUD operacional: execuções, conversas, notificações,
agendamentos e import/export de backup. Mixin composto em src/storage.py."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src.storage_models import (
    _now, _parse_dt, Execution, SessionMessage, SessionMeta,
    Notification, ScheduledStudy, LearnedTopic,
)


class ConversationsMixin:
    # ── Execuções ─────────────────────────────────────────────
    def save_execution(self, data: dict) -> int:
        with Session(self.engine) as s:
            row = Execution(
                timestamp=datetime.fromisoformat(data.get("timestamp", _now().isoformat())),
                request=data["request"],
                result=data.get("result", ""),
                status=data.get("status", "pending"),
            )
            s.add(row); s.commit()
            return row.id

    def get_history(self, limit: int = 20) -> list[dict]:
        with Session(self.engine) as s:
            rows = (s.query(Execution)
                    .filter(Execution.deleted == False)
                    .order_by(Execution.timestamp.desc())
                    .limit(limit).all())
            return [{"id": r.id, "timestamp": r.timestamp.isoformat(),
                     "request": r.request, "status": r.status} for r in rows]

    def soft_delete(self, execution_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(Execution, execution_id)
            if row:
                row.deleted = True; s.commit(); return True
            return False

    # ── Sessões de conversa ───────────────────────────────────
    def save_message(self, session_id: str, role: str, content: str) -> None:
        with Session(self.engine) as s:
            s.add(SessionMessage(session_id=session_id, role=role, content=content))
            s.commit()

    def load_session(self, session_id: str) -> list[dict]:
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage)
                    .filter(SessionMessage.session_id == session_id)
                    .order_by(SessionMessage.timestamp.asc()).all())
            return [{"role": r.role, "content": r.content} for r in rows]

    def delete_session(self, session_id: str) -> None:
        with Session(self.engine) as s:
            s.query(SessionMessage).filter(SessionMessage.session_id == session_id).delete()
            # Remove também o título — senão sobra metadado órfão (sessão fantasma).
            s.query(SessionMeta).filter(SessionMeta.session_id == session_id).delete()
            s.commit()

    def save_session_title(self, session_id: str, title: str) -> None:
        with Session(self.engine) as s:
            existing = s.get(SessionMeta, session_id)
            if existing:
                existing.title = title
            else:
                s.add(SessionMeta(session_id=session_id, title=title))
            s.commit()

    def list_sessions(self, days: int = 0, limit: int = 100) -> list[dict]:
        """Sessões recentes para a sidebar. days=0 → todo o histórico (chats antigos
        continuam aparecendo); >0 limita à janela. Ordena pela última atividade."""
        with Session(self.engine) as s:
            q = (s.query(SessionMessage)
                 .filter(SessionMessage.role == "user"))
            if days > 0:
                q = q.filter(SessionMessage.timestamp >= _now() - timedelta(days=days))
            rows = q.order_by(SessionMessage.timestamp.desc()).all()
            seen: dict[str, dict] = {}
            for r in rows:
                if r.session_id not in seen:
                    meta = s.get(SessionMeta, r.session_id)
                    seen[r.session_id] = {
                        "session_id": r.session_id,
                        "title": meta.title if meta else r.content[:60],
                        "first_message": r.content[:80],
                        "last_active": r.timestamp.isoformat(),
                    }
            return list(seen.values())[:limit]

    def first_user_messages(self, limit: int = 300, min_len: int = 8) -> list[str]:
        """A PRIMEIRA mensagem do usuário de cada sessão — a entrada real na
        distribuição de inferência (pergunta que abre a conversa). É exatamente
        o que o M25 destila em título: o descasamento do M14.2 (treinou em prosa,
        recebe pergunta) some quando o professor rotula ESTAS entradas.
        Mais recentes primeiro; deduplicadas por sessão; sem as curtas demais."""
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage)
                    .filter(SessionMessage.role == "user")
                    .order_by(SessionMessage.timestamp.asc()).all())
            first_by_session: dict[str, SessionMessage] = {}
            for r in rows:                       # asc → o 1º visto é o mais antigo
                if r.session_id not in first_by_session:
                    first_by_session[r.session_id] = r
            firsts = sorted(first_by_session.values(),
                            key=lambda r: r.timestamp, reverse=True)
            out = [(r.content or "").strip() for r in firsts]
            return [c for c in out if len(c) >= min_len][:limit]

    def diagnose_pair_sourcing(self, min_len: int = 8, sample: int = 5) -> dict:
        """Por que o flywheel mostra 'poucos pares' mesmo com várias conversas
        recentes (dúvida real, 2026-07-14): `first_user_messages` conta UMA
        entrada POR SESSÃO (a 1ª mensagem que abre a conversa) — continuar uma
        conversa existente não soma novo par; só sessões NOVAS contam. Este
        instrumento mostra o funil de verdade: total de sessões → quantas têm
        1ª mensagem longa o bastante (min_len) → amostra das descartadas
        (curtas demais, tipo 'oi'). Não chama o professor — é só leitura/contagem,
        o passo ANTES da validação do teacher (que reduz o número de novo)."""
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage)
                    .filter(SessionMessage.role == "user")
                    .order_by(SessionMessage.timestamp.asc()).all())
            first_by_session: dict[str, SessionMessage] = {}
            for r in rows:
                if r.session_id not in first_by_session:
                    first_by_session[r.session_id] = r
            total = len(first_by_session)
            valid, curtas = [], []
            for r in first_by_session.values():
                text = (r.content or "").strip()
                if len(text) >= min_len:
                    valid.append(text)
                else:
                    curtas.append(text)
        reacted = len(self.positive_reaction_pairs(limit=10_000, min_len=min_len))
        return {
                "total_sessoes": total,
                "com_1a_mensagem_valida": len(valid),
                "descartadas_curtas_demais": len(curtas),
                "min_len": min_len,
                "amostra_descartadas": curtas[:sample],
                "pares_de_reacoes_up": reacted,
                "nota": "cada SESSÃO conta 1 vez (a 1ª mensagem que abre ela) — "
                        "continuar uma conversa existente não soma; abrir '+ Nova' soma. "
                        "Já os 👍 contam por si (pares_de_reacoes_up) — cada resposta "
                        "aprovada vira 1 par de treino direto, sem precisar de sessão nova.",
            }

    def search_messages(self, query: str, limit: int = 30) -> list[dict]:
        """Busca no histórico de conversas — retorna trechos com a sessão de origem.
        Agrupa por sessão (mostra o primeiro acerto de cada) para a sidebar de busca."""
        q = (query or "").strip()
        if len(q) < 2:
            return []
        like = f"%{q}%"
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage)
                    .filter(SessionMessage.content.ilike(like))
                    .order_by(SessionMessage.timestamp.desc())
                    .limit(limit * 8).all())
            seen: dict[str, dict] = {}
            for r in rows:
                if r.session_id in seen:
                    continue
                meta = s.get(SessionMeta, r.session_id)
                # Recorta um trecho ao redor do termo encontrado.
                low = r.content.lower()
                idx = low.find(q.lower())
                start = max(0, idx - 40)
                snippet = ("…" if start > 0 else "") + r.content[start:start + 140].strip()
                seen[r.session_id] = {
                    "session_id": r.session_id,
                    "title": meta.title if meta else r.content[:60],
                    "role": r.role,
                    "snippet": snippet,
                    "matched_at": r.timestamp.isoformat(),
                }
                if len(seen) >= limit:
                    break
            return list(seen.values())

    def export_session_markdown(self, session_id: str) -> str:
        """Exporta uma conversa como Markdown legível (título + turnos)."""
        with Session(self.engine) as s:
            meta = s.get(SessionMeta, session_id)
            rows = (s.query(SessionMessage)
                    .filter(SessionMessage.session_id == session_id)
                    .order_by(SessionMessage.timestamp.asc()).all())
            title = meta.title if meta else "Conversa"
            out = [f"# {title}", ""]
            if rows:
                out.append(f"*Exportado de A.P.O.L.O. — {len(rows)} mensagens*")
                out.append("")
            for r in rows:
                who = "🧑 Você" if r.role == "user" else "☀️ A.P.O.L.O."
                ts = r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else ""
                out.append(f"### {who}  \n<sub>{ts}</sub>")
                out.append("")
                out.append(r.content or "")
                out.append("")
                out.append("---")
                out.append("")
            return "\n".join(out).strip() + "\n"

    def export_all(self) -> dict:
        """Dump completo do SQLite (sessões + tópicos aprendidos) para backup/export."""
        with Session(self.engine) as s:
            messages = [
                {"session_id": r.session_id, "role": r.role, "content": r.content,
                 "timestamp": r.timestamp.isoformat() if r.timestamp else None}
                for r in s.query(SessionMessage).order_by(SessionMessage.timestamp.asc()).all()
            ]
            titles = [
                {"session_id": r.session_id, "title": r.title,
                 "created_at": r.created_at.isoformat() if r.created_at else None}
                for r in s.query(SessionMeta).all()
            ]
            topics = [
                {"topic": r.topic, "url": r.url, "summary": r.summary,
                 "category": r.category,
                 "studied_at": r.studied_at.isoformat() if r.studied_at else None}
                for r in s.query(LearnedTopic).order_by(LearnedTopic.studied_at.asc()).all()
            ]
        return {
            "exported_at": _now().isoformat(),
            "counts": {"messages": len(messages), "sessions": len(titles), "learned_topics": len(topics)},
            "sessions_titles": titles,
            "messages": messages,
            "learned_topics": topics,
        }

    # ── Notificações ──────────────────────────────────────────
    NOTIF_KEEP = 200  # notificações são efêmeras → mantém só as mais recentes

    def add_notification(self, message: str, kind: str = "info", link: str = "") -> dict:
        """Cria um aviso já com PRIORIDADE por tipo (M4 4.3). Tipos de baixa
        prioridade (ex.: 'study') COLAPSAM num único aviso rolante — se já há um
        não-lido do mesmo tipo na janela, incrementa a contagem em vez de spammar."""
        from datetime import timedelta
        from src.notifications import priority_for, collapses, collapsed_message, COLLAPSE_WINDOW_MIN
        message = message[:500]
        prio = priority_for(kind)
        with Session(self.engine) as s:
            if collapses(kind):
                cutoff = _now() - timedelta(minutes=COLLAPSE_WINDOW_MIN)
                recent = (s.query(Notification)
                          .filter(Notification.kind == kind, Notification.read == False,
                                  Notification.created_at >= cutoff)
                          .order_by(Notification.created_at.desc()).first())
                if recent:
                    recent.count += 1
                    recent.message = collapsed_message(kind, recent.count, message)
                    recent.created_at = _now()      # sobe para o topo
                    recent.priority = prio
                    s.commit()
                    return _notif_dict(recent)
            row = Notification(message=message, kind=kind, link=link or None, priority=prio)
            s.add(row); s.commit()
            result = _notif_dict(row)
            # Poda: remove o excedente além das NOTIF_KEEP mais recentes.
            ids = [r.id for r in (s.query(Notification.id)
                                  .order_by(Notification.created_at.desc())
                                  .offset(self.NOTIF_KEEP).all())]
            if ids:
                (s.query(Notification).filter(Notification.id.in_(ids))
                 .delete(synchronize_session=False))
                s.commit()
            return result

    def list_notifications(self, limit: int = 30, unread_only: bool = False,
                           min_priority: int = 0) -> list[dict]:
        """Avisos recentes. `min_priority` filtra o ruído de fundo (0 mostra tudo;
        1+ esconde os 'study' colapsados de prioridade 0 — o modo 'que importam')."""
        with Session(self.engine) as s:
            q = s.query(Notification)
            if unread_only:
                q = q.filter(Notification.read == False)
            if min_priority > 0:
                q = q.filter(Notification.priority >= min_priority)
            rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
            return [_notif_dict(r) for r in rows]

    def unread_count(self) -> int:
        with Session(self.engine) as s:
            return s.query(Notification).filter(Notification.read == False).count()

    def mark_notifications_read(self) -> int:
        with Session(self.engine) as s:
            n = (s.query(Notification).filter(Notification.read == False)
                 .update({Notification.read: True}, synchronize_session=False))
            s.commit()
            return n

    def clear_notifications(self) -> int:
        with Session(self.engine) as s:
            n = s.query(Notification).delete(synchronize_session=False)
            s.commit()
            return n

    # ── Estudos agendados ─────────────────────────────────────
    def add_schedule(self, topic: str, time_of_day: str) -> dict:
        with Session(self.engine) as s:
            row = ScheduledStudy(topic=topic.strip()[:200], time_of_day=time_of_day.strip())
            s.add(row); s.commit()
            return {"id": row.id, "topic": row.topic, "time_of_day": row.time_of_day,
                    "enabled": row.enabled, "last_run": None}

    def list_schedules(self) -> list[dict]:
        with Session(self.engine) as s:
            rows = s.query(ScheduledStudy).order_by(ScheduledStudy.time_of_day.asc()).all()
            return [{"id": r.id, "topic": r.topic, "time_of_day": r.time_of_day,
                     "enabled": r.enabled,
                     "last_run": r.last_run.isoformat() if r.last_run else None}
                    for r in rows]

    def delete_schedule(self, schedule_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(ScheduledStudy, schedule_id)
            if not row:
                return False
            s.delete(row); s.commit()
            return True

    def toggle_schedule(self, schedule_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(ScheduledStudy, schedule_id)
            if not row:
                return False
            row.enabled = not row.enabled
            s.commit()
            return True

    def due_schedules(self, now_local: datetime) -> list[dict]:
        """Agendamentos cujo horário 'HH:MM' já passou hoje e que ainda não rodaram hoje.
        Retorna os que devem disparar agora; o caller marca como executados."""
        hhmm = now_local.strftime("%H:%M")
        today = now_local.date()
        due: list[dict] = []
        with Session(self.engine) as s:
            rows = s.query(ScheduledStudy).filter(ScheduledStudy.enabled == True).all()
            for r in rows:
                if r.last_run and r.last_run.date() == today:
                    continue  # já rodou hoje
                if r.time_of_day <= hhmm:  # chegou (ou passou) a hora
                    due.append({"id": r.id, "topic": r.topic, "time_of_day": r.time_of_day})
        return due

    def mark_schedule_ran(self, schedule_id: int, when: datetime) -> None:
        with Session(self.engine) as s:
            row = s.get(ScheduledStudy, schedule_id)
            if row:
                row.last_run = when
                s.commit()

    def import_all(self, data: dict) -> dict:
        """Restaura um backup gerado por export_all(). Idempotente: pula mensagens e
        tópicos já presentes (mesmo conteúdo/url) e faz upsert de títulos."""
        added = {"messages": 0, "sessions": 0, "learned_topics": 0}
        with Session(self.engine) as s:
            # Títulos (upsert por session_id)
            for t in data.get("sessions_titles", []):
                sid = t.get("session_id")
                if not sid:
                    continue
                existing = s.get(SessionMeta, sid)
                if existing:
                    existing.title = t.get("title") or existing.title
                else:
                    s.add(SessionMeta(session_id=sid, title=t.get("title") or "(sem título)"))
                    added["sessions"] += 1

            # Mensagens — evita duplicar (mesma sessão+role+conteúdo+timestamp)
            for m in data.get("messages", []):
                sid, role, content = m.get("session_id"), m.get("role"), m.get("content")
                if not (sid and role and content is not None):
                    continue
                ts = _parse_dt(m.get("timestamp"))
                dup = (s.query(SessionMessage.id)
                       .filter(SessionMessage.session_id == sid,
                               SessionMessage.role == role,
                               SessionMessage.content == content).first())
                if dup:
                    continue
                row = SessionMessage(session_id=sid, role=role, content=content)
                if ts:
                    row.timestamp = ts
                s.add(row)
                added["messages"] += 1

            # Tópicos aprendidos — evita duplicar pela URL (ou topic se sem url)
            for lt in data.get("learned_topics", []):
                topic = lt.get("topic")
                if not topic:
                    continue
                url = lt.get("url") or ""
                q = s.query(LearnedTopic.id)
                q = q.filter(LearnedTopic.url == url) if url else q.filter(LearnedTopic.topic == topic)
                if q.first():
                    continue
                ts = _parse_dt(lt.get("studied_at"))
                row = LearnedTopic(topic=topic, url=url or None,
                                   summary=lt.get("summary"), category=lt.get("category") or "web")
                if ts:
                    row.studied_at = ts
                s.add(row)
                added["learned_topics"] += 1

            s.commit()
        return added

    def cleanup_orphan_meta(self) -> int:
        """Remove títulos de sessões que não têm mais mensagens (limpeza de fantasmas)."""
        with Session(self.engine) as s:
            metas = s.query(SessionMeta.session_id).all()
            removed = 0
            for (sid,) in metas:
                has_msg = (s.query(SessionMessage.id)
                           .filter(SessionMessage.session_id == sid).first())
                if not has_msg:
                    s.query(SessionMeta).filter(SessionMeta.session_id == sid).delete()
                    removed += 1
            if removed:
                s.commit()
        return removed


def _notif_dict(r) -> dict:
    return {
        "id": r.id, "kind": r.kind, "message": r.message, "link": r.link,
        "read": r.read, "created_at": r.created_at.isoformat() if r.created_at else None,
        "priority": r.priority if r.priority is not None else 1,
        "count": r.count if r.count is not None else 1,
    }
