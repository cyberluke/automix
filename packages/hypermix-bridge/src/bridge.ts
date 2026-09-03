/** Bridge — thin transport wrapper with request/response correlation (§35).
 * Transport-agnostic: works over VS Code webview postMessage or a plain
 * MessagePort, with no dependency on either. */

import { isEnvelope, makeEnvelope, type Envelope } from "./messages";

export interface Transport {
  postMessage(message: unknown): void;
  onMessage(handler: (message: unknown) => void): void;
}

type Pending = { resolve: (v: unknown) => void; reject: (e: unknown) => void };

export class HyperMixBridge {
  private pending = new Map<string, Pending>();
  private listeners = new Map<string, Set<(payload: unknown) => void>>();
  private seq = 0;

  constructor(private transport: Transport) {
    transport.onMessage((raw) => this.handle(raw));
  }

  private handle(raw: unknown): void {
    if (!isEnvelope(raw)) return;
    const env = raw as Envelope;
    if (env.id && this.pending.has(env.id)) {
      const p = this.pending.get(env.id)!;
      this.pending.delete(env.id);
      p.resolve(env.payload);
      return;
    }
    this.listeners.get(env.type)?.forEach((h) => h(env.payload));
  }

  on(type: string, handler: (payload: any) => void): () => void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(handler);
    return () => this.listeners.get(type)?.delete(handler);
  }

  notify(type: string, payload: unknown): void {
    this.transport.postMessage(makeEnvelope(type, payload));
  }

  request<T = unknown>(type: string, payload: unknown, timeoutMs = 10000): Promise<T> {
    const id = `req-${++this.seq}`;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
      this.transport.postMessage(makeEnvelope(type, payload, id));
      setTimeout(() => {
        if (this.pending.delete(id)) reject(new Error(`bridge request ${type} timed out`));
      }, timeoutMs);
    });
  }
}
