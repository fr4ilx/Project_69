import { forwardRef } from "react";

interface Props {
  src?: string;
}

const AudioPlayer = forwardRef<HTMLAudioElement, Props>(
  ({ src = "/api/audio" }, ref) => (
    <audio ref={ref} controls src={src}>
      Your browser does not support audio playback.
    </audio>
  )
);
AudioPlayer.displayName = "AudioPlayer";

export default AudioPlayer;
