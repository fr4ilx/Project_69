import type { Message } from "../App";

interface Props {
  message: Message;
}

export default function MessageBubble({ message }: Props) {
  switch (message.type) {
    case "bot-text":
      return <div className="message bot">{message.text}</div>;

    case "user-text":
      return <div className="message user">{message.text}</div>;

    case "bot-progress":
      return <div className="message progress">{message.text}</div>;
  }
}
