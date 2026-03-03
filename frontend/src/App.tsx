import { useState, useCallback, useRef } from "react";
import ChatWindow from "./components/ChatWindow";
import QuickReplies from "./components/QuickReplies";
import { streamGenerate } from "./api";
import landingBg from "./assets/landing-bg.png";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Stage = "landing" | "time" | "fantasy" | "generating" | "done";

export interface Message {
  id: string;
  type: "bot-text" | "user-text" | "bot-progress" | "bot-story" | "bot-audio";
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
  const timeRef = useRef("");
  const inputRef = useRef<HTMLInputElement>(null);

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

  // ── Stage: fantasy → generating ──────────────────────────

  const handleFantasySubmit = useCallback(async () => {
    const f = fantasy.trim();
    if (!f) return;

    setFantasy("");
    addMessage({ type: "user-text", text: f });
    setStage("generating");

    const progressId = addMessage({
      type: "bot-progress",
      text: "Starting generation…",
    });

    try {
      for await (const event of streamGenerate(timeRef.current, f)) {
        if (event.type === "story") {
          addMessage({ type: "bot-story", text: event.text });
        } else if (event.type === "progress") {
          updateMessage(progressId, event.text ?? "");
        } else if (event.type === "done") {
          updateMessage(progressId, "Audio ready.");
          addMessage({ type: "bot-audio" });
          setStage("done");
        } else if (event.type === "error") {
          updateMessage(progressId, `Error: ${event.text ?? "unknown"}`);
        }
      }
    } catch (err) {
      updateMessage(progressId, `Error: ${String(err)}`);
    }
  }, [fantasy, addMessage, updateMessage]);

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

        {stage === "generating" && (
          <div className="status-bar">Generating your story…</div>
        )}

        {stage === "done" && (
          <div className="status-bar">Your story is ready. Enjoy.</div>
        )}
      </div>
    </div>
  );
}
