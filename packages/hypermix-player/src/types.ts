/** HyperMix pack type definitions (§2, §17, §24). Canonical time is an integer
 * sample index; seconds are only ever a derived view. */

export interface TransitionTimeline {
  t1Sample: number;
  t2Sample: number;
  t3Sample: number;
}

export interface PackEvent {
  sample: number;
  type: string;
  payload: Record<string, unknown>;
}

export interface Segment {
  id: string;
  trackId: string;
  startSample: number;
  endSample: number;
  lengthSamples: number;
  bars: number;
  bpm: number;
  entryClass: string;
  exitClass: string;
  energyStart: number;
  energyEnd: number;
  rating: number;
  tags: string[];
  asset: string;
  assetSha256?: string;
  assetSamples?: number;
}

export interface TransitionEdge {
  id: string;
  from: string;
  to: string;
  technique: string;
  timeline: TransitionTimeline;
  tempoContinuityRequired: boolean;
  phraseSafe: boolean;
  quality: number;
  asset: string;
  assetSha256?: string;
  assetSamples?: number;
  events: PackEvent[];
}

export interface PackManifest {
  schema: string;
  id: string;
  name: string;
  version: string;
  sampleRate: number;
  channels: number;
  fallbackTransition: string;
  segments: number;
  edges: number;
  entrySegments: string[];
  integrity: {
    manifestSha256: string;
    assets: Array<{ path: string; sha256: string; bytes: number; samples?: number }>;
  };
}

export interface PackGraph {
  entrySegments: string[];
  fallbackTransition: string;
  adjacency: Record<string, string[]>;
}

export interface HyperMixPack {
  manifest: PackManifest;
  segments: Map<string, Segment>;
  edges: Map<string, TransitionEdge>;
  graph: PackGraph;
  /** Fetch a decoded AudioBuffer for a pack-relative asset path. */
  loadAudio: (assetPath: string) => Promise<AudioBuffer>;
}

export type PlayerMode = "deterministic" | "weighted-random" | "manual";

export interface PlayOptions {
  seed?: number;
  mode?: PlayerMode;
  targetMood?: string[];
  energyMin?: number;
  energyMax?: number;
}
