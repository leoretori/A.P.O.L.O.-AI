"""Abstração de provedor de inferência — soberania sobre o motor de LLM.

O A.P.O.L.O. fala com um *provedor* através de uma interface única; por baixo pode
ser o **Ollama** (padrão) ou um motor **próprio** baseado em `llama-cpp-python`
(o mesmo llama.cpp que o Ollama embrulha), rodando dentro do processo — sem
nenhum serviço externo nem o próprio binário do Ollama.

Selecione por variável de ambiente:
    LLM_BACKEND=ollama      (padrão)
    LLM_BACKEND=llamacpp    (motor próprio embutido)

Backend llama.cpp — configuração:
    LLAMACPP_MODELS="qwen2.5-coder:3b=models/qwen3b.gguf;qwen2.5-coder:14b=models/qwen14b.gguf"
    LLAMACPP_CTX=8192            # tamanho do contexto
    LLAMACPP_THREADS=0           # 0 = auto (nº de CPUs)
    LLAMACPP_GPU_LAYERS=0        # >0 descarrega camadas na GPU

Interface do provedor:
    .complete(model, messages, options) -> str           (não-streaming)
    .stream(model, messages, options)   -> Iterator[str]  (tokens)
    .list_models()                      -> list[str]
"""

import logging
import os

logger = logging.getLogger(__name__)


# ── Backend Ollama (padrão) ──────────────────────────────────────
class OllamaProvider:
    name = "ollama"

    def __init__(self, default_keep_alive="30m"):
        import ollama
        # Usa OLLAMA_HOST se definido (ex.: http://ollama:11434 em Docker),
        # caso contrário usa o padrão da lib (http://localhost:11434).
        host = os.getenv("OLLAMA_HOST", "").strip()
        self._client = ollama.Client(host=host) if host else ollama.Client()
        self._ollama = ollama
        self._keep_alive = default_keep_alive
        if host:
            logger.info(f"[ollama] usando host: {host}")

    def _opts(self, options):
        # Mescla as opções do perfil de hardware (threads/contexto); o chamador vence.
        from src.hardware import inference_options
        return {**inference_options(), **(options or {})}

    def complete(self, model, messages, options=None, keep_alive=None) -> str:
        resp = self._client.chat(
            model=model, messages=messages,
            keep_alive=self._keep_alive if keep_alive is None else keep_alive,
            options=self._opts(options),
        )
        return resp.message.content

    def stream(self, model, messages, options=None, keep_alive=None):
        for chunk in self._client.chat(
            model=model, messages=messages, stream=True,
            keep_alive=self._keep_alive if keep_alive is None else keep_alive,
            options=self._opts(options),
        ):
            yield chunk.message.content

    def list_models(self) -> list[str]:
        try:
            listed = self._client.list()
            return sorted({m.get("model") or m.get("name") for m in (listed.get("models") or [])})
        except Exception as e:
            logger.warning(f"Ollama list_models: {e}")
            return []


# ── Backend llama.cpp (motor próprio) ────────────────────────────
class LlamaCppProvider:
    """Motor embutido via `llama-cpp-python`. Carrega arquivos GGUF locais e os
    mantém em cache (carregar um modelo é caro). Sem processo/serviço externo."""
    name = "llamacpp"

    def __init__(self):
        self._models = self._parse_model_map(os.getenv("LLAMACPP_MODELS", ""))
        self._ctx = int(os.getenv("LLAMACPP_CTX", "8192"))
        self._threads = int(os.getenv("LLAMACPP_THREADS", "0")) or None
        self._gpu_layers = int(os.getenv("LLAMACPP_GPU_LAYERS", "0"))
        self._loaded: dict[str, object] = {}
        if not self._models:
            logger.warning("LLAMACPP_MODELS vazio — configure 'nome=caminho.gguf;…'")

    @staticmethod
    def _parse_model_map(spec: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in spec.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, path = pair.split("=", 1)
                out[name.strip()] = path.strip()
        return out

    def _resolve_path(self, model: str) -> str:
        # 1) mapa explícito; 2) o único modelo configurado; 3) o próprio nome como caminho.
        if model in self._models:
            return self._models[model]
        if len(self._models) == 1:
            return next(iter(self._models.values()))
        return model  # deixa o llama.cpp validar; erro claro se não existir

    def _get(self, model: str):
        path = self._resolve_path(model)
        if path not in self._loaded:
            from llama_cpp import Llama  # import preguiçoso: só exige a lib se este backend for usado
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"GGUF não encontrado: {path}. Baixe um modelo (Hugging Face) e "
                    f"aponte LLAMACPP_MODELS para ele.")
            logger.info(f"[llamacpp] carregando {path} (ctx={self._ctx}, gpu_layers={self._gpu_layers})…")
            self._loaded[path] = Llama(
                model_path=path, n_ctx=self._ctx, n_threads=self._threads,
                n_gpu_layers=self._gpu_layers, verbose=False,
            )
        return self._loaded[path]

    @staticmethod
    def _opts(options):
        options = options or {}
        out = {}
        if "temperature" in options:
            out["temperature"] = options["temperature"]
        if "num_predict" in options:
            out["max_tokens"] = options["num_predict"]  # nome equivalente no llama.cpp
        if "top_p" in options:
            out["top_p"] = options["top_p"]
        return out

    def complete(self, model, messages, options=None, keep_alive=None) -> str:
        llm = self._get(model)
        resp = llm.create_chat_completion(messages=messages, stream=False, **self._opts(options))
        return resp["choices"][0]["message"]["content"]

    def stream(self, model, messages, options=None, keep_alive=None):
        llm = self._get(model)
        for chunk in llm.create_chat_completion(messages=messages, stream=True, **self._opts(options)):
            delta = chunk["choices"][0].get("delta", {})
            piece = delta.get("content")
            if piece:
                yield piece

    def list_models(self) -> list[str]:
        return sorted(self._models.keys())


# ── Seleção do provedor (singleton) ──────────────────────────────
_provider = None


def get_provider():
    """Devolve o provedor configurado (cacheado). Padrão: Ollama."""
    global _provider
    if _provider is None:
        backend = os.getenv("LLM_BACKEND", "ollama").strip().lower()
        if backend == "llamacpp":
            _provider = LlamaCppProvider()
            logger.info("LLM backend: llama.cpp (motor próprio embutido)")
        else:
            from src.llm import KEEP_ALIVE
            _provider = OllamaProvider(default_keep_alive=KEEP_ALIVE)
            logger.info("LLM backend: Ollama")
    return _provider


def reset_provider():
    """Limpa o singleton — usado em testes para trocar de backend."""
    global _provider
    _provider = None
