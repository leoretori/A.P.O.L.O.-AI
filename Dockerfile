FROM python:3.12-slim

WORKDIR /app

# ── Dependências do sistema ───────────────────────────────────────────────────
# curl: healthcheck interno
# build-essential: compilar wheels C (chromadb, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# ── Dependências Python ───────────────────────────────────────────────────────
# Copia só o requirements.txt primeiro — aproveita cache do Docker quando
# apenas o código muda mas as dependências não.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código da aplicação ───────────────────────────────────────────────────────
COPY . .

# Remove artefatos de desenvolvimento que não devem entrar na imagem
RUN rm -rf .git __pycache__ .pytest_cache apolo-vscode 2>/dev/null || true

# ── Diretórios de dados ───────────────────────────────────────────────────────
# Criados aqui como fallback; o docker-compose sobrepõe com volumes do host.
RUN mkdir -p data/examples data/chroma_db workspace

# ── Usuário não-root ──────────────────────────────────────────────────────────
RUN useradd -m apolo && chown -R apolo:apolo /app
USER apolo

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health > /dev/null || exit 1

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
