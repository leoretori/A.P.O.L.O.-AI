"""Sandbox para execução segura de código Python."""

import subprocess
import sys
import logging
import tempfile
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int


class CodeExecutor:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def run(self, code: str) -> ExecutionResult:
        """Executa código Python em subprocesso isolado com timeout."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            result = ExecutionResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
            )
            if result.success:
                logger.debug("Execução bem-sucedida")
            else:
                logger.warning(f"Erro na execução (exit {proc.returncode}): {proc.stderr[:200]}")
            return result

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout após {self.timeout}s")
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=f"TimeoutError: execução excedeu {self.timeout} segundos",
                exit_code=-1,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
