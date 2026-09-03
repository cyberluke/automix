/** HyperMixPlayer — the public player facade (§24-§28). Orchestrates loading,
 * deterministic selection, sample-accurate scheduling, hot-swap, and events.
 * No Python. No localhost. No VS Code imports. */

import { HyperMixAssetLoader } from "./HyperMixAssetLoader";
import { HyperMixDiagnostics } from "./HyperMixDiagnostics";
import { HyperMixEventBus } from "./HyperMixEventBus";
import { HyperMixHotSwap } from "./HyperMixHotSwap";
import { HyperMixScheduler } from "./HyperMixScheduler";
import { HyperMixStateMachine } from "./HyperMixStateMachine";
import type { HyperMixPack, PlayOptions, Segment } from "./types";

// Small deterministic PRNG (mulberry32) so the player matches compiler behaviour.
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const HOT_SWAP_DEADLINE_MS = 120;

export class HyperMixPlayer {
  readonly events = new HyperMixEventBus();
  readonly diagnostics = new HyperMixDiagnostics();
  readonly state = new HyperMixStateMachine();

  private pack: HyperMixPack | null = null;
  private scheduler: HyperMixScheduler | null = null;
  private hotSwap: HyperMixHotSwap | null = null;
  private currentSegmentId: string | null = null;
  private options: Required<PlayOptions> = {
    seed: 0, mode: "weighted-random", targetMood: [], energyMin: 0, energyMax: 1,
  };
  private rng: () => number = Math.random;

  constructor(private context: BaseAudioContext) {}

  async loadPack(rootUrl: string): Promise<void> {
    this.state.transition("loading");
    try {
      const loader = new HyperMixAssetLoader(this.context);
      this.pack = await loader.loadPack(rootUrl);
      this.scheduler = new HyperMixScheduler(this.context, this.events);
      this.hotSwap = new HyperMixHotSwap(this.pack);
      this.diagnostics.record("pack.loaded", { id: this.pack.manifest.id });
      this.state.transition("ready");
    } catch (e) {
      this.diagnostics.record("pack.loadError", { error: String(e) });
      this.state.transition("error");
      throw e;
    }
  }

  play(options: PlayOptions = {}): void {
    if (!this.pack || !this.scheduler) throw new Error("no pack loaded");
    this.options = { ...this.options, ...options };
    this.rng = mulberry32(this.options.seed);
    this.scheduler.start();
    this.state.transition("playing");
    void this.advanceFrom(null);
  }

  stop(): void {
    this.scheduler?.stopAll();
    this.currentSegmentId = null;
    this.state.transition("stopped");
  }

  /** Request the next segment (deterministic director in-player). */
  async next(targetMood?: string[]): Promise<void> {
    if (!this.currentSegmentId) return;
    await this.advanceFrom(this.currentSegmentId, targetMood);
  }

  /** Hot-swap the upcoming transition target with a strict deadline (§27). */
  async requestHotSwap(preferredToId: string): Promise<boolean> {
    if (!this.pack || !this.scheduler || !this.hotSwap || !this.currentSegmentId) return false;
    const gen = this.scheduler.bumpGeneration();
    this.state.transition("hotSwapping");
    const decision = await this.hotSwap.resolve(this.currentSegmentId, preferredToId, HOT_SWAP_DEADLINE_MS);
    if (!decision || gen !== this.scheduler.currentGeneration) {
      this.state.transition("playing");
      return false;
    }
    this.scheduler.scheduleTransition(decision.edge, decision.buffer, gen);
    this.diagnostics.record("hotSwap", {
      from: this.currentSegmentId, to: decision.edge.to,
      technique: decision.technique, fellBackTo: decision.fellBackTo,
    });
    this.events.emit("transition.switch", {
      technique: decision.technique, fellBackTo: decision.fellBackTo,
    });
    this.state.transition("playing");
    return true;
  }

  // -- director -------------------------------------------------------------
  private pickEntry(): Segment | null {
    if (!this.pack) return null;
    const entries = this.pack.graph.entrySegments
      .map((id) => this.pack!.segments.get(id))
      .filter((s): s is Segment => !!s);
    if (entries.length === 0) return null;
    if (this.options.mode === "deterministic") {
      return entries.reduce((a, b) => (b.rating > a.rating ? b : a));
    }
    return entries[Math.floor(this.rng() * entries.length)];
  }

  private pickNext(fromId: string, targetMood?: string[]): Segment | null {
    if (!this.pack) return null;
    const options = (this.pack.graph.adjacency[fromId] ?? [])
      .map((id) => this.pack!.segments.get(id))
      .filter((s): s is Segment => !!s);
    if (options.length === 0) return null;
    const score = (s: Segment) => {
      let sc = s.rating / 10;
      const mood = new Set(targetMood ?? this.options.targetMood);
      if (mood.size > 0) sc += 0.1 * s.tags.filter((t) => mood.has(t)).length;
      if (s.energyStart >= this.options.energyMin && s.energyStart <= this.options.energyMax) sc += 0.25;
      return sc;
    };
    if (this.options.mode === "deterministic") {
      return options.reduce((a, b) => (score(b) > score(a) ? b : a));
    }
    const weights = options.map((s) => Math.max(0.001, score(s)));
    const total = weights.reduce((a, b) => a + b, 0);
    let r = this.rng() * total;
    for (let i = 0; i < options.length; i++) {
      r -= weights[i];
      if (r <= 0) return options[i];
    }
    return options[options.length - 1];
  }

  private async advanceFrom(currentId: string | null, targetMood?: string[]): Promise<void> {
    if (!this.pack || !this.scheduler) return;
    const next = currentId === null ? this.pickEntry() : this.pickNext(currentId, targetMood);
    if (!next) {
      this.events.emit("set.end", {});
      return;
    }
    const gen = this.scheduler.bumpGeneration();

    if (currentId !== null) {
      const decision = await this.hotSwap!.resolve(currentId, next.id, HOT_SWAP_DEADLINE_MS);
      if (decision && gen === this.scheduler.currentGeneration) {
        this.state.transition("transitioning");
        this.scheduler.scheduleTransition(decision.edge, decision.buffer, gen);
        this.state.transition("playing");
      }
    }

    const buffer = await this.pack.loadAudio(next.asset);
    if (gen !== this.scheduler.currentGeneration) return;
    this.scheduler.scheduleSegment(next, buffer, gen);
    this.currentSegmentId = next.id;
    this.events.emit("segment.enter", { segmentId: next.id });
  }
}
