/** HyperMixHotSwap — hot-swap with a strict deadline fallback order (§27).
 *
 * If a preferred transition asset is not decoded by the deadline, the scheduler
 * walks down the fallback chain to the next safe compiled alternative — never
 * starting late. The chain is data-driven from the pack graph, ending at the
 * crate fallback transition (universal safe exit). */

import type { HyperMixPack, TransitionEdge } from "./types";

export interface HotSwapDecision {
  edge: TransitionEdge;
  buffer: AudioBuffer;
  technique: string;
  fellBackTo: string | null;
}

export class HyperMixHotSwap {
  constructor(private pack: HyperMixPack) {}

  /** Ordered fallback candidates for leaving `fromSegmentId` toward a preferred
   * target, walking the adjacency graph and ending at any safe exit. */
  fallbackChain(fromSegmentId: string, preferredToId: string | null): TransitionEdge[] {
    const chain: TransitionEdge[] = [];
    const seen = new Set<string>();
    const outgoing = this.pack.graph.adjacency[fromSegmentId] ?? [];

    const pushEdge = (toId: string) => {
      const edge = [...this.pack.edges.values()].find(
        (e) => e.from === fromSegmentId && e.to === toId,
      );
      if (edge && !seen.has(edge.id)) {
        seen.add(edge.id);
        chain.push(edge);
      }
    };

    if (preferredToId && outgoing.includes(preferredToId)) pushEdge(preferredToId);
    // Then the remaining compiled neighbours, highest quality first.
    outgoing
      .filter((id) => id !== preferredToId)
      .sort((a, b) => {
        const ea = [...this.pack.edges.values()].find((e) => e.from === fromSegmentId && e.to === a);
        const eb = [...this.pack.edges.values()].find((e) => e.from === fromSegmentId && e.to === b);
        return (eb?.quality ?? 0) - (ea?.quality ?? 0);
      })
      .forEach(pushEdge);
    return chain;
  }

  /** Pick the first edge whose audio decodes before the deadline. */
  async resolve(
    fromSegmentId: string,
    preferredToId: string | null,
    deadlineMs: number,
  ): Promise<HotSwapDecision | null> {
    const chain = this.fallbackChain(fromSegmentId, preferredToId);
    if (chain.length === 0) return null;

    const withTimeout = (edge: TransitionEdge) =>
      Promise.race([
        this.pack.loadAudio(edge.asset).then((buffer) => ({ edge, buffer })),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), deadlineMs)),
      ]);

    // Race all candidates; pick the highest-priority one that arrives in time.
    const results = await Promise.all(chain.map(withTimeout));
    for (let i = 0; i < chain.length; i++) {
      const r = results[i];
      if (r) {
        return {
          edge: r.edge,
          buffer: r.buffer,
          technique: r.edge.technique,
          fellBackTo: i === 0 ? null : r.edge.technique,
        };
      }
    }
    return null;
  }
}
