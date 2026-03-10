#!/bin/sh
# Copy /data/.env and /data/voice-1.wav (or /data/voices) into /app if present.
# RunPod: mount a volume at /data with these files, then the container will use them.
set -e
if [ -f /data/.env ]; then cp /data/.env /app/.env; fi
if [ -f /data/voice-1.wav ]; then cp /data/voice-1.wav /app/voice-1.wav; fi
if [ -d /data/voices ] && [ -n "$(ls -A /data/voices 2>/dev/null)" ]; then cp -r /data/voices/* /app/voices/ 2>/dev/null || true; fi
exec "$@"
