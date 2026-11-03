import { describe, expect, it } from 'vitest';
import { BACKOFF_MS, NativeLink, explain } from '../src/native';
import type { LinkState, Port, Timers } from '../src/native';
import { PROTOCOL } from '../src/protocol';
import type { Command } from '../src/protocol';

class FakePort implements Port {
  sent: unknown[] = [];
  closed = false;
  private onMsg: ((m: unknown) => void)[] = [];
  private onDisc: (() => void)[] = [];
  onMessage = { addListener: (cb: (m: unknown) => void) => void this.onMsg.push(cb) };
  onDisconnect = { addListener: (cb: () => void) => void this.onDisc.push(cb) };
  postMessage(m: unknown): void {
    this.sent.push(m);
  }
  disconnect(): void {
    this.closed = true;
  }
  // test side
  say(m: unknown): void {
    this.onMsg.forEach((cb) => cb(m));
  }
  drop(): void {
    this.onDisc.forEach((cb) => cb());
  }
}

class FakeTimers implements Timers {
  pending: { fn: () => void; ms: number; id: number }[] = [];
  private n = 0;
  set(fn: () => void, ms: number): unknown {
    const id = (this.n += 1);
    this.pending.push({ fn, ms, id });
    return id;
  }
  clear(h: unknown): void {
    this.pending = this.pending.filter((p) => p.id !== h);
  }
  /** Run the one pending timer, returning the delay it was set for. */
  fire(): number {
    const t = this.pending.shift();
    if (!t) throw new Error('no timer pending');
    t.fn();
    return t.ms;
  }
}

function setup(opts: { lastError?: string; throwOnConnect?: string } = {}) {
  const ports: FakePort[] = [];
  const states: LinkState[] = [];
  const cmds: Command[] = [];
  const timers = new FakeTimers();
  const link = new NativeLink(
    () => {
      if (opts.throwOnConnect) throw new Error(opts.throwOnConnect);
      const p = new FakePort();
      ports.push(p);
      return p;
    },
    { onCommand: (c) => cmds.push(c), onState: (s) => states.push(s) },
    timers,
    () => opts.lastError,
    '0.2.0',
  );
  return { link, ports, states, cmds, timers };
}

describe('explain', () => {
  it.each([
    ['Specified native messaging host not found.', 'host_missing'],
    ['Access to the specified native messaging host is forbidden.', 'host_forbidden'],
    ['Native host has exited.', 'host_exited'],
    [undefined, 'host_exited'],
  ])('%s -> %s', (text, code) => {
    expect(explain(text).code).toBe(code);
  });
});

