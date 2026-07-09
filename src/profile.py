"""Modelo pessoal do A.P.O.L.O. sobre o usuário (M16.1 — modelo profundo do Leo).

Diferente da base de conhecimento técnica: aqui fica o que o Apolo entende sobre
VOCÊ. Evoluiu de uma lista rasa de fatos para um modelo ESTRUTURADO por categoria
— metas, projetos, hábitos, pessoas, preferências, valores — sem quebrar nada:
entradas antigas (sem categoria) viram "fato". Tudo editável e curado por você;
persistido em JSON, injetado no system prompt agrupado por seção.
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_FACT_CHARS = 300
MAX_FACTS_IN_CONTEXT = 25

# Categorias do modelo profundo. Ordem = ordem de apresentação no contexto.
# slug -> (rótulo da seção, aceita horizonte curto/longo?)
CATEGORIES: dict[str, tuple[str, bool]] = {
    "goal": ("Metas", True),
    "project": ("Projetos ativos", False),
    "habit": ("Hábitos & rotinas", False),
    "person": ("Pessoas", False),
    "preference": ("Preferências", False),
    "value": ("Valores", False),
    "fact": ("Sobre você", False),  # genérico / legado
}
DEFAULT_CATEGORY = "fact"
HORIZONS = ("short", "long")


def normalize_category(category: str | None) -> str:
    """Categoria válida ou o default — nunca deixa entrar categoria inventada."""
    cat = (category or "").strip().lower()
    return cat if cat in CATEGORIES else DEFAULT_CATEGORY


class UserProfile:
    """Modelo pessoal estruturado, persistido em data/user_profile.json.

    Cada entrada: {id, fact, category, source, created_at, horizon?}.
    A API antiga (add/list/remove/as_context) segue idêntica; os campos novos
    são aditivos e retrocompatíveis com perfis já gravados.
    """

    def __init__(self, path: str = "data/user_profile.json"):
        self.path = Path(path)
        self._facts: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:  # migração suave: entrada sem categoria = fato
                        if isinstance(item, dict):
                            item.setdefault("category", DEFAULT_CATEGORY)
                    return data
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

    def by_category(self) -> dict[str, list[dict]]:
        """Entradas agrupadas por categoria, na ordem de CATEGORIES."""
        groups: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
        for f in self._facts:
            groups.setdefault(f.get("category", DEFAULT_CATEGORY), []).append(f)
        return {c: items for c, items in groups.items() if items}

    def add(self, fact: str, source: str = "user", category: str | None = None,
            horizon: str | None = None) -> dict | None:
        """Adiciona uma entrada. `category` inválida cai no default; dedup por texto."""
        fact = (fact or "").strip()[:MAX_FACT_CHARS]
        if len(fact) < 3:
            return None
        if any(f.get("fact", "").lower() == fact.lower() for f in self._facts):
            return None
        item = {
            "id": f"f{int(time.time() * 1000)}",
            "fact": fact,
            "category": normalize_category(category),
            "source": source,
            "created_at": int(time.time()),
        }
        if horizon in HORIZONS:
            item["horizon"] = horizon
        self._facts.append(item)
        self._save()
        return item

    def update(self, fact_id: str, *, fact: str | None = None,
               category: str | None = None, horizon: str | None = None) -> dict | None:
        """Edita uma entrada existente (curadoria pelo usuário). None se não achar."""
        for item in self._facts:
            if item.get("id") == fact_id:
                if fact is not None:
                    new = fact.strip()[:MAX_FACT_CHARS]
                    if len(new) >= 3:
                        item["fact"] = new
                if category is not None:
                    item["category"] = normalize_category(category)
                if horizon is not None:
                    if horizon in HORIZONS:
                        item["horizon"] = horizon
                    else:
                        item.pop("horizon", None)
                self._save()
                return item
        return None

    def remove(self, fact_id: str) -> bool:
        before = len(self._facts)
        self._facts = [f for f in self._facts if f.get("id") != fact_id]
        if len(self._facts) != before:
            self._save()
            return True
        return False

    def as_context(self, limit: int = MAX_FACTS_IN_CONTEXT) -> str:
        """Renderiza o modelo AGRUPADO por seção para o system prompt.

        Só inclui seções com conteúdo; metas mostram o horizonte quando houver.
        Um perfil só de fatos legados vira uma seção "Sobre você" limpa.
        """
        groups = self.by_category()
        if not groups:
            return ""
        remaining = limit
        lines: list[str] = []
        for cat, (label, _) in CATEGORIES.items():
            items = groups.get(cat)
            if not items or remaining <= 0:
                continue
            lines.append(f"## {label}")
            for f in items[:remaining]:
                hz = ""
                if f.get("horizon") == "short":
                    hz = " (curto prazo)"
                elif f.get("horizon") == "long":
                    hz = " (longo prazo)"
                lines.append(f"- {f['fact']}{hz}")
                remaining -= 1
            if remaining <= 0:
                break
        return "\n".join(lines)
