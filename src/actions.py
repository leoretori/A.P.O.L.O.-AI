"""Ações confirmáveis e REVERSÍVEIS (M10, Épico 10.1).

As ferramentas do M6 LEEM o mundo; as ações do M10 o MODIFICAM — e por isso nunca
acontecem num passo só. O ciclo é sempre:

    preview  → mostra EXATAMENTE o que vai mudar, sem tocar em nada
    confirm  → aplica de fato E captura os dados de UNDO
    undo     → desfaz, restaurando o estado anterior

Cada tipo de ação declara três funções: `preview(args, ctx)` (sem efeito
colateral), `apply(args, ctx)` (devolve `{result, undo, description}`) e
`undo(undo_data, ctx)`. Tudo passa pelo mesmo portão do M6 — consentimento por
escopo + auditoria — antes de qualquer efeito. O núcleo é determinístico; os
efeitos ficam nas funções concretas (ex.: `src/tools/files_write.py`).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("apolo.actions")


@dataclass
class ActionContext:
    """Contexto passado às funções da ação (mesmo formato do ToolContext do M6):
    carrega o `db` e a `note` do grant (para files.write, a allowlist de pastas).
    Definido aqui — e não importado de src.tools — para evitar import circular
    (src.tools importa este módulo para registrar as ações)."""
    db: object | None = None
    scope: str = ""
    note: str = ""


@dataclass
class Action:
    kind: str
    scope: str                        # escopo de permissão exigido
    description: str
    preview: Callable[..., dict]      # (args, ctx) -> dict, SEM efeito colateral
    apply: Callable[..., dict]        # (args, ctx) -> {result, undo, description}
    undo: Callable[..., dict]         # (undo_data, ctx) -> dict


_REGISTRY: dict[str, Action] = {}


def register(action: Action) -> None:
    _REGISTRY[action.kind] = action


def get(kind: str) -> Action | None:
    return _REGISTRY.get(kind)


def all_actions() -> list[Action]:
    return list(_REGISTRY.values())


def _summarize(obj) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    return s[:400]


def _context(action: Action, db) -> ActionContext:
    note = ""
    if db is not None and action.scope:
        try:
            note = db.permission_note(action.scope)
        except Exception:
            note = ""
    return ActionContext(db=db, scope=action.scope, note=note)


def _granted(action: Action, db) -> bool:
    return (not action.scope) or (db is not None and db.is_permission_granted(action.scope))


def _denied(action: Action) -> dict:
    from src.tools.registry import SCOPES        # tardio: evita import circular
    return {"ok": False, "denied": True, "scope": action.scope,
            "error": f"permissão '{action.scope}' não concedida",
            "scope_label": SCOPES.get(action.scope, action.scope)}


def _audit(db, name: str, scope: str, allowed: bool, args, result) -> None:
    if db is None:
        return
    try:
        db.log_tool(name, scope, allowed, _summarize(args), _summarize(result))
    except Exception as e:
        logger.debug(f"[action] audit falhou: {e}")


def preview_action(kind: str, args: dict | None, db=None) -> dict:
    """Fase 1: prévia SEM efeito colateral. Exige permissão (a prévia de uma
    escrita lê o arquivo atual) e é auditada como '<kind>:preview'."""
    action = get(kind)
    if not action:
        return {"ok": False, "error": f"ação desconhecida: {kind}"}
    if not _granted(action, db):
        _audit(db, f"{kind}:preview", action.scope, False, args or {}, "denied")
        return _denied(action)
    try:
        preview = action.preview(args or {}, _context(action, db))
    except Exception as e:
        _audit(db, f"{kind}:preview", action.scope, True, args or {}, f"erro: {e}")
        return {"ok": False, "error": str(e)[:300]}
    _audit(db, f"{kind}:preview", action.scope, True, args or {}, preview)
    return {"ok": True, "kind": kind, "scope": action.scope,
            "description": action.description, "preview": preview}


def apply_action(kind: str, args: dict | None, db=None) -> dict:
    """Fase 2: aplica de fato e GRAVA o undo (se houver db). Auditada como
    '<kind>:apply'. Devolve undo_id para desfazer depois."""
    action = get(kind)
    if not action:
        return {"ok": False, "error": f"ação desconhecida: {kind}"}
    if not _granted(action, db):
        _audit(db, f"{kind}:apply", action.scope, False, args or {}, "denied")
        return _denied(action)
    try:
        out = action.apply(args or {}, _context(action, db))
    except Exception as e:
        _audit(db, f"{kind}:apply", action.scope, True, args or {}, f"erro: {e}")
        return {"ok": False, "error": str(e)[:300]}

    description = out.get("description") or action.description
    undo_data = out.get("undo")
    undo_id = None
    if db is not None and undo_data is not None:
        try:
            undo_id = db.save_undo(kind, description, undo_data)
        except Exception as e:
            logger.warning(f"[action] não gravou undo de {kind}: {e}")
    _audit(db, f"{kind}:apply", action.scope, True, args or {}, out.get("result"))
    return {"ok": True, "kind": kind, "result": out.get("result"),
            "description": description, "undo_id": undo_id,
            "reversible": undo_id is not None}


def undo_action(undo_id: int, db=None) -> dict:
    """Desfaz uma ação aplicada, pelo registro do ledger. Idempotente: um id já
    desfeito não é reaplicado. Exige o MESMO escopo de preview/apply — sem
    isso, revogar uma permissão não impedia desfazer ações antigas dela
    (achado na auditoria de segurança 2026-07-15: `note`/allowlist do grant
    sobrevive à revogação, então o undo continuava escrevendo/apagando
    arquivos mesmo depois do Leo tirar a permissão)."""
    if db is None:
        return {"ok": False, "error": "sem banco para reverter"}
    entry = db.get_undo(undo_id)
    if not entry:
        return {"ok": False, "error": "registro de undo não encontrado"}
    if entry.get("undone"):
        return {"ok": False, "error": "esta ação já foi desfeita", "already": True}
    action = get(entry["kind"])
    if not action:
        return {"ok": False, "error": f"ação desconhecida: {entry['kind']}"}
    if not _granted(action, db):
        _audit(db, f"{entry['kind']}:undo", action.scope, False, {"undo_id": undo_id}, "denied")
        return _denied(action)
    try:
        result = action.undo(entry["undo_data"], _context(action, db))
    except Exception as e:
        _audit(db, f"{entry['kind']}:undo", action.scope, True, {"undo_id": undo_id}, f"erro: {e}")
        return {"ok": False, "error": str(e)[:300]}
    db.mark_undone(undo_id)
    _audit(db, f"{entry['kind']}:undo", action.scope, True, {"undo_id": undo_id}, result)
    return {"ok": True, "undo_id": undo_id, "kind": entry["kind"], "result": result}
