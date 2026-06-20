"""Workspace de codificação isolado — o "Claude Code" interno do A.P.O.L.O.

Ferramentas de arquivo e shell confinadas a um diretório raiz (workspace). Todo
caminho é resolvido e validado para impedir escapar da raiz (path traversal).
"""

import difflib
import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def make_diff(old: str, new: str, path: str, max_lines: int = 120) -> dict:
    """Diff unificado entre conteúdo antigo e novo de um arquivo.
    Retorna {text, added, removed, is_new} — base do preview estilo Claude Code."""
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    ))
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    truncated = False
    if len(diff) > max_lines:
        diff = diff[:max_lines]
        truncated = True
    text = "\n".join(diff)
    if truncated:
        text += "\n… (diff truncado)"
    return {"text": text, "added": added, "removed": removed, "is_new": not old_lines}

# Comandos catastróficos fora do escopo de um agente de código — bloqueados por
# segurança mesmo dentro do workspace (defesa em profundidade).
_BLOCKED_PATTERNS = (
    r"\brm\s+-rf\s+/", r"\brm\s+-rf\s+~", r":\(\)\s*\{",  # fork bomb
    r"\bmkfs\b", r"\bdd\s+if=", r"\bshutdown\b", r"\breboot\b",
    r">\s*/dev/sd", r"\bchmod\s+-R\s+777\s+/", r"\bgit\s+push\b",
)

TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".html",
    ".css", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh", ".sql", ".env",
    ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".php", ".xml", ".csv", "",
}


def normalize_cmd(cmd: str) -> str:
    """Reescreve comandos que costumam falhar por não estarem no PATH do subprocess
    (ex.: 'pytest' no Windows) para a forma robusta 'python -m ...'."""
    c = (cmd or "").strip()
    # Só reescreve quando o comando COMEÇA com a ferramenta (evita mexer em pipes/args).
    for tool in ("pytest", "pip"):
        if re.match(rf"^{tool}(\s|$)", c):
            return re.sub(rf"^{tool}", f"python -m {tool}", c, count=1)
    return c


def extract_fenced(text: str) -> str | None:
    """Extrai o conteúdo do primeiro bloco cercado por ``` (qualquer linguagem)."""
    m = re.search(r"```[a-zA-Z0-9_+-]*\n(.*?)```", text, re.S)
    return m.group(1) if m else None


