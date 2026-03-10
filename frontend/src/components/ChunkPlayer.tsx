import { forwardRef, useImperativeHandle, useRef } from "react";

export interface ChunkPlayerHandle {
  /** Call this inside a user gesture (click handler) to unlock the AudioContext. */
  prime(): void;
  addChunk(url: string): void;
  getAnalyser(): AnalyserNode | null;
  /** Returns the 0-based index of the chunk currently playing (or last played). */
  getCurrentChunkIndex(): number;
  reset(): void;
  /** Clear queue and stop sources but keep AudioContext alive (for edit flow so new chunks can play). */
  resetForEdit(): void;
  /** Stop and discard all sources from `fromIndex` onward, keeping earlier ones. */
  resetFromIndex(fromIndex: number): void;
}

/**
 * Invisible audio engine. Fetches and schedules WAV chunks for gapless
 * playback via Web Audio API. Exposes an AnalyserNode for the orb.
 */
const ChunkPlayer = forwardRef<ChunkPlayerHandle>((_, ref) => {
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const nextStartTimeRef = useRef<number>(0);
  const queueRef = useRef<string[]>([]);
  const processingRef = useRef(false);
  const sourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const currentChunkIndexRef = useRef<number>(-1);
  // Track scheduled start times so we can figure out which chunk is playing
  const chunkStartTimesRef = useRef<number[]>([]);

  // Lazily create the AudioContext + AnalyserNode on first use.
  const getOrCreateCtx = (): AudioContext => {
    if (!audioCtxRef.current) {
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.3;
      analyser.minDecibels = -90;
      analyser.maxDecibels = -10;
      analyser.connect(ctx.destination);

      audioCtxRef.current = ctx;
      analyserRef.current = analyser;
      nextStartTimeRef.current = ctx.currentTime;
    }
    return audioCtxRef.current;
  };

  const processQueue = async () => {
    if (processingRef.current) return;
    processingRef.current = true;

    while (queueRef.current.length > 0) {
      const url = queueRef.current.shift()!;
      try {
        const ctx = getOrCreateCtx();
        if (ctx.state === "suspended") await ctx.resume();

        const res = await fetch(url);
        const buf = await res.arrayBuffer();
        const audioBuffer = await ctx.decodeAudioData(buf);

        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(analyserRef.current!);
        sourcesRef.current.push(source);

        // Schedule: start at nextStartTime, but never in the past
        const startAt = Math.max(nextStartTimeRef.current, ctx.currentTime + 0.05);
        source.start(startAt);
        chunkStartTimesRef.current.push(startAt);

        // Track which chunk is playing via onended
        const chunkIdx = sourcesRef.current.length - 1;
        source.onended = () => {
          // Only advance if this is the latest chunk to finish
          if (chunkIdx >= currentChunkIndexRef.current) {
            currentChunkIndexRef.current = chunkIdx;
          }
        };

        nextStartTimeRef.current = startAt + audioBuffer.duration;
      } catch (err) {
        console.warn("ChunkPlayer: failed to load chunk", url, err);
      }
    }

    processingRef.current = false;
  };

  useImperativeHandle(ref, () => ({
    prime() {
      const ctx = getOrCreateCtx();
      ctx.resume();
    },

    addChunk(url: string) {
      queueRef.current.push(url);
      processQueue();
    },

    getAnalyser() {
      return analyserRef.current;
    },

    getCurrentChunkIndex() {
      // Best estimate: check scheduled start times against current time
      const ctx = audioCtxRef.current;
      if (!ctx) return -1;
      const now = ctx.currentTime;
      let playing = -1;
      for (let i = 0; i < chunkStartTimesRef.current.length; i++) {
        if (chunkStartTimesRef.current[i] <= now) playing = i;
        else break;
      }
      return Math.max(playing, currentChunkIndexRef.current);
    },

    reset() {
      // Stop all playing sources
      for (const src of sourcesRef.current) {
        try { src.stop(); } catch { /* already stopped */ }
      }
      sourcesRef.current = [];
      queueRef.current = [];
      processingRef.current = false;
      currentChunkIndexRef.current = -1;
      chunkStartTimesRef.current = [];

      // Close and nullify the context so a fresh one is created next session
      audioCtxRef.current?.close();
      audioCtxRef.current = null;
      analyserRef.current = null;
      nextStartTimeRef.current = 0;
    },

    /** For edit: clear queue and stop sources but keep context so addChunk() can play without new user gesture. */
    resetForEdit() {
      for (const src of sourcesRef.current) {
        try { src.stop(); } catch { /* already stopped */ }
      }
      sourcesRef.current = [];
      queueRef.current = [];
      processingRef.current = false;
      currentChunkIndexRef.current = -1;
      chunkStartTimesRef.current = [];
      if (audioCtxRef.current) {
        nextStartTimeRef.current = audioCtxRef.current.currentTime + 0.05;
      } else {
        nextStartTimeRef.current = 0;
      }
    },

    resetFromIndex(fromIndex: number) {
      // Stop and remove sources from fromIndex onward, keep earlier ones playing
      for (let i = fromIndex; i < sourcesRef.current.length; i++) {
        try { sourcesRef.current[i].stop(); } catch { /* already stopped */ }
      }
      sourcesRef.current = sourcesRef.current.slice(0, fromIndex);
      chunkStartTimesRef.current = chunkStartTimesRef.current.slice(0, fromIndex);
      queueRef.current = [];
      processingRef.current = false;

      // Recalculate nextStartTime from the last kept source
      if (fromIndex > 0 && audioCtxRef.current) {
        // We don't store durations, so set nextStartTime to "now" —
        // new chunks will schedule from the current playback position
        const ctx = audioCtxRef.current;
        nextStartTimeRef.current = Math.max(
          nextStartTimeRef.current,
          ctx.currentTime + 0.05,
        );
      } else if (audioCtxRef.current) {
        nextStartTimeRef.current = audioCtxRef.current.currentTime + 0.05;
      }
    },
  }));

  return null;
});

ChunkPlayer.displayName = "ChunkPlayer";
export default ChunkPlayer;
