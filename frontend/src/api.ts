export interface SSEEvent {
  type: "story" | "progress" | "chunk" | "done" | "error" | "aborted";
  text?: string;
  story_id?: string; // present when type === "story"
  url?: string;      // present when type === "chunk"
  index?: number;    // present when type === "chunk"
  kept?: boolean;    // true for pre-existing chunks replayed during edit
  chunks_completed?: number; // present when type === "aborted"
}

/**
 * POST /api/edit and parse the SSE response as an async generator.
 */
export async function* streamEdit(
  storyId: string,
  instruction: string,
  fromChunkIndex?: number,
): AsyncGenerator<SSEEvent> {
  const body: Record<string, unknown> = { story_id: storyId, instruction };
  if (fromChunkIndex != null) body.from_chunk_index = fromChunkIndex;

  const response = await fetch("/api/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok || !response.body) {
    const err = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail ?? `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop()!;
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as SSEEvent;
        } catch {
          // skip malformed lines
        }
      }
    }
  }
}

export async function fetchVoices(): Promise<string[]> {
  const res = await fetch("/api/voices");
  if (!res.ok) return ["alyssa"];
  const data = await res.json();
  return data.voices as string[];
}

/**
 * Signal the server to abort the current generation/edit after the current chunk.
 */
export async function abortGeneration(): Promise<void> {
  await fetch("/api/abort", { method: "POST" });
}

/**
 * Queue an event hint to be woven into the next generated paragraph.
 */
export async function injectEvent(event: string): Promise<void> {
  await fetch("/api/inject", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  });
}

/**
 * Set a persistent course change for all remaining paragraphs.
 */
export async function redirectStory(event: string): Promise<void> {
  await fetch("/api/redirect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  });
}

export async function* streamGenerate(
  time: string,
  fantasy: string,
  voice: string
): AsyncGenerator<SSEEvent> {
  const response = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ time, fantasy, voice }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Server error: HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop()!; // keep incomplete last line

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as SSEEvent;
        } catch {
          // skip malformed lines
        }
      }
    }
  }
}
