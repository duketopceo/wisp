import { describe, expect, it } from 'vitest';
import { Epoch } from '../src/epoch';

describe('Epoch', () => {
  it('counts up from where it was given', () => {
    const e = new Epoch(4);
    expect(e.next()).toBe(5);
    expect(e.next()).toBe(6);
  });

  it('accepts a ref from the current epoch', () => {
    const e = new Epoch();
    e.next();
    expect(e.parse('1:7')).toEqual({ ok: true, epoch: 1, index: 7 });
    expect(e.parse(' 1:0 ')).toEqual({ ok: true, epoch: 1, index: 0 });
  });

  it('refuses a ref from an older snapshot and says what to do', () => {
    const e = new Epoch();
    e.next();
    e.next();
    const r = e.parse('1:3');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe('stale ref 1:3 (snapshot again; now at epoch 2)');
  });

  it.each([undefined, null, '', 'x', '1', '1:', ':1', '1:2:3', '-1:2', '1:-2', 12])(
    'refuses the malformed ref %j',
    (ref) => {
      const e = new Epoch(1);
      expect(e.parse(ref).ok).toBe(false);
    },
  );
});