describe('NativeLink', () => {
  it('does nothing until it is started', () => {
    const { link, ports, states } = setup();
    expect(link.current).toEqual({ kind: 'off' });
    expect(ports).toHaveLength(0);
    expect(states).toHaveLength(0);
  });

  it('says hello and is connected after hello_ok', () => {
    const { link, ports } = setup();
    link.start();
    expect(link.current).toEqual({ kind: 'connecting' });
    expect(ports[0]!.sent).toEqual([{ t: 'hello', v: PROTOCOL, ext: '0.2.0' }]);
    ports[0]!.say({ t: 'hello_ok', v: PROTOCOL });
    expect(link.current).toEqual({ kind: 'connected' });
  });

  it('will not send before it is connected', () => {
    const { link, ports } = setup();
    expect(link.send({ t: 'stop' })).toBe(false);
    link.start();
    expect(link.send({ t: 'stop' })).toBe(false);
    ports[0]!.say({ t: 'hello_ok', v: PROTOCOL });
    expect(link.send({ t: 'stop' })).toBe(true);
    expect(ports[0]!.sent.at(-1)).toEqual({ t: 'stop' });
  });

  it('hands valid commands to the handler and drops junk', () => {
    const { link, ports, cmds } = setup();
    link.start();
    const p = ports[0]!;
    p.say({ t: 'hello_ok', v: PROTOCOL });
    p.say({ t: 'cmd', cmd: { id: 'c1', op: 'batch', steps: [{ do: 'snapshot' }] } });
    p.say({ t: 'cmd', cmd: { id: 'c2', op: 'rm -rf' } });
    p.say('garbage');
    expect(cmds.map((c) => c.id)).toEqual(['c1']);
  });

  it('reconnects with back-off, then gives up and says why', () => {
    const { link, ports, timers } = setup({ lastError: 'Specified native messaging host not found.' });
    link.start();
    const delays: number[] = [];
    for (let i = 0; i < BACKOFF_MS.length; i++) {
      ports[i]!.drop();
      expect(link.current).toEqual({ kind: 'connecting' });
      delays.push(timers.fire());
    }
    expect(delays).toEqual(BACKOFF_MS);
    ports[BACKOFF_MS.length]!.drop();
    expect(link.current).toEqual({
      kind: 'unavailable',
      code: 'host_missing',
      message: 'The Wisp native host is not installed.',
    });
    expect(timers.pending).toHaveLength(0);
    expect(ports).toHaveLength(BACKOFF_MS.length + 1);
  });

  it('prefers the host’s own error over the generic reason', () => {
    const { link, ports, timers } = setup();
    link.start();
    ports[0]!.say({ t: 'error', code: 'wisp_unavailable', message: 'Wisp is not running.' });
    ports[0]!.drop();
    for (let i = 1; i < BACKOFF_MS.length; i++) {
      timers.fire();
      ports[i]!.say({ t: 'error', code: 'wisp_unavailable', message: 'Wisp is not running.' });
      ports[i]!.drop();
    }
    timers.fire();
    ports.at(-1)!.say({ t: 'error', code: 'wisp_unavailable', message: 'Wisp is not running.' });
    ports.at(-1)!.drop();
    expect(link.current).toEqual({
      kind: 'unavailable',
      code: 'wisp_unavailable',
      message: 'Wisp is not running.',
    });
  });

  it('starts the back-off over after a good connection', () => {
    const { link, ports, timers } = setup();
    link.start();
    ports[0]!.drop();
    expect(timers.fire()).toBe(BACKOFF_MS[0]);
    ports[1]!.say({ t: 'hello_ok', v: PROTOCOL });
    ports[1]!.drop();
    expect(timers.fire()).toBe(BACKOFF_MS[0]);
  });

  it('treats a throwing connect like a drop', () => {
    const { link, timers } = setup({ throwOnConnect: 'Specified native messaging host not found.' });
    link.start();
    expect(link.current).toEqual({ kind: 'connecting' });
    expect(timers.pending).toHaveLength(1);
  });

  it('stop says bye, disconnects, cancels the retry and stays off', () => {
    const { link, ports, timers } = setup();
    link.start();
    ports[0]!.say({ t: 'hello_ok', v: PROTOCOL });
    link.stop();
    expect(ports[0]!.sent.at(-1)).toEqual({ t: 'bye' });
    expect(ports[0]!.closed).toBe(true);
    expect(link.current).toEqual({ kind: 'off' });
    ports[0]!.drop(); // a late event from the old port changes nothing
    expect(link.current).toEqual({ kind: 'off' });
    expect(timers.pending).toHaveLength(0);
    expect(ports).toHaveLength(1);
  });

  it('stop during a pending retry cancels it', () => {
    const { link, ports, timers } = setup();
    link.start();
    ports[0]!.drop();
    expect(timers.pending).toHaveLength(1);
    link.stop();
    expect(timers.pending).toHaveLength(0);
    expect(link.current).toEqual({ kind: 'off' });
  });

  it('ignores messages from a port it has replaced', () => {
    const { link, ports, timers, cmds } = setup();
    link.start();
    ports[0]!.drop();
    timers.fire();
    ports[0]!.say({ t: 'cmd', cmd: { id: 'old', op: 'batch', steps: [] } });
    expect(cmds).toHaveLength(0);
    expect(link.current).toEqual({ kind: 'connecting' });
  });

  it('start again after unavailable tries afresh', () => {
    const { link, ports, timers } = setup();
    link.start();
    for (let i = 0; i < BACKOFF_MS.length; i++) {
      ports[i]!.drop();
      timers.fire();
    }
    ports.at(-1)!.drop();
    expect(link.current.kind).toBe('unavailable');
    const before = ports.length;
    link.start();
    expect(link.current).toEqual({ kind: 'connecting' });
    expect(ports).toHaveLength(before + 1);
  });
});
