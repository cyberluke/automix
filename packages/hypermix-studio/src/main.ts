/** @hypermix/studio entry — wire the bridge + editor when running inside a
 * webview host. The module is side-effect-free so it can be embedded. */

import { HyperMixBridge, type Transport } from "@hypermix/bridge";
import { CrateEditor } from "./editor/CrateEditor";
import { TransitionDesigner } from "./transitions/TransitionDesigner";

export interface StudioApp {
  bridge: HyperMixBridge;
  editor: CrateEditor;
  transitions: TransitionDesigner;
}

export function createStudio(transport: Transport): StudioApp {
  const bridge = new HyperMixBridge(transport);
  return {
    bridge,
    editor: new CrateEditor(bridge),
    transitions: new TransitionDesigner(bridge),
  };
}

export { CrateEditor } from "./editor/CrateEditor";
export type { CrateSummary } from "./editor/CrateEditor";
export { CuePanel } from "./cues/CuePanel";
export type { EditableCue } from "./cues/CuePanel";
export { WaveformView } from "./waveform/WaveformView";
export type { WaveformPeak, CueMarker } from "./waveform/WaveformView";
export { TransitionDesigner } from "./transitions/TransitionDesigner";
export type { PreviewResult } from "./transitions/TransitionDesigner";
