"""Ação de MOVER/ORGANIZAR arquivo — confirmável e reversível (M21, Épico 21.1).

A primeira ação de SISTEMA (fora do texto): reorganizar arquivos no disco. Reusa
integralmente a disciplina do M10 — grant `files.write` + allowlist de pastas
(Permission.note) + as defesas de `files.py` (`_within` neutraliza `..`/symlink)
— e é a tarefa de sistema mais REVERSÍVEL que existe: desfazer = mover de volta.

  preview → mostra origem→destino, se é rename (mesma pasta) ou move, se colide
  apply   → move de fato e devolve o undo (os dois caminhos)
  undo    → move de volta para a origem (recusa se a origem foi reocupada)

Nunca sobrescreve um destino existente (segurança + reversibilidade). Núcleo
puro (preview/apply/undo_move) testável com pastas temporárias, sem DB/registry.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from src.actions import Action, register
from src.tools.files import _within, parse_roots

_NO_ROOTS = ("nenhuma pasta autorizada — abra 🔐 Permissões, autorize 'files.write' "
             "e informe a pasta onde o A.P.O.L.O. pode organizar arquivos")


def _checked(path_str: str, roots: list[Path], *, must_be_file: bool = False) -> Path:
    if not path_str:
        raise ValueError("caminho vazio")
    p = Path(path_str).expanduser()
    if not _within(p, roots):
        raise PermissionError("caminho fora das pastas autorizadas")
    rp = p.resolve()
    if must_be_file and not rp.is_file():
        raise FileNotFoundError(f"arquivo não encontrado: {rp.name}")
    return rp


def _resolve_dst(dst_str: str, src: Path, roots: list[Path]) -> Path:
    """Destino resolvido. Se `dst` é uma pasta existente, organiza PARA DENTRO
    dela mantendo o nome do arquivo."""
    if not dst_str:
        raise ValueError("informe 'dst' (destino)")
    p = Path(dst_str).expanduser()
    if not _within(p, roots):
        raise PermissionError("destino fora das pastas autorizadas")
    rp = p.resolve()
    if rp.is_dir():
        rp = rp / src.name
    if not rp.parent.exists():
        raise FileNotFoundError("a pasta de destino não existe")
    return rp


def preview_move(args: dict, roots: list[Path]) -> dict:
    """Prévia SEM efeito: o que aconteceria ao mover `src` para `dst`."""
    if not roots:
        raise PermissionError(_NO_ROOTS)
    src = _checked(args.get("src", ""), roots, must_be_file=True)
    dst = _resolve_dst(args.get("dst", ""), src, roots)
    if dst == src:
        raise ValueError("origem e destino são iguais")
    return {
        "src": str(src), "dst": str(dst),
        "action": "rename" if src.parent == dst.parent else "move",
        "target_exists": dst.exists(),
        "reversible": True,
    }


def apply_move(args: dict, roots: list[Path]) -> dict:
    """Move de fato e devolve os dados de undo (os dois caminhos)."""
    if not roots:
        raise PermissionError(_NO_ROOTS)
    src = _checked(args.get("src", ""), roots, must_be_file=True)
    dst = _resolve_dst(args.get("dst", ""), src, roots)
    if dst == src:
        raise ValueError("origem e destino são iguais")
    if dst.exists():
        raise FileExistsError(f"o destino já existe: {dst.name} — não sobrescrevo")
    shutil.move(str(src), str(dst))
    return {
        "result": {"src": str(src), "dst": str(dst)},
        "undo": {"src": str(src), "dst": str(dst)},
        "description": f"Moveu {src.name} → {dst.parent.name}/{dst.name}",
    }


def undo_move(undo_data: dict, roots: list[Path]) -> dict:
    """Reverte: move o arquivo de volta para a origem."""
    src = Path((undo_data or {}).get("src", "")).expanduser()
    dst = Path((undo_data or {}).get("dst", "")).expanduser()
    if not (_within(src, roots) and _within(dst, roots)):
        raise PermissionError("caminho de undo fora das pastas autorizadas")
    src, dst = src.resolve(), dst.resolve()
    if not dst.is_file():
        raise FileNotFoundError("o arquivo movido não está mais no destino")
    if src.exists():
        raise FileExistsError("a origem foi reocupada — não desfaço para não sobrescrever")
    shutil.move(str(dst), str(src))
    return {"restored": f"{src.name} de volta em {src.parent.name}"}


# ── Wiring no motor de ações (a allowlist vem de ctx.note) ──────
def _preview(args: dict, ctx) -> dict:
    return preview_move(args, parse_roots(getattr(ctx, "note", "")))


def _apply(args: dict, ctx) -> dict:
    return apply_move(args, parse_roots(getattr(ctx, "note", "")))


def _undo(undo_data: dict, ctx) -> dict:
    return undo_move(undo_data, parse_roots(getattr(ctx, "note", "")))


register(Action(kind="files.move", scope="files.write",
                description="Move/organiza um arquivo entre as pastas autorizadas (com desfazer)",
                preview=_preview, apply=_apply, undo=_undo))
