"""Ação de ESCRITA de arquivo — confirmável e reversível (M10, Épico 10.1).

Primeira ação que MODIFICA o mundo. Exige o grant `files.write` e fica CONFINADA
às pastas autorizadas (Permission.note = allowlist), reusando as mesmas defesas
de `files.py` (`_within`: `resolve()` neutraliza `..`/symlink de fuga). Fluxo:

  preview → mostra criar-vs-sobrescrever + tamanhos + trecho antigo/novo
  apply   → grava e devolve o undo (conteúdo antigo, ou "não existia")
  undo    → restaura o conteúdo antigo, ou apaga o arquivo recém-criado

As funções puras (preview_write/apply_write/undo_write) recebem a allowlist já
resolvida e são testáveis com pastas temporárias, sem DB nem registry.
"""
from __future__ import annotations

from pathlib import Path

from src.actions import Action, register
from src.tools.files import MAX_READ_BYTES, _within, parse_roots

MAX_WRITE_BYTES = 1_000_000        # teto de segurança por escrita (1 MB)
_PREVIEW_CHARS = 600               # trecho mostrado na prévia
_NO_ROOTS = ("nenhuma pasta autorizada para escrita — abra 🔐 Permissões, autorize "
             "'files.write' e informe a pasta onde o A.P.O.L.O. pode escrever")


def _resolve_target(path_str: str, roots: list[Path]) -> Path:
    """Valida que o alvo (existente ou não) cai DENTRO da allowlist e que a pasta
    pai existe. Levanta PermissionError/ValueError como as tools de leitura."""
    if not path_str:
        raise ValueError("informe 'path' do arquivo a escrever")
    p = Path(path_str).expanduser()
    if not _within(p, roots):
        raise PermissionError("caminho fora das pastas autorizadas para escrita")
    rp = p.resolve()
    if rp.is_dir():
        raise ValueError("o caminho é uma pasta, não um arquivo")
    if not rp.parent.exists():
        raise FileNotFoundError("a pasta de destino não existe")
    return rp


def _read_existing(rp: Path) -> str | None:
    if not rp.is_file():
        return None
    with open(rp, "rb") as fh:
        return fh.read(MAX_READ_BYTES).decode("utf-8", errors="replace")


def preview_write(args: dict, roots: list[Path]) -> dict:
    """Prévia SEM efeito: o que aconteceria se gravasse `content` em `path`."""
    if not roots:
        raise PermissionError(_NO_ROOTS)
    content = args.get("content", "")
    if not isinstance(content, str):
        raise ValueError("'content' deve ser texto")
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ValueError(f"conteúdo excede o teto de {MAX_WRITE_BYTES} bytes")
    rp = _resolve_target(args.get("path", ""), roots)
    old = _read_existing(rp)
    exists = old is not None
    return {
        "path": str(rp),
        "action": "overwrite" if exists else "create",
        "exists": exists,
        "old_bytes": len((old or "").encode("utf-8")),
        "new_bytes": len(content.encode("utf-8")),
        "old_preview": (old or "")[:_PREVIEW_CHARS],
        "new_preview": content[:_PREVIEW_CHARS],
        "reversible": True,
    }


def apply_write(args: dict, roots: list[Path]) -> dict:
    """Grava de fato e devolve os dados de undo (estado anterior)."""
    if not roots:
        raise PermissionError(_NO_ROOTS)
    content = args.get("content", "")
    if not isinstance(content, str):
        raise ValueError("'content' deve ser texto")
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ValueError(f"conteúdo excede o teto de {MAX_WRITE_BYTES} bytes")
    rp = _resolve_target(args.get("path", ""), roots)
    old = _read_existing(rp)
    existed = old is not None
    with open(rp, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    return {
        "result": {"path": str(rp), "action": "overwrite" if existed else "create",
                   "bytes_written": len(content.encode("utf-8"))},
        "undo": {"path": str(rp), "existed": existed, "old_content": old},
        "description": f"{'Sobrescreveu' if existed else 'Criou'} {rp.name}",
    }


def undo_write(undo_data: dict, roots: list[Path]) -> dict:
    """Reverte: restaura o conteúdo antigo, ou apaga o arquivo recém-criado."""
    path_str = (undo_data or {}).get("path", "")
    p = Path(path_str).expanduser()
    if not _within(p, roots):
        raise PermissionError("caminho de undo fora das pastas autorizadas")
    rp = p.resolve()
    if undo_data.get("existed"):
        with open(rp, "w", encoding="utf-8", newline="") as fh:
            fh.write(undo_data.get("old_content") or "")
        return {"path": str(rp), "restored": "conteúdo anterior"}
    # Não existia antes → desfazer = remover o que foi criado (se ainda existe)
    if rp.is_file():
        rp.unlink()
    return {"path": str(rp), "restored": "arquivo removido (não existia antes)"}


# ── Wiring no motor de ações (a allowlist vem de ctx.note) ──────
def _preview(args: dict, ctx) -> dict:
    return preview_write(args, parse_roots(getattr(ctx, "note", "")))


def _apply(args: dict, ctx) -> dict:
    return apply_write(args, parse_roots(getattr(ctx, "note", "")))


def _undo(undo_data: dict, ctx) -> dict:
    return undo_write(undo_data, parse_roots(getattr(ctx, "note", "")))


register(Action(kind="files.write", scope="files.write",
                description="Escreve/cria um arquivo de texto nas pastas autorizadas",
                preview=_preview, apply=_apply, undo=_undo))
