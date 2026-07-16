"""Placar histórico append-only genérico (src/jsonl_history, extraído no P2.6)."""

from src.jsonl_history import append_entry, read_entries


def test_append_e_read_roundtrip(tmp_path):
    path = tmp_path / "hist.jsonl"
    append_entry(path, {"n": 1})
    append_entry(path, {"n": 2})
    hist = read_entries(path)
    assert len(hist) == 2
    assert hist[0]["n"] == 1 and hist[1]["n"] == 2
    assert all("timestamp" in h for h in hist)


def test_read_entries_arquivo_inexistente(tmp_path):
    assert read_entries(tmp_path / "nao_existe.jsonl") == []


def test_read_entries_respeita_limit(tmp_path):
    path = tmp_path / "hist.jsonl"
    for i in range(10):
        append_entry(path, {"n": i})
    ultimos = read_entries(path, limit=3)
    assert [h["n"] for h in ultimos] == [7, 8, 9]


def test_append_entry_nunca_reescreve_o_passado(tmp_path):
    path = tmp_path / "hist.jsonl"
    append_entry(path, {"n": 1})
    conteudo_antes = path.read_text(encoding="utf-8")
    append_entry(path, {"n": 2})
    conteudo_depois = path.read_text(encoding="utf-8")
    assert conteudo_depois.startswith(conteudo_antes)


def test_append_entry_cria_diretorio_pai(tmp_path):
    path = tmp_path / "sub" / "dir" / "hist.jsonl"
    append_entry(path, {"n": 1})
    hist = read_entries(path)
    assert len(hist) == 1 and hist[0]["n"] == 1
