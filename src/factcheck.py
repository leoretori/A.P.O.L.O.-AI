"""Verificação de fatos (M8, Épico 8.2).

Cruza uma síntese NOVA com o que o A.P.O.L.O. já sabe e marca:
- fatos NÃO corroborados (afirmações com número/data que não batem com a base);
- DERIVA numérica (uma data/quantidade sobre o MESMO tópico que "mudou" entre o
  que já sabia e a nova síntese) — candidata a contradição, para revisão.

Determinístico e barato (sem LLM): ancora em FATOS objetivos — anos e quantidades
com unidade — porque são os que dá para comparar de forma confiável. Não decide o
que é verdade; sinaliza o que DIVERGE do que já foi aprendido.
"""
from __future__ import annotations

import re

_YEAR = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")               # 1500–2099
_QTY = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(%|por\s*cento|km|kg|graus|anos?|s[eé]culos?|bilh[õo]es?|milh[õo]es?|"
    r"mil|metros?|litros?|toneladas?)(?!\w)",   # \b falha após '%'; lookahead cobre
    re.I)

_UNIT_ALIAS = {"por cento": "%", "porcento": "%", "ano": "anos", "século": "seculos",
               "seculo": "seculos", "seculos": "seculos", "metro": "metros",
               "litro": "litros", "tonelada": "toneladas", "bilhao": "bilhoes",
               "bilhões": "bilhoes", "milhao": "milhoes", "milhões": "milhoes"}


def _norm_unit(u: str) -> str:
    u = re.sub(r"\s+", " ", (u or "").strip().lower())
    return _UNIT_ALIAS.get(u, u.rstrip("s") + "s" if u not in ("%",) else u)


def extract_facts(text: str) -> set[str]:
    """Fatos objetivos do texto: anos (`ano:1969`) e quantidades (`qty:27:%`)."""
    facts: set[str] = set()
    t = text or ""
    for y in _YEAR.findall(t):
        facts.add(f"ano:{y}")
    for num, unit in _QTY.findall(t):
        try:
            n = float(num.replace(".", "").replace(",", ".")) if "," in num else float(num)
        except ValueError:
            continue
        facts.add(f"qty:{n:g}:{_norm_unit(unit)}")
    return facts


def corroboration(new_text: str, known_texts: list[str]) -> dict:
    """Fração dos fatos da síntese nova que já aparecem na base. Baixa + fatos
    sem apoio → sinaliza para revisão."""
    nf = extract_facts(new_text)
    if not nf:
        return {"facts": 0, "corroborated": 0, "unsupported": [],
                "score": 1.0, "note": None}
    known: set[str] = set()
    for t in known_texts or []:
        known |= extract_facts(t)
    corroborated = nf & known
    unsupported = sorted(nf - known)
    score = round(len(corroborated) / len(nf), 3)
    note = None
    if score < 0.5 and unsupported:
        note = ("🔍 Fatos novos que ainda não bati com o que sei (podem ser novidade "
                "ou erro — vale conferir): " + ", ".join(_pretty(f) for f in unsupported[:5]))
    return {"facts": len(nf), "corroborated": len(corroborated),
            "unsupported": unsupported, "score": score, "note": note}


def numeric_drift(old_text: str, new_text: str) -> dict:
    """Sobre o MESMO tópico: anos que sumiram E foram trocados por outros indicam
    que um fato datado mudou — candidato a contradição."""
    old_years = {f for f in extract_facts(old_text) if f.startswith("ano:")}
    new_years = {f for f in extract_facts(new_text) if f.startswith("ano:")}
    dropped = old_years - new_years
    added = new_years - old_years
    drift = bool(dropped) and bool(added)
    note = None
    if drift:
        note = ("⚠️ Uma data mudou sobre este tópico — antes: "
                f"{sorted(y.split(':')[1] for y in dropped)}, agora: "
                f"{sorted(y.split(':')[1] for y in added)}. Contradição? Verificar.")
    return {"drift": drift, "dropped": sorted(dropped),
            "added": sorted(added), "note": note}


def _pretty(fact: str) -> str:
    if fact.startswith("ano:"):
        return f"ano {fact[4:]}"
    parts = fact.split(":")
    return f"{parts[1]} {parts[2]}" if len(parts) == 3 else fact
