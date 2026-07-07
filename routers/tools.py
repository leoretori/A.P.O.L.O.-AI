"""Agência com permissão (M6, Épico 6.1): consentimento + ferramentas + auditoria.

Rotas:
  GET  /api/permissions            — escopos e o que está autorizado
  POST /api/permissions/grant      — autoriza um escopo (consentimento)
  POST /api/permissions/revoke     — revoga
  GET  /api/tools                  — ferramentas registradas (+ se estão liberadas)
  POST /api/tools/run              — executa uma ferramenta (passa pela porteira)
  GET  /api/tools/audit            — log de auditoria das invocações
"""
import asyncio

from fastapi import APIRouter

from src import runtime as rt
from src.tools import SCOPES, all_tools, run_tool
from src.tools.intent import detect_intent, format_answer

router = APIRouter()


@router.get("/api/permissions")
async def list_permissions():
    """Catálogo de escopos + estado de consentimento de cada um."""
    grants = {}
    if rt.db:
        grants = {p["scope"]: p for p in await asyncio.to_thread(rt.db.list_permissions)}
    scopes = [{"scope": s, "label": label,
               "granted": bool(grants.get(s, {}).get("granted", False)),
               "note": grants.get(s, {}).get("note", "")}
              for s, label in SCOPES.items()]
    return {"scopes": scopes}


@router.post("/api/permissions/grant")
async def grant_permission(payload: dict):
    scope = (payload or {}).get("scope", "").strip()
    if not scope or scope not in SCOPES:
        return {"ok": False, "error": "escopo inválido"}
    note = (payload or {}).get("note", "")
    p = await asyncio.to_thread(rt.db.grant_permission, scope, note)
    return {"ok": True, "permission": p}


@router.post("/api/permissions/revoke")
async def revoke_permission(payload: dict):
    scope = (payload or {}).get("scope", "").strip()
    ok = await asyncio.to_thread(rt.db.revoke_permission, scope)
    return {"ok": ok}


@router.get("/api/tools")
async def list_tools():
    """Ferramentas registradas + se cada uma está liberada (scope concedido)."""
    out = []
    for t in all_tools():
        granted = (not t.scope) or (rt.db and
                                    await asyncio.to_thread(rt.db.is_permission_granted, t.scope))
        out.append({"name": t.name, "scope": t.scope,
                    "description": t.description, "allowed": bool(granted)})
    return {"tools": out}


@router.post("/api/tools/run")
async def run(payload: dict):
    """Executa uma ferramenta pelo caminho seguro (consentimento + auditoria)."""
    name = (payload or {}).get("name", "").strip()
    args = (payload or {}).get("args") or {}
    if not name:
        return {"ok": False, "error": "nome da ferramenta ausente"}
    return await asyncio.to_thread(run_tool, name, args, rt.db)


@router.post("/api/agency/ask")
async def agency_ask(payload: dict):
    """Ponte linguagem-natural → ferramenta (M6 DoD). Detecta a intenção
    ('resuma meus e-mails de hoje', 'o que tenho na agenda amanhã', 'lê o arquivo
    X'), executa pela porteira (consentimento + auditoria) e formata a resposta.
    Desacoplado do chat — não interfere na conversa nem no aprendizado."""
    text = (payload or {}).get("text", "").strip()
    if not text:
        return {"ok": False, "error": "texto vazio"}
    intent = detect_intent(text)
    if not intent:
        return {"ok": False, "understood": False,
                "answer": "Ainda não sei fazer isso. Posso ler seus e-mails, sua "
                          "agenda (.ics) e arquivos de pastas autorizadas."}
    name, args = intent
    res = await asyncio.to_thread(run_tool, name, args, rt.db)
    if res.get("denied"):
        label = res.get("scope_label", res.get("scope", ""))
        return {"ok": False, "understood": True, "denied": True, "tool": name,
                "scope": res.get("scope"),
                "answer": f"Preciso da sua permissão para isso ({label}). Abra 🔐 "
                          f"Permissões e autorize '{res.get('scope')}'."}
    if not res.get("ok"):
        return {"ok": False, "understood": True, "tool": name,
                "answer": f"Não consegui: {res.get('error', 'erro desconhecido')}"}
    return {"ok": True, "understood": True, "tool": name,
            "answer": format_answer(name, res.get("result", {})),
            "result": res.get("result", {})}


@router.get("/api/tools/audit")
async def tool_audit(limit: int = 50, hours: int = 0):
    """Log de auditoria — o que foi invocado, permitido ou negado."""
    if not rt.db:
        return {"audit": []}
    limit = max(1, min(limit, 200))
    rows = await asyncio.to_thread(rt.db.list_tool_audit, limit, hours or None)
    return {"audit": rows}
