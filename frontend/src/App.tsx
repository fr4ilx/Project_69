import { useState, useCallback, useRef, useEffect } from "react";
import ChatWindow from "./components/ChatWindow";
import QuickReplies from "./components/QuickReplies";
import AudioPlayer from "./components/AudioPlayer";
import ChunkPlayer, { type ChunkPlayerHandle } from "./components/ChunkPlayer";
import { VoicePoweredOrb } from "./components/VoicePoweredOrb";
import { streamGenerate, streamEdit, abortGeneration, fetchVoices } from "./api";
import landingBg from "./assets/landing-bg.png";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Stage = "landing" | "time" | "fantasy" | "voice" | "generating" | "done";

export interface Message {
  id: string;
  type: "bot-text" | "user-text" | "bot-progress";
  text?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TIME_OPTIONS = ["5 minutes", "15 minutes", "30 minutes", "An hour"];

const VIBE_CHIPS = [
  {
    label: "Delivery Driver",
    fill: "I want the delivery driver to come inside and use me however he wants—I've been waiting all day and I'll do anything to keep him there—",
  },
  {
    label: "Late-Night Office Encounter",
    fill: "I want a steamy, private moment in the office after everyone's gone—",
  },
  {
    label: "Passionate Car Ride",
    fill: "I want an impulsive, heated connection in the back of a car—",
  },
  {
    label: "Intense Close Moment",
    fill: "I want something deeply intimate and overwhelming, raw closeness—",
  },
  {
    label: "Desperate Pleading Scene",
    fill: "I want a scene where I'm completely surrendered, begging—",
  },
  {
    label: "Playful Discipline Fantasy",
    fill: "I want a teasing punishment that turns into something far more passionate—",
  },
  {
    label: "Deep Connection Fantasy",
    fill: "I want to be claimed completely, in the most primal way—",
  },
  {
    label: "Whispered Midnight Rendezvous",
    fill: "I want a hushed, forbidden encounter late at night—slow, deep, full of tension—",
  },
  {
    label: "Surrender & Devotion",
    fill: "I want to give myself over entirely—total devotion, complete surrender—",
  },
  {
    label: "Spontaneous Use Fantasy",
    fill: "I want to be taken whenever the urge strikes, anytime, anywhere—",
  },
  {
    label: "Overwhelming Full Experience",
    fill: "I want to be completely consumed in every way—",
  },
];

let _id = 0;
const nextId = () => String(++_id);

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const [stage, setStage] = useState<Stage>("landing");
  const [messages, setMessages] = useState<Message[]>([]);
  const [fantasy, setFantasy] = useState("");
  const [availableVoices, setAvailableVoices] = useState<string[]>([]);
  const [editInstruction, setEditInstruction] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [storyText, setStoryText] = useState<string | null>(null);
  const [storyId, setStoryId] = useState<string | null>(null);
  const [audioSrc, setAudioSrc] = useState<string | null>(null); // used for post-edit replay
  const [analyserNode, setAnalyserNode] = useState<AnalyserNode | null>(null);
  const [isPlaying, setIsPlaying] = useState(false); // true once first chunk arrives
  const isPlayingRef = useRef(false);
  const timeRef = useRef("");
  const fantasyRef = useRef("");
  const voiceRef = useRef("alyssa");
  const inputRef = useRef<HTMLInputElement>(null);
  const chunkPlayerRef = useRef<ChunkPlayerHandle>(null);
  // Track whether a generation SSE stream is currently active
  const generatingRef = useRef(false);

  useEffect(() => {
    fetchVoices().then(setAvailableVoices);
  }, []);

  const addMessage = useCallback((msg: Omit<Message, "id">): string => {
    const id = nextId();
    setMessages((prev) => [...prev, { ...msg, id }]);
    return id;
  }, []);

