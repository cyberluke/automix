/** CuePanel — cue list editor model. Manual cues are authoritative (§5);
 * stale cues are shown but never auto-moved. */

export interface EditableCue {
  id: string;
  sample: number;
  kind: string;
  rating: number;
  tags: string[];
  locked: boolean;
  stale: boolean;
}

export class CuePanel {
  cues: EditableCue[] = [];
  private listeners = new Set<() => void>();

  add(cue: EditableCue): void {
    this.cues.push(cue);
    this.emit();
  }

  update(id: string, patch: Partial<EditableCue>): void {
    const c = this.cues.find((x) => x.id === id);
    if (!c) return;
    // A stale cue can be edited but stays stale until re-snapped explicitly.
    Object.assign(c, patch);
    this.emit();
  }

  resnap(id: string, newSample: number): void {
    const c = this.cues.find((x) => x.id === id);
    if (!c) return;
    c.sample = newSample;
    c.stale = false;
    this.emit();
  }

  remove(id: string): void {
    this.cues = this.cues.filter((c) => c.id !== id);
    this.emit();
  }

  onChange(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    this.listeners.forEach((l) => l());
  }
}
