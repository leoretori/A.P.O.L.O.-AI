"""Testes do núcleo determinístico da Visão útil (M22, Épicos 22.1/22.3) —
22.1 adiados a pedido do Leo ("testes fazemos depois") e fechados agora
(2026-07-15). 22.3 (câmera) fecha no mesmo dia."""
import base64
import sys
import types

from src import vision_read as V


def _fake_cv2(*, opens=True, read_ok=True):
    """cv2 falso — evita depender do pacote pesado (opcional, `opt-in`) real
    nos testes; injetado direto em sys.modules, como `import cv2` acharia."""
    import numpy as np
    mod = types.ModuleType("cv2")

    class _Cap:
        def __init__(self, index):
            self.index = index

        def isOpened(self):
            return opens

        def read(self):
            if not read_ok:
                return False, None
            return True, np.zeros((60, 100, 3), dtype=np.uint8)

        def release(self):
            pass

    mod.VideoCapture = _Cap
    return mod


# ── capture_screen ──────────────────────────────────────────────
def test_capture_screen_redimensiona_quando_maior_que_max_width(monkeypatch):
    from PIL import Image
    fake_img = Image.new("RGB", (2000, 1000), color="red")
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: fake_img)

    out = V.capture_screen(max_width=1000)
    assert out["ok"] is True
    assert out["size"] == [1000, 500]  # proporção preservada
    # o PNG em base64 decodifica de volta pro tamanho certo
    decoded = base64.b64decode(out["image_b64"])
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n"  # assinatura PNG


def test_capture_screen_nao_redimensiona_quando_menor(monkeypatch):
    from PIL import Image
    fake_img = Image.new("RGB", (640, 480), color="blue")
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: fake_img)

    out = V.capture_screen(max_width=1280)
    assert out["ok"] is True
    assert out["size"] == [640, 480]


def test_capture_screen_erro_quando_indisponivel(monkeypatch):
    def _boom():
        raise RuntimeError("sem display")
    monkeypatch.setattr("PIL.ImageGrab.grab", _boom)

    out = V.capture_screen()
    assert out["ok"] is False
    assert "captura de tela indisponível" in out["error"]


# ── capture_camera (M22.3) ──────────────────────────────────────
def test_capture_camera_sem_lib_instalada():
    # opencv-python de fato NÃO está instalado neste ambiente — exercita o
    # ImportError real, sem monkeypatch (mesmo padrão do docx no 22.1).
    out = V.capture_camera()
    assert out["ok"] is False
    assert "opencv-python" in out["error"]


