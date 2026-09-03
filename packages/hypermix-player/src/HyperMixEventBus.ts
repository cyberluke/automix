/** Minimal typed event bus (§34). UI position events are throttled by the
 * scheduler to 10–30 Hz; the musical clock itself stays sample-accurate. */

export type EventHandler<T = unknown> = (payload: T) => void;

export class HyperMixEventBus {
  private handlers = new Map<string, Set<EventHandler<any>>>();

  on<T>(type: string, handler: EventHandler<T>): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type)!.add(handler);
    return () => this.off(type, handler);
  }

  off<T>(type: string, handler: EventHandler<T>): void {
    this.handlers.get(type)?.delete(handler);
  }

  emit<T>(type: string, payload: T): void {
    this.handlers.get(type)?.forEach((h) => h(payload));
  }

  clear(): void {
    this.handlers.clear();
  }
}
