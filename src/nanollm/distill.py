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
import re
from pathlib import Path
from typing import Callable

from src.nanollm.taskdata import (
    TITLE_TEMPLATE,
    _valid_title,
    _write_tokenized,
)
# Um número só para treino e inferência (E26): o corte da entrada mora no lado
# do produto (`tasks.py`), que é quem monta o prompt de verdade.
from src.nanollm.tasks import MAX_INPUT_CHARS  # noqa: F401 (re-export histórico)

logger = logging.getLogger("apolo.nano.distill")

# Prompt-professor: pede ao Qwen exatamente a tarefa, na distribuição de
# inferência (pergunta → título curto), para o rótulo casar com o uso real.
TITLE_TEACHER_PROMPT = (
    "Dê um título curto (3 a 6 palavras, em português, sem aspas) para uma "
    "conversa que começa com esta mensagem do usuário:\n\n{input}\n\nTítulo:"
)



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
        # Cede a GPU ao usuário antes de CADA rótulo: o flywheel roda em thread de
        # fundo e pode gerar dezenas de rótulos — sem isso, seguraria o lock do
        # motor e faria o chat do usuário esperar atrás do treino noturno.
        try:
            from src import runtime as rt
            if rt.gpu_gate:
                rt.gpu_gate.wait_for_idle_sync()
        except Exception:
            pass
        return prov.complete(model, [{"role": "user", "content": prompt}], options=opts)

    return teacher_fn


def source_title_inputs(db, *, limit: int = 300, min_len: int = 8) -> list[str]:
    """Puxa do banco as entradas reais a destilar: a 1ª mensagem de cada sessão
    (a pergunta que abre a conversa — a distribuição de inferência). `db` é o
    DatabaseManager; mantido como parâmetro (não import global) para o pipeline
    seguir testável com um banco falso."""
    return db.first_user_messages(limit=limit, min_len=min_len)


# ── M28: destilação de RESPOSTA CURTA (o passo rumo ao chat próprio) ──
# Tarefa muito mais dura que título — de propósito. Num Nano de 3,4M no CPU o
# resultado NÃO será um chat bom; o valor é o arcabouço + a medição às cegas
# (blind_eval), que dirá a verdade quando a ESCALA vier. O professor responde
# curto e factual; o aluno tenta imitar na mesma distribuição de pergunta real.
ANSWER_TEACHER_PROMPT = (
    "Responda de forma curta, direta e factual (1 a 3 frases, em português) à "
    "pergunta abaixo. Sem rodeios, sem listas.\n\nPergunta: {input}\n\nResposta:"
)
ANSWER_TEMPLATE = "Pergunta: {context}\n\nResposta: {title}"


def _valid_answer(ans: str) -> bool:
    """Resposta de treino: curta, sem código/markdown pesado, com conteúdo real."""
    ans = (ans or "").strip()
    if not (4 <= len(ans) <= 280):
        return False
    if "```" in ans or ans.count("\n") > 3:
        return False
    return any(c.isalpha() for c in ans)


def distill_answers(
    inputs: list[str],
    teacher_fn: Callable[[str], str],
    *,
    max_pairs: int | None = None,
) -> list[tuple[str, str]]:
    """Destila pares `pergunta → resposta curta` na distribuição de inferência.
    O passo do M28 rumo ao diálogo próprio (medido às cegas em `blind_eval`)."""
    return generate_distill_pairs(
        inputs, teacher_fn,
        prompt_template=ANSWER_TEACHER_PROMPT,
        validate=_valid_answer,
        max_pairs=max_pairs,
    )


# ── M28: Q&A ANCORADO no banco de conhecimento dos 7 agentes ──
# Fonte SEPARADA do flywheel de título (que vive na distribuição de conversa).
# Aqui o conhecimento que os agentes sintetizaram vira combustível do Nano-de-
# diálogo — o Qwen transforma cada síntese num par pergunta→resposta ancorado.
# NÃO se mistura com título: título ficaria com distribuição errada (lição do
# M14.2). São dois datasets/tarefas distintos, de propósito.
GROUND_QA_PROMPT = (
    "Com base APENAS no resumo abaixo, escreva UMA pergunta curta e natural que "
    "ele responda, e a resposta (1 a 2 frases, factual, em português). Use "
    "EXATAMENTE este formato:\nP: <pergunta>\nR: <resposta>\n\nResumo:\n{input}"
)

