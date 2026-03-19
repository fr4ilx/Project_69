import { useState, useCallback, useRef, useEffect } from "react";
import ChatWindow from "./components/ChatWindow";
import QuickReplies from "./components/QuickReplies";
import AudioPlayer from "./components/AudioPlayer";
import ChunkPlayer, { type ChunkPlayerHandle } from "./components/ChunkPlayer";
import { VoicePoweredOrb } from "./components/VoicePoweredOrb";
import { streamGenerate, abortGeneration, injectEvent, redirectStory, fetchVoices } from "./api";
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
const VOICE_LABEL_OVERRIDES: Record<string, string> = {
  jean: "Jean",
};

function toVoiceLabel(voice: string): string {
  if (VOICE_LABEL_OVERRIDES[voice]) return VOICE_LABEL_OVERRIDES[voice];
  return voice
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

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
  const [actionMode, setActionMode] = useState<"none" | "inject" | "redirect" | "new_fantasy">("none");
  const [storyText, setStoryText] = useState<string | null>(null);
  const [storyId, setStoryId] = useState<string | null>(null);
  const [isStoryOpen, setIsStoryOpen] = useState(false);
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
        if (event.type === "session") {
          setStoryId(event.story_id ?? null);
        } else if (event.type === "story") {
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
          setAudioSrc(`/api/audio?t=${Date.now()}`);
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

  // ── Action: Inject event into next paragraph ──────────────

  const handleInject = useCallback(async () => {
    const text = editInstruction.trim();
    if (!text || isEditing) return;
    setEditInstruction("");
    setActionMode("none");
    addMessage({ type: "user-text", text });
    addMessage({ type: "bot-text", text: "Got it — weaving that into the next paragraph…" });
    await injectEvent(text, storyId);
  }, [editInstruction, isEditing, addMessage, storyId]);

  // ── Action: Redirect story (persistent course change) ────

  const handleRedirect = useCallback(async () => {
    const text = editInstruction.trim();
    if (!text || isEditing) return;
    setEditInstruction("");
    setActionMode("none");
    addMessage({ type: "user-text", text });
    addMessage({ type: "bot-text", text: "Got it — changing course from here on…" });
    await redirectStory(text, storyId);
  }, [editInstruction, isEditing, addMessage, storyId]);

  // ── Action: New fantasy (restart from scratch) ───────────

  const handleNewFantasy = useCallback(async () => {
    const text = editInstruction.trim();
    if (!text || isEditing) return;
    setEditInstruction("");
    setActionMode("none");

    // Prime AudioContext NOW while still in user gesture call stack
    chunkPlayerRef.current?.prime();

    addMessage({ type: "user-text", text });
    const progressId = addMessage({ type: "bot-progress", text: "Stopping current story…" });

    // Abort current generation and wait for it to fully release the lock
    if (generatingRef.current) {
      await abortGeneration(storyId);
      const waitStart = Date.now();
      while (generatingRef.current && Date.now() - waitStart < 30000) {
        await new Promise((r) => setTimeout(r, 100));
      }
    }

    // Reset everything and restart with new fantasy
    fantasyRef.current = text;
    setStoryText(null);
    setStoryId(null);
    setAudioSrc(null);

    // Kick off generation
    setStage("generating");
    updateMessage(progressId, "Starting new story…");

    // Use resetForEdit (not reset) to keep the AudioContext alive —
    // reset() closes the context, but prime() was called in the gesture
    // call stack above and we can't re-prime after the awaits.
    chunkPlayerRef.current?.resetForEdit();
    setIsPlaying(false);
    isPlayingRef.current = false;
    setAnalyserNode(null);
    generatingRef.current = true;

    try {
      for await (const event of streamGenerate(timeRef.current, text, voiceRef.current)) {
        if (event.type === "session") {
          setStoryId(event.story_id ?? null);
        } else if (event.type === "story") {
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
          updateMessage(progressId, "Story complete.");
          setAudioSrc(`/api/audio?t=${Date.now()}`);
          setStage("done");
        } else if (event.type === "aborted") {
          updateMessage(progressId, "Generation stopped.");
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
  }, [editInstruction, isEditing, addMessage, updateMessage, storyId]);

  // ── Action: I'm done (stop generation) ───────────────────

  const handleStop = useCallback(async () => {
    setActionMode("none");
    if (generatingRef.current) {
      addMessage({ type: "user-text", text: "That's enough." });
      addMessage({ type: "bot-text", text: "Wrapping up…" });
      await abortGeneration(storyId);
    }
  }, [addMessage, storyId]);

  // ── Submit handler routes to the active action mode ──────

  const handleActionSubmit = useCallback(() => {
    if (actionMode === "inject") handleInject();
    else if (actionMode === "redirect") handleRedirect();
    else if (actionMode === "new_fantasy") handleNewFantasy();
  }, [actionMode, handleInject, handleRedirect, handleNewFantasy]);

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
                options={availableVoices.length ? availableVoices.map(toVoiceLabel) : ["Alyssa"]}
                onSelect={(label) => {
                  const selected = availableVoices.find((v) => toVoiceLabel(v) === label);
                  handleVoiceSelect(selected ?? label.toLowerCase());
                }}
              />
            )}

            {(stage === "generating" || stage === "done") && (
              <>
                {storyText && (
                  <button className="mobile-story-btn" onClick={() => setIsStoryOpen(true)}>
                    View Story here
                  </button>
                )}
                {actionMode === "none" && !isEditing && (
                  <div className="action-buttons">
                    <button className="action-btn" onClick={() => setActionMode("new_fantasy")}>
                      New fantasy
                    </button>
                    <button className="action-btn" onClick={() => setActionMode("inject")}>
                      Add event
                    </button>
                    <button className="action-btn" onClick={() => setActionMode("redirect")}>
                      Change course
                    </button>
                    <button className="action-btn action-btn--stop" onClick={handleStop}>
                      I'm done
                    </button>
                  </div>
                )}

                {actionMode !== "none" && (
                  <div className="input-row">
                    <input
                      className="text-input"
                      value={editInstruction}
                      onChange={(e) => setEditInstruction(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleActionSubmit();
                        if (e.key === "Escape") { setActionMode("none"); setEditInstruction(""); }
                      }}
                      placeholder={
                        actionMode === "inject"
                          ? "What should happen next?"
                          : actionMode === "redirect"
                            ? "Where should the story go?"
                            : "Describe your new fantasy…"
                      }
                      disabled={isEditing}
                      autoFocus
                    />
                    <button className="send-btn" onClick={handleActionSubmit} disabled={isEditing}>
                      {isEditing ? "…" : "Go"}
                    </button>
                    <button className="cancel-btn" onClick={() => { setActionMode("none"); setEditInstruction(""); }}>
                      ✕
                    </button>
                  </div>
                )}

                {isEditing && actionMode === "none" && (
                  <div className="input-row">
                    <input className="text-input" disabled placeholder="Working on it…" />
                  </div>
                )}
              </>
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
                <a className="download-btn" href="/api/audio" download="story.wav">
                  Download
                </a>
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

      {isStoryOpen && (
        <div className="mobile-story-modal" onClick={() => setIsStoryOpen(false)}>
          <div className="mobile-story-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="mobile-story-header">
              <p className="story-panel-label">Your Story</p>
              <button className="mobile-story-close" onClick={() => setIsStoryOpen(false)}>
                Close
              </button>
            </div>
            {audioSrc && (
              <div className="story-panel-audio">
                <AudioPlayer src={audioSrc} />
                <a className="download-btn" href="/api/audio" download="story.wav">
                  Download
                </a>
              </div>
            )}
            <div className="story-panel">
              <div className="story-panel-body">{storyText}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
