"""Gera os ícones PNG do A.P.O.L.O. para o PWA (192x192 e 512x512).

Requer: pip install Pillow
Saída:  static/apolo-icon-192.png
        static/apolo-icon-512.png

Execute uma vez após clonar o projeto ou quando quiser atualizar os ícones.
O manifest.json já referencia esses arquivos — sem eles o PWA ainda funciona
com o ícone SVG, mas o Chrome exige PNG 192x192 para o prompt de instalação.
"""

import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow não encontrado. Execute:  pip install Pillow")
    sys.exit(1)

ROOT = Path(__file__).parent.parent
STATIC = ROOT / "static"


def _draw_sun(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Desenha o sol do A.P.O.L.O. no objeto ImageDraw."""
    cx = cy = size // 2
    margin = int(size * 0.06)

    # Raios (8 barras arredondadas ao redor do núcleo)
    ray_len   = int(size * 0.165)
    ray_w     = int(size * 0.058)
    ray_start = int(size * 0.32)
    for i in range(8):
        angle = math.radians(i * 45 - 90)
        x0 = cx + math.cos(angle) * ray_start
        y0 = cy + math.sin(angle) * ray_start
        x1 = cx + math.cos(angle) * (ray_start + ray_len)
        y1 = cy + math.sin(angle) * (ray_start + ray_len)
        # Simula barra arredondada com uma série de círculos
        steps = 12
        for s in range(steps + 1):
            t = s / steps
            px = x0 + (x1 - x0) * t
            py = y0 + (y1 - y0) * t
            r = ray_w // 2
            draw.ellipse((px - r, py - r, px + r, py + r), fill=(245, 158, 11, 140))

    # Núcleo do sol — 4 círculos concêntricos
    def circle(r: int, color: tuple) -> None:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)

    circle(int(size * 0.205), (146, 64, 14, 255))   # borda escura
    circle(int(size * 0.175), (217, 119,  6, 255))  # anel médio
    circle(int(size * 0.145), (245, 158, 11, 255))  # corpo
    circle(int(size * 0.110), (251, 191, 36, 255))  # brilho
    circle(int(size * 0.075), (254, 243, 199, 255)) # centro claro


def make_icon(size: int, path: Path) -> None:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fundo arredondado (corner ≈ 22.5 % do tamanho — padrão iOS/Android)
    radius = int(size * 0.225)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=(12, 12, 14, 255))

    _draw_sun(draw, size)

    img.save(str(path), "PNG")
    print(f"OK {path.relative_to(ROOT)} ({size}x{size})")


if __name__ == "__main__":
    STATIC.mkdir(parents=True, exist_ok=True)
    make_icon(192, STATIC / "apolo-icon-192.png")
    make_icon(512, STATIC / "apolo-icon-512.png")
    print("\nÍcones gerados! Reinicie o servidor para que o PWA os utilize.")
