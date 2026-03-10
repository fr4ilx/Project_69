# GPU Throughput Model

## Objective

Estimate system capacity and cost efficiency.

Assumptions:

- average narration length: 30 minutes
- chunk size: 75 seconds
- chunks per story: ~24

## Example Hardware

RTX 4090
NVIDIA L4
A10

## Estimated Generation Speed

Typical TTS generation:

1 second audio ≈ 0.05–0.15 seconds compute

Thus:

75 second chunk ≈ 4–10 seconds generation

## Parallelization

GPU can batch multiple chunks.

Example:

batch size: 6

Total generation time per batch:

~8 seconds

Thus GPU throughput:

6 chunks per 8 seconds

≈ 45 chunks per minute

## Stories per Hour

Chunks per story: 24

Chunks per hour:

45 × 60 = 2700

Stories per hour:

2700 / 24 ≈ 112

## Stories per Day

112 × 24 ≈ 2688 stories

## Monthly Capacity

2688 × 30 ≈ 80,000 narrations

Realistic safe capacity:

10k – 30k long narrations per month per GPU

## Cost Model

Example GPU rental:

RTX 4090 server ≈ $220/month

Cost per story at 10k stories:

$220 / 10000 ≈ $0.022