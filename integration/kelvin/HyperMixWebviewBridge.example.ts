/**
 * HyperMixWebviewBridge (EXAMPLE) — webview-side glue. Wraps acquireVsCodeApi
 * as a Transport for HyperMixBridge, then drives the HyperMixPlayer.
 */
import { HyperMixBridge, commands, HostMessages, type Transport } from "@hypermix/bridge";
import { HyperMixPlayer } from "@hypermix/player";

interface VsCodeApi {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

declare function acquireVsCodeApi(): VsCodeApi;

export function bootHyperMixWebview(): void {
  const vscode = acquireVsCodeApi();

  const transport: Transport = {
    postMessage: (m) => vscode.postMessage(m),
    onMessage: (h) => window.addEventListener("message", (e) => h(e.data)),
  };

  const bridge = new HyperMixBridge(transport);
  const player = new HyperMixPlayer(new AudioContext({ sampleRate: 48000 }));

  // Host -> webview notifications.
  bridge.on(HostMessages.PackLoaded, async (p: any) => {
    await player.loadPack(p.rootUrl);
  });

  // Player events -> host (throttled by the scheduler already).
  player.events.on("position", (p) => bridge.notify(HostMessages.Position, p));
  player.events.on("segment.enter", (p) => bridge.notify(HostMessages.SegmentEnter, p));
  player.events.on("transition.switch", (p) => bridge.notify(HostMessages.TransitionSwitch, p));

  // Example UI wiring.
  document.getElementById("play")?.addEventListener("click", () => {
    player.play({ seed: 42, mode: "weighted-random" });
    bridge.notify(HostMessages.StateChanged, { state: "playing" });
  });
  document.getElementById("stop")?.addEventListener("click", () => player.stop());
  document.getElementById("next")?.addEventListener("click", () => player.next());

  // Kick off: ask the host for the pack.
  vscode.postMessage(commands.loadPack({ rootUrl: "pack" }));
}