_QA_Q = re.compile(r"^\s*(?:P|Pergunta)\s*[:\-]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_QA_A = re.compile(r"^\s*(?:R|Resposta)\s*[:\-]\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def _parse_qa(text: str) -> tuple[str | None, str | None]:
    """Extrai (pergunta, resposta) do formato P:/R: devolvido pelo professor."""
    q = _QA_Q.search(text or "")
    a = _QA_A.search(text or "")
    return (q.group(1).strip() if q else None,
            a.group(1).strip() if a else None)


def is_meta_item(item: dict) -> bool:
    """O item é META-informação sobre o processo, não conhecimento? (E18)

    As "Síntese #N" (cruzamentos de domínio que o próprio Apolo escreve) viravam
    pares Q&A "ancorados" com perguntas artificiais sobre um documento interno —
    e entravam no prompt do auto-currículo. A clusterização do learner já
    filtrava (`learner_synthesis.py`); a destilação, não. Mesma regra nos dois:
    categoria `synthesis` ou tópico que começa com "Síntese"."""
    if (item.get("category") or "").strip().lower() == "synthesis":
        return True
    topico = (item.get("topic") or "").strip().lower()
    return topico.startswith("síntese") or topico.startswith("sintese")


def _stratify_by_sector(history: list[dict], max_per_sector: int) -> list[dict]:
    """Teto de `max_per_sector` itens por setor (via `classify_sector`), preservando
    a ordem original dentro de cada setor. Achado real (PLANO_CORPUS_DIVERSO.md): um
    dataset de destilação ~80% de um só setor (backend/devops/dados) fez um fine-tune
    fazer o Nano "esquecer" prosa geral e derivar pra vocabulário tech em qualquer
    pergunta — este teto existe pra isso não se repetir."""
    from src.topics import classify_sector

    counts: dict[str, int] = {}
    out: list[dict] = []
    for item in history:
        topic = item.get("topic") or ""
        summ = (item.get("summary") or "")[:200]
        sector = classify_sector(f"{topic} {summ}")
        if counts.get(sector, 0) >= max_per_sector:
            continue
        counts[sector] = counts.get(sector, 0) + 1
        out.append(item)
    return out


def source_knowledge_grounded_pairs(
    db,
    teacher_fn: Callable[[str], str],
    *,
    limit: int = 200,
    max_pairs: int | None = None,
    max_per_sector: int | None = None,
) -> list[tuple[str, str]]:
    """Puxa as sínteses dos 7 agentes e o professor as vira pares pergunta→
    resposta ANCORADOS. Isolado do título — combustível do chat próprio (M28).

    `max_per_sector`, se dado, estratifica por setor ANTES de chamar o professor
    (economiza chamadas também) — sem isso, "as primeiras N sínteses" pode ficar
    dominado por 1-2 setores (medido: ~80% num caso real)."""
    history = [h for h in db.get_learning_history(limit=limit) if not is_meta_item(h)]
    if max_per_sector:
        history = _stratify_by_sector(history, max_per_sector)
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in history:
        summ = (item.get("summary") or "").strip()
        if len(summ) < 40:                       # síntese curta demais não ancora
            continue
        try:
            raw = teacher_fn(GROUND_QA_PROMPT.format(input=summ[:1200]))
        except Exception as e:
            logger.debug(f"[distill] professor falhou numa síntese: {e}")
            continue
        q, a = _parse_qa(raw or "")
        if not q or not a:
            continue
        q = q.strip(' \t"\'`')
        a = a.strip(' \t"\'`')
        key = q[:80].lower()
        if key in seen or len(q) < 6 or not _valid_answer(a):
            continue
        seen.add(key)
        pairs.append((q, a))
        if max_pairs and len(pairs) >= max_pairs:
            break
    return pairs


def source_reaction_pairs(db, *, limit: int = 300, min_len: int = 8) -> list[tuple[str, str]]:
    """Pares pergunta→resposta que o Leo já avaliou com 👍 (2026-07-15): dispensa
    o professor rotular de novo — a aprovação do Leo É o rótulo, direto na
    distribuição real de diálogo (a mesma tarefa de `distill_answers`, só que
    sem custo de professor e com veredito humano em vez de auto-avaliação)."""
    pairs = db.positive_reaction_pairs(limit=limit, min_len=min_len)
    return [(q, a) for q, a in pairs if _valid_answer(a)]


def run_reaction_distillation(
    db,
    tokenizer_path: str | Path,
    out_dir: str | Path,
    *,
    limit: int = 300,
    val_fraction: float = 0.1,
) -> dict:
    """Destila os 👍 do Leo em dataset de treino (M-reações), ponta a ponta.
    Dataset SEPARADO (task `answer_distill_reactions`) — mesma distribuição de
    `distill_answers`, mas com rótulo humano em vez do professor Qwen."""
    pairs = source_reaction_pairs(db, limit=limit)
    if not pairs:
        raise ValueError("sem 👍 aproveitáveis ainda — avalie algumas respostas "
                         "com pergunta+resposta completas para gerar pares")
    meta = write_distill_dataset(pairs, tokenizer_path, out_dir,
                                 template=ANSWER_TEMPLATE, task="answer_distill_reactions",
                                 val_fraction=val_fraction)
    meta["source"] = "reações do Leo (👍 vira rótulo direto, sem professor)"
    (Path(out_dir) / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def _read_pairs_jsonl(path: str | Path) -> list[tuple[str, str]]:
    """Lê os pares já destilados (`pairs.jsonl`) — vazio se não existir."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[tuple[str, str]] = []
    for linha in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(linha)
        except json.JSONDecodeError:
            continue
        c, t = d.get("context"), d.get("title")
        if c and t:
            out.append((c, t))
    return out


def _merge_pairs(anteriores: list[tuple[str, str]],
                 novos: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], int]:
    """Junta preservando os antigos e a ordem; dedup pela PERGUNTA normalizada.
    Devolve (lista, quantos entraram de novo)."""
    vistos = {c.strip().lower()[:120] for c, _ in anteriores}
    saida = list(anteriores)
    n = 0
    for c, t in novos:
        chave = c.strip().lower()[:120]
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append((c, t))
        n += 1
    return saida, n


def run_knowledge_distillation(
    db,
    tokenizer_path: str | Path,
    out_dir: str | Path,
    *,
    teacher_fn: Callable[[str], str] | None = None,
    limit: int = 200,
    max_pairs: int | None = None,
    max_per_sector: int | None = None,
    val_fraction: float = 0.1,
    append: bool = True,
    teacher_cache: str | Path | None = None,
) -> dict:
    """Destila o banco de conhecimento em Q&A ancorado (M28), ponta a ponta.
    Dataset SEPARADO (task `answer_distill_grounded`), no formato do fine-tune.
    `max_per_sector`: teto por setor (ver `_stratify_by_sector`) — sem ele, o
    dataset pode ficar dominado por 1-2 setores (medido: ~80% num caso real).

    **Append-only com dedup por pergunta** (E10): toda noite o corpus era
    reescrito do zero — o professor re-rotulava as MESMAS sínteses (pagando de
    novo, e produzindo pares diferentes), e o split train/val era re-sorteado.
    O portão de crescimento do flywheel (`pairs - last_pairs`) media um dataset
    que trocava de identidade a cada noite. Agora os pares antigos ficam, os
    novos são acrescentados, e o professor tem GABARITO em disco
    (`teacher_cache`, padrão `<out_dir>/teacher_cache.json`) — a mesma síntese
    nunca é rotulada duas vezes."""
    from src.nanollm.blind_eval import cached_teacher

    out = Path(out_dir)
    teacher = teacher_fn or make_llm_teacher()
    teacher = cached_teacher(teacher, teacher_cache or (out / "teacher_cache.json"))
    novos = source_knowledge_grounded_pairs(db, teacher, limit=limit, max_pairs=max_pairs,
                                            max_per_sector=max_per_sector)
    anteriores = _read_pairs_jsonl(out / "pairs.jsonl") if append else []
    pairs, n_novos = _merge_pairs(anteriores, novos)
    if not pairs:
        raise ValueError("sem sínteses aproveitáveis no banco de conhecimento — "
                         "deixe os 7 agentes estudarem primeiro")
    meta = write_distill_dataset(pairs, tokenizer_path, out_dir,
                                 template=ANSWER_TEMPLATE, task="answer_distill_grounded",
                                 val_fraction=val_fraction)
    meta["source"] = "knowledge grounded (7 agentes → Qwen Q&A)"
    meta["pares_novos"] = n_novos
    meta["pares_anteriores"] = len(anteriores)
    meta["append_only"] = append
    (Path(out_dir) / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


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
    exclude: set[str] | None = None,
) -> dict:
    """FLYWHEEL, ponta a ponta (M25.2): banco → professor rotula → dataset.

    (1) puxa as entradas reais (1ª mensagem de cada sessão), (2) o professor
    (Qwen real por padrão; injetável nos testes) rotula pergunta→título na
    distribuição de inferência, (3) grava no formato do fine-tune. Devolve o
    `meta` com um resumo (quantas entradas viraram quantos pares). O TREINO em
    si é o `train.py` apontado para `out_dir` — de propósito um passo à parte,
    para rodar de madrugada (M25.3) sem segurar este processo.

    `exclude` tira entradas do treino — é como o conjunto de avaliação do
    portão fica HELD-OUT de verdade (senão o candidato é medido nas mesmas
    mensagens em que treinou, e a taxa de aceitação sai inflada)."""
    inputs = source_title_inputs(db, limit=limit)
    if exclude:
        inputs = [i for i in inputs if i not in exclude]
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

    p = argparse.ArgumentParser(description="Destila conhecimento do Qwen para o Apolo-Nano")
    p.add_argument("--tokenizer", required=True, help="caminho do tokenizer do checkpoint")
    p.add_argument("--out", default="", help="pasta de saída (padrão por fonte)")
    p.add_argument("--source", choices=("conversations", "knowledge", "reactions"),
                   default="conversations",
                   help="conversations → pergunta→título (distribuição de conversa); "
                        "knowledge → Q&A ancorado nas sínteses dos 7 agentes (M28, isolado); "
                        "reactions → pergunta→resposta dos 👍 do Leo (rótulo humano direto)")
    p.add_argument("--limit", type=int, default=300, help="máx. de itens do banco")
    p.add_argument("--max-pairs", type=int, default=None, help="teto de pares (custo do professor)")
    p.add_argument("--max-per-sector", type=int, default=None,
                   help="(--source knowledge) teto por setor — evita dataset dominado por 1-2 setores")
    args = p.parse_args(argv)

    from src.storage import DatabaseManager

    db = DatabaseManager()
    if args.source == "knowledge":
        out = args.out or "data/nano/distill_answers"
        meta = run_knowledge_distillation(db, args.tokenizer, out, limit=args.limit,
                                          max_pairs=args.max_pairs,
                                          max_per_sector=args.max_per_sector)
        print(f"✓ destilados {meta['pairs']} pares Q&A ancorados → {out}")
    elif args.source == "reactions":
        out = args.out or "data/nano/distill_reactions"
        meta = run_reaction_distillation(db, args.tokenizer, out, limit=args.limit)
        print(f"✓ destilados {meta['pairs']} pares dos 👍 do Leo → {out}")
    else:
        out = args.out or "data/nano/distill_titles"
        meta = run_distillation(db, args.tokenizer, out,
                                limit=args.limit, max_pairs=args.max_pairs)
        print(f"✓ destilados {meta['pairs']} pares de {meta['inputs_seen']} entradas → {out}")
    print(f"  treine com:  python -m src.nanollm.train --data {out} --init-from <checkpoint>")
    return 0


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    raise SystemExit(main())
