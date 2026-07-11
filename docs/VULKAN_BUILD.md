# Acelerar o motor próprio com a iGPU (Vulkan) — M26

O motor soberano (`llama.cpp` via `llama-cpp-python`) hoje roda **100% no CPU**. A
Ryzen 5 4600G tem uma **iGPU Vega** integrada que o `llama.cpp` sabe usar via
**Vulkan**. Este guia recompila a lib com Vulkan e liga o *offload* de camadas
para a iGPU.

> **Expectativa honesta.** A Vega é integrada e **divide a banda de RAM com o
> CPU** — não é uma GPU dedicada. O ganho num modelo 7B é **modesto** (não
> multiplica como uma RTX). Vale medir antes/depois. O caminho de escala de
> verdade continua sendo GPU dedicada; isto é o quanto dá para extrair do que
> já temos, sem gastar nada.

## 1. Pré-requisitos (uma vez)

- **Vulkan SDK** (LunarG): https://vulkan.lunarg.com/sdk/home#windows — instala o
  runtime + headers. Confirme no terminal:
  ```powershell
  vulkaninfo --summary   # deve listar a "AMD Radeon Vega" como device
  ```
- O mesmo toolchain que já usamos para o build AVX2: **Visual Studio Build Tools**
  (vcvars64), **CMake**, **Ninja**. (Se você já compilou o motor AVX2, tem tudo.)

## 2. Recompilar `llama-cpp-python` com Vulkan

Num **"x64 Native Tools Command Prompt for VS"** (para o `vcvars64` estar ativo):

```bat
set TMP=C:\t
set TEMP=C:\t
set PYTHONIOENCODING=utf-8
set CMAKE_GENERATOR=Ninja
:: Vulkan + AVX2 (mantém o fix do crash 0xc000001d em Zen2: SEM AVX-512)
set CMAKE_ARGS=-DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DGGML_AVX512=OFF

pip install --force-reinstall --no-binary :all: llama-cpp-python
```

> `TMP=C:\t` evita o erro de MAX_PATH (caminhos > 260 chars no build).

## 3. Ligar o offload

No `.env` (pasta principal), suba as camadas na iGPU. A Vega tem VRAM
compartilhada limitada — **comece baixo e vá medindo**:

```env
LLAMACPP_GPU_LAYERS=8      # experimente 8 → 16 → mais; se travar/faltar RAM, baixe
```

Reinicie o app.

## 4. Verificar (sem adivinhação)

O painel **Saúde do Sistema → Motor de inferência → Aceleração** mostra o estado
real, lido da própria API do `llama.cpp` (`llama_supports_gpu_offload()`):

- `iGPU/Vulkan · N camada(s)` → **funcionando**.
- `build sem GPU — recompile com Vulkan` → o passo 2 não pegou; refaça no prompt
  com `vcvars64` ativo e o Vulkan SDK instalado.
- `CPU (build sem GPU)` → build padrão, offload desligado.

Ou via API:
```powershell
python -c "from src.providers import backend_status; import json; print(json.dumps(backend_status()['gpu'], ensure_ascii=False))"
```

## 5. Medir o ganho (antes de comemorar)

Cronometize uma geração fixa nas duas versões (CPU puro vs. Vulkan) e compare
tokens/s. Guarde o número — é a métrica do M26. Se o ganho for pequeno (provável
para 7B numa iGPU), tudo bem: o motor **funciona** no CPU e a escala real virá com
GPU dedicada. O ganho garantido do M26 está no **Nano** (presets `medium`/`large`)
e no **roteamento** (M27), não na iGPU.

## Reverter

Volte para o build só-CPU (rápido, sem compilar):
```powershell
pip install --force-reinstall --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu llama-cpp-python
```
E `LLAMACPP_GPU_LAYERS=0` no `.env`.
