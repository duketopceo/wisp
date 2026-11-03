import { describe, expect, it } from 'vitest';
import { Lane, emptyState } from '../src/lane';
import type { LaneState } from '../src/lane';
import { pageAct } from '../src/page/act';
import { pageScroll, pageWait } from '../src/page/misc';
import { pageSnapshot } from '../src/page/snapshot';
import { RULE } from '../src/fieldrule';
import type { Command } from '../src/protocol';
import { harness, until } from './fakes';

const SITE = 'http://127.0.0.1:8123/*';
const batch = (steps: Command['steps'], extra: Partial<Command> = {}): Command => ({
  id: 'c1',
  op: 'batch',
  task: 't1',
  steps,
  ...extra,
});
const open = { do: 'open', url: 'http://127.0.0.1:8123/login' };

async function opened() {
  const h = harness();
  h.chrome.grant(SITE);
  const lane = new Lane(h.env);
  const r = await lane.execute(batch([open]));
  return { h, lane, r };
}

describe('Lane: opening pages', () => {
  it('opens in the background, in a group named Wisp, and logs the host', async () => {
    const { h, r } = await opened();
    expect(r.ok).toBe(true);
    expect(h.chrome.calls).toEqual([
      'tabs.create http://127.0.0.1:8123/login active=false',
      'tabs.group 100 group=new',
      'tabGroups.update 500 Wisp',
    ]);
    expect(h.logs).toEqual([{ task: 't1', op: 'open', host: '127.0.0.1:8123', ok: true }]);
  });

  it('puts later tabs of the task in the same group', async () => {
    const { h, lane } = await opened();
    await lane.execute(batch([open]));
    expect(h.chrome.calls).toContain('tabs.group 101 group=500');
  });

  it.each(['file:///etc/passwd', 'chrome://settings', 'javascript:alert(1)', 'data:text/html,x'])(
    'refuses to open %s',
    async (url) => {
      const h = harness();
      const r = await new Lane(h.env).execute(batch([{ do: 'open', url }]));
      expect(r.ok).toBe(false);
      expect(r.error).toBe('only http and https pages can be opened');
      expect(h.chrome.calls).toEqual([]);
    },
  );

  it('closes and refuses a tab that turns out to be private', async () => {
    const h = harness();
    h.chrome.grant(SITE);
    h.chrome.incognitoNext = true;
    const r = await new Lane(h.env).execute(batch([open]));
    expect(r.error).toBe('private windows are not supported');
    expect(h.chrome.calls).toContain('tabs.remove 100');
    expect(h.chrome.calls.some((c) => c.startsWith('tabs.group'))).toBe(false);
  });
});

describe('Lane: batches', () => {
  it('refuses an empty batch and an oversized one', async () => {
    const h = harness();
    const lane = new Lane(h.env);
    expect((await lane.execute(batch([]))).error).toBe('no steps');
    const many = Array.from({ length: 21 }, () => ({ do: 'snapshot' }));
    expect((await lane.execute(batch(many))).error).toBe('too many steps (21, most is 20)');
  });

  it('stops at the first failing step and reports the ones before it', async () => {
    const { h, lane } = await opened();
    const r = await lane.execute(batch([{ do: 'click', ref: '1:0' }, { do: 'snapshot' }]));
    expect(r.ok).toBe(false);
    expect(r.results).toHaveLength(1);
    expect(r.error).toMatch(/^stale ref 1:0/);
    expect(h.logs.at(-1)).toMatchObject({ op: 'click', ok: false });
  });

  it('says so for a step it does not know', async () => {
    const { lane } = await opened();
    const r = await lane.execute(batch([{ do: 'eval', code: '1' }]));
    expect(r.error).toBe('unknown step eval');
  });

  it('refuses a tab that is not one of its own', async () => {
    const { lane } = await opened();
    const r = await lane.execute(batch([{ do: 'snapshot', tab: 1 }]));
    expect(r.error).toBe("tab 1 is not one of Wisp's tabs");
  });

  it('needs a page before anything else', async () => {
    const h = harness();
    const r = await new Lane(h.env).execute(batch([{ do: 'snapshot' }]));
    expect(r.error).toBe('no tab yet: open a page first');
  });
});

