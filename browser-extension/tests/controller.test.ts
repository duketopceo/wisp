import { describe, expect, it } from 'vitest';
import { Controller } from '../src/controller';
import type { ControllerDeps, LinkLike } from '../src/controller';
import type { LinkState } from '../src/native';
import type { BatchResult, Command, ToHost } from '../src/protocol';
import { initialUi } from '../src/state';
import type { UiState } from '../src/state';

function setup(opts: { consent?: boolean; prior?: UiState | null; result?: BatchResult } = {}) {
  let consent = opts.consent ?? false;
  const sent: ToHost[] = [];
  const events: string[] = [];
  const saved: UiState[] = [];
  const badges: string[] = [];
  let handlers!: { onCommand(c: Command): void; onState(s: LinkState): void };
  let linkUp = false;
  const link: LinkLike = {
    start: () => void events.push('link.start'),
    stop: () => {
      events.push('link.stop');
      linkUp = false;
    },
    send: (m) => {
      if (!linkUp) return false;
      sent.push(m);
      return true;
    },
  };
  const laneCalls: Command[] = [];
  let release: (() => void) | null = null;
  const deps: ControllerDeps = {
    makeLink: (h) => {
      handlers = h;
      return link;
    },
    lane: {
      execute: async (cmd) => {
        laneCalls.push(cmd);
        if (opts.result) return opts.result;
        await new Promise<void>((r) => (release = r));
        return { ok: true, results: [] };
      },
      stop: async () => void events.push('lane.stop'),
    },
    getConsent: async () => consent,
    setConsent: async (on) => {
      consent = on;
      events.push(`consent=${on}`);
    },
    loadUi: async () => opts.prior ?? null,
    saveUi: (ui) => void saved.push(structuredClone(ui)),
    badge: (ui) => void badges.push(`${ui.consent}/${ui.link.kind}`),
  };
  const c = new Controller(deps);
  return {
    c,
    sent,
    events,
    saved,
    badges,
    laneCalls,
    finish: () => release?.(),
    connectLink: () => {
      linkUp = true;
      handlers.onState({ kind: 'connected' });
    },
    command: (cmd: Command) => handlers.onCommand(cmd),
  };
}

const cmd = (extra: Partial<Command> = {}): Command => ({
  id: 'c1',
  op: 'batch',
  task: 't',
  steps: [{ do: 'snapshot' }],
  ...extra,
});
const flush = () => new Promise<void>((r) => setTimeout(r, 0));

describe('Controller: consent and pairing that survives a restart', () => {
  it('does not connect on start without consent', async () => {
    const t = setup({ consent: false });
    await t.c.init();
    expect(t.events).toEqual([]);
    expect(t.c.ui.consent).toBe(false);
  });

  it('reconnects on start when the user connected before (a browser restart)', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    expect(t.events).toEqual(['link.start']);
    expect(t.c.ui.consent).toBe(true);
  });

  it('Connect stores consent first, then starts the link', async () => {
    const t = setup();
    await t.c.init();
    await t.c.onMessage({ type: 'connect' });
    expect(t.events).toEqual(['consent=true', 'link.start']);
    expect(t.c.ui.consent).toBe(true);
  });

  it('Disconnect withdraws consent, stops the link and the lane, and leaves a clean panel', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    t.connectLink();
    await t.c.onMessage({ type: 'disconnect' });
    expect(t.events).toEqual(['link.start', 'consent=false', 'link.stop', 'lane.stop']);
    expect(t.c.ui.consent).toBe(false);
    expect(t.c.ui.stopped).toBe(false);
  });

  it('Retry reconnects only for a user who consented', async () => {
    const off = setup();
    await off.c.init();
    await off.c.onMessage({ type: 'retry' });
    expect(off.events).toEqual([]);
    const on = setup({ consent: true });
    await on.c.init();
    await on.c.onMessage({ type: 'retry' });
    expect(on.events).toEqual(['link.start', 'link.start']);
  });

  it('ignores messages that are not its own', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    for (const m of [null, 'connect', { type: 'rm' }, { type: 42 }, {}]) await t.c.onMessage(m);
    expect(t.events).toEqual(['link.start']);
  });

  it('restores the step log after a worker restart but not the link', async () => {
    const prior = initialUi();
    prior.log = [{ n: 7, task: 't', op: 'open', host: 'a.test', ok: true }];
    prior.link = { kind: 'connected' };
    const t = setup({ consent: true, prior });
    await t.c.init();
    expect(t.c.ui.log).toHaveLength(1);
    expect(t.c.ui.link).toEqual({ kind: 'off' });
    t.c.logEntry({ task: 't', op: 'click', host: '', ok: true });
    expect(t.c.ui.log.map((r) => r.n)).toEqual([7, 8]);
  });
});

