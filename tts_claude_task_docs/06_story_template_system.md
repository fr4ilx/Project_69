# Story / Meditation Template System - Claude Code Ready

## Template Structure
- Templates are JSON objects describing segment order and placeholders
- Example:
```json
{
 "template_id": "fantasy_adventure",
 "segments": [
   {"type": "intro", "placeholder": "{intro_text}"},
   {"type": "scene", "placeholder": "{scene_1_text}"},
   {"type": "scene", "placeholder": "{scene_2_text}"},
   {"type": "climax", "placeholder": "{climax_text}"},
   {"type": "ending", "placeholder": "{ending_text}"}
 ]
}
```

## Features
- Define default structure for stories or meditations
- Supports branching narratives
- Supports mid-generation editing (chunks not yet rendered can be changed)
- Can include metadata for emotion, voice style, pace

## Editable Pipeline
1. User selects template
2. Story Engine fills placeholders with generated text
3. Chunk Manager splits segments
4. GPU Workers synthesize audio
5. Unrendered segments can be updated and re-queued