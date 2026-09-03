/** CrateEditor — top-level studio model tying waveform, cues and transitions
 * together and persisting via the bridge. */

import type { HyperMixBridge } from "@hypermix/bridge";
import { CuePanel, type EditableCue } from "../cues/CuePanel";

export interface CrateSummary {
  crateId: string;
  name: string;
  tracks: number;
}

export class CrateEditor {
  readonly cues = new CuePanel();
  currentCrate: CrateSummary | null = null;

  constructor(private bridge: HyperMixBridge) {}

  async openCrate(path: string): Promise<CrateSummary> {
    const result = await this.bridge.request<CrateSummary>("crate.open", { path });
    this.currentCrate = result;
    return result;
  }

  async saveCrate(path: string): Promise<void> {
    if (!this.currentCrate) throw new Error("no crate open");
    await this.bridge.request("crate.save", {
      crateId: this.currentCrate.crateId,
      path,
    });
  }

  importCues(cues: EditableCue[]): void {
    cues.forEach((c) => this.cues.add(c));
  }
}
