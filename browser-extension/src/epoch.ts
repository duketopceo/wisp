// A ref is "<epoch>:<index>". Each snapshot starts a new epoch, and every
// ref from an older one is refused here and again inside the page.

export type RefParse =
  | { ok: true; epoch: number; index: number }
  | { ok: false; error: string };

export class Epoch {
  constructor(public n = 0) {}

  next(): number {
    this.n += 1;
    return this.n;
  }

  parse(ref: unknown): RefParse {
    const m = /^(\d+):(\d+)$/.exec(String(ref ?? '').trim());
    if (!m) {
      return {
        ok: false,
        error: 'bad ref (expected epoch:index from the last snapshot)',
      };
    }
    const epoch = Number(m[1]);
    if (epoch !== this.n) {
      return {
        ok: false,
        error: `stale ref ${String(ref)} (snapshot again; now at epoch ${this.n})`,
      };
    }
    return { ok: true, epoch, index: Number(m[2]) };
  }
}
