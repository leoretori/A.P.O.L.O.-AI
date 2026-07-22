"""Avaliação ÀS CEGAS: o cérebro próprio (Nano) contra o professor (Qwen) — M28.

O DoD do M28 pede "medir contra o Qwen às cegas". Aqui está o juiz honesto: para
cada pergunta, geramos a resposta do Nano e a do Qwen, **embaralhamos a ordem**
(semente fixa → reprodutível) e mostramos as duas ao juiz como "A" e "B", SEM
dizer quem é quem. O juiz escolhe a melhor; só depois mapeamos de volta. Assim o
placar não pode ser enviesado por saber qual é o modelo próprio.

Núcleo determinístico: `model_a_fn`/`model_b_fn`/`judge_fn` são injetáveis (fakes
nos testes). `make_llm_judge` monta um juiz real com o motor; `run_blind_eval`
liga tudo no banco + Nano + Qwen para rodar de verdade.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import re
from pathlib import Path
from typing import Callable

logger = logging.getLogger("apolo.nano.blindeval")

JUDGE_PROMPT = (
    "Você é um juiz imparcial. Para a pergunta abaixo, há duas respostas, A e B. "
    "Escolha a MELHOR (mais correta, direta e útil). Responda APENAS com a letra "
    "A ou B.\n\nPergunta: {q}\n\n[A]\n{a}\n\n[B]\n{b}\n\nMelhor (A ou B):"
)


def _parse_choice(text: str) -> str | None:
    """Extrai 'A'/'B' da resposta do juiz. Casa a letra ISOLADA (fronteira de
    palavra) — senão o 'a' de 'resposta' seria lido como voto em A."""
    m = re.search(r"\b([AB])\b", (text or "").upper())
    return m.group(1) if m else None


def blind_compare(
    prompts: list[str],
    nano_fn: Callable[[str], str],
    teacher_fn: Callable[[str], str],
    judge_fn: Callable[[str, str, str], str],
    *,
    seed: int = 0,
    two_pass: bool = False,
) -> dict:
    """Compara Nano vs professor às cegas. Retorna placar + win-rate do Nano.

    `judge_fn(pergunta, respA, respB) -> "A"|"B"` (cego: não sabe quem é quem).
    A ordem A/B é sorteada por pergunta (semente fixa) e desfeita no placar.

    `two_pass=True` julga CADA par duas vezes, com as posições trocadas, e só
    conta o veredito quando ele se repete; discordância entre as duas ordens é
    viés de posição do juiz, não preferência, e vira empate (E5). Dobra o custo
    de juiz — por isso é opção, ligada onde a medição DECIDE promoção."""
    rng = random.Random(seed)
    wins = {"nano": 0, "teacher": 0, "tie": 0}
    rounds = []
    inconsistentes = 0
    for i, q in enumerate(prompts):
        a_nano = (nano_fn(q) or "").strip()
        a_teach = (teacher_fn(q) or "").strip()
        nano_is_A = rng.random() < 0.5           # embaralha a posição
        first, second = (a_nano, a_teach) if nano_is_A else (a_teach, a_nano)

        winner = _winner_from(judge_fn(q, first, second), nano_is_A)
        consistente = True
        if two_pass:
            # mesma dupla, posições trocadas: o juiz tem que manter o veredito
            verso = _winner_from(judge_fn(q, second, first), not nano_is_A)
            consistente = winner == verso
            if not consistente:
                inconsistentes += 1
                winner = "tie"
        wins[winner] += 1
        rounds.append({"i": i, "q": q[:80], "winner": winner,
                       "nano_was": "A" if nano_is_A else "B",
                       "consistent": consistente})
    decided = wins["nano"] + wins["teacher"]
    win_rate = round(100 * wins["nano"] / decided, 1) if decided else 0.0
    return {"n": len(prompts), "wins": wins, "nano_win_rate": win_rate,
            "rounds": rounds, "inconsistentes": inconsistentes,
            "two_pass": two_pass}


def _winner_from(veredito: str, nano_is_A: bool) -> str:
    """Traduz a letra do juiz para quem ganhou, desfazendo o embaralhamento."""
    choice = _parse_choice(veredito)
    if choice is None:
        return "tie"
    return "nano" if ((choice == "A") == nano_is_A) else "teacher"


def cached_teacher(teacher_fn: Callable[[str], str], cache_path: str | Path):
    """Professor com GABARITO em disco: a mesma pergunta devolve sempre a mesma
    resposta de referência.

    Sem isso, o professor re-gera a resposta a cada chamada (temperatura > 0),
    então candidato e titular eram comparados contra gabaritos DIFERENTES — e
    entre noites, contra outros ainda (E5). Efeito colateral bom: o custo de
    professor cai pela metade já na primeira noite (candidato e titular
    reaproveitam as mesmas referências)."""
    path = Path(cache_path)
    cache: dict[str, str] = {}
    if path.exists():
        try:
            cache = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[blind_eval] gabarito ilegível em {path}: {e} — recomeçando")

    def fn(q: str) -> str:
        key = hashlib.sha1(q.encode("utf-8")).hexdigest()
        if key in cache:
            return cache[key]
        resp = teacher_fn(q) or ""
        cache[key] = resp
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        except OSError as e:
            logger.warning(f"[blind_eval] não consegui gravar o gabarito: {e}")
        return resp

    return fn


def _binomial_two_sided_p(b: int, n: int) -> float:
    """p-valor exato do teste de sinais: P(|X - n/2| >= |b - n/2|), X~Bin(n, ½).

    Exato de propósito — n aqui é de dezenas, `math.comb` resolve, e assim o
    portão não depende de aproximação normal (nem de scipy)."""
    if n <= 0:
        return 1.0
    k = max(b, n - b)
    cauda = sum(math.comb(n, i) for i in range(k, n + 1)) / (2 ** n)
    return min(1.0, 2 * cauda)


def paired_sign_test(cand: dict[int, bool], base: dict[int, bool],
                     *, alpha: float = 0.05) -> dict:
    """Candidato é MELHOR que o titular, ou é sorteio? (teste de sinais pareado)

    `cand`/`base` mapeiam item → acertou/ganhou. Como as duas medições rodam
    nos MESMOS itens, a comparação certa é pareada (McNemar/sinais): conta só
    os itens em que os dois discordam — `b` = só o candidato acertou, `c` = só
    o titular. Sob a hipótese nula, b ~ Binomial(b+c, ½).

    Por que isto substitui a "margem de 5pp": com n=15 o desvio-padrão de um
    win-rate de ~40% é ~12,6pp; o MESMO checkpoint marcou 33,3% e 46,7% em
    duas noites sem mudar um peso (E5). 5pp de margem não distingue nada — o
    que distingue é o p-valor do delta pareado."""
    comuns = sorted(set(cand) & set(base))
    b = sum(1 for i in comuns if cand[i] and not base[i])
    c = sum(1 for i in comuns if base[i] and not cand[i])
    p = _binomial_two_sided_p(b, b + c)
    return {
        "pareadas": len(comuns), "candidato_ganhou": b, "titular_ganhou": c,
        "discordantes": b + c, "p_value": round(p, 4), "alpha": alpha,
        "significativo": bool(b > c and p <= alpha),
    }


def paired_win_test(cand_rounds: list[dict], base_rounds: list[dict],
                    *, alpha: float = 0.05) -> dict:
    """`paired_sign_test` sobre os `rounds` do blind-eval (vitória = "nano")."""
    return paired_sign_test(
        {r["i"]: r["winner"] == "nano" for r in cand_rounds if "i" in r},
        {r["i"]: r["winner"] == "nano" for r in base_rounds if "i" in r},
        alpha=alpha)


def make_llm_judge(model: str | None = None, *, temperature: float = 0.0):
    """Juiz real usando o motor próprio (Qwen). Import preguiçoso (sem LLM nos testes)."""
    from src.providers import get_provider

    prov = get_provider()
    if model is None:
        try:
            from src import runtime
            model = runtime.get_chat_model()
        except Exception:
            model = None
        if not model:
            models = prov.list_models()
            model = models[0] if models else "apolo"

    def judge_fn(q: str, a: str, b: str) -> str:
        # Mesma disciplina do teacher_fn (distill.py): cede a GPU ao usuário antes
        # de cada veredito — a avaliação às cegas também roda em thread de fundo.
        try:
            from src import runtime as rt
            if rt.gpu_gate:
                rt.gpu_gate.wait_for_idle_sync()
        except Exception:
            pass
        prompt = JUDGE_PROMPT.format(q=q, a=a[:600], b=b[:600])
        return prov.complete(model, [{"role": "user", "content": prompt}],
                             options={"temperature": temperature, "num_predict": 4})

    return judge_fn


def run_blind_eval(db, nano_engine, *, limit: int = 30, seed: int = 0,
                   max_tokens: int = 80, questions: list[str] | None = None,
                   teacher_cache: str | Path | None = None) -> dict:
    """Roda a avaliação às cegas de verdade: Nano do checkpoint vivo, professor +
    juiz no motor próprio. É o número honesto do M28 (win-rate do Nano vs Qwen).
    Barato de pular se não há checkpoint/perguntas.

    `questions`, se dado, SUBSTITUI a amostragem de `db.first_user_messages` —
    é o que permite medir sempre no MESMO conjunto (P1.4/`freeze_questions`),
    em vez de um número novo (e não comparável) a cada rodada.

    `teacher_cache` congela o GABARITO em disco: duas rodadas passam a comparar
    o Nano contra as MESMAS respostas do professor (E5)."""
    from src.nanollm.distill import make_llm_teacher

    prompts = questions if questions is not None else db.first_user_messages(limit=limit)
    if not prompts:
        return {"status": "skipped", "reason": "sem perguntas no banco"}
    if nano_engine is None or not nano_engine.available():
        return {"status": "skipped", "reason": "Nano sem checkpoint treinado"}

    teacher = make_llm_teacher(max_tokens=max_tokens)
    if teacher_cache:
        teacher = cached_teacher(teacher, teacher_cache)

    def nano_fn(q: str) -> str:
        return nano_engine.complete(q, max_tokens=max_tokens).get("text", "")

    res = blind_compare(prompts, nano_fn, teacher, make_llm_judge(), seed=seed)
    res["status"] = "ok"
    logger.info(f"[blind_eval] Nano win-rate {res['nano_win_rate']}% em {res['n']} perguntas")
    return res


# ── Placar histórico rastreável (P1.4) ─────────────────────────────
def freeze_questions(db, path: str | Path, limit: int = 30,
                     min_questions: int = 30) -> list[str]:
    """O MESMO conjunto de perguntas em toda rodada futura — sem isso, o
    win-rate de duas rodadas não é comparável (n pequeno, amostra nova a cada
    vez = ruído, exatamente o problema medido no M28 em 2026-07-15: 20% → 40%
    era só ruído de amostra, não melhora real).

    Se `path` já existe, carrega e devolve o conjunto congelado (idempotente —
    rodar de novo NÃO re-sorteia). Senão, tira uma amostra nova de
    `db.first_user_messages` e congela. Levanta ValueError se não houver
    `min_questions` perguntas reais disponíveis — não força medição com n
    pequeno demais pra significar algo (mesmo espírito do 'poucos pares' do
    resto do projeto).

    O conjunto **cresce, nunca é re-sorteado**: se o arquivo congelado tem
    menos que `min_questions` (o caso real — 15 perguntas, ruído puro, E5), as
    antigas são mantidas na mesma ordem e as novas do banco são ACRESCENTADAS
    até o alvo. Assim o histórico não é jogado fora ao subir o n."""
    p = Path(path)
    alvo = max(int(limit), int(min_questions))
    congeladas: list[str] = []
    if p.exists():
        congeladas = json.loads(p.read_text(encoding="utf-8"))
        if len(congeladas) >= min_questions:
            return congeladas

    prompts = db.first_user_messages(limit=alvo)
    vistas = set(congeladas)
    novas = [q for q in prompts if q not in vistas]
    total = congeladas + novas[: max(0, alvo - len(congeladas))]
    if len(total) < min_questions:
        raise ValueError(
            f"poucas perguntas reais pra congelar o conjunto do blind-eval "
            f"({len(total)} < {min_questions}) — junte mais conversas antes de medir")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(total, indent=2, ensure_ascii=False), encoding="utf-8")
    if congeladas:
        logger.info(f"[blind_eval] conjunto congelado cresceu {len(congeladas)}→{len(total)} "
                    f"perguntas (as antigas foram mantidas)")
    return total


def append_history(path: str | Path, result: dict, seed: int) -> None:
    """Acrescenta 1 linha ao placar histórico (JSONL — append-only, nunca
    reescreve o passado, via `src.jsonl_history`). Só grava rodadas com
    resultado real (`status=ok`); pular por falta de checkpoint/perguntas
    não é um ponto da série."""
    if result.get("status") != "ok":
        return
    from src.jsonl_history import append_entry
    append_entry(path, {
        "n": result["n"], "wins": result["wins"],
        "nano_win_rate": result["nano_win_rate"], "seed": seed,
    })


def read_history(path: str | Path, limit: int = 50) -> list[dict]:
    """Lê o placar histórico, mais recente por último (ordem de gravação)."""
    from src.jsonl_history import read_entries
    return read_entries(path, limit)


def run_tracked_blind_eval(db, nano_engine, *, questions_path: str | Path,
                           history_path: str | Path, limit: int = 30,
                           min_questions: int = 30, seed: int = 0,
                           max_tokens: int = 80,
                           teacher_cache: str | Path | None = None) -> dict:
    """`run_blind_eval` no conjunto CONGELADO de perguntas, registrando o
    resultado no placar histórico — o jeito certo de rodar isto a partir de
    agora (em vez de `run_blind_eval` cru, que reamostra toda vez).

    Comparabilidade entre rodadas exige as duas pontas fixas: as mesmas
    perguntas (`freeze_questions`) e as mesmas respostas de referência
    (`teacher_cache`) — senão a série mistura mudança do Nano com mudança do
    gabarito (E5)."""
    questions = freeze_questions(db, questions_path, limit, min_questions)
    result = run_blind_eval(db, nano_engine, seed=seed, max_tokens=max_tokens,
                            questions=questions, teacher_cache=teacher_cache)
    append_history(history_path, result, seed)
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m src.nanollm.blind_eval [--limit N]`. Roda o Nano do
    checkpoint vivo contra o Qwen, às cegas, no conjunto CONGELADO de
    perguntas (P1.4) — comparável entre rodadas, registrado no histórico."""
    import argparse

    p = argparse.ArgumentParser(description="Nano vs Qwen às cegas (M28/P1.4)")
    p.add_argument("--limit", type=int, default=30, help="tamanho do conjunto ao congelar")
    p.add_argument("--min-questions", type=int, default=30)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--questions", default="data/nano/blind_eval_questions.json")
    p.add_argument("--history", default="data/nano/blind_eval_history.jsonl")
    p.add_argument("--teacher-cache", default="data/nano/blind_eval_teacher_cache.json",
                   help="gabarito do professor em disco (mesma referência entre rodadas)")
    args = p.parse_args(argv)

    from src.nanollm.engine import NanoEngine
    from src.storage import DatabaseManager

    try:
        res = run_tracked_blind_eval(
            DatabaseManager(), NanoEngine(), questions_path=args.questions,
            history_path=args.history, limit=args.limit,
            min_questions=args.min_questions, seed=args.seed,
            teacher_cache=args.teacher_cache)
    except ValueError as e:
        print(f"pulado: {e}")
        return 1
    if res.get("status") != "ok":
        print(f"pulado: {res.get('reason')}")
        return 1
    w = res["wins"]
    print(f"Nano vs Qwen (às cegas, {res['n']} perguntas, conjunto congelado): "
          f"Nano {w['nano']} · Qwen {w['teacher']} · empates {w['tie']}")
    print(f"→ win-rate do cérebro próprio: {res['nano_win_rate']}%")
    return 0


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    raise SystemExit(main())