describe('Lane: snapshots, refs and the password rule', () => {
  it('snapshots with a new epoch each time and passes the shared rule to the page', async () => {
    const { h, lane } = await opened();
    h.chrome.page.set(pageSnapshot as never, (args) => ({ ok: true, epoch: (args as number[])[0] }));
    const r1 = await lane.execute(batch([{ do: 'snapshot' }]));
    const r2 = await lane.execute(batch([{ do: 'snapshot' }]));
    expect(r1.results[0]).toMatchObject({ ok: true, epoch: 1, tab: 100 });
    expect(r2.results[0]).toMatchObject({ epoch: 2 });
    expect(h.chrome.injected[0]!.args).toEqual([1, RULE]);
  });

  it('refuses a ref from before the latest snapshot without touching the page', async () => {
    const { h, lane } = await opened();
    h.chrome.page.set(pageSnapshot as never, () => ({ ok: true }));
    await lane.execute(batch([{ do: 'snapshot' }]));
    await lane.execute(batch([{ do: 'snapshot' }]));
    const before = h.chrome.injected.length;
    const r = await lane.execute(batch([{ do: 'fill', ref: '1:0', value: 'x' }]));
    expect(r.error).toBe('stale ref 1:0 (snapshot again; now at epoch 2)');
    expect(h.chrome.injected).toHaveLength(before);
  });

  it('passes the page’s refusal of a password field back as the step error', async () => {
    const { h, lane } = await opened();
    h.chrome.page.set(pageSnapshot as never, () => ({ ok: true }));
    h.chrome.page.set(pageAct as never, () => ({
      ok: false,
      error: 'refused: sensitive field (password, one-time code or card)',
    }));
    await lane.execute(batch([{ do: 'snapshot' }]));
    const r = await lane.execute(batch([{ do: 'fill', ref: '1:0', value: 'hunter2' }]));
    expect(r.ok).toBe(false);
    expect(r.error).toBe('refused: sensitive field (password, one-time code or card)');
    // the value reached the page function only as an argument, never the lane's log
    expect(JSON.stringify(h.logs)).not.toContain('hunter2');
    expect(h.chrome.injected.at(-1)!.args).toEqual([1, 0, 'fill', 'hunter2', RULE]);
  });

  it('fills when the page accepts', async () => {
    const { h, lane } = await opened();
    h.chrome.page.set(pageSnapshot as never, () => ({ ok: true }));
    h.chrome.page.set(pageAct as never, () => ({ ok: true }));
    await lane.execute(batch([{ do: 'snapshot' }]));
    const r = await lane.execute(batch([{ do: 'fill', ref: '1:2', value: 'ada' }]));
    expect(r.ok).toBe(true);
  });
});

describe('Lane: wait_for, scroll, screenshot', () => {
  it('waits in 250 ms polls and gives up at its limit', async () => {
    const h = harness({ sleep: async () => {} });
    h.chrome.grant(SITE);
    const lane = new Lane(h.env);
    await lane.execute(batch([open]));
    h.chrome.page.set(pageWait as never, () => false);
    const r = await lane.execute(batch([{ do: 'wait_for', text: 'never', timeout_ms: 1000 }]));
    expect(r.error).toBe('wait_for timed out');
    expect(h.chrome.injected.filter((i) => i.func === (pageWait as never))).toHaveLength(4);
  });

  it('caps the wait at fifteen seconds', async () => {
    const h = harness({ sleep: async () => {} });
    h.chrome.grant(SITE);
    const lane = new Lane(h.env);
    await lane.execute(batch([open]));
    h.chrome.page.set(pageWait as never, () => false);
    await lane.execute(batch([{ do: 'wait_for', text: 'x', timeout_ms: 600000 }]));
    expect(h.chrome.injected.filter((i) => i.func === (pageWait as never))).toHaveLength(60);
  });

  it('returns as soon as the text shows', async () => {
    const { h, lane } = await opened();
    h.chrome.page.set(pageWait as never, () => true);
    const r = await lane.execute(batch([{ do: 'wait_for', text: 'hi' }]));
    expect(r.results[0]).toMatchObject({ ok: true, waited_ms: 0 });
  });

  it('scrolls', async () => {
    const { h, lane } = await opened();
    h.chrome.page.set(pageScroll as never, (a) => ({ y: (a as number[])[0] }));
    const r = await lane.execute(batch([{ do: 'scroll', dy: 300 }]));
    expect(r.results[0]).toMatchObject({ y: 300 });
  });

  it('takes the screenshot and puts the user’s own tab back', async () => {
    const { h, lane } = await opened();
    h.chrome.grant('<all_urls>');
    const r = await lane.execute(batch([{ do: 'screenshot' }]));
    expect(r.results[0]).toMatchObject({ ok: true, png: 'QUJD' });
    const calls = h.chrome.calls.slice(-3);
    expect(calls).toEqual(['tabs.update 100 active=true', 'tabs.capture active=100', 'tabs.update 1 active=true']);
    expect(h.chrome.activeTab).toBe(1);
  });

  it('asks for all sites before a screenshot, because Chrome requires it', async () => {
    const { h, lane } = await opened();
    const run = lane.execute(batch([{ do: 'screenshot' }]));
    await until(() => h.grants.length > 0);
    expect(h.grants.at(-1)).toEqual({ host: 'all sites', pattern: '<all_urls>' });
    expect(h.chrome.calls.some((c) => c.startsWith('tabs.capture'))).toBe(false);
    h.chrome.grant('<all_urls>');
    expect((await run).ok).toBe(true);
    expect(h.chrome.calls.some((c) => c.startsWith('tabs.capture'))).toBe(true);
  });

  it('restores the user’s tab even when the capture fails', async () => {
    const { h, lane } = await opened();
    h.chrome.grant('<all_urls>');
    const api = h.env.api.tabs as unknown as { captureVisibleTab: () => Promise<string> };
    api.captureVisibleTab = async () => {
      throw new Error('capture failed');
    };
    const r = await lane.execute(batch([{ do: 'screenshot' }]));
    expect(r.error).toBe('capture failed');
    expect(h.chrome.activeTab).toBe(1);
  });
});

