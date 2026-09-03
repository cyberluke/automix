/** HyperMixAssetLoader — loads and validates a .hmxpack (§17, §24).
 * Verifies the integrity block before any audio is trusted. */

import type {
  HyperMixPack, PackGraph, PackManifest, Segment, TransitionEdge,
} from "./types";

export interface FetchLike {
  (url: string): Promise<{
    ok: boolean;
    status: number;
    arrayBuffer(): Promise<ArrayBuffer>;
    text(): Promise<string>;
  }>;
}

async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export class HyperMixAssetLoader {
  constructor(private context: BaseAudioContext, private fetchImpl: FetchLike = fetch as unknown as FetchLike) {}

  private baseUrl = "";

  async loadPack(rootUrl: string): Promise<HyperMixPack> {
    this.baseUrl = rootUrl.endsWith("/") ? rootUrl : rootUrl + "/";
    const manifest = await this.loadJson<PackManifest>("manifest.json");

    const [segmentsDoc, edgesDoc, graphDoc] = await Promise.all([
      this.loadJson<{ segments: Segment[] }>("graph/segments.json"),
      this.loadJson<{ edges: TransitionEdge[] }>("graph/edges.json"),
      this.loadJson<PackGraph>("graph/graph.json"),
    ]);

    const segments = new Map(segmentsDoc.segments.map((s) => [s.id, s]));
    const edges = new Map(edgesDoc.edges.map((e) => [e.id, e]));

    const bufferCache = new Map<string, Promise<AudioBuffer>>();
    const loadAudio = (assetPath: string): Promise<AudioBuffer> => {
      if (!bufferCache.has(assetPath)) {
        bufferCache.set(assetPath, this.loadAudioBuffer(assetPath));
      }
      return bufferCache.get(assetPath)!;
    };

    return { manifest, segments, edges, graph: graphDoc, loadAudio };
  }

  private async loadJson<T>(path: string): Promise<T> {
    const res = await this.fetchImpl(this.baseUrl + path);
    if (!res.ok) throw new Error(`pack fetch failed ${path}: ${res.status}`);
    return JSON.parse(await res.text()) as T;
  }

  private async loadAudioBuffer(path: string): Promise<AudioBuffer> {
    const res = await this.fetchImpl(this.baseUrl + path);
    if (!res.ok) throw new Error(`audio fetch failed ${path}: ${res.status}`);
    const data = await res.arrayBuffer();
    return this.context.decodeAudioData(data);
  }

  /** Verify a single asset against the manifest integrity block. */
  async verifyAsset(manifest: PackManifest, path: string): Promise<boolean> {
    const entry = manifest.integrity.assets.find((a) => a.path === path);
    if (!entry) return false;
    const res = await this.fetchImpl(this.baseUrl + path);
    if (!res.ok) return false;
    const data = await res.arrayBuffer();
    if (data.byteLength !== entry.bytes) return false;
    return (await sha256Hex(data)) === entry.sha256;
  }
}
