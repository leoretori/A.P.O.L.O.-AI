"""
Agente de Code Review do A.P.O.L.O.

Revisa código usando o conhecimento que ele mesmo acumulou (recall semântico do ChromaDB)
+ raciocínio do LLM. Devolve uma revisão estruturada por severidade, em streaming.
"""

import asyncio
import logging
import re
import threading

from src.llm import KEEP_ALIVE_HEAVY, stream_sync
from src.prompts import CODE_REVIEW_PROMPT

logger = logging.getLogger(__name__)

MAX_CODE_CHARS    = 6000
RECALL_FOR_REVIEW = 3


# Heurística leve de detecção de linguagem quando o usuário escolhe "auto"
_LANG_HINTS = [
    ("python",     [r"\bdef\s+\w+\s*\(", r"\bimport\s+\w+", r"\bself\b", r"->\s*\w+:", r":\s*$"]),
    ("typescript", [r"\binterface\s+\w+", r":\s*(string|number|boolean)\b", r"\bexport\s+(const|class|function)"]),
    ("javascript", [r"\bconst\s+\w+\s*=", r"=>", r"\bfunction\s*\(", r"\bconsole\.log"]),
    ("go",         [r"\bfunc\s+\w+\s*\(", r"\bpackage\s+\w+", r":=", r"\bimport\s+\("]),
    ("rust",       [r"\bfn\s+\w+\s*\(", r"\blet\s+mut\b", r"\bimpl\b", r"->\s*Result<"]),
    ("sql",        [r"\bSELECT\b.*\bFROM\b", r"\bCREATE\s+TABLE\b", r"\bINSERT\s+INTO\b"]),
    ("bash",       [r"^#!/.*sh", r"\becho\s+", r"\$\{?\w+\}?", r"\bfi\b"]),
]


def detect_language(code: str) -> str:
    sample = code[:1200]
    best, best_score = "python", 0
    for lang, patterns in _LANG_HINTS:
        score = sum(1 for p in patterns if re.search(p, sample, re.MULTILINE | re.IGNORECASE))
        if score > best_score:
            best, best_score = lang, score
    return best


class CodeReviewAgent:
    """Revisa código com apoio da base de conhecimento do A.P.O.L.O."""

    def __init__(self, model: str, rag=None):
        self.model = model
        self.rag = rag

    def _recall_practices(self, code: str, language: str) -> tuple[str, list[dict]]:
        """Busca boas práticas relevantes que o A.P.O.L.O. já estudou."""
        if not self.rag:
            return "", []
        # Query: linguagem + símbolos mais frequentes do código (frameworks, libs)
        symbols = " ".join(list(dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", code[:800])))[:12])
        query = f"{language} boas práticas {symbols}"
        try:
            memories = self.rag.recall(query, RECALL_FOR_REVIEW)
        except Exception as e:
            logger.debug(f"[review] recall: {e}")
            return "", []
        if not memories:
            return "", []
        block = "\n\n".join(
            f"- {m.get('title') or 'memória'}: {(m.get('snippet') or '')[:300]}"
            for m in memories
        )
        return block, memories

    async def _stream_review(self, prompt: str):
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker():
            try:
                for piece in stream_sync(
                    self.model,
                    [{"role": "user", "content": prompt}],
                    keep_alive=KEEP_ALIVE_HEAVY,
                ):
                    loop.call_soon_threadsafe(q.put_nowait, ("token", piece))
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))
            finally:
                loop.call_soon_threadsafe(q.put_nowait, ("end", None))

        threading.Thread(target=worker, daemon=True).start()
        while True:
            kind, val = await q.get()
            if kind == "end":
                break
            yield kind, val

    async def review(self, code: str, language: str = "auto"):
        """Async generator de eventos SSE: status / token / done / error."""
        code = (code or "").strip()
        if len(code) < 10:
            yield {"type": "error", "message": "Cole um trecho de código para revisar."}
            return

        code = code[:MAX_CODE_CHARS]
        if language in ("", "auto"):
            language = detect_language(code)
            yield {"type": "status", "message": f"Linguagem detectada: {language}"}

        yield {"type": "status", "message": "Consultando boas práticas aprendidas..."}
        knowledge_block, memories = await asyncio.to_thread(self._recall_practices, code, language)

        knowledge_section = ""
        if knowledge_block:
            knowledge_section = (
                "\nBOAS PRÁTICAS RELEVANTES (que você estudou — use se aplicável):\n"
                f"{knowledge_block}\n"
            )
            yield {"type": "status", "message": f"{len(memories)} práticas relevantes recuperadas"}

        yield {"type": "status", "message": "Revisando o código..."}
        prompt = CODE_REVIEW_PROMPT.format(
            language=language, code=code, knowledge_block=knowledge_section
        )

        review_text = ""
        async for kind, val in self._stream_review(prompt):
            if kind == "token":
                review_text += val
                yield {"type": "token", "content": val}
            elif kind == "error":
                yield {"type": "error", "message": f"Falha na revisão: {val}"}
                return

        yield {"type": "done", "review": review_text, "language": language,
               "sources": [{"title": m.get("title"), "url": m.get("source")} for m in memories]}
