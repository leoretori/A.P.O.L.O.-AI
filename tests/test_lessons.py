"""Testes da memória de lições do Coder (src/lessons.py) e da compactação
de contexto do loop ReAct (src/coder.py::compact_messages)."""

import pytest

from src.lessons import LessonMemory, _tokens
from src.coder import compact_messages


@pytest.fixture
def mem(tmp_path):
    return LessonMemory(str(tmp_path / "lessons.db"))


# ── Tokenização ───────────────────────────────────────────────────
def test_tokens_remove_stopwords_e_acentos():
    toks = _tokens("Crie um arquivo de configuração para o FastAPI")
    assert "fastapi" in toks
    assert "configuracao" in toks
    assert "para" not in toks and "crie" not in toks


# ── Adição e dedup ────────────────────────────────────────────────
def test_add_e_count(mem):
    lid = mem.add("corrigir bug no parser", "Sempre rodar pytest antes de concluir edições no parser.")
    assert lid is not None
    assert mem.count() == 1


def test_add_curta_demais_ignorada(mem):
    assert mem.add("tarefa", "ok") is None
    assert mem.count() == 0


def test_dedup_mesma_licao_nao_duplica(mem):
    lesson = "Preferir EDITAR cirúrgico a reescrever módulos grandes do projeto."
    id1 = mem.add("tarefa A", lesson)
    id2 = mem.add("tarefa B", lesson)
    assert id1 == id2
    assert mem.count() == 1


# ── Recall por relevância ─────────────────────────────────────────
def test_relevant_encontra_por_sobreposicao(mem):
    mem.add("criar endpoint FastAPI de upload",
            "Endpoints de upload no FastAPI precisam de python-multipart instalado.")
    mem.add("refatorar consultas SQL do storage",
            "O storage usa SQLAlchemy 2.x — sessões precisam de commit explícito.")
    res = mem.relevant("adicionar endpoint FastAPI para download")
    assert res, "deveria achar a lição de FastAPI"
    assert "multipart" in res[0]["lesson"]


def test_relevant_sem_match_retorna_vazio(mem):
    mem.add("tarefa de kubernetes", "Sempre validar o manifesto YAML com kubectl apply --dry-run.")
    assert mem.relevant("escrever poema sobre flores") == []


def test_regressao_pesa_mais_que_reflexao(mem):
    mem.add("editar parser", "Reflexão: o parser aceita marcadores tolerantes.", kind="reflection")
    mem.add("editar parser", "Regressão: mudar o parser quebrou a suíte inteira uma vez.", kind="regression")
    res = mem.relevant("melhorar o parser", limit=2)
    assert res[0]["kind"] == "regression"


def test_format_section_vazia_e_preenchida(mem):
    assert mem.format_section("qualquer tarefa") == ""
    mem.add("configurar docker compose", "O docker-compose do projeto usa a porta 8000 mapeada.")
    section = mem.format_section("ajustar docker compose do projeto")
    assert "LIÇÕES APRENDIDAS" in section
    assert "porta 8000" in section


def test_persistencia_entre_instancias(tmp_path):
    path = str(tmp_path / "l.db")
    LessonMemory(path).add("tarefa git", "Nunca fazer git push sem confirmação do usuário.")
    mem2 = LessonMemory(path)
    assert mem2.count() == 1
    assert mem2.relevant("comandos git da tarefa")


def test_delete(mem):
    lid = mem.add("tarefa X", "Lição temporária que será removida depois do teste.")
    assert mem.delete(lid) is True
    assert mem.count() == 0
    assert mem.delete(999) is False


# ── Compactação de contexto do loop ReAct ─────────────────────────
def _msgs(n_pairs: int, obs_size: int = 2000):
    msgs = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Tarefa: melhorar o app"},
        {"role": "assistant", "content": "Plano:\n1. LER\n2. EDITAR"},
        {"role": "user", "content": "Execute o primeiro passo."},
    ]
    for i in range(n_pairs):
        msgs.append({"role": "assistant", "content": f"LER arquivo_{i}.py"})
        msgs.append({"role": "user", "content": f"conteudo {i} " + "x" * obs_size})
    return msgs


def test_compact_abaixo_do_limite_intacto():
    msgs = _msgs(2, obs_size=100)
    assert compact_messages(msgs, max_chars=20000) is msgs


def test_compact_preserva_head_e_tail_e_reduz():
    msgs = _msgs(8, obs_size=4000)
    out = compact_messages(msgs, max_chars=10000, keep_head=4, keep_tail=4)
    assert out is not msgs
    # Head intacto (tarefa e plano são a âncora do loop).
    assert out[:4] == msgs[:4]
    # Tail intacto (o presente do loop).
    assert out[-4:] == msgs[-4:]
    # Miolo truncado.
    total_antes = sum(len(m["content"]) for m in msgs)
    total_depois = sum(len(m["content"]) for m in out)
    assert total_depois < total_antes / 2
    assert any("compactado" in m["content"] for m in out[4:-4])


def test_compact_poucas_mensagens_nao_mexe():
    msgs = _msgs(1, obs_size=50000)  # estoura o limite, mas só tem head+1 par
    out = compact_messages(msgs, max_chars=1000, keep_head=4, keep_tail=6)
    assert out is msgs
