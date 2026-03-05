export interface SSEEvent {
  type: "story" | "progress" | "done" | "error";
  text?: string;
}

/**
 * POST /api/generate and parse the SSE response as an async generator.
 * Yields SSEEvent objects as they arrive from the server.
 */
export async function fetchVoices(): Promise<string[]> {
  const res = await fetch("/api/voices");
  if (!res.ok) return ["alyssa"];
  const data = await res.json();
  return data.voices as string[];
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
