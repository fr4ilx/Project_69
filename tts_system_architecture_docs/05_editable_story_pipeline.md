# Editable Story Pipeline

## Goal

Allow stories or meditations to change while generation is in progress.

## Concept

Chunks not yet rendered remain editable.

Example timeline:

chunk 1 → rendered
chunk 2 → rendered
chunk 3 → rendering
chunk 4 → pending
chunk 5 → pending

User edits story.

System invalidates:

chunk 4
chunk 5

New chunks generated.

## Workflow

Edit request arrives

system checks which chunks finished

future chunks invalidated

new chunks scheduled

## Benefits

Interactive storytelling
adaptive meditation scripts
branching narratives

## Example Use Case

User prompt:

"Instead of meeting a dragon, discover a hidden temple."

Future narration updates automatically.

## Implementation Notes

Store chunk status in database.

Allow state transitions:

pending → invalidated
invalidated → regenerated

Workers must ignore invalidated chunks.