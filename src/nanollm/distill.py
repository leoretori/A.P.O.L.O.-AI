"""Flywheel de destilação (M25) — o Qwen (professor) ensina o Apolo-Nano (aluno).

O M14.2 mediu o teto e revelou a CAUSA-RAIZ: descasamento de distribuição. O
fine-tune do 4.1 treinou em `prosa enciclopédica → título`, mas a inferência
recebe `pergunta → título`; o Nano aprendeu a FORMA, não a ANCORAGEM. E havia
pouquíssimos pares reais na distribuição certa (4 conversas).

O M25 fecha o loop no HARDWARE ATUAL, sem esperar GPU: o **Qwen** (que já roda
no motor próprio) gera os rótulos-professor **na distribuição de inferência** e
em VOLUME, a partir de entradas reais do Leo. O Nano treina para imitá-lo. É
destilação de conhecimento clássica — professor grande → aluno pequeno — só que
soberana e local.

Núcleo DETERMINÍSTICO e testável: `teacher_fn` (o Qwen) é injetável; os testes
usam um professor fake, sem LLM nem rede. A escrita reusa o pipeline do
`taskdata` (mesmo tokenizer/template/split do fine-tune).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from src.nanollm.taskdata import (
    TITLE_TEMPLATE,
    _valid_title,
    _write_tokenized,
)

logger = logging.getLogger("apolo.nano.distill")

# Prompt-professor: pede ao Qwen exatamente a tarefa, na distribuição de
# inferência (pergunta → título curto), para o rótulo casar com o uso real.
TITLE_TEACHER_PROMPT = (
    "Dê um título curto (3 a 6 palavras, em português, sem aspas) para uma "
    "conversa que começa com esta mensagem do usuário:\n\n{input}\n\nTítulo:"
)

MAX_INPUT_CHARS = 300


def generate_distill_pairs(
    inputs: list[str],
    teacher_fn: Callable[[str], str],
    *,
    prompt_template: str = "{input}",
    validate: Callable[[str], bool] | None = None,
    max_pairs: int | None = None,
) -> list[tuple[str, str]]:
    """Gera pares (entrada → rótulo) rotulados pelo PROFESSOR.

    `teacher_fn(prompt) -> texto` é o Qwen (injetável; fake nos testes). Para
    cada entrada, monta o prompt-professor, coleta o rótulo, valida e guarda.
    Determinístico dado o `teacher_fn`. Entradas que falham/produzem rótulo
    inválido são puladas (o dataset só recebe o que passa no portão).
    """
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in inputs:
        inp = (raw or "").strip()[:MAX_INPUT_CHARS]
        if len(inp) < 3:
            continue
        key = inp[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            label = (teacher_fn(prompt_template.format(input=inp)) or "").strip()
        except Exception as e:
            logger.debug(f"[distill] professor falhou numa entrada: {e}")
            continue
        # limpa aspas/prefixos comuns que o professor às vezes devolve
        label = label.strip(' \t"\'`').removeprefix("Título:").strip(' \t"\'`')
        if label and (validate is None or validate(label)):
            pairs.append((inp, label))
            if max_pairs and len(pairs) >= max_pairs:
                break
    return pairs


def distill_titles(
    inputs: list[str],
    teacher_fn: Callable[[str], str],
    *,
    max_pairs: int | None = None,
) -> list[tuple[str, str]]:
    """Conveniência: destila pares `pergunta → título` na distribuição de
    inferência (a que faltava no 4.1), validando com o mesmo `_valid_title`."""
    return generate_distill_pairs(
        inputs, teacher_fn,
        prompt_template=TITLE_TEACHER_PROMPT,
        validate=_valid_title,
        max_pairs=max_pairs,
    )


def write_distill_dataset(
    pairs: list[tuple[str, str]],
    tokenizer_path: str | Path,
    out_dir: str | Path,
    *,
    template: str = TITLE_TEMPLATE,
    task: str = "title_distill",
    val_fraction: float = 0.1,
    seed: int = 42,
) -> dict:
    """Escreve o dataset destilado no MESMO formato do fine-tune (para o
    `train.py` consumir sem mudança): pairs.jsonl + train/val.npy + meta.json.
    Reusa o tokenizer do checkpoint (fine-tune não troca vocab)."""
    from src.nanollm.tokenizer import ByteBPETokenizer

    if not pairs:
        raise ValueError("sem pares destilados — o professor não produziu rótulos válidos")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tok = ByteBPETokenizer.load(tokenizer_path)

    # o template usa {context}/{title}: (entrada→rótulo) mapeiam nesses campos
    examples = [template.format(context=c, title=t) for c, t in pairs]
    (out / "pairs.jsonl").write_text(
        "\n".join(json.dumps({"context": c, "title": t}, ensure_ascii=False)
                  for c, t in pairs),
        encoding="utf-8",
    )
    meta = {"task": task, "pairs": len(pairs), "template": template,
            "source": "distillation (Qwen→Nano)"}
    meta.update(_write_tokenized(examples, tok, out, val_fraction, seed))
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    return meta