def test_capture_camera_sucesso(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", _fake_cv2())
    out = V.capture_camera()
    assert out["ok"] is True
    assert out["size"] == [100, 60]
    decoded = base64.b64decode(out["image_b64"])
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n"


def test_capture_camera_redimensiona_quando_maior_que_max_width(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", _fake_cv2())
    out = V.capture_camera(max_width=50)
    assert out["ok"] is True
    assert out["size"] == [50, 30]


def test_capture_camera_nao_encontrada(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", _fake_cv2(opens=False))
    out = V.capture_camera()
    assert out["ok"] is False
    assert "não encontrada" in out["error"]


def test_capture_camera_falha_ao_ler_frame(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", _fake_cv2(read_ok=False))
    out = V.capture_camera()
    assert out["ok"] is False
    assert "falha ao capturar frame" in out["error"]


def test_capture_camera_libera_a_camera_sempre(monkeypatch):
    released = []

    class _CapTracked:
        def __init__(self, index): pass
        def isOpened(self): return True
        def read(self):
            raise RuntimeError("erro no meio da leitura")
        def release(self): released.append(True)

    mod = types.ModuleType("cv2")
    mod.VideoCapture = _CapTracked
    monkeypatch.setitem(sys.modules, "cv2", mod)

    try:
        V.capture_camera()
    except RuntimeError:
        pass
    assert released == [True]  # release() roda mesmo se read() explodir


# ── read_document ────────────────────────────────────────────────
def test_read_document_texto():
    out = V.read_document("notas.txt", "olá mundo".encode("utf-8"))
    assert out == {"ok": True, "kind": "text", "text": "olá mundo", "chars": 9}


def test_read_document_sem_extensao_trata_como_texto():
    out = V.read_document("README", b"conteudo sem extensao")
    assert out["ok"] is True and out["kind"] == "text"


def test_read_document_trunca_texto_grande():
    big = "a" * (V.MAX_TEXT_CHARS + 500)
    out = V.read_document("grande.txt", big.encode("utf-8"))
    assert out["ok"] is True
    assert len(out["text"]) == V.MAX_TEXT_CHARS
    assert out["chars"] == len(big)  # o contador reporta o tamanho REAL, não o truncado


def test_read_document_imagem_marca_needs_vision():
    raw = b"\x89PNG\r\n\x1a\nfake-bytes"
    out = V.read_document("foto.png", raw)
    assert out == {"ok": True, "kind": "image", "needs_vision": True,
                    "image_b64": base64.b64encode(raw).decode("ascii")}


def test_read_document_tipo_desconhecido():
    out = V.read_document("arquivo.xyz", b"\x00\x01")
    assert out["ok"] is False and out["kind"] == "unknown"
    assert "xyz" in out["error"]


def test_read_document_pdf_ok(monkeypatch):
    monkeypatch.setattr("src.ingest.extract_pdf_text", lambda raw: "texto do pdf")
    out = V.read_document("doc.pdf", b"%PDF-fake")
    assert out == {"ok": True, "kind": "pdf", "text": "texto do pdf", "chars": 12}


def test_read_document_pdf_sem_lib(monkeypatch):
    def _boom(raw):
        raise ImportError("no module named pypdf")
    monkeypatch.setattr("src.ingest.extract_pdf_text", _boom)
    out = V.read_document("doc.pdf", b"%PDF-fake")
    assert out["ok"] is False and out["kind"] == "pdf"
    assert "pypdf" in out["error"]


def test_read_document_pdf_falha_de_parse(monkeypatch):
    def _boom(raw):
        raise ValueError("pdf corrompido")
    monkeypatch.setattr("src.ingest.extract_pdf_text", _boom)
    out = V.read_document("doc.pdf", b"%PDF-fake")
    assert out["ok"] is False and out["kind"] == "pdf"
    assert "falha ao ler o PDF" in out["error"]


def test_read_document_docx_ok(monkeypatch):
    monkeypatch.setattr("src.ingest.extract_docx_text", lambda raw: "texto do docx")
    out = V.read_document("doc.docx", b"fake-docx-bytes")
    assert out == {"ok": True, "kind": "docx", "text": "texto do docx", "chars": 13}


def test_read_document_docx_sem_lib_instalada():
    # python-docx de fato NÃO está instalado neste ambiente — exercita o caminho
    # real de ImportError, sem precisar de monkeypatch.
    out = V.read_document("doc.docx", b"fake-docx-bytes")
    assert out["ok"] is False and out["kind"] == "docx"
    assert "python-docx" in out["error"]


# ── describe_image ───────────────────────────────────────────────
def test_describe_image_sem_modelo_de_visao():
    out = V.describe_image("base64img", None, lambda m, msgs: "nunca chamado")
    assert out["ok"] is False
    assert "modelo de visão" in out["error"]


def test_describe_image_sucesso():
    calls = []

    def fake_complete(model, messages):
        calls.append((model, messages))
        return "  uma tela com um editor de código  "

    out = V.describe_image("base64img", "llava", fake_complete)
    assert out == {"ok": True, "description": "uma tela com um editor de código",
                    "model": "llava"}
    assert calls[0][0] == "llava"
    assert calls[0][1][0]["images"] == ["base64img"]


def test_describe_image_usa_prompt_customizado():
    captured = {}

    def fake_complete(model, messages):
        captured["prompt"] = messages[0]["content"]
        return "ok"

    V.describe_image("b64", "llava", fake_complete, prompt="descreva a tela")
    assert captured["prompt"] == "descreva a tela"


def test_describe_image_propaga_erro_do_modelo():
    def fake_complete(model, messages):
        raise RuntimeError("modelo offline")

    out = V.describe_image("b64", "llava", fake_complete)
    assert out["ok"] is False and "modelo offline" in out["error"]


# ── capabilities ─────────────────────────────────────────────────
def test_capabilities_com_modelo_de_visao():
    out = V.capabilities("llava")
    assert out["vision"] is True and out["vision_model"] == "llava"
    assert out["text_docs"] is True
    assert out["pdf"] is True   # pypdf está instalado neste ambiente
    assert out["camera"] is False   # opencv-python NÃO está instalado (honesto)


def test_capabilities_sem_modelo_de_visao():
    out = V.capabilities(None)
    assert out["vision"] is False and out["vision_model"] is None
