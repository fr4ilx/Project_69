# Backend for Story TTS — RunPod / generic container (CUDA build)
# Expose port 8000; set GROK_API_KEY and HF_TOKEN via env or /data/.env at run time.
# Validated for RunPod GPU pods (Ubuntu, amd64, RTX 4000 Ada): CUDA 12.4 + cuDNN runtime;
# PyTorch cu124 wheels so torch.cuda.is_available() is True when GPU is exposed.

FROM --platform=linux/amd64 nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

WORKDIR /app

# Python 3.12 and build deps (noninteractive so tzdata doesn't prompt)
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    curl \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12
ENV PATH="/usr/local/bin:$PATH"
RUN ln -sf /usr/bin/python3.12 /usr/local/bin/python && ln -sf /usr/bin/python3.12 /usr/local/bin/python3

# PyTorch + torchaudio with CUDA 12.4
RUN python3.12 -m pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# numpy>=1.26 first (chatterbox pins numpy<1.26 but we need 1.26+ for Python 3.12)
RUN python3.12 -m pip install --no-cache-dir "numpy>=1.26.0"

# Chatterbox without deps so it doesn't pull numpy<1.26; we already have numpy
RUN python3.12 -m pip install --no-cache-dir --no-deps "git+https://github.com/resemble-ai/chatterbox.git"

# App code and install editable (--no-deps to avoid re-resolving chatterbox), then rest of deps
COPY pyproject.toml README.md story_tts.py server.py params.md ./
RUN python3.12 -m pip install --no-cache-dir -e . --no-deps \
    && python3.12 -m pip install --no-cache-dir \
    "fastapi>=0.135.1" \
    "openai>=2.24.0" \
    "python-dotenv>=1.2.2" \
    "sse-starlette>=3.3.2" \
    "uvicorn>=0.41.0" \
    "ml-dtypes>=0.3.0"

# voices dir; entrypoint copies /data/.env and /data/voice-1.wav into /app if mounted
RUN mkdir -p voices
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["sh", "-c", "exec python3.12 -m uvicorn server:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]

EXPOSE 8000
ENV HOST=0.0.0.0
ENV PORT=8000
