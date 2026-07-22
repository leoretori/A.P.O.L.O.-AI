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
import threading

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

    def stream(self, model, messages, options=None, keep_alive=None, cancel=None):
        for chunk in self._client.chat(
            model=model, messages=messages, stream=True,
            keep_alive=self._keep_alive if keep_alive is None else keep_alive,
            options=self._opts(options),
        ):
            if cancel is not None and cancel.is_set():
                break  # cliente cancelou (clicou "parar") — encerra a geração
            yield chunk.message.content

    def list_models(self) -> list[str]:
        try:
            listed = self._client.list()
            return sorted({m.get("model") or m.get("name") for m in (listed.get("models") or [])})
        except Exception as e:
            logger.warning(f"Ollama list_models: {e}")
            return []


# ── Backend llama.cpp (motor próprio) ────────────────────────────
# Padrão do mapa de penalidade: os modelos pequenos do setup atual (E19).
SMALL_MODEL_PENALTY_DEFAULT = "qwen-1.5b=1.3"


class LlamaCppProvider:
    """Motor embutido via `llama-cpp-python`. Carrega arquivos GGUF locais e os
    mantém em cache (carregar um modelo é caro). Sem processo/serviço externo."""
    name = "llamacpp"

    def __init__(self):
        self._models = self._parse_model_map(os.getenv("LLAMACPP_MODELS", ""))
        self._ctx = int(os.getenv("LLAMACPP_CTX", "8192"))
        self._threads = int(os.getenv("LLAMACPP_THREADS", "0")) or None
        self._gpu_layers = int(os.getenv("LLAMACPP_GPU_LAYERS", "0"))
        # Teto de segurança da geração (ver _opts). Sem isto o llama.cpp gera até
        # encher o contexto (max_tokens=None) — o 1.5B entrava em loop e segurava o
        # lock indefinidamente, travando o chat E o estudo ao mesmo tempo.
        self._max_tokens = int(os.getenv("LLAMACPP_MAX_TOKENS", "2048"))
        # Penalidade de repetição POR MODELO (E19). O 1.3 global existia por causa
        # do 1.5B degenerando em loop, mas castigava também o 7B/14B: em código,
        # listas e JSON o modelo PRECISA reusar tokens (`{`, `def`, vírgulas) e
        # 1.3 é agressivo (default do llama.cpp: 1.1). Agora o piso é 1.1 e os
        # modelos pequenos levam o 1.3 pelo mapa — ajustável por env:
        #   LLAMACPP_REPEAT_PENALTY=1.1
        #   LLAMACPP_REPEAT_PENALTY_MAP="qwen-1.5b=1.3;outro=1.2"
        self._repeat_penalty = float(os.getenv("LLAMACPP_REPEAT_PENALTY", "1.1"))
        self._repeat_penalty_map = {
            k: float(v) for k, v in
            self._parse_model_map(os.getenv("LLAMACPP_REPEAT_PENALTY_MAP",
                                            SMALL_MODEL_PENALTY_DEFAULT)).items()
        }
        self._loaded: dict[str, object] = {}
        # Um lock POR instância: o llama.cpp NÃO é thread-safe num mesmo contexto —
        # duas gerações simultâneas no mesmo modelo (ex.: o chat e o summarizer do
        # learner, ambos no 1.5B) corrompem o buffer de trabalho e estouram um
        # GGML_ASSERT (repack.cpp) que derruba o processo. O lock serializa por modelo.
        self._locks: dict[str, threading.Lock] = {}
        self._load_lock = threading.Lock()
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
        # 1) mapa explícito; 2) fallback TOLERANTE: nome desconhecido cai no PRIMEIRO
        #    modelo configurado (avisa quando há mais de um). Assim um nome legado —
        #    ex.: 'qwen2.5-coder:14b' herdado do Ollama — NÃO quebra o estudo/summarizer
        #    (era isto que derrubava o pipeline: GGUF não encontrado → circuito abria).
        if model in self._models:
            return self._models[model]
        if self._models:
            if len(self._models) > 1:
                logger.warning(
                    f"[llamacpp] modelo '{model}' fora de LLAMACPP_MODELS — usando o "
                    f"primeiro configurado. Ajuste LLAMACPP_CHAT_MODEL/HEAVY_MODEL se não for o desejado.")
            return next(iter(self._models.values()))
        return model  # sem mapa: deixa o llama.cpp validar (erro claro se não existir)

    def _get(self, model: str):
        """Devolve (llm, lock) do modelo. Carga protegida por _load_lock (evita
        carregar o mesmo GGUF duas vezes numa corrida de warmup+1ª requisição)."""
        path = self._resolve_path(model)
        if path not in self._loaded:
            with self._load_lock:
                if path not in self._loaded:            # dupla checagem sob o lock
                    from llama_cpp import Llama  # import preguiçoso
                    if not os.path.exists(path):
                        raise FileNotFoundError(
                            f"GGUF não encontrado: {path}. Baixe um modelo (Hugging Face) e "
                            f"aponte LLAMACPP_MODELS para ele.")
                    logger.info(f"[llamacpp] carregando {path} (ctx={self._ctx}, gpu_layers={self._gpu_layers})…")
                    self._locks[path] = threading.Lock()
                    self._loaded[path] = Llama(
                        model_path=path, n_ctx=self._ctx, n_threads=self._threads,
                        n_gpu_layers=self._gpu_layers, verbose=False,
                    )
        return self._loaded[path], self._locks[path]

    def _penalty_for(self, model: str) -> float:
        """Penalidade de repetição deste modelo (E19): mapa explícito primeiro,
        depois heurística de tamanho pelo nome (1.5b/0.5b são os que degeneram),
        senão o padrão global."""
        if model in self._repeat_penalty_map:
            return self._repeat_penalty_map[model]
        nome = (model or "").lower()
        if any(t in nome for t in ("0.5b", "1.5b", "1b-", "nano", "tiny")):
            return max(self._repeat_penalty, 1.3)
        return self._repeat_penalty

    def _opts(self, options, model: str = ""):
        options = options or {}
        out = {}
        if "temperature" in options:
            out["temperature"] = options["temperature"]
        # Teto de tokens SEMPRE presente: o chamador manda num_predict; senão cai no
        # teto padrão. NENHUMA geração roda sem limite — com max_tokens=None o
        # llama.cpp gera até encher o contexto e um modelo pequeno degenera em loop,
        # segurando o lock por minutos e derrubando chat + estudo juntos.
        out["max_tokens"] = int(options.get("num_predict") or self._max_tokens)
        # Penalidade de repetição POR MODELO: o pequeno repete trecho inteiro
        # ("gcloud components install" ×132) e precisa de 1.3; o grande escreve
        # código/JSON e é castigado por isso (E19). O chamador ainda manda.
        out["repeat_penalty"] = float(options.get("repeat_penalty")
                                      or self._penalty_for(model))
        if "top_p" in options:
            out["top_p"] = options["top_p"]
        return out

    def complete(self, model, messages, options=None, keep_alive=None) -> str:
        llm, lock = self._get(model)
        with lock:   # serializa: uma geração por vez neste modelo (thread-safety)
            resp = llm.create_chat_completion(messages=messages, stream=False,
                                              **self._opts(options, model))
        return resp["choices"][0]["message"]["content"]

    def stream(self, model, messages, options=None, keep_alive=None, cancel=None):
        llm, lock = self._get(model)
        # Segura o lock durante TODA a geração em streaming — só um gerador ativo
        # por modelo (evita o crash de acesso concorrente ao mesmo contexto).
        with lock:
            for chunk in llm.create_chat_completion(messages=messages, stream=True,
                                                    **self._opts(options, model)):
                # Aborto cooperativo: quando o cliente clica "parar" (fetch abortado →
                # conexão fecha), o consumidor sinaliza `cancel` e nós paramos AQUI —
                # senão a thread seguiria gerando até o teto, segurando o lock e
                # travando o estudo (mesmo 1.5B). Sair do laço libera o `with lock`.
                if cancel is not None and cancel.is_set():
                    break
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


