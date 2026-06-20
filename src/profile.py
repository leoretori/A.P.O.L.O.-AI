"""Memória pessoal do A.P.O.L.O. sobre o usuário.

Diferente da base de conhecimento técnica: aqui ficam fatos sobre VOCÊ (projeto
atual, stack preferida, nomes de serviços, preferências) que tornam o assistente
mais pessoal. Persistido em JSON simples, injetado no system prompt do chat.
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_FACT_CHARS = 300
MAX_FACTS_IN_CONTEXT = 25


class UserProfile:
    """Lista de fatos sobre o usuário, persistida em data/user_profile.json."""

    def __init__(self, path: str = "data/user_profile.json"):
        self.path = Path(path)
        self._facts: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"profile load: {e}")
        return []

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._facts, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"profile save: {e}")

    def list(self) -> list[dict]:
        return list(self._facts)

    def add(self, fact: str, source: str = "user") -> dict | None:
        fact = (fact or "").strip()[:MAX_FACT_CHARS]
        if len(fact) < 3:
            return None
        # Evita duplicar o mesmo fato.
        if any(f.get("fact", "").lower() == fact.lower() for f in self._facts):
            return None
        item = {"id": f"f{int(time.time() * 1000)}", "fact": fact, "source": source}
        self._facts.append(item)
        self._save()
        return item

    def remove(self, fact_id: str) -> bool:
        before = len(self._facts)
        self._facts = [f for f in self._facts if f.get("id") != fact_id]
        if len(self._facts) != before:
            self._save()
            return True
        return False

    def as_context(self, limit: int = MAX_FACTS_IN_CONTEXT) -> str:
        facts = self._facts[:limit]
        return "\n".join(f"- {f['fact']}" for f in facts)
