/**
 * Query-local read transport ownership. No global cache and no mutation retries.
 * Abort/timeout stops browser fetch, not necessarily already-dispatched server work.
 */
export class ReadRequestContext {
  private controller = new AbortController();
  private pending = new Map<string, Promise<unknown>>();
  private queue: Array<() => void> = [];
  private active = 0;
  private readonly identity: string;

  private readonly currentIdentity: () => string;
  private readonly limit: number;
  private readonly timeoutMs: number;

  constructor(currentIdentity: () => string, limit = 4, timeoutMs = 30_000) {
    this.currentIdentity = currentIdentity;
    this.limit = limit;
    this.timeoutMs = timeoutMs;
    this.identity = currentIdentity();
    if (!Number.isInteger(limit) || limit < 1) throw new Error("Invalid concurrency limit");
  }

  get signal() { return this.controller.signal; }

  cancel() {
    this.controller.abort();
    this.queue = [];
    this.pending.clear();
  }

  read<T>(key: string, fetcher: (signal: AbortSignal) => Promise<T>): Promise<T> {
    if (this.identity !== this.currentIdentity()) this.cancel();
    if (this.signal.aborted) return Promise.reject(new DOMException("Read context cancelled", "AbortError"));
    const existing = this.pending.get(key);
    if (existing) return existing as Promise<T>;
    const promise = new Promise<T>((resolve, reject) => {
      const child = new AbortController();
      let started = false;
      let settled = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const finish = (error: unknown, value?: T, failed = true) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.signal.removeEventListener("abort", abort);
        this.pending.delete(key);
        if (started) this.active--;
        if (failed) reject(error); else resolve(value as T);
        this.drain();
      };
      const abort = () => {
        child.abort();
        finish(new DOMException("Read context cancelled", "AbortError"));
      };
      this.signal.addEventListener("abort", abort, { once: true });
      this.queue.push(() => {
        if (settled) return;
        if (this.identity !== this.currentIdentity()) { this.cancel(); return; }
        started = true;
        this.active++;
        timer = setTimeout(() => {
          child.abort();
          finish(new Error("读取超时，请重试"));
        }, this.timeoutMs);
        try {
          fetcher(child.signal).then(value => {
            if (this.identity !== this.currentIdentity()) { this.cancel(); return; }
            finish(null, value, false);
          }, error => finish(error));
        } catch (error) { finish(error); }
      });
    });
    this.pending.set(key, promise);
    this.drain();
    return promise;
  }

  private drain() {
    while (!this.signal.aborted && this.active < this.limit && this.queue.length) this.queue.shift()!();
  }
}
