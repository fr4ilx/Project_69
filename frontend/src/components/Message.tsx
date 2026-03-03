import { useState } from "react";
import type { Message } from "../App";
import AudioPlayer from "./AudioPlayer";

interface Props {
  message: Message;
}

export default function MessageBubble({ message }: Props) {
  const [expanded, setExpanded] = useState(false);

  switch (message.type) {
    case "bot-text":
      return <div className="message bot">{message.text}</div>;

    case "user-text":
      return <div className="message user">{message.text}</div>;

    case "bot-progress":
      return <div className="message progress">{message.text}</div>;

    case "bot-story":
      return (
        <div className="message story">
          <button
            className="story-toggle"
            onClick={() => setExpanded((e) => !e)}
          >
            {expanded ? "Hide story ▲" : "Show story ▼"}
          </button>
          {expanded && (
            <div className="story-body">{message.text}</div>
          )}
        </div>
      );

    case "bot-audio":
      return (
        <div className="message audio">
          <AudioPlayer />
        </div>
      );
  }
}
