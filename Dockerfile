FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código da aplicação
COPY . .

# Diretórios de dados
RUN mkdir -p data/examples data/chroma_db

# Usuário não-root
RUN useradd -m apolo && chown -R apolo:apolo /app
USER apolo

EXPOSE 8000

# Servidor web por padrão (use --entrypoint python main.py para CLI)
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
