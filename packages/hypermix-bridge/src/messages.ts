/** Versioned webview<->host message envelopes (§35). All traffic carries
 * protocol "hypermix.webview.v1" so the host and webview can evolve safely. */

export const PROTOCOL_VERSION = "hypermix.webview.v1" as const;

export interface Envelope<T = unknown> {
  protocol: typeof PROTOCOL_VERSION;
  id?: string;
  type: string;
  payload: T;
}

export function makeEnvelope<T>(type: string, payload: T, id?: string): Envelope<T> {
  return { protocol: PROTOCOL_VERSION, type, payload, ...(id ? { id } : {}) };
}

export function isEnvelope(value: unknown): value is Envelope {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Envelope).protocol === PROTOCOL_VERSION &&
    typeof (value as Envelope).type === "string"
  );
}

/** Host -> webview notifications. */
export const HostMessages = {
  PackLoaded: "pack.loaded",
  Position: "player.position",
  SegmentEnter: "player.segmentEnter",
  TransitionSwitch: "player.transitionSwitch",
  StateChanged: "player.stateChanged",
  Error: "player.error",
} as const;

/** Webview -> host commands. */
export const WebviewCommands = {
  LoadPack: "pack.load",
  Play: "player.play",
  Stop: "player.stop",
  Next: "player.next",
  HotSwap: "player.hotSwap",
  Seek: "player.seek",
} as const;