  const updateMessage = useCallback((id: string, text: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, text } : m))
    );
  }, []);

  // ── Stage: landing → time ─────────────────────────────────

  const handleStart = useCallback(() => {
    setMessages([{ id: nextId(), type: "bot-text", text: "How much time do you have?" }]);
    setStage("time");
  }, []);

  // ── Stage: time ───────────────────────────────────────────

  const handleTimeSelect = useCallback(
    (t: string) => {
      timeRef.current = t;
      addMessage({ type: "user-text", text: t });
      addMessage({ type: "bot-text", text: "Tell me your fantasy." });
      setStage("fantasy");
    },
    [addMessage]
  );

  // ── Stage: fantasy → voice ────────────────────────────────

  const handleFantasySubmit = useCallback(() => {
    const f = fantasy.trim();
    if (!f) return;
    fantasyRef.current = f;
    setFantasy("");
    addMessage({ type: "user-text", text: f });
    addMessage({ type: "bot-text", text: "Which narrator would you like to use today?" });
    setStage("voice");
  }, [fantasy, addMessage]);

  // ── Stage: voice → generating ─────────────────────────────

  const handleVoiceSelect = useCallback(async (voice: string) => {
    voiceRef.current = voice;
    addMessage({ type: "user-text", text: voice });
    setStage("generating");

    const progressId = addMessage({
      type: "bot-progress",
      text: "Starting generation…",
    });

    // Reset the chunk player for a fresh session, then prime the AudioContext
    // while we're still inside the click handler (user gesture window).
    chunkPlayerRef.current?.reset();
    chunkPlayerRef.current?.prime();
    setIsPlaying(false);
    isPlayingRef.current = false;
    setAnalyserNode(null);
    setAudioSrc(null);
    generatingRef.current = true;

    try {
      for await (const event of streamGenerate(timeRef.current, fantasyRef.current, voiceRef.current)) {
        if (event.type === "story") {
          setStoryText(event.text ?? null);
          setStoryId(event.story_id ?? null);
        } else if (event.type === "progress") {
          updateMessage(progressId, event.text ?? "");
        } else if (event.type === "chunk") {
          chunkPlayerRef.current?.addChunk(event.url!);
          // Grab the analyser node on the first chunk
          if (!isPlayingRef.current) {
            setIsPlaying(true);
            isPlayingRef.current = true;
            const node = chunkPlayerRef.current?.getAnalyser() ?? null;
            setAnalyserNode(node);
          }
        } else if (event.type === "done") {
          updateMessage(progressId, "Story complete.");
          setStage("done");
        } else if (event.type === "aborted") {
          updateMessage(progressId, "Generation stopped — redirecting…");
          setStage("done");
        } else if (event.type === "error") {
          updateMessage(progressId, `Error: ${event.text ?? "unknown"}`);
        }
      }
    } catch (err) {
      updateMessage(progressId, `Error: ${String(err)}`);
    } finally {
      generatingRef.current = false;
    }
  }, [addMessage, updateMessage]);

  // ── Edit / redirect (works during generating OR done) ─────

  const handleEdit = useCallback(async () => {
    const instruction = editInstruction.trim();
    if (!instruction || isEditing) return;
    // During generation, storyId may not be set yet — that's OK, we'll
    // abort and wait for it. But if we're in "done" stage we need it.
    if (!storyId && stage === "done") return;
    setEditInstruction("");
    setIsEditing(true);

    addMessage({ type: "user-text", text: instruction });
    const progressId = addMessage({ type: "bot-progress", text: "Rewriting story…" });

    // Prime AudioContext NOW while we're still in the user gesture call stack.
    // After awaits below we lose the gesture window and browsers may block resume().
    chunkPlayerRef.current?.prime();

    // If generation is still running, abort it first
    if (generatingRef.current) {
      updateMessage(progressId, "Stopping current generation…");
      await abortGeneration();
      // Wait for the generate SSE stream to finish and set generatingRef = false
      const waitStart = Date.now();
      while (generatingRef.current && Date.now() - waitStart < 5000) {
        await new Promise((r) => setTimeout(r, 100));
      }
    }

    // After abort, storyId should be set (the story event arrives before chunks).
    // If it's still null, we can't edit.
    if (!storyId) {
      updateMessage(progressId, "No story to edit yet — try again after the story loads.");
      setIsEditing(false);
      return;
    }

    // Get the current playback chunk index so we edit from where the user is listening
    const fromChunk = chunkPlayerRef.current?.getCurrentChunkIndex() ?? undefined;
    const fromChunkIndex = fromChunk != null && fromChunk >= 0 ? fromChunk + 1 : undefined;

    // Reset player — kept chunks will be re-streamed by the server
    chunkPlayerRef.current?.reset();
    setIsPlaying(false);
    isPlayingRef.current = false;

    try {
      for await (const event of streamEdit(storyId, instruction, fromChunkIndex)) {
        if (event.type === "story") {
          setStoryText(event.text ?? null);
          setStoryId(event.story_id ?? null);
        } else if (event.type === "progress") {
          updateMessage(progressId, event.text ?? "");
        } else if (event.type === "chunk") {
          chunkPlayerRef.current?.addChunk(event.url!);
          if (!isPlayingRef.current) {
            setIsPlaying(true);
            isPlayingRef.current = true;
            const node = chunkPlayerRef.current?.getAnalyser() ?? null;
            setAnalyserNode(node);
          }
        } else if (event.type === "done") {
          updateMessage(progressId, "Story updated.");
          setStage("done");
        } else if (event.type === "aborted") {
          updateMessage(progressId, "Edit stopped.");
          setStage("done");
        } else if (event.type === "error") {
          updateMessage(progressId, `Error: ${event.text ?? "unknown"}`);
        }
      }
    } catch (err) {
      updateMessage(progressId, `Couldn't update: ${String(err)}`);
    } finally {
      setIsEditing(false);
    }
  }, [editInstruction, isEditing, storyId, stage, addMessage, updateMessage]);

  // ── Render ────────────────────────────────────────────────

  if (stage === "landing") {
    return (
      <div
        className="landing"
        style={{ backgroundImage: `linear-gradient(rgba(15, 15, 15, 0.72), rgba(15, 15, 15, 0.78)), url(${landingBg})` }}
      >
        <div className="landing-content">
          <p className="landing-eyebrow">A personal satisfaction machine</p>
          <h1 className="landing-title">Kinky Audio</h1>
          <p className="landing-sub">Close your eyes. Let us tell you a story.</p>
          <button className="landing-btn" onClick={handleStart}>
            Begin your session
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">Kinky Audio</header>

      <div className="app-body">
        {/* ── Left: chat ── */}
        <div className="app-left">
          <ChatWindow messages={messages} />

          <div className="app-footer">
            {stage === "time" && (
              <QuickReplies options={TIME_OPTIONS} onSelect={handleTimeSelect} />
            )}

            {stage === "fantasy" && (
              <div className="fantasy-footer">
                <div className="vibe-chips">
                  {VIBE_CHIPS.map((chip) => (
                    <button
                      key={chip.label}
                      className="vibe-chip"
                      onClick={() => {
                        setFantasy(chip.fill);
                        inputRef.current?.focus();
                      }}
                    >
                      {chip.label}
                    </button>
                  ))}
                </div>
                <div className="input-row">
                  <input
                    ref={inputRef}
                    className="text-input"
                    value={fantasy}
                    onChange={(e) => setFantasy(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleFantasySubmit()}
                    placeholder="Describe your story…"
                    autoFocus
                  />
                  <button className="send-btn" onClick={handleFantasySubmit}>
                    Send
                  </button>
                </div>
              </div>
            )}

            {stage === "voice" && (
              <QuickReplies
                options={availableVoices.length ? availableVoices.map((v) => v.charAt(0).toUpperCase() + v.slice(1)) : ["Alyssa"]}
                onSelect={(v) => handleVoiceSelect(v.toLowerCase())}
              />
            )}

            {(stage === "generating" || stage === "done") && (
              <div className="input-row">
                <input
                  className="text-input"
                  value={editInstruction}
                  onChange={(e) => setEditInstruction(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleEdit()}
                  placeholder={
                    isEditing
                      ? "Updating story…"
                      : stage === "generating"
                        ? "Redirect the story… (stops current generation)"
                        : "Change something… (e.g. 'make it darker')"
                  }
                  disabled={isEditing}
                />
                <button className="send-btn" onClick={handleEdit} disabled={isEditing}>
                  {isEditing ? "…" : "Redirect"}
                </button>
              </div>
            )}
          </div>
        </div>

        {/* ── Right: orb + story + audio ── */}
        <div className="app-right">
          {/* Invisible audio engine */}
          <ChunkPlayer ref={chunkPlayerRef} />

          {/* Orb zone — fills available space, orb centered within */}
          <div className="orb-zone">
            <div className={`orb-container${isPlaying ? "" : " orb-container--idle"}`}>
              <VoicePoweredOrb analyserNode={analyserNode} />
            </div>
          </div>

          {/* Bottom zone — story text + post-edit audio replay */}
          <div className="orb-bottom">
            {audioSrc && (
              <div className="story-panel-audio">
                <AudioPlayer src={audioSrc} />
              </div>
            )}

            {storyText ? (
              <div className="story-panel">
                <p className="story-panel-label">Your Story</p>
                <div className="story-panel-body">{storyText}</div>
              </div>
            ) : (
              <div className="story-panel-empty">
                Your story will appear here once generated.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
