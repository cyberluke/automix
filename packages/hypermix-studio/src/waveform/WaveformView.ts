/** WaveformView — canvas renderer for downsampled peaks with cue markers and
 * phrase grid overlay. Samples are the unit; seconds are derived labels. */

export interface WaveformPeak { min: number; max: number }

export interface CueMarker {
  sample: number;
  kind: string;
  label: string;
  stale?: boolean;
}

export class WaveformView {
  private ctx: CanvasRenderingContext2D;

  constructor(private canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no 2d context");
    this.ctx = ctx;
  }

  render(
    peaks: WaveformPeak[],
    totalSamples: number,
    cues: CueMarker[],
    phraseGrid: number[] = [],
    viewportStartSample = 0,
    viewportLengthSamples = totalSamples,
  ): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#0b0f14";
    ctx.fillRect(0, 0, width, height);

    const mid = height / 2;
    const toX = (sample: number) =>
      ((sample - viewportStartSample) / viewportLengthSamples) * width;

    // Phrase grid.
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    for (const p of phraseGrid) {
      const x = toX(p);
      if (x < 0 || x > width) continue;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
    }

    // Peaks.
    ctx.strokeStyle = "#5eead4";
    ctx.beginPath();
    const step = viewportLengthSamples / width;
    for (let x = 0; x < width; x++) {
      const i = Math.floor((viewportStartSample + x * step) / totalSamples * peaks.length);
      const peak = peaks[Math.min(peaks.length - 1, Math.max(0, i))];
      if (!peak) continue;
      ctx.moveTo(x, mid - peak.max * mid);
      ctx.lineTo(x, mid - peak.min * mid);
    }
    ctx.stroke();

    // Cues.
    for (const cue of cues) {
      const x = toX(cue.sample);
      if (x < 0 || x > width) continue;
      ctx.strokeStyle = cue.stale ? "#f59e0b" : "#f472b6";
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
      ctx.fillStyle = cue.stale ? "#f59e0b" : "#f472b6";
      ctx.font = "10px sans-serif";
      ctx.fillText(`${cue.kind}:${cue.label}`, x + 2, 12);
    }
  }
}
