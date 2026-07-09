"""Automação de tarefas web em sandbox (M10, Épico 10.3).

  GET  /api/webtask/example  → uma receita de exemplo
  POST /api/webtask/plan     → valida a receita contra a sandbox SEM executar (prévia)
  POST /api/webtask/run      → executa (read-only) pelo portão do M6 (consentimento + auditoria)

O `run` passa por `run_tool("browser.run")` → consentimento por escopo
`browser.control` + auditoria de graça. `plan` é só leitura da própria config
(allowlist) + validação — não navega, não audita.
"""
import asyncio

from fastapi import APIRouter

from src import runtime as rt
from src import webtask
from src.tools import run_tool

router = APIRouter()


def _allowed_domains() -> list[str]:
    try:
        note = rt.db.permission_note("browser.control") if rt.db else ""
    except Exception:
        note = ""
    return webtask.parse_domains(note)


@router.get("/api/webtask/example")
async def example():
    return {"steps": webtask.EXAMPLE_RECIPE,
            "ops": list(webtask.OPS), "extract_what": list(webtask.EXTRACT_WHAT)}


@router.post("/api/webtask/plan")
async def plan(payload: dict):
    """Prévia (opt-in): mostra a sandbox e valida a receita SEM navegar."""
    granted = bool(rt.db and rt.db.is_permission_granted("browser.control"))
    allowed = _allowed_domains()
    steps = (payload or {}).get("steps") or []
    errors = webtask.validate(steps, allowed)
    return {"ok": not errors, "granted": granted, "allowed_domains": allowed,
            "errors": errors, "steps": steps}


@router.post("/api/webtask/run")
async def run(payload: dict):
    """Executa a receita (read-only) na sandbox — consentimento + auditoria via M6."""
    steps = (payload or {}).get("steps") or []
    res = await asyncio.to_thread(run_tool, "browser.run", {"steps": steps}, rt.db)
    # run_tool embrulha em {ok, result}; desembrulha o resultado do webtask.run
    if res.get("ok") and isinstance(res.get("result"), dict):
        return res["result"]
    return res
