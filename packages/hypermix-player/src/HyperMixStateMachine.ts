/** Player state machine (§26). Explicit states; no implicit transitions. */

export type PlayerState =
  | "idle"
  | "loading"
  | "ready"
  | "playing"
  | "transitioning"
  | "hotSwapping"
  | "seeking"
  | "paused"
  | "stopped"
  | "error";

const ALLOWED: Record<PlayerState, PlayerState[]> = {
  idle: ["loading", "error"],
  loading: ["ready", "error", "idle"],
  ready: ["playing", "loading", "idle", "error"],
  playing: ["transitioning", "hotSwapping", "seeking", "paused", "stopped", "error"],
  transitioning: ["playing", "stopped", "error"],
  hotSwapping: ["playing", "stopped", "error"],
  seeking: ["playing", "paused", "stopped", "error"],
  paused: ["playing", "stopped", "error"],
  stopped: ["loading", "ready", "idle", "error"],
  error: ["idle", "loading"],
};

export class HyperMixStateMachine {
  private state: PlayerState = "idle";
  private listeners = new Set<(s: PlayerState, prev: PlayerState) => void>();

  get current(): PlayerState {
    return this.state;
  }

  canTransition(to: PlayerState): boolean {
    return ALLOWED[this.state].includes(to);
  }

  transition(to: PlayerState): boolean {
    if (!this.canTransition(to)) return false;
    const prev = this.state;
    this.state = to;
    this.listeners.forEach((l) => l(to, prev));
    return true;
  }

  onChange(listener: (s: PlayerState, prev: PlayerState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
