"""Endpoint do A.P.O.L.O. Coder (routers/coder.py) — o último e maior endpoint
extraído do monólito na M1. O parser (parse_coder_action) já é coberto à exaustão
em test_coder_autonomy/test_coder/test_coder_edit; aqui garantimos que a rota foi
registrada e que o parser está acessível pelo novo módulo.
"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from src.coder import CoderWorkspace
import routers.coder as coder_mod
from routers.coder import router, parse_coder_action


def test_rota_registrada():
    assert any(getattr(r, "path", None) == "/api/coder" for r in router.routes)


def test_parser_acessivel_pelo_router():
    # sanity: o parser mora agora em routers.coder e responde às ações básicas
    assert parse_coder_action("LISTAR .")[0] == "list"
    assert parse_coder_action("BUSCAR_WEB: fastapi sse")[0] == "web"
    assert parse_coder_action("CONSULTAR asyncio")[0] == "consult"
    assert parse_coder_action("resposta final sem acao")[0] == "done"


def test_workspace_vazio_barra_antes_de_chamar_o_modelo(tmp_path, monkeypatch):
    """Achado ao vivo (2026-07-14): reaproveitar uma tarefa antiga com 'Executar'
    depois de reiniciar o app (ponteiro da cópia sandbox zera no restart) rodava
    o loop inteiro contra um workspace vazio — minutos de geração fracassada até
    'concluir' sem ter feito nada. Agora barra ANTES de qualquer chamada ao LLM."""
    def _boom(*a, **k):
        raise AssertionError("não deveria chamar o modelo com workspace vazio")
    monkeypatch.setattr(coder_mod, "chat_resilient", _boom)

    ws = CoderWorkspace(root=str(tmp_path / "vazio"))
    rt.configure(coder_ws=ws, model="qwen-7b", get_chat_model=lambda: "qwen-1.5b",
                 project_mem=None, lesson_mem=None, gpu_gate=None, db=None)

    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).post("/api/coder", json={"message": "melhore o código", "session_id": "s1"})
    assert r.status_code == 200
    eventos = [json.loads(ln[6:]) for ln in r.text.splitlines() if ln.startswith("data: ")]
    assert eventos[0]["type"] == "error"
    assert "vazio" in eventos[0]["message"].lower()
    assert len(eventos) == 1   # nada mais rodou depois do erro


def _scripted_chat(responses):
    """Fake chat_resilient: devolve as respostas na ordem, capturando os `messages`
    de cada chamada (pra inspecionar o que o loop pediu na chamada seguinte)."""
    calls = []
    i = {"n": 0}

    def fake(model, messages, keep_alive=None):
        calls.append(list(messages))
        out = responses[min(i["n"], len(responses) - 1)]
        i["n"] += 1
        return out
    fake.calls = calls
    return fake


def _client_with_workspace(tmp_path, fake_chat, monkeypatch, filename="demo.py", content="print('hola')\n"):
    monkeypatch.setattr(coder_mod, "chat_resilient", fake_chat)
    ws = CoderWorkspace(root=str(tmp_path / "proj"))
    ws.write_file(filename, content)
    rt.configure(coder_ws=ws, model="qwen-7b", get_chat_model=lambda: "qwen-1.5b",
                 project_mem=None, lesson_mem=None, gpu_gate=None, db=None)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_editar_falhando_2x_empurra_para_escrever(tmp_path, monkeypatch):
    """Achado ao vivo (2026-07-14): EDITAR falhou 3x seguidas (texto não bateu
    exato) e a tarefa gastou ~50min sem escrever NADA. Agora, na 2a falha seguida
    no mesmo arquivo, o próximo prompt ao modelo inclui um empurrão explícito
    para trocar de estratégia (ESCREVER, que não exige match exato)."""
    edit_fail = "EDITAR demo.py\n<<<<<<<\ntexto que não existe no arquivo\n=======\nnovo\n>>>>>>>\n"
    fake = _scripted_chat([
        "plano: ler e editar",              # fase de planejamento
        edit_fail,                          # passo 1: falha
        edit_fail,                          # passo 2: falha de novo (streak=2)
        "CONCLUIR: parei por aqui",         # passo 3: encerra
    ])
    client = _client_with_workspace(tmp_path, fake, monkeypatch)
    r = client.post("/api/coder", json={"message": "melhore demo.py", "session_id": "s1"})
    assert r.status_code == 200
    # a 4ª chamada (índice 3) é a que roda DEPOIS da 2ª falha — a mensagem do
    # usuário mais recente nela precisa conter o empurrão para ESCREVER.
    last_user_msg = fake.calls[3][-1]["content"]
    assert "ESCREVER" in last_user_msg and "pare de tentar editar" in last_user_msg.lower()


def test_conclusao_lixo_apos_resgate_vira_mensagem_honesta(tmp_path, monkeypatch):
    """Achado ao vivo: a 'conclusão' final era um EDITAR cru cortado no meio
    (marcadores <<<<<<< sem fechar) — e ainda assim aparecia como '✅ Concluído'.
    Isso não pode virar a resposta final quando o resgate único já foi gasto."""
    garbled = "EDITAR demo.py\n<<<<<<< algo\nsem fechar direito"
    fake = _scripted_chat([
        "plano",
        garbled,   # passo 1: nem vira 'edit' válido (sem >>>>>>>) nem tem CONCLU → resgate
        garbled,   # passo 2: lixo de novo, mas o resgate já foi usado
    ])
    client = _client_with_workspace(tmp_path, fake, monkeypatch)
    r = client.post("/api/coder", json={"message": "melhore demo.py", "session_id": "s1"})
    assert r.status_code == 200
    eventos = [json.loads(ln[6:]) for ln in r.text.splitlines() if ln.startswith("data: ")]
    done = next(e for e in eventos if e["type"] == "done")
    assert "<<<<<<<" not in done["answer"]           # nunca mostra o lixo cru
    assert "não consegui concluir" in done["answer"].lower()
