"""Execução direta no workspace do Coder (fora do loop ReAct): terminal via
WebSocket e SSE, e o commit assistido.

Rotas: /ws/coder/exec (WebSocket), /api/coder/exec (SSE), /api/coder/commit.
Extraído de app.py na M1 do JARVIS_ROADMAP. Usa coder_ws (runtime), o
gpu_priority/invalidate_baseline (coder_state) e, no commit, o modelo leve
para gerar a mensagem (Conventional Commits). NUNCA faz push.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src import runtime as rt
from src.coder_state import invalidate_baseline, gpu_priority
from src.llm import chat_resilient, KEEP_ALIVE
from src.prompts import COMMIT_MSG_PROMPT

router = APIRouter()
logger = logging.getLogger("apolo.routers.coder_run")


class CoderExecRequest(BaseModel):
    cmd: str


@router.websocket("/ws/coder/exec")
async def coder_exec_ws(ws: WebSocket):
    """WebSocket para o terminal do Coder — bidirecional real.
    Recebe {cmd} → transmite linhas de saída → envia {type: done, ok: bool}.
    Vantagem sobre SSE: permite enviar Ctrl+C para interromper processos."""
    await ws.accept()
    try:
        data = await ws.receive_json()
        cmd = (data.get("cmd") or "").strip()
        if not cmd:
            await ws.send_json({"type": "done", "ok": False, "error": "cmd vazio"})
            return

        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _worker():
            for kind, val in rt.coder_ws.run_cmd_stream(cmd):
                loop.call_soon_threadsafe(q.put_nowait, (kind, val))

        fut = loop.run_in_executor(None, _worker)
        ok = False
        while True:
            kind, val = await q.get()
            if kind == "line":
                await ws.send_json({"type": "line", "content": val[:500]})
            else:
                ok = val
                break
        await fut
        invalidate_baseline()  # o comando pode ter mudado o workspace
        await ws.send_json({"type": "done", "ok": ok})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)[:200]})
        except Exception:
            pass


@router.post("/api/coder/exec")
async def coder_exec(req: CoderExecRequest):
    """Executa um comando direto no workspace (sem o loop LLM), transmitindo a saída
    ao vivo — um terminal leve confinado ao workspace, com as mesmas proteções."""
    cmd = (req.cmd or "").strip()

    def _ev(d): return f"data: {json.dumps(d)}\n\n"

    async def stream():
        if not cmd:
            yield _ev({"type": "done", "ok": False}); return
        yield _ev({"type": "step", "icon": "⚙️", "message": f"$ {cmd[:80]}"})
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _worker():
            ok_local = False
            for kind, val in rt.coder_ws.run_cmd_stream(cmd):
                if kind == "line":
                    loop.call_soon_threadsafe(q.put_nowait, ("line", val))
                else:
                    ok_local = val
            loop.call_soon_threadsafe(q.put_nowait, ("done", ok_local))

        fut = loop.run_in_executor(None, _worker)
        ok = False
        while True:
            kind, val = await q.get()
            if kind == "line":
                yield _ev({"type": "cmd_line", "content": val[:300]})
            else:
                ok = val; break
        await fut
        invalidate_baseline()  # o comando pode ter mudado o workspace
        yield _ev({"type": "step", "icon": "✓" if ok else "✗", "message": "concluído" if ok else "falhou"})
        yield _ev({"type": "done", "ok": ok})

    return StreamingResponse(gpu_priority(stream()), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class CoderCommitRequest(BaseModel):
    message: str = ""


@router.post("/api/coder/commit")
async def coder_commit(req: CoderCommitRequest):
    """Commit assistido: sem mensagem, o modelo leve gera uma (Conventional
    Commits) a partir do diff real. NUNCA faz push (bloqueado no sandbox)."""
    msg = (req.message or "").strip()
    if not msg:
        st = await asyncio.to_thread(rt.coder_ws.git_status)
        if not st.get("is_repo"):
            return {"ok": False, "error": "o workspace não é um repositório git"}
        if not st.get("dirty"):
            return {"ok": False, "error": "nada para commitar"}
        diff = await asyncio.to_thread(rt.coder_ws.git_diff)
        prompt = COMMIT_MSG_PROMPT.format(
            status=(st.get("status") or "")[:800], diff=diff[:3000])
        try:
            raw = await asyncio.to_thread(
                chat_resilient, rt.get_chat_model(),
                [{"role": "user", "content": prompt}], keep_alive=KEEP_ALIVE) or ""
            msg = raw.strip().splitlines()[0].strip().strip('`"\'')[:150]
        except Exception as e:
            logger.debug(f"commit msg: {e}")
        if not msg:
            msg = "chore: alterações via A.P.O.L.O. Coder"
    return await asyncio.to_thread(rt.coder_ws.git_commit_all, msg)
