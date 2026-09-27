// A FIFO slot limiter. A released slot passes straight to the next waiter.
export class Semaphore {
  private active = 0;
  private waiting: (() => void)[] = [];
  constructor(private limit: number) {}
  async run<T>(task: () => Promise<T>) {
    if (this.active < this.limit) this.active++;
    else await new Promise<void>(resolve => this.waiting.push(resolve));
    try { return await task(); }
    finally { const next = this.waiting.shift(); if (next) next(); else this.active--; }
  }
}
