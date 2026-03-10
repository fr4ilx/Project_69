# Deploying the backend to RunPod (Docker)

This guide deploys the Story TTS FastAPI backend to [RunPod](https://runpod.io) using the project’s **Docker image**. You can run on a **GPU Pod** (faster TTS) or **CPU Pod** (cheaper; fine for MVP).

---

## 1. Prerequisites

- [RunPod](https://runpod.io) account and payment method.
- [Docker](https://docs.docker.com/get-docker/) on your Mac (to build the image).
- [Docker Hub](https://hub.docker.com) account (or another registry) to push the image.
- Your repo cloned locally (e.g. `/Users/syeo/Documents/Project_69`).

---

## 2. Build and push the Docker image

RunPod needs a **linux/amd64** image. On Apple Silicon you must build for that platform explicitly or RunPod will fail with “no matching manifest for linux/amd64”.

On your **Mac**, in the project root:

```bash
cd /Users/syeo/Documents/Project_69
docker login

# Build for amd64 and push in one step (required for RunPod)
docker buildx build --platform linux/amd64 -t YOUR_DOCKERHUB_USER/story-tts:latest --push .
```

Or use the script (default tag `fr4ilx/story-tts:latest`):

```bash
chmod +x scripts/docker-build-push.sh
./scripts/docker-build-push.sh
# Or: ./scripts/docker-build-push.sh youruser/story-tts:latest
```

Use your actual Docker Hub username. The first build can take several minutes (PyTorch, chatterbox, etc.).

---

## 3. Create a RunPod Pod with your image

1. In RunPod go to **Pods** → **Deploy**.
2. **GPU or CPU**: Pick a GPU template for faster TTS, or CPU-only for cheaper MVP.
3. **Container Image**: Choose **Custom Image** and enter:
   ```text
   YOUR_DOCKERHUB_USER/story-tts:latest
   ```
   (Use the same name you pushed, e.g. `syeo/story-tts:latest`.)
4. **Container Disk**: 30–50 GB.
5. **Expose HTTP Ports**: Add **8000** so RunPod gives you `https://<POD_ID>-8000.proxy.runpod.net`.
6. **Environment Variables**: Add at least:
   - `GROK_API_KEY` = your xAI API key  
   - `HF_TOKEN` = your HuggingFace token (for ChatterboxTurbo model download)
7. **Volume (recommended)**:
   - Create or attach a **Network Volume**.
   - Mount it at **`/data`** in the Pod.
   - After the Pod starts, SSH in and put your files on the volume:
     - `/data/.env` (with `GROK_API_KEY`, `HF_TOKEN`, etc.)
     - `/data/voice-1.wav` (or put pre-baked voices in `/data/voices/`).
   The container’s entrypoint copies `/data/.env` and `/data/voice-1.wav` into `/app` at startup, so the app will see them.
8. **SSH key**: Add your public key so you can SSH in to place files on the volume (first time).
9. Deploy and note the Pod **ID** and the HTTP URL (e.g. `https://xxxxx-8000.proxy.runpod.net`).

---

## 4. Put `.env` and `voice-1.wav` on the volume (first time)

If you mounted a volume at `/data`, SSH into the Pod and create the files there:

```bash
# From your Mac: use the SSH command RunPod gives you, e.g.:
# ssh 9tg7dpsccdg1e4-64410d4a@ssh.runpod.io -i ~/.ssh/id_ed25519
```

On the Pod:

```bash
# Install nano if you need an editor
apt update && apt install -y nano

# Create .env on the volume (so the entrypoint copies it into /app)
nano /data/.env
# Paste GROK_API_KEY=... and HF_TOKEN=...
```

From your **Mac**, upload the voice file (use the SSH user/host from RunPod):

```bash
scp -i ~/.ssh/id_ed25519 voice-1.wav 9tg7dpsccdg1e4-64410d4a@ssh.runpod.io:/data/
```

If you use pre-baked voices, put `voices/` contents in `/data/voices/` on the Pod instead.

**Restart the Pod** (or the container) so the entrypoint runs again and copies the new files into `/app`. Or start the Pod only after `/data` is populated.

---

## 5. Access the API

- **HTTP (recommended):**  
  `https://<POD_ID>-8000.proxy.runpod.net`  
  e.g. `https://xxxxx-8000.proxy.runpod.net/api/voices` or `/docs`.
- **TCP:** If you exposed port 8000 via TCP, use `http://<POD_IP>:8000`.

---

## 6. How the container works

- **Image**: Built from the repo’s `Dockerfile` (Python 3.12, deps from `pyproject.toml`, app code in `/app`).
- **Entrypoint**: `docker-entrypoint.sh` runs at start. It copies:
  - `/data/.env` → `/app/.env`
  - `/data/voice-1.wav` → `/app/voice-1.wav`
  - `/data/voices/*` → `/app/voices/`  
  if they exist. Then it starts uvicorn.
- **Secrets**: Not in the image. Set `GROK_API_KEY` and `HF_TOKEN` in RunPod’s **Environment Variables**, and/or put `.env` on the `/data` volume.
- **Port**: Server listens on `0.0.0.0:8000` (or `PORT` env). RunPod’s “Expose HTTP Port 8000” maps it to the proxy URL.

---

## Checklist

- [ ] Image built and pushed to Docker Hub (`YOUR_DOCKERHUB_USER/story-tts:latest`).
- [ ] RunPod Pod created with **Custom Image** = that image.
- [ ] **Expose HTTP Port** 8000.
- [ ] Env vars set: `GROK_API_KEY`, `HF_TOKEN`.
- [ ] Volume mounted at `/data` with `.env` and `voice-1.wav` (or `voices/`) if needed.
- [ ] `GET /api/voices` and `POST /api/generate` work at the RunPod URL.

---

## Stopping the Pod

RunPod bills while the Pod is running. **Stop** the Pod from the console when not in use. Data on the container disk is lost; use a **Network Volume** mounted at `/data` to keep `.env` and voice files across restarts.

---

## Alternative: SSH + venv (no Docker)

If you prefer to run the app directly on a RunPod template (e.g. RunPod Pytorch) without building an image:

1. Create a Pod from a **RunPod template** (not Custom Image).
2. SSH in, install Python 3.12, clone the repo, create a venv, `uv pip install -e .`.
3. Create `.env` and put `voice-1.wav` in the app directory.
4. Run `python -m uvicorn server:app --host 0.0.0.0 --port 8000` (or use systemd).

See the previous version of this doc or the Linode-style steps for the exact commands.

---

*Guide for Project 69 — Story TTS backend on RunPod (Docker).*
