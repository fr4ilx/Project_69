# Deployment Architecture

## Core Services

API Server
Story Engine
Queue Server
GPU Worker Pool
Streaming Server
Object Storage

## Container Layout

Each component runs inside containers.

Example:

api-service
story-engine
tts-worker
audio-stitcher
stream-server
redis

## Recommended Stack

Python
FastAPI
Redis
PostgreSQL
PyTorch
FFmpeg
Docker

## GPU Worker Deployment

Workers connect to Redis queue.

Example worker cluster:

worker-1
worker-2
worker-3

Each worker:

loads TTS model
processes chunk jobs

## Storage Strategy

Use object storage for audio.

Example:

MinIO
S3 compatible storage

Audio file layout:

stories/
story_id/
chunk_01.wav
chunk_02.wav

## Horizontal Scaling

Scaling methods:

add more GPU workers
increase chunk batch size
add multiple queue partitions

## Monitoring

Track:

GPU utilization
queue depth
generation latency
failed chunk rate

Recommended tools:

Prometheus
Grafana