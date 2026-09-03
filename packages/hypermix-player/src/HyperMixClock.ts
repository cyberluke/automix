/** HyperMixClock — maps AudioContext output clock to integer sample indices
 * (§25). The sample clock is the single source of truth; setTimeout is never
 * used as a musical clock. */

export class HyperMixClock {
  private epochContextTime: number | null = null;
  private epochSample: number = 0;

  constructor(private context: BaseAudioContext) {}

  /** Anchor the sample clock to the context clock. */
  anchor(startContextTime: number, startSample: number): void {
    this.epochContextTime = startContextTime;
    this.epochSample = startSample;
  }

  /** Current absolute sample position. */
  nowSample(): number {
    if (this.epochContextTime === null) return this.epochSample;
    const elapsed = this.context.currentTime - this.epochContextTime;
    return this.epochSample + Math.max(0, Math.floor(elapsed * this.context.sampleRate));
  }

  /** Convert a future context time to an absolute sample. */
  contextTimeToSample(contextTime: number): number {
    if (this.epochContextTime === null) return this.epochSample;
    return this.epochSample + Math.round((contextTime - this.epochContextTime) * this.context.sampleRate);
  }

  /** Convert an absolute sample to a context time. */
  sampleToContextTime(sample: number): number {
    if (this.epochContextTime === null) return 0;
    return this.epochContextTime + (sample - this.epochSample) / this.context.sampleRate;
  }

  reset(): void {
    this.epochContextTime = null;
    this.epochSample = 0;
  }
}