class CoderWorkspace:
    def __init__(self, root: str = "./workspace"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # Histórico de escritas (snapshots) para revisar e desfazer ("descartar").
        # Cada item: {path, before (str|None=arquivo novo), added, removed, ts}
        self.history: list[dict] = []
        logger.info(f"Coder workspace: {self.root}")

    # ── Raiz do workspace (apontar para projeto real) ─────────
    def set_root(self, path: str) -> dict:
        """Aponta o workspace para um diretório EXISTENTE (projeto real). Limpa o
        histórico (snapshots pertencem à raiz anterior)."""
        p = Path(path).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            return {"ok": False, "error": f"diretório não existe: {p}"}
        self.root = p
        self.history = []
        logger.info(f"Coder workspace alterado para: {self.root}")
        return {"ok": True, "root": str(self.root)}

    def open_in_vscode(self, rel: str = "") -> dict:
        """Abre o workspace (ou um arquivo específico) no VS Code via CLI `code`.
        Com `rel:linha` posiciona o cursor na linha (ex.: 'app.py:42').
        Requer o comando `code` no PATH (Shell Command do VS Code)."""
        import shutil
        line = None
        rel = (rel or "").strip()
        m = re.match(r"^(.*?):(\d+)$", rel)
        if m:
            rel, line = m.group(1), m.group(2)
        # Confina ao workspace; vazio = abre a pasta-raiz.
        try:
            target = self._safe(rel) if rel else self.root
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if not target.exists():
            return {"ok": False, "error": f"não existe: {rel or self.root}"}

        code_bin = shutil.which("code") or shutil.which("code.cmd")
        if not code_bin:
            return {"ok": False, "error": "VS Code CLI 'code' não está no PATH. "
                    "No VS Code: Ctrl+Shift+P → 'Shell Command: Install code command in PATH'."}
        args = [code_bin]
        if line:
            args += ["-g", f"{target}:{line}"]
        else:
            args.append(str(target))
        try:
            # shell=True no Windows resolve o .cmd; não há entrada de usuário não-confinada.
            subprocess.Popen(args, cwd=str(self.root),
                             shell=(os.name == "nt"))
            return {"ok": True, "opened": str(target), "line": line}
        except Exception as e:
            return {"ok": False, "error": f"falha ao abrir VS Code: {e}"}

    # ── Resolução segura de caminho ───────────────────────────
    def _safe(self, rel: str) -> Path:
        rel = (rel or "").strip().strip('"').strip("'").lstrip("/\\")
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"caminho fora do workspace: {rel}")
        return p

    # ── Ferramentas ───────────────────────────────────────────
    def list_dir(self, rel: str = ".") -> str:
        try:
            base = self._safe(rel)
        except ValueError as e:
            return f"({e})"
        if not base.exists():
            return f"(não existe: {rel})"
        if base.is_file():
            return base.name
        entries = []
        for p in sorted(base.iterdir()):
            if p.name.startswith(".git"):
                continue
            entries.append(f"{p.name}/" if p.is_dir() else p.name)
        return "\n".join(entries) if entries else "(vazio)"

    def read_file(self, rel: str, max_chars: int = 6000) -> str:
        try:
            p = self._safe(rel)
        except ValueError as e:
            return f"({e})"
        if not p.exists() or not p.is_file():
            return f"(arquivo não encontrado: {rel})"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"(erro ao ler: {e})"
        return text[:max_chars] + ("\n…(truncado)" if len(text) > max_chars else "")

    def current_content(self, rel: str) -> str:
        """Conteúdo atual do arquivo (cru, sem truncar) — usado para gerar o diff."""
        try:
            p = self._safe(rel)
        except ValueError:
            return ""
        if not p.exists() or not p.is_file():
            return ""
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def write_file(self, rel: str, content: str, allow_shrink: bool = False) -> str:
        try:
            p = self._safe(rel)
        except ValueError as e:
            return f"({e})"
        if p.suffix.lower() not in TEXT_SUFFIXES:
            return f"(extensão não permitida para escrita: {p.suffix})"
        before = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
        # Guarda anti-reescrita catastrófica: sobrescrever um arquivo não-trivial por
        # algo drasticamente menor quase sempre é destruição (alucinação), não edição.
        # Bloqueia e orienta o uso de SUBSTITUIR para mudanças pontuais.
        if before is not None and not allow_shrink:
            old_lines = before.count("\n") + 1
            new_lines = content.count("\n") + 1
            if old_lines >= 20 and new_lines < old_lines * 0.35:
                return (f"(BLOQUEADO: reescrita encolheria {rel} de {old_lines} para "
                        f"{new_lines} linhas — perda de {round((1-new_lines/old_lines)*100)}%. "
                        f"Isso costuma ser destruição acidental. Para mudanças pontuais use "
                        f"SUBSTITUIR <texto> ==> <novo>; só reescreva o arquivo inteiro se "
                        f"realmente pretende substituir todo o conteúdo.)")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        # Registra snapshot para revisão/undo.
        d = make_diff(before or "", content, rel)
        from datetime import datetime, timezone
        self.history.append({
            "path": rel.strip().lstrip("/\\"), "before": before,
            "added": d["added"], "removed": d["removed"],
            "is_new": before is None, "ts": datetime.now(timezone.utc).isoformat(),
        })
        lines = content.count("\n") + 1
        return f"OK — gravado {rel} ({lines} linhas, {len(content)} chars)"

    def edit_file(self, rel: str, old: str, new: str) -> str:
        """Edição CIRÚRGICA: troca um trecho exato por outro, sem reescrever o arquivo
        inteiro (como o Edit do Claude Code). `old` precisa aparecer EXATAMENTE uma vez
        — isso evita ambiguidade e a destruição típica do 'reescrever tudo'. Snapshot
        para undo. Retorna 'OK — ...' ou uma mensagem de erro acionável."""
        try:
            p = self._safe(rel)
        except ValueError as e:
            return f"({e})"
        if not p.is_file():
            return f"(arquivo não encontrado: {rel} — use ESCREVER para criar um novo arquivo)"
        if not old:
            return "(o trecho a buscar está vazio — informe o texto exato a substituir)"
        before = p.read_text(encoding="utf-8", errors="replace")
        count = before.count(old)
        if count == 0:
            return (f"(trecho não encontrado em {rel} — copie o texto EXATO do arquivo, "
                    f"com a mesma indentação. Use LER para conferir.)")
        if count > 1:
            return (f"(o trecho aparece {count}x em {rel} — inclua mais linhas de contexto "
                    f"para torná-lo único antes de editar.)")
        after = before.replace(old, new, 1)
        p.write_text(after, encoding="utf-8")
        d = make_diff(before, after, rel)
        from datetime import datetime, timezone
        self.history.append({
            "path": rel.strip().lstrip("/\\"), "before": before,
            "added": d["added"], "removed": d["removed"],
            "is_new": False, "ts": datetime.now(timezone.utc).isoformat(),
        })
        return f"OK — editado {rel} (+{d['added']} -{d['removed']})"

    def delete_file(self, rel: str) -> str:
        """Apaga um arquivo (reversível via histórico/undo — guarda o conteúdo)."""
        try:
            p = self._safe(rel)
        except ValueError as e:
            return f"({e})"
        if not p.exists() or not p.is_file():
            return f"(arquivo não encontrado: {rel})"
        from datetime import datetime, timezone
        before = p.read_text(encoding="utf-8", errors="replace")
        p.unlink()
        self.history.append({
            "path": rel.strip().lstrip("/\\"), "before": before,
            "added": 0, "removed": before.count("\n") + 1,
            "is_new": False, "ts": datetime.now(timezone.utc).isoformat(),
        })
        return f"OK — apagado {rel}"

    def rename_file(self, src: str, dst: str) -> str:
        """Renomeia/move um arquivo (cria o destino + apaga a origem; ambos reversíveis)."""
        try:
            ps = self._safe(src)
        except ValueError as e:
            return f"({e})"
        if not ps.exists() or not ps.is_file():
            return f"(arquivo não encontrado: {src})"
        content = ps.read_text(encoding="utf-8", errors="replace")
        w = self.write_file(dst, content)   # snapshot do destino
        if not w.startswith("OK"):
            return w
        self.delete_file(src)               # snapshot da origem
        return f"OK — {src} → {dst}"

    def search_replace(self, find: str, replace: str, max_files: int = 50) -> dict:
        """Busca-e-substitui literal em todos os arquivos de texto. Cada arquivo
        alterado vira um snapshot (reversível). Retorna resumo."""
        if not find:
            return {"ok": False, "error": "termo de busca vazio", "files": [], "count": 0}
        changed, total = [], 0
        for p in self._iter_text_files():
            if len(changed) >= max_files:
                break
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if find not in content:
                continue
            n = content.count(find)
            rel = p.relative_to(self.root).as_posix()
            self.write_file(rel, content.replace(find, replace))  # snapshot automático
            changed.append({"path": rel, "count": n})
            total += n
        return {"ok": True, "files": changed, "count": total,
                "files_changed": len(changed)}

    # ── Revisão e desfazer (snapshots) ────────────────────────
    def list_changes(self) -> list[dict]:
        """Mudanças desta sessão (mais recentes primeiro), para revisão/undo."""
        return [
            {"path": h["path"], "added": h["added"], "removed": h["removed"],
             "is_new": h["is_new"], "ts": h["ts"]}
            for h in reversed(self.history)
        ]

    def _revert(self, entry: dict) -> None:
        p = self._safe(entry["path"])
        if entry["before"] is None:
            # Era arquivo novo → desfazer = remover.
            if p.is_file():
                p.unlink()
        else:
            p.write_text(entry["before"], encoding="utf-8")

    def undo_last(self) -> dict:
        """Desfaz a última escrita (descartar a alteração mais recente)."""
        if not self.history:
            return {"ok": False, "error": "nada para desfazer"}
        entry = self.history.pop()
        try:
            self._revert(entry)
            return {"ok": True, "path": entry["path"],
                    "restored": "removido" if entry["before"] is None else "revertido"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def undo_file(self, rel: str) -> dict:
        """Desfaz a última alteração de UM arquivo específico."""
        rel = (rel or "").strip().lstrip("/\\")
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i]["path"] == rel:
                entry = self.history.pop(i)
                try:
                    self._revert(entry)
                    return {"ok": True, "path": rel}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"sem histórico para {rel}"}

    def undo_all(self) -> dict:
        """Descarta TODAS as alterações desta sessão (reverte na ordem inversa)."""
        n = 0
        while self.history:
            entry = self.history.pop()
            try:
                self._revert(entry)
                n += 1
            except Exception:
                pass
        return {"ok": True, "reverted": n}

    def _blocked_reason(self, cmd: str) -> str | None:
        for pat in _BLOCKED_PATTERNS:
            if re.search(pat, cmd):
                return f"(comando bloqueado por segurança: {cmd[:60]})"
        return None

    def run_cmd_stream(self, cmd: str, timeout: int = 120):
        """Executa um comando transmitindo a saída linha a linha (generator).
        Yields ('line', texto) durante a execução e ('done', ok) ao final.
        Mata o processo se exceder `timeout` (watchdog), evitando travas."""
        import threading
        cmd = (cmd or "").strip()
        if not cmd:
            yield ("done", False); return
        blocked = self._blocked_reason(cmd)
        if blocked:
            yield ("line", blocked); yield ("done", False); return
        cmd = normalize_cmd(cmd)
        try:
            proc = subprocess.Popen(
                cmd, shell=True, cwd=str(self.root),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
            )
        except Exception as e:
            yield ("line", f"(erro ao iniciar: {e})"); yield ("done", False); return

        killed = {"v": False}
        def _kill():
            killed["v"] = True
            try: proc.kill()
            except Exception: pass
        timer = threading.Timer(timeout, _kill)
        timer.start()
        try:
            for line in proc.stdout:
                yield ("line", line.rstrip("\n"))
            proc.wait()
        finally:
            timer.cancel()
        if killed["v"]:
            yield ("line", f"(tempo esgotado após {timeout}s — processo encerrado)")
            yield ("done", False)
        else:
            yield ("done", proc.returncode == 0)

    def run_cmd(self, cmd: str, timeout: int = 60) -> tuple[bool, str]:
        cmd = (cmd or "").strip()
        if not cmd:
            return False, "(comando vazio)"
        blocked = self._blocked_reason(cmd)
        if blocked:
            return False, blocked
        cmd = normalize_cmd(cmd)
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(self.root), capture_output=True,
                text=True, timeout=timeout, encoding="utf-8", errors="replace",
            )
            out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
            return proc.returncode == 0, out.strip() or "(sem saída)"
        except subprocess.TimeoutExpired:
            return False, f"(tempo esgotado após {timeout}s)"
        except Exception as e:
            return False, f"(erro ao executar: {e})"

    _SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".mypy_cache", ".pytest_cache"}

    def _iter_text_files(self):
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in self._SKIP_DIRS for part in p.parts):
                continue
            if p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            yield p

    def search(self, query: str, max_results: int = 40) -> str:
        """Grep de conteúdo no workspace (case-insensitive). Retorna 'path:linha: trecho'."""
        q = (query or "").strip()
        if len(q) < 2:
            return "(consulta muito curta)"
        ql = q.lower()
        hits, scanned = [], 0
        for p in self._iter_text_files():
            scanned += 1
            try:
                for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if ql in line.lower():
                        rel = p.relative_to(self.root).as_posix()
                        hits.append(f"{rel}:{i}: {line.strip()[:120]}")
                        if len(hits) >= max_results:
                            return "\n".join(hits) + f"\n…(parou em {max_results} resultados)"
            except Exception:
                continue
        return "\n".join(hits) if hits else f"(nenhum resultado para '{q}' em {scanned} arquivos)"

    def find_files(self, pattern: str, max_results: int = 60) -> str:
        """Acha arquivos cujo nome (ou caminho relativo) contém o padrão."""
        pat = (pattern or "").strip().lower()
        if not pat:
            return "(padrão vazio)"
        out = []
        for p in self.root.rglob("*"):
            if any(part in self._SKIP_DIRS for part in p.parts):
                continue
            rel = p.relative_to(self.root).as_posix()
            if pat in rel.lower():
                out.append(rel + ("/" if p.is_dir() else ""))
                if len(out) >= max_results:
                    break
        return "\n".join(out) if out else f"(nenhum arquivo combina com '{pattern}')"

    # ── Git (read-only, confinado à raiz) ─────────────────────
    def _git(self, args: list[str], timeout: int = 15) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(self.root), capture_output=True,
                text=True, timeout=timeout, encoding="utf-8", errors="replace",
            )
            return proc.returncode == 0, (proc.stdout + proc.stderr).strip()
        except FileNotFoundError:
            return False, "(git não instalado)"
        except Exception as e:
            return False, f"(erro git: {e})"

    def git_status(self) -> dict:
        ok, out = self._git(["rev-parse", "--is-inside-work-tree"])
        if not ok or out.strip() != "true":
            return {"is_repo": False}
        _, branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"])
        _, status = self._git(["status", "--short"])
        _, ahead = self._git(["rev-list", "--count", "@{u}..HEAD"])
        return {"is_repo": True, "branch": branch.strip(),
                "status": status, "dirty": bool(status.strip()),
                "ahead": ahead.strip() if ahead.strip().isdigit() else "0"}

    def git_diff(self, path: str = "") -> str:
        args = ["diff", "--", path] if path else ["diff"]
        ok, out = self._git(args)
        return out if out else "(sem alterações não commitadas)"

    def list_files(self, max_files: int = 200) -> list[str]:
        """Lista plana de arquivos de texto (caminhos relativos) — para o painel clicável."""
        out = []
        for p in self._iter_text_files():
            out.append(p.relative_to(self.root).as_posix())
            if len(out) >= max_files:
                break
        return sorted(out)

    def tree(self, max_entries: int = 60) -> str:
        """Visão rápida da árvore do workspace (para dar contexto inicial ao agente)."""
        out, n = [], 0
        for p in sorted(self.root.rglob("*")):
            if ".git" in p.parts or "__pycache__" in p.parts:
                continue
            rel = p.relative_to(self.root)
            depth = len(rel.parts) - 1
            out.append("  " * depth + (p.name + "/" if p.is_dir() else p.name))
            n += 1
            if n >= max_entries:
                out.append("…")
                break
        return "\n".join(out) if out else "(workspace vazio)"