describe('Lane: ending, keeping and stopping', () => {
  it('done closes the task’s tabs', async () => {
    const { h, lane } = await opened();
    await lane.execute(batch([{ do: 'done' }]));
    expect(h.chrome.calls).toContain('tabs.remove 100');
    expect(h.chrome.tabs.has(100)).toBe(false);
  });

  it('keep ungroups a tab and it survives done', async () => {
    const { h, lane } = await opened();
    await lane.execute(batch([{ do: 'keep' }]));
    await lane.execute(batch([{ do: 'done' }]));
    expect(h.chrome.calls).toContain('tabs.ungroup 100');
    expect(h.chrome.tabs.has(100)).toBe(true);
  });

  it('end_task closes quietly even when the user closed a tab first', async () => {
    const { h, lane } = await opened();
    h.chrome.removeFails.add(100);
    const r = await lane.execute({ id: 'c9', op: 'end_task', task: 't1' });
    expect(r).toEqual({ ok: true, results: [] });
  });

  it('stop closes the tabs, and a batch started after it runs nothing', async () => {
    const { h, lane } = await opened();
    await lane.stop();
    expect(h.chrome.tabs.has(100)).toBe(false);
    const before = h.chrome.calls.length;
    const r = await lane.execute(batch([open]));
    expect(r).toEqual({ ok: false, error: 'stopped', results: [] });
    expect(h.chrome.calls).toHaveLength(before);
  });

  it('a resume command lifts the stop', async () => {
    const { h, lane } = await opened();
    await lane.stop();
    const r = await lane.execute(batch([open], { resume: true }));
    expect(r.ok).toBe(true);
    expect(h.chrome.tabs.has(101)).toBe(true);
  });

  it('stop ends a wait_for between polls', async () => {
    const h = harness({ sleep: async () => {} });
    h.chrome.grant(SITE);
    const lane = new Lane(h.env);
    await lane.execute(batch([open]));
    let polls = 0;
    h.chrome.page.set(pageWait as never, () => {
      polls += 1;
      if (polls === 2) void lane.stop();
      return false;
    });
    const r = await lane.execute(batch([{ do: 'wait_for', text: 'x', timeout_ms: 15000 }]));
    expect(r.error).toBe('stopped');
    expect(polls).toBe(2);
  });
});

describe('Lane: the user’s say over each site', () => {
  it('waits for the grant, shows what it waits for, and carries on when it arrives', async () => {
    const h = harness();
    const lane = new Lane(h.env);
    const run = lane.execute(batch([open]));
    await until(() => h.grants.length > 0);
    expect(h.grants).toEqual([{ host: '127.0.0.1:8123', pattern: SITE }]);
    expect(h.chrome.calls).toEqual([]); // nothing opened yet
    h.chrome.grant(SITE);
    const r = await run;
    expect(r.ok).toBe(true);
    expect(h.grants.at(-1)).toBeNull();
    expect(h.chrome.addedListeners.size).toBe(0); // no leaked listener
  });

  it('gives up with a clear error when the user never answers', async () => {
    const h = harness({ sleep: async () => {} });
    const r = await new Lane(h.env).execute(batch([open]));
    expect(r.error).toBe('not allowed: 127.0.0.1:8123 was not granted in the side panel');
    expect(h.chrome.calls).toEqual([]);
    expect(h.grants.at(-1)).toBeNull();
  });

  it('a grant for another site does not satisfy it', async () => {
    const h = harness();
    const lane = new Lane(h.env);
    const run = lane.execute(batch([open]));
    await until(() => h.grants.length > 0);
    h.chrome.grant('https://other.test/*');
    await until(() => h.chrome.addedListeners.size > 0);
    await new Promise<void>((r) => setTimeout(r, 0));
    expect(h.chrome.calls).toEqual([]);
    await lane.stop();
    expect((await run).error).toBe('stopped');
  });

  it('stop ends the wait at once', async () => {
    const h = harness();
    const lane = new Lane(h.env);
    const run = lane.execute(batch([open]));
    await until(() => h.grants.length > 0);
    await lane.stop();
    const r = await run;
    expect(r.error).toBe('stopped');
    expect(h.chrome.calls).toEqual([]);
  });

  it('checks the grant again before acting on a tab, so a revoke takes effect', async () => {
    const { h, lane } = await opened();
    h.chrome.granted.clear();
    h.env.grantWaitMs = 1;
    const sleepNow = h.env as unknown as { sleep: () => Promise<void> };
    sleepNow.sleep = async () => {};
    h.chrome.page.set(pageSnapshot as never, () => ({ ok: true }));
    const r = await lane.execute(batch([{ do: 'snapshot' }]));
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/^not allowed: /);
    expect(h.chrome.injected).toHaveLength(0);
  });
});

