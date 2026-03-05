# Deploying the backend to Linode

This guide walks you through deploying the Story TTS FastAPI backend (`server.py`) to a Linode (Akamai) VPS. The app is CPU/RAM-heavy due to PyTorch and ChatterboxTTS, so instance size matters.

---

## 1. Create a Linode instance

1. **Sign up / log in** at [linode.com](https://www.linode.com) (or [akamai.com/cloud/linode](https://www.akamai.com/cloud/linode)).
2. **Create a Linode**:
   - **Image:** Ubuntu 22.04 LTS (or 24.04).
   - **Region:** Pick one close to your users.
   - **Plan:** **Recommended: 4GB RAM or higher** (e.g. “Dedicated 4GB” or “Shared 8GB”). The TTS model loads into memory; 2GB is usually too tight.
   - **Root password:** Set a strong password (you’ll use it for first login or Lish).
3. **Boot** the Linode and note its **IP address**.

---

## 2. First login and basic security

From your Mac (replace `YOUR_LINODE_IP`):

```bash
ssh root@YOUR_LINODE_IP
```

Optional but recommended:

- **Create a non-root user** and use it for app and deploys:
  ```bash
  adduser deploy
  usermod -aG sudo deploy
  su - deploy
  ```
- **SSH key auth:** Copy your public key to the server so you can log in without password:
  ```bash
  # On your Mac
  ssh-copy-id deploy@YOUR_LINODE_IP
  ```
- **Disable root SSH** (after key auth works):
  ```bash
  sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
  sudo systemctl restart sshd
  ```
- **Firewall:** Allow SSH and HTTP/HTTPS only:
  ```bash
  sudo ufw allow 22
  sudo ufw allow 80
  sudo ufw allow 443
  sudo ufw enable
  ```

Use `deploy` (or your chosen user) for the rest of the steps.

---

## 3. Install dependencies on the server

Still on the Linode (as `deploy` or root):

```bash
# System packages
sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip build-essential git

# Install uv (recommended for fast, reproducible installs)
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"  # or log out and back in
```

---

## 4. Deploy the app

**Option A — Clone from Git (recommended)**

```bash
sudo mkdir -p /var/www/story-tts
sudo chown $USER:$USER /var/www/story-tts
cd /var/www/story-tts
git clone https://github.com/YOUR_ORG/Project_69.git .
# or: git clone YOUR_REPO_URL .
```

**Option B — Copy files with `rsync` (from your Mac)**

```bash
# From your Mac, in the project root
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
  ./ deploy@YOUR_LINODE_IP:/var/www/story-tts/
```

Then on the server:

```bash
cd /var/www/story-tts
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .   # or: uv sync (if you use a lock file)
# Or install from pyproject.toml explicitly:
# uv pip install fastapi uvicorn sse-starlette python-dotenv openai torch torchaudio chatterbox-tts numpy ml-dtypes
```

---

## 5. Environment and secrets

On the server:

```bash
cd /var/www/story-tts
nano .env
```

Add (no quotes around the value if it’s a single line):

```env
GROK_API_KEY=your_xai_api_key_here
```

Upload your voice clone file (from your Mac):

```bash
scp voice-1.wav deploy@YOUR_LINODE_IP:/var/www/story-tts/
```

Ensure `story_tts.py` (or config) points to `voice-1.wav` and that `params.md` is present. Restrict permissions:

```bash
chmod 600 .env
```

---

## 6. Run the backend with systemd

So the server restarts on reboot and stays up:

```bash
sudo nano /etc/systemd/system/story-tts.service
```

Paste (adjust user/path if you used a different app user or path):

```ini
[Unit]
Description=Story TTS FastAPI backend
After=network.target

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/var/www/story-tts
Environment="PATH=/var/www/story-tts/.venv/bin"
ExecStart=/var/www/story-tts/.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable story-tts
sudo systemctl start story-tts
sudo systemctl status story-tts
```

The app listens on `127.0.0.1:8000` so only Nginx (next step) talks to it.

---

## 7. Reverse proxy with Nginx (HTTPS and /api)

Install Nginx and (optionally) Certbot for TLS:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

Create a site config:

```bash
sudo nano /etc/nginx/sites-available/story-tts
```

Example (replace `YOUR_DOMAIN` with your domain or use the Linode IP and skip SSL for a first test):

```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN;   # or YOUR_LINODE_IP for testing

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # If you build and serve the frontend from this server:
    # root /var/www/story-tts/frontend/dist;
    # index index.html;
    # location / { try_files $uri $uri/ /index.html; }
}
```

Enable and test:

```bash
sudo ln -s /etc/nginx/sites-available/story-tts /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Get a free TLS certificate (only if you have a domain pointing to this IP):

```bash
sudo certbot --nginx -d YOUR_DOMAIN
```

Then test from your Mac:

```bash
curl http://YOUR_LINODE_IP/api/voices
# Or with domain:
curl https://YOUR_DOMAIN/api/voices
```

---

## 8. Frontend (optional)

If the frontend runs on the same server:

1. On your Mac, build it: `cd frontend && npm run build`.
2. Copy `frontend/dist` to the server (e.g. `/var/www/story-tts/frontend/dist`).
3. In the Nginx config above, uncomment the `root` / `location /` block and set `root` to that path.
4. Point the frontend’s API base to `https://YOUR_DOMAIN` (or set a relative `/api` so the same origin is used).

If the frontend is on another host (e.g. Vercel), set its API URL to `https://YOUR_DOMAIN` and ensure CORS allows that origin in `server.py` if needed.

---

## 9. Checklist

- [ ] Linode created (4GB+ RAM recommended)
- [ ] SSH access (key-based) and firewall (22, 80, 443)
- [ ] Python 3.12, uv, app code in `/var/www/story-tts`
- [ ] `.env` with `GROK_API_KEY`, `voice-1.wav` and `params.md` in place
- [ ] systemd service `story-tts` enabled and running
- [ ] Nginx proxying `/api/` to `127.0.0.1:8000`
- [ ] TLS with Certbot if you use a domain
- [ ] `GET /api/voices` and `POST /api/generate` tested

---

## 10. Useful commands

```bash
# Logs
sudo journalctl -u story-tts -f

# Restart backend
sudo systemctl restart story-tts

# Update app (after git pull or rsync)
cd /var/www/story-tts && source .venv/bin/activate && uv pip install -e . && sudo systemctl restart story-tts
```

If you hit OOM (out of memory) during model load, upgrade to a larger Linode plan or add swap (temporary mitigation):

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

*Guide tailored for Project 69 — Story TTS backend (FastAPI + ChatterboxTTS) on Linode.*
