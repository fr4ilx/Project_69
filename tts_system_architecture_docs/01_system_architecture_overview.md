# System Architecture Overview

## Goal
Design a scalable system for generating long-form adaptive audio (stories, audiobooks, meditation sessions)
using self‑hosted TTS models such as Orpheus TTS or Chatterbox.

The architecture prioritizes:

- low GPU cost
- streaming playback
- chunk-based synthesis
- editable narrative pipelines
- high throughput on minimal hardware

## High Level Architecture

Client
↓
API Gateway
↓
Story Engine
↓
Chunk Manager
↓
Queue (Redis)
↓
GPU TTS Workers
↓
Audio Stitcher
↓
Streaming Server
↓
Client Playback

## Core Principles

### Chunk-first processing
Long stories must be broken into chunks (30–120 seconds).

### Streaming delivery
Audio should begin playing within seconds.

### Deferred generation
Only generate what is necessary immediately.

### GPU efficiency
Maximize GPU utilization through batching and parallel chunk generation.

## System Layers

### Application Layer
Handles:

- story generation
- meditation script creation
- template processing
- interactive editing

### Audio Synthesis Layer
Handles:

- TTS generation
- voice embedding reuse
- chunk audio rendering

### Media Layer
Handles:

- audio stitching
- ambience mixing
- streaming delivery

## Scalability Strategy

Scale primarily through:

- more GPU workers
- larger chunk batching
- distributed queue workers

A single RTX 4090 class GPU can handle thousands of narrations per day.