interface Props {
  options: string[];
  onSelect: (option: string) => void;
}

export default function QuickReplies({ options, onSelect }: Props) {
  return (
    <div className="quick-replies">
      {options.map((opt) => (
        <button
          key={opt}
          className="quick-reply-btn"
          onClick={() => onSelect(opt)}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}
