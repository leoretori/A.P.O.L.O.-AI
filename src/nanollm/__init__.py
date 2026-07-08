"""Apolo-Nano — LLM própria, do zero, sem dependências de terceiros.

Tudo aqui é implementado à mão sobre NumPy: tokenizer BPE byte-level,
transformer GPT decoder-only com forward E backward manuais (sem autograd),
otimizador Adam e loop de treino. Nenhum peso pré-treinado, nenhuma lib de ML.

Uso típico:
    python -m src.nanollm.data --corpus data/nanollm/corpus --out data/nanollm
    python -m src.nanollm.train --data data/nanollm --out data/nanollm/ckpt --preset small
    python -m src.nanollm.generate --ckpt data/nanollm/ckpt --prompt "O Apolo é"
"""

from src.nanollm.model import GPT, GPTConfig
from src.nanollm.tokenizer import ByteBPETokenizer

__all__ = ["GPT", "GPTConfig", "ByteBPETokenizer"]