describe('Lane: surviving a service-worker restart', () => {
  it('saves state after a batch and a new Lane resumes from it', async () => {
    const { h, lane } = await opened();
    h.chrome.page.set(pageSnapshot as never, () => ({ ok: true }));
    await lane.execute(batch([{ do: 'snapshot' }]));
    const state = h.saved.at(-1) as LaneState;
    expect(state.tabs).toEqual({ t1: [100] });
    expect(state.groups).toEqual({ t1: 500 });
    expect(state.epoch).toBe(1);

    const again = new Lane(h.env, structuredClone(state));
    h.chrome.page.set(pageAct as never, () => ({ ok: true }));
    // the old epoch is still current: its refs still work after the restart
    expect((await again.execute(batch([{ do: 'click', ref: '1:0' }]))).ok).toBe(true);
    // and the new one carries on counting
    h.chrome.page.set(pageSnapshot as never, (a) => ({ ok: true, epoch: (a as number[])[0] }));
    expect((await again.execute(batch([{ do: 'snapshot' }]))).results[0]).toMatchObject({ epoch: 2 });
  });

  it('starts empty with no saved state', () => {
    expect(emptyState()).toEqual({ groups: {}, tabs: {}, kept: {}, current: {}, epoch: 0 });
  });
});

describe('Lane: waiting for a page to load', () => {
  it('notices a page that finished loading before anyone listened', async () => {
    const h = harness({ sleep: async () => {} });
    h.chrome.grant(SITE);
    const api = h.env.api.tabs as unknown as { create: (p: { url: string }) => Promise<{ id: number; status: string }> };
    const create = api.create.bind(api);
    let polls = 0;
    api.create = async (p) => {
      const t = await create(p);
      h.chrome.tabs.get(t.id)!.status = 'loading';
      return t;
    };
    const get = h.env.api.tabs.get.bind(h.env.api.tabs);
    (h.env.api.tabs as unknown as { get: typeof get }).get = async (id: number) => {
      polls += 1;
      // no update event is ever sent: only the status changes
      if (polls === 3) h.chrome.tabs.get(id)!.status = 'complete';
      return get(id);
    };
    const r = await new Lane(h.env).execute(batch([open]));
    expect(r.ok).toBe(true);
    expect(polls).toBe(3);
    expect(h.chrome.updatedListeners.size).toBe(0);
  });

  it('gives up at its limit instead of hanging on a page that never loads', async () => {
    const h = harness({ sleep: async () => {} });
    h.chrome.grant(SITE);
    const tabs = h.env.api.tabs as unknown as { create: (p: { url: string }) => Promise<{ id: number }> };
    const create = tabs.create.bind(tabs);
    tabs.create = async (p) => {
      const t = await create(p);
      h.chrome.tabs.get(t.id)!.status = 'loading';
      return t;
    };
    const r = await new Lane(h.env).execute(batch([open]));
    expect(r.ok).toBe(true);
  });

  it('wakes on the update event without waiting out the poll', async () => {
    let wake: (() => void) | undefined;
    const h = harness({ sleep: () => new Promise<void>(() => {}) });
    h.chrome.grant(SITE);
    const tabs = h.env.api.tabs as unknown as { create: (p: { url: string }) => Promise<{ id: number }> };
    const create = tabs.create.bind(tabs);
    tabs.create = async (p) => {
      const t = await create(p);
      h.chrome.tabs.get(t.id)!.status = 'loading';
      wake = () => {
        h.chrome.tabs.get(t.id)!.status = 'complete';
        h.chrome.updatedListeners.forEach((cb) => cb(t.id, { status: 'complete' }));
      };
      return t;
    };
    const run = new Lane(h.env).execute(batch([open]));
    await until(() => wake !== undefined);
    wake?.();
    expect((await run).ok).toBe(true);
  });
});
