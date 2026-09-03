/** Runtime diagnostics ring buffer (§34). */

export interface DiagnosticEntry {
  ts: number;
  type: string;
  payload: Record<string, unknown>;
}

export class HyperMixDiagnostics {
  private entries: DiagnosticEntry[] = [];
  private readonly max = 500;

  record(type: string, payload: Record<string, unknown>): void {
    this.entries.push({ ts: Date.now(), type, payload });
    if (this.entries.length > this.max) {
      this.entries = this.entries.slice(-this.max);
    }
  }

  snapshot(): DiagnosticEntry[] {
    return [...this.entries];
  }

  clear(): void {
    this.entries = [];
  }
}
