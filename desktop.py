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
    # 1) Sobe o servidor só se ninguém já estiver na porta (evita conflito). Se já
    #    estava no ar (ex.: você rodou app.py à mão), este script não é DONO do
    #    servidor — só abre uma janela/aba por cima. Isso importa para os avisos
    #    abaixo: "fechar isso encerra o A.P.O.L.O." só é verdade quando FOMOS nós
    #    que subimos o servidor (senão é outro processo, alheio a esta janela).
    started_here = not _port_open()
    if started_here:
        threading.Thread(target=_serve, daemon=True).start()
        print("Iniciando o A.P.O.L.O.…")
        if not _wait_until_up():
            print("O servidor não subiu a tempo. Veja o log e tente de novo.")
            return 1

    # 2) Abre a JANELA NATIVA (sem navegador). Fallback robusto: navegador padrão.
    #    Qualquer falha do webview (lib ausente OU WebView2 quebrado) NÃO derruba
    #    o servidor — cai no navegador.
    try:
        import webview
        webview.create_window("A.P.O.L.O.", URL, width=1280, height=860,
                              min_size=(900, 600))
        if started_here:
            print("Janela do A.P.O.L.O. aberta. Fechá-la encerra o app.")
        else:
            print("Janela do A.P.O.L.O. aberta (servidor já estava rodando em "
                  "outro processo — fechar esta janela não o encerra).")
        webview.start()                 # bloqueia até fechar a janela
        return 0
    except ImportError:
        print("Janela nativa indisponível — 'pywebview' não está instalado.")
        print("Para abrir SEM navegador:  pip install pywebview")
    except Exception as e:
        print(f"Não consegui abrir a janela nativa ({e}). Usando o navegador.")

    # Fallback: abre no navegador padrão. Só precisamos manter este terminal vivo
    # (e o servidor com ele) quando FOMOS nós que o subimos — se já estava rodando
    # em outro processo, abrir a aba basta; não há nada aqui para manter de pé.
    import webbrowser
    print(f"Abrindo no navegador: {URL}")
    webbrowser.open(URL)
    if not started_here:
        return 0
    print("⚠️  Deixe este terminal ABERTO — fechá-lo encerra o servidor do A.P.O.L.O.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
