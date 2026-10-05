export interface Playback {
  cursor: number;
  speed: number;
  playing: boolean;
}
export type Command =
  | { type: "toggle" | "pause" | "restart" }
  | { type: "seek"; time: number }
  | { type: "speed"; speed: number };
export function playbackCommand(
  state: Playback,
  command: Command,
  start: number,
  end: number,
): Playback {
  switch (command.type) {
    case "toggle":
      return {
        ...state,
        cursor: state.cursor >= end ? start : state.cursor,
        playing: !state.playing,
      };
    case "pause":
      return { ...state, playing: false };
    case "restart":
      return { ...state, cursor: start, playing: false };
    case "seek":
      if (!Number.isFinite(command.time))
        throw new Error("Seek time must be finite");
      return {
        ...state,
        cursor: Math.min(end, Math.max(start, command.time)),
        playing: false,
      };
    case "speed":
      if (
        !Number.isFinite(command.speed) ||
        command.speed <= 0 ||
        command.speed > 64
      )
        throw new Error("Speed must be between 0 and 64");
      return { ...state, speed: command.speed };
  }
}
export function advancePlayback(
  state: Playback,
  elapsed: number,
  start: number,
  end: number,
): Playback {
  if (!Number.isFinite(elapsed) || elapsed < 0)
    throw new Error("Elapsed time must be nonnegative and finite");
  if (!state.playing) return state;
  const cursor = Math.min(
    end,
    Math.max(start, state.cursor + elapsed * state.speed),
  );
  return { ...state, cursor, playing: cursor < end };
}
