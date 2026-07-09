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
        # Candidatos PENDENTES (M16.2): propostos pela extração, aguardando a
        # confirmação do usuário. Guardados num arquivo irmão p/ não mexer no
        # formato (lista) do perfil já gravado.
        self.cand_path = self.path.with_name(self.path.stem + "_candidates.json")
        self._candidates: list[dict] = self._load_candidates()
        self._rejected: set[str] = set()  # textos recusados (não re-propor na sessão)

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

    # ---------------------------------------------- candidatos (M16.2)
    def _load_candidates(self) -> list[dict]:
        try:
            if self.cand_path.exists():
                data = json.loads(self.cand_path.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"profile candidates load: {e}")
        return []

    def _save_candidates(self) -> None:
        try:
            self.cand_path.parent.mkdir(parents=True, exist_ok=True)
            self.cand_path.write_text(
                json.dumps(self._candidates, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"profile candidates save: {e}")

    def _known(self, text: str) -> bool:
        """Já é fato, já é candidato pendente, ou foi recusado nesta sessão?"""
        low = text.lower()
        return (
            low in self._rejected
            or any(f.get("fact", "").lower() == low for f in self._facts)
            or any(c.get("text", "").lower() == low for c in self._candidates)
        )

    def pending(self) -> list[dict]:
        return list(self._candidates)

    def propose(self, text: str, category: str | None = None, *,
                source: str = "auto", horizon: str | None = None) -> dict | None:
        """Registra um CANDIDATO (não grava no perfil). None se já conhecido/curto."""
        text = (text or "").strip()[:MAX_FACT_CHARS]
        if len(text) < 3 or self._known(text):
            return None
        item = {
            "id": f"c{int(time.time() * 1000)}{len(self._candidates)}",
            "text": text,
            "category": normalize_category(category),
            "source": source,
            "created_at": int(time.time()),
        }
        if horizon in HORIZONS:
            item["horizon"] = horizon
        self._candidates.append(item)
        self._save_candidates()
        return item

    def confirm(self, cand_id: str, *, text: str | None = None,
                category: str | None = None, horizon: str | None = None) -> dict | None:
        """Move um candidato para o perfil (com edições opcionais). None se não achar."""
        for i, c in enumerate(self._candidates):
            if c.get("id") == cand_id:
                added = self.add(
                    text if text is not None else c["text"],
                    source="user",  # confirmado = veio do usuário
                    category=category if category is not None else c.get("category"),
                    horizon=horizon if horizon is not None else c.get("horizon"),
                )
                self._candidates.pop(i)
                self._save_candidates()
                return added
        return None

    def reject(self, cand_id: str) -> bool:
        """Descarta um candidato; lembra o texto p/ não re-propor na sessão."""
        for i, c in enumerate(self._candidates):
            if c.get("id") == cand_id:
                self._rejected.add(c.get("text", "").lower())
                self._candidates.pop(i)
                self._save_candidates()
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