def backend_status() -> dict:
    """Estado do motor de LLM selecionado, para o 'cortar o cordão do Ollama':
    diz se o motor PRÓPRIO (llama.cpp) está de fato pronto para assumir — lib
    instalada + modelo GGUF apontado e presente — ou o que falta. Determinístico
    e barato (não carrega modelo): dá para checar antes de virar a chave.

    Retorna {backend, sovereign, ready, detail}.
    """
    backend = os.getenv("LLM_BACKEND", "ollama").strip().lower()
    if backend != "llamacpp":
        return {"backend": "ollama", "sovereign": False, "ready": True,
                "detail": "usando Ollama — troque com LLM_BACKEND=llamacpp para o motor próprio"}
    import importlib.util
    lib = importlib.util.find_spec("llama_cpp") is not None
    models = LlamaCppProvider._parse_model_map(os.getenv("LLAMACPP_MODELS", ""))
    paths_ok = bool(models) and all(os.path.exists(p) for p in models.values())
    missing: list[str] = []
    if not lib:
        missing.append("instale llama-cpp-python")
    if not models:
        missing.append("defina LLAMACPP_MODELS=nome=caminho.gguf")
    elif not paths_ok:
        missing.append("arquivo .gguf apontado não existe")
    ready = lib and paths_ok

    # Aceleração por iGPU/GPU (M26): honesto sobre o que o BUILD instalado suporta.
    # `LLAMACPP_GPU_LAYERS>0` só faz efeito se a lib foi compilada com um backend
    # de GPU (ex.: Vulkan p/ a Vega integrada). Sem isso, offload é silenciosamente
    # ignorado — então checamos de verdade via a API do próprio llama.cpp.
    layers = int(os.getenv("LLAMACPP_GPU_LAYERS", "0"))
    gpu: dict = {"layers_configured": layers, "offload_supported": None}
    if lib:
        try:
            from llama_cpp import llama_supports_gpu_offload
            gpu["offload_supported"] = bool(llama_supports_gpu_offload())
        except Exception:
            gpu["offload_supported"] = None  # desconhecido nesta versão da lib
    if layers > 0 and gpu["offload_supported"] is False:
        gpu["note"] = ("gpu_layers>0 mas o build não tem GPU — recompile com Vulkan "
                       "(ver docs/VULKAN_BUILD.md) ou volte gpu_layers=0")
    elif gpu["offload_supported"] and layers > 0:
        gpu["note"] = f"offload ativo: {layers} camada(s) na GPU"

    return {"backend": "llamacpp", "sovereign": True, "ready": ready, "gpu": gpu,
            "detail": "motor próprio pronto (Ollama dispensável)" if ready
                      else "falta: " + "; ".join(missing)}
