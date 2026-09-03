/** TransitionDesigner — request sidecar previews and visualise t1/t2/t3. */

import type { HyperMixBridge } from "@hypermix/bridge";

export interface PreviewResult {
  technique: string;
  path: string;
  sha256: string;
  timeline: { t1Sample: number; t2Sample: number; t3Sample: number };
}

export class TransitionDesigner {
  constructor(private bridge: HyperMixBridge) {}

  async preview(params: {
    outgoingPath: string;
    incomingPath: string;
    outgoingBpm: number;
    incomingBpm: number;
    technique: string;
    seconds?: number;
    outPath: string;
  }): Promise<PreviewResult> {
    return this.bridge.request<PreviewResult>("transition.preview", params);
  }
}