describe('Controller: commands', () => {
  it('runs a command in the lane and sends the result with its id', async () => {
    const t = setup({ consent: true, result: { ok: true, results: [{ ok: true }] } });
    await t.c.init();
    t.connectLink();
    t.command(cmd({ id: 'c42' }));
    await flush();
    expect(t.sent).toEqual([{ t: 'result', id: 'c42', ok: true, results: [{ ok: true }] }]);
    expect(t.c.ui.running).toBe(false);
  });

  it('shows running while the lane works', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    t.connectLink();
    t.command(cmd());
    await flush();
    expect(t.c.ui.running).toBe(true);
    t.finish();
    await flush();
    expect(t.c.ui.running).toBe(false);
  });

  it('turns a lane that throws into a failed result instead of silence', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    t.connectLink();
    (t.c as unknown as { d: ControllerDeps }).d.lane.execute = async () => {
      throw new Error('boom');
    };
    t.command(cmd({ id: 'c5' }));
    await flush();
    expect(t.sent).toEqual([{ t: 'result', id: 'c5', ok: false, error: 'boom', results: [] }]);
  });

  it('a stopped result marks the panel stopped; a resume command clears it', async () => {
    const t = setup({ consent: true, result: { ok: false, error: 'stopped', results: [] } });
    await t.c.init();
    t.connectLink();
    t.command(cmd());
    await flush();
    expect(t.c.ui.stopped).toBe(true);
    (t.c as unknown as { d: ControllerDeps }).d.lane.execute = async () => ({ ok: true, results: [] });
    t.command(cmd({ id: 'c2', resume: true }));
    await flush();
    expect(t.c.ui.stopped).toBe(false);
  });
});

describe('Controller: Stop', () => {
  it('tells wispd and the lane, in that order, and shows stopped', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    t.connectLink();
    t.c.needGrant({ host: 'a.test', pattern: 'https://a.test/*' });
    await t.c.onMessage({ type: 'stop' });
    expect(t.sent).toEqual([{ t: 'stop' }]);
    expect(t.events.at(-1)).toBe('lane.stop');
    expect(t.c.ui).toMatchObject({ stopped: true, running: false, pendingGrant: null });
  });

  it('works from the keyboard shortcut path too', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    t.connectLink();
    await t.c.stop();
    expect(t.c.ui.stopped).toBe(true);
  });

  it('still stops the lane when the link is down', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    await t.c.stop();
    expect(t.sent).toEqual([]);
    expect(t.events).toContain('lane.stop');
  });
});

describe('Controller: what it publishes', () => {
  it('saves state and sets the badge on every change', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    t.connectLink();
    expect(t.saved.at(-1)!.link).toEqual({ kind: 'connected' });
    expect(t.badges.at(-1)).toBe('true/connected');
  });

  it('keeps the newest hundred log rows', async () => {
    const t = setup({ consent: true });
    await t.c.init();
    for (let i = 0; i < 130; i++) t.c.logEntry({ task: 't', op: 'snapshot', host: '', ok: true });
    expect(t.c.ui.log).toHaveLength(100);
    expect(t.c.ui.log[0]!.n).toBe(31);
    expect(t.c.ui.log.at(-1)!.n).toBe(130);
  });
});
