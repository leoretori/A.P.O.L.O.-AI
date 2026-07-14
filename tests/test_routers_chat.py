"""Chat principal (routers/chat.py) — o último endpoint extraído na M1.
Fecha o app.py sem rotas próprias. Testa o fast-path (mensagem curta → sem
recall/FTS) com stream_chat fake, e a persistência da conversa.
"""
import json
from collections import defaultdict

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.chat as chat_mod
from routers.chat import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rota_registrada():
    assert any(getattr(r, "path", None) == "/api/chat" for r in router.routes)


def test_chat_fast_path_streama_e_persiste(monkeypatch):
    async def fake_stream_chat(model, messages, keep_alive=None):
        for tok in ("Olá", "!"):
            yield tok

    monkeypatch.setattr(chat_mod, "stream_chat", fake_stream_chat)

    saved = []

    class FakeExecResult:
        success = True
        stdout = ""
        stderr = ""

    class FakeDB:
        def load_session(self, sid): return None
        def save_message(self, sid, role, content): saved.append((role, content))
        def save_execution(self, d): pass

    sessions = defaultdict(list)   # igual à produção (auto-cria lista por sessão)
    session_summaries = {}
    rt.configure(rag=None, knowledge_db=None, learner=None, profile=None,
                 project_mem=None, db=FakeDB(), executor=None, gpu_gate=None,
                 sessions=sessions, session_summaries=session_summaries,
                 model="qwen2.5-coder:14b", get_chat_model=lambda: "qwen2.5-coder:3b",
                 get_vision_model=lambda: "")

    # "oi" tem <= SHORT_MSG_CHARS → fast path (sem recall/FTS)
    r = _client().post("/api/chat", json={"message": "oi", "session_id": "s1"})
    assert r.status_code == 200
    eventos = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    tipos = [e["type"] for e in eventos]
    assert "token" in tipos and eventos[-1]["type"] == "done"
    # resposta montada dos tokens e conversa persistida (dict + banco)
    assert sessions["s1"][-1]["content"] == "Olá!"
    assert ("assistant", "Olá!") in saved


def test_chat_comum_nao_executa_codigo_da_resposta(monkeypatch):
    """Código no chat COMUM é ilustrativo — quem executa de verdade é o Modo
    Agente (/api/agent), caminho separado. Rodar aqui sem essa intenção explícita
    gerava falsos 'erros' quando o modelo escrevia um exemplo (import imaginado)
    que nunca deveria ser executado (achado ao vivo: pergunta conceitual sobre
    auto-melhoria → o modelo ilustrou código → o app tentou rodar e falhou)."""
    async def fake_stream_chat(model, messages, keep_alive=None):
        yield "Aqui vai um exemplo:\n```python\nimport modulo_inventado\n```\n"
    monkeypatch.setattr(chat_mod, "stream_chat", fake_stream_chat)

    class _BoomExecutor:
        def run(self, code):
            raise AssertionError("chat comum não deve executar código — isso é o Modo Agente")

    class FakeDB:
        def load_session(self, sid): return None
        def save_message(self, sid, role, content): pass
        def save_execution(self, d): pass

    rt.configure(rag=None, knowledge_db=None, learner=None, profile=None,
                 project_mem=None, db=FakeDB(), executor=_BoomExecutor(), gpu_gate=None,
                 sessions=defaultdict(list), session_summaries={},
                 model="qwen2.5-coder:14b", get_chat_model=lambda: "qwen2.5-coder:3b",
                 get_vision_model=lambda: "")

    r = _client().post("/api/chat", json={
        "message": "como você poderia melhorar seu próprio código?", "session_id": "s-code"})
    assert r.status_code == 200
    eventos = [json.loads(ln[6:]) for ln in r.text.splitlines() if ln.startswith("data: ")]
    done = eventos[-1]
    assert done["type"] == "done"
    assert done["has_code"] is True          # o código aparece pra leitura...
    assert "import modulo_inventado" in done["code"]
    assert done["success"] is None           # ...mas NUNCA foi executado
    assert done["output"] == "" and done["error"] == ""


def test_chat_recall_passa_pelo_memory_fabric(monkeypatch):
    """Mensagem longa (não fast-path) → o recall semântico do chat vai pelo
    MemoryFabric. A memória recuperada vira memory_sources no evento 'done'."""
    from src.memory import MemoryFabric

    async def fake_stream_chat(model, messages, keep_alive=None):
        yield "resposta"
    monkeypatch.setattr(chat_mod, "stream_chat", fake_stream_chat)

    class FakeRag:
        def recall(self, query, n):
            return [{"title": "FastAPI streaming", "snippet": "use StreamingResponse",
                     "source": "doc:fastapi", "relevance": 0.9}]

    class FakeDB:
        def load_session(self, sid): return None
        def save_message(self, sid, role, content): pass
        def save_execution(self, d): pass

    rt.configure(rag=None, knowledge_db=None, learner=None, profile=None,
                 project_mem=None, db=FakeDB(), executor=None, gpu_gate=None,
                 memory=MemoryFabric(rag=FakeRag()),
                 sessions=defaultdict(list), session_summaries={},
                 model="qwen2.5-coder:14b", get_chat_model=lambda: "qwen2.5-coder:3b",
                 get_vision_model=lambda: "")

    r = _client().post("/api/chat", json={
        "message": "como faço streaming de resposta no FastAPI com SSE?",
        "session_id": "s2"})
    assert r.status_code == 200
    eventos = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    done = eventos[-1]
    assert done["type"] == "done"
    # a memória recuperada (via fabric) apareceu como fonte e NÃO foi tratada como lacuna
    titles = [s["title"] for s in done["memory_sources"]]
    assert "FastAPI streaming" in titles
    assert done["gap"] is False


def test_maybe_extract_fact_ignora_mensagem_impessoal():
    # Sem pista pessoal → não chama LLM (retorna cedo). Só garante que não quebra.
    import asyncio
    rt.configure(profile=None)
    asyncio.run(chat_mod._maybe_extract_fact("qual a capital da França?"))


def test_maybe_extract_fact_propoe_candidato_sem_gravar(tmp_path):
    """M16.2: mensagem pessoal vira CANDIDATO (não fato) — determinístico, sem LLM."""
    import asyncio

    from src.profile import UserProfile
    prof = UserProfile(path=str(tmp_path / "p.json"))
    rt.configure(profile=prof)
    asyncio.run(chat_mod._maybe_extract_fact("prefiro respostas diretas e honestas"))
    assert len(prof.pending()) == 1          # proposto
    assert prof.pending()[0]["category"] == "preference"
    assert prof.list() == []                 # NADA gravado sem confirmação
