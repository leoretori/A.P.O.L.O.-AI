"""Abre o A.P.O.L.O. como APP DE DESKTOP — janela nativa, sem navegador.

Sobe o servidor local numa thread e abre uma janela nativa apontando para ele.
No Windows usa o WebView2 (Edge), já embutido no Win10/11 — sem barra de endereço,
sem aba, parece um programa comum. Se o servidor já estiver rodando (porta 8000
ocupada), só abre a janela por cima dele. Se o `pywebview` não estiver instalado,
cai no navegador padrão e explica como ter a janela nativa.

Uso:
    pip install pywebview      # uma vez (a lib da janela nativa)
    pythonw desktop.py         # 'pythonw' = sem janela preta de console

Dica: crie um atalho na Área de Trabalho apontando para
    <caminho do python>\\pythonw.exe  "<pasta do projeto>\\desktop.py"
e troque o ícone para o static/apolo-icon (via um .ico) — vira um app de verdade.
"""
import socket
import sys
import threading
import time

HOST, PORT = "127.0.0.1", 8000
URL = f"http://{HOST}:{PORT}"


def _port_open(timeout: float = 0.6) -> bool:
    """A porta já responde? (servidor do A.P.O.L.O. já no ar)"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((HOST, PORT))
            return True
        except OSError:
            return False


def _serve() -> None:
    import uvicorn
    uvicorn.run("app:app", host=HOST, port=PORT, log_level="warning")


def _wait_until_up(timeout: float = 60) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _port_open():
            return True
        time.sleep(0.4)
    return False


def main() -> int:
    # 1) Sobe o servidor só se ninguém já estiver na porta (evita conflito).
    if not _port_open():
        threading.Thread(target=_serve, daemon=True).start()
        print("Iniciando o A.P.O.L.O.…")
        if not _wait_until_up():
            print("O servidor não subiu a tempo. Veja o log e tente de novo.")
            return 1

    # 2) Abre a JANELA NATIVA (sem navegador). Fallback: navegador padrão.
    try:
        import webview
    except ImportError:
        import webbrowser
        print("Janela nativa indisponível — 'pywebview' não está instalado.")
        print("Para abrir SEM navegador:  pip install pywebview")
        print(f"Abrindo no navegador padrão: {URL}")
        webbrowser.open(URL)
        try:
            while True:                 # mantém o servidor vivo enquanto usa
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    webview.create_window("A.P.O.L.O.", URL, width=1280, height=860,
                          min_size=(900, 600))
    webview.start()                     # bloqueia até fechar a janela
    return 0


if __name__ == "__main__":
    sys.exit(main())
