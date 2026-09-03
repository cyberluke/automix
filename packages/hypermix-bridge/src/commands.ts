/** Typed command helpers for the webview side (§35). */

import { makeEnvelope, WebviewCommands, type Envelope } from "./messages";

export interface PlayPayload { seed?: number; mode?: string; targetMood?: string[] }
export interface LoadPackPayload { rootUrl: string }
export interface HotSwapPayload { targetSegmentId: string }
export interface NextPayload { targetMood?: string[] }
export interface SeekPayload { sample: number }

export const commands = {
  loadPack: (payload: LoadPackPayload, id?: string): Envelope<LoadPackPayload> =>
    makeEnvelope(WebviewCommands.LoadPack, payload, id),
  play: (payload: PlayPayload, id?: string): Envelope<PlayPayload> =>
    makeEnvelope(WebviewCommands.Play, payload, id),
  stop: (id?: string): Envelope<Record<string, never>> =>
    makeEnvelope(WebviewCommands.Stop, {}, id),
  next: (payload: NextPayload, id?: string): Envelope<NextPayload> =>
    makeEnvelope(WebviewCommands.Next, payload, id),
  hotSwap: (payload: HotSwapPayload, id?: string): Envelope<HotSwapPayload> =>
    makeEnvelope(WebviewCommands.HotSwap, payload, id),
  seek: (payload: SeekPayload, id?: string): Envelope<SeekPayload> =>
    makeEnvelope(WebviewCommands.Seek, payload, id),
};
