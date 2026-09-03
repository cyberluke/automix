/** HyperMixScheduler — sample-accurate segment/transition scheduling (§25, §27).
 *
 * - Schedules AudioBufferSourceNodes against the AudioContext clock.
 * - Uses a generation token so stale async work can never start audio late.
 * - Emits throttled UI position events (10–30 Hz) while the clock stays
 *   sample-accurate.
 */

import { HyperMixClock } from "./HyperMixClock";
import { HyperMixEventBus } from "./HyperMixEventBus";
import type { Segment, TransitionEdge } from "./types";

export interface ScheduledUnit {
  kind: "segment" | "transition";
  id: string;
  startSample: number;
  lengthSamples: number;
  source?: AudioBufferSourceNode;
}

const POSITION_EVENT_MIN_INTERVAL_MS = 33; // ~30 Hz

export class HyperMixScheduler {
  private clock: HyperMixClock;
  private nextStartContextTime: number | null = null;
  private active: AudioBufferSourceNode[] = [];
  private generation = 0;
  private lastPositionEventAt = 0;
  private queue: ScheduledUnit[] = [];

  constructor(
    private context: BaseAudioContext,
    private events: HyperMixEventBus,
    private destination: AudioNode = context.destination,
  ) {
    this.clock = new HyperMixClock(context);
  }

  get positionSample(): number {
    return this.clock.nowSample();
  }

  get currentGeneration(): number {
    return this.generation;
  }

  /** Begin playback at the next safe scheduling point. */
  start(): number {
    const startTime = this.context.currentTime + 0.05;
    this.clock.anchor(startTime, 0);
    this.nextStartContextTime = startTime;
    return this.generation;
  }

  /** Schedule a segment. Returns the scheduled start sample. */
  scheduleSegment(segment: Segment, buffer: AudioBuffer, gen: number): number {
    if (gen !== this.generation || this.nextStartContextTime === null) return -1;
    const start = this.nextStartContextTime;
    const src = this.context.createBufferSource();
    src.buffer = buffer;
    src.connect(this.destination);
    src.start(start);
    this.active.push(src);
    const startSample = this.clock.contextTimeToSample(start);
    this.queue.push({ kind: "segment", id: segment.id, startSample, lengthSamples: buffer.length, source: src });
    this.nextStartContextTime = start + buffer.duration;
    this.events.emit("segment.scheduled", { segmentId: segment.id, startSample });
    src.onended = () => this.maybeEmitPosition();
    return startSample;
  }

  /** Schedule a precompiled transition edge. */
  scheduleTransition(edge: TransitionEdge, buffer: AudioBuffer, gen: number): number {
    if (gen !== this.generation || this.nextStartContextTime === null) return -1;
    const start = this.nextStartContextTime;
    const src = this.context.createBufferSource();
    src.buffer = buffer;
    src.connect(this.destination);
    src.start(start);
    this.active.push(src);
    const startSample = this.clock.contextTimeToSample(start);
    this.queue.push({ kind: "transition", id: edge.id, startSample, lengthSamples: buffer.length, source: src });
    this.nextStartContextTime = start + buffer.duration;
    this.events.emit("transition.scheduled", { edgeId: edge.id, technique: edge.technique, startSample });
    return startSample;
  }

  /** Stop everything and invalidate pending async work. */
  stopAll(): void {
    this.generation++;
    this.active.forEach((s) => { try { s.stop(); } catch { /* already stopped */ } });
    this.active = [];
    this.queue = [];
    this.nextStartContextTime = null;
    this.clock.reset();
  }

  /** Invalidate pending work without stopping already-started sources. */
  bumpGeneration(): number {
    return ++this.generation;
  }

  private maybeEmitPosition(): void {
    const now = performance.now();
    if (now - this.lastPositionEventAt < POSITION_EVENT_MIN_INTERVAL_MS) return;
    this.lastPositionEventAt = now;
    this.events.emit("position", { sample: this.positionSample });
  }
}
