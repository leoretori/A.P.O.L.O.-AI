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


def make_llm_teacher(
    model: str | None = None,
    *,
    temperature: float = 0.3,
    max_tokens: int = 48,
) -> Callable[[str], str]:
    """Constrói o PROFESSOR real: o Qwen que já roda no motor próprio (llama.cpp).
    Devolve `teacher_fn(prompt) -> texto` para alimentar `generate_distill_pairs`.

    Import preguiçoso de `get_provider`/`runtime` — assim o núcleo de destilação e
    seus testes seguem sem LLM nem rede; só quem chama ISTO paga o custo do motor.
    O modelo padrão é o de chat resolvido em runtime (o mesmo que responde ao Leo),
    então o aluno imita o professor que ele de fato substituirá."""
    from src.providers import get_provider

    prov = get_provider()
    if model is None:
        try:
            from src import runtime
            model = runtime.get_chat_model()
        except Exception:
            model = None
        if not model:                       # fallback: 1º modelo que o motor expõe
            models = prov.list_models()
            model = models[0] if models else "apolo"

    opts = {"temperature": temperature, "num_predict": max_tokens, "max_tokens": max_tokens}

    def teacher_fn(prompt: str) -> str:
        return prov.complete(model, [{"role": "user", "content": prompt}], options=opts)

    return teacher_fn


def source_title_inputs(db, *, limit: int = 300, min_len: int = 8) -> list[str]:
    """Puxa do banco as entradas reais a destilar: a 1ª mensagem de cada sessão
    (a pergunta que abre a conversa — a distribuição de inferência). `db` é o
    DatabaseManager; mantido como parâmetro (não import global) para o pipeline
    seguir testável com um banco falso."""
    return db.first_user_messages(limit=limit, min_len=min_len)


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


def run_distillation(
    db,
    tokenizer_path: str | Path,
    out_dir: str | Path,
    *,
    teacher_fn: Callable[[str], str] | None = None,
    limit: int = 300,
    max_pairs: int | None = None,
    val_fraction: float = 0.1,
) -> dict:
    """FLYWHEEL, ponta a ponta (M25.2): banco → professor rotula → dataset.

    (1) puxa as entradas reais (1ª mensagem de cada sessão), (2) o professor
    (Qwen real por padrão; injetável nos testes) rotula pergunta→título na
    distribuição de inferência, (3) grava no formato do fine-tune. Devolve o
    `meta` com um resumo (quantas entradas viraram quantos pares). O TREINO em
    si é o `train.py` apontado para `out_dir` — de propósito um passo à parte,
    para rodar de madrugada (M25.3) sem segurar este processo."""
    inputs = source_title_inputs(db, limit=limit)
    if not inputs:
        raise ValueError("sem entradas no banco para destilar — converse com o A.P.O.L.O. primeiro")
    teacher = teacher_fn or make_llm_teacher()
    pairs = distill_titles(inputs, teacher, max_pairs=max_pairs)
    logger.info(f"[distill] {len(inputs)} entradas → {len(pairs)} pares válidos do professor")
    meta = write_distill_dataset(pairs, tokenizer_path, out_dir, val_fraction=val_fraction)
    meta["inputs_seen"] = len(inputs)
    return meta


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m src.nanollm.distill --tokenizer … --out …`.
    Liga o banco real e o professor Qwen real. Sem argumentos extras, usa padrões
    sensatos. É o comando que o Leo roda para gerar o dataset destilado."""
    import argparse

    p = argparse.ArgumentParser(description="Destila pergunta→título do Qwen para o Apolo-Nano")
    p.add_argument("--tokenizer", required=True, help="caminho do tokenizer do checkpoint")
    p.add_argument("--out", default="data/nano/distill_titles", help="pasta de saída do dataset")
    p.add_argument("--limit", type=int, default=300, help="máx. de entradas do banco")
    p.add_argument("--max-pairs", type=int, default=None, help="teto de pares (custo do professor)")
    args = p.parse_args(argv)

    from src.storage import DatabaseManager

    db = DatabaseManager()
    meta = run_distillation(db, args.tokenizer, args.out,
                            limit=args.limit, max_pairs=args.max_pairs)
    print(f"✓ destilados {meta['pairs']} pares de {meta['inputs_seen']} entradas → {args.out}")
    print(f"  treine com:  python -m src.nanollm.train --data {args.out} --init-from <checkpoint>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
