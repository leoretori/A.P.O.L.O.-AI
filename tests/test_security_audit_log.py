"""Registro histórico de auditorias de segurança (src.security_audit_log, P4.2)."""

from src.security_audit_log import log_audit, read_audit_history


def _achado(status="fixed", severity="high"):
    return {"category": "csrf", "severity": severity, "file": "routers/vision.py",
            "summary": "captura de tela sem checagem de origem", "status": status}


def test_log_audit_grava_e_le(tmp_path):
    path = tmp_path / "hist.jsonl"
    entry = log_audit(path, date="2026-07-15", trigger="manual",
                      findings=[_achado(), _achado(status="open", severity="medium")],
                      notes="4 vulns achadas via /security-review")
    assert entry["total"] == 2 and entry["fixed"] == 1

    hist = read_audit_history(path)
    assert len(hist) == 1
    assert hist[0]["date"] == "2026-07-15"
    assert hist[0]["trigger"] == "manual"
    assert hist[0]["total"] == 2 and hist[0]["fixed"] == 1
    assert "timestamp" in hist[0]  # carimbo automático do jsonl_history


def test_log_audit_acumula_historico_sem_reescrever(tmp_path):
    path = tmp_path / "hist.jsonl"
    log_audit(path, date="2026-07-15", trigger="manual", findings=[_achado()])
    log_audit(path, date="2026-08-01", trigger="pre-merge-large", findings=[])
    hist = read_audit_history(path)
    assert len(hist) == 2
    assert [h["date"] for h in hist] == ["2026-07-15", "2026-08-01"]


def test_log_audit_sem_achados(tmp_path):
    path = tmp_path / "hist.jsonl"
    entry = log_audit(path, date="2026-08-01", trigger="pre-merge-large", findings=[])
    assert entry["total"] == 0 and entry["fixed"] == 0


def test_read_audit_history_arquivo_inexistente(tmp_path):
    assert read_audit_history(tmp_path / "nao_existe.jsonl") == []
