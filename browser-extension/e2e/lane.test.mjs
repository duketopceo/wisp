// The extension against the real wispd lane, in headless Chromium, on
// local fixture pages. Every wait is for an observable state with a
// bound, never a sleep.
import AxeSource from 'axe-core';
import assert from 'node:assert/strict';
import { after, before, describe, test } from 'node:test';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import {
  EXT_ID,
  installHost,
  launchBrowser,
  openPanel,
  scratch,
  serveFixtures,
  startLane,
  tabInfo,
} from './harness.mjs';

const TIMEOUT = 20_000;
let fixtures;
before(async () => {
  fixtures = await serveFixtures();
});
after(() => fixtures.close());

/** A scratch home, the real host install, wispd's lane and a browser. */
async function world({ host = true, consent = false, hosts = 'site' } = {}) {
  const s = scratch();
  if (host) installHost(s);
  const lane = await startLane(s);
  let ctx = await launchBrowser(s, hosts);
  const w = {
    s,
    lane,
    ctx,
    async panel() {
      return openPanel(w.ctx);
    },
    async connect(panel) {
      await panel.getByRole('button', { name: 'Connect Wisp' }).click();
      await panel.getByRole('heading', { name: 'Connected' }).waitFor({ timeout: TIMEOUT });
    },
    async restart() {
      await w.ctx.close();
      w.ctx = await launchBrowser(s, hosts);
    },
    async close() {
      await w.ctx.close().catch(() => {});
      lane.close();
      s.remove();
    },
  };
  if (consent) await w.connect(await w.panel());
  return w;
}

const refOf = (out, re) => {
  const m = new RegExp(`(\\d+:\\d+) ${re}`).exec(out);
  assert.ok(m, `no element matching ${re} in:\n${out}`);
  return m[1];
};

describe('the extension and wispd', () => {
  test('is off until the user presses Connect: nothing pairs, nothing opens', async () => {
    const w = await world();
    try {
      const panel = await w.panel();
      await panel.getByRole('heading', { name: 'Wisp is off in this browser' }).waitFor();
      assert.equal(await w.lane.paired(), false);
      const out = await w.lane.tool({ steps: [{ do: 'open', url: fixtures.url('login.html') }] });
      assert.match(out, /pair|connect|press/i);
      assert.equal((await tabInfo(panel)).urls.some((u) => u.includes('login.html')), false);
    } finally {
      await w.close();
    }
  });

  test('Connect pairs through the real native host', async () => {
    const w = await world();
    try {
      const panel = await w.panel();
      await w.connect(panel);
      assert.equal(await w.lane.paired(), true);
    } finally {
      await w.close();
    }
  });

  test('runs a task in a Wisp tab group and leaves the user’s tab alone', async () => {
    const w = await world({ consent: true, hosts: 'all' });
    try {
      const panel = (await w.ctx.pages()).find((p) => p.url().includes('sidepanel'));
      const user = await w.ctx.newPage();
      await user.goto(fixtures.url('done.html'));
      await user.bringToFront();
      const before = await tabInfo(panel);
      const url = fixtures.url('login.html');

      const out = await w.lane.tool({
        steps: [{ do: 'open', url }, { do: 'snapshot' }],
      });
      assert.match(out, /opened tab \d+ in the Wisp tab group/);
      assert.match(out, /page 'Sign in'/);
      const user_ref = refOf(out, 'input/text \'Username\'');
      const go_ref = refOf(out, "button/submit 'Continue'|button 'Continue'");

      const out2 = await w.lane.tool({
        steps: [
          { do: 'fill', ref: user_ref, value: 'ada' },
          { do: 'click', ref: go_ref },
          { do: 'wait_for', text: 'Submitted for ada', timeout_ms: 5000 },
          { do: 'scroll', dy: 100 },
        ],
      });
      assert.doesNotMatch(out2, /FAILED|REFUSED/);

      const during = await tabInfo(panel);
      assert.ok(during.groupTitles.includes('Wisp'));
      assert.deepEqual(during.grouped, [url]);
      assert.deepEqual(during.active, before.active, 'the user’s active tab changed');

      const shot = await w.lane.tool({ steps: [{ do: 'screenshot' }] });
      assert.match(shot, /screenshot saved to .*\.png/);
      assert.ok(existsSync(shot.match(/saved to (\S+\.png)/)[1]));
      assert.deepEqual((await tabInfo(panel)).active, before.active, 'screenshot left a different tab active');

      await panel.getByRole('listitem').first().waitFor();
      const rows = await panel.getByRole('listitem').allInnerTexts();
      assert.ok(rows.some((r) => r.includes('open') && r.includes('127.0.0.1')));

      await w.lane.tool({ steps: [{ do: 'done' }] });
      const after = await tabInfo(panel);
      assert.equal(after.urls.some((u) => u.includes('login.html')), false);
      assert.deepEqual(after.groupTitles, []);
    } finally {
      await w.close();
    }
  });

  test('never fills a password or one-time-code field, with or without wispd’s own check', async () => {
    const w = await world({ consent: true });
    try {
      const panel = (await w.ctx.pages()).find((p) => p.url().includes('sidepanel'));
      const url = fixtures.url('login.html');
      const out = await w.lane.tool({ steps: [{ do: 'open', url }, { do: 'snapshot' }] });
      const pw = refOf(out, 'input/password');
      const code = refOf(out, "input/text 'Verification code'");
      assert.match(out, /Password' \[never filled\]/);

      // wispd refuses before sending
      const viaWisp = await w.lane.tool({ steps: [{ do: 'fill', ref: pw, value: 'hunter2' }] });
      assert.match(viaWisp, /never filled/);

      // and the extension refuses on its own when wispd's check is skipped
      for (const ref of [pw, code]) {
        const res = await w.lane.raw({ op: 'batch', task: 't1', steps: [{ do: 'fill', ref, value: 'hunter2' }] });
        assert.equal(res.ok, false);
        assert.match(res.error, /never filled/);
      }
      const page = w.ctx.pages().find((p) => p.url() === url);
      assert.equal(await page.inputValue('#pw'), '');
      assert.equal(await page.inputValue('#code'), '');
      assert.equal(await panel.getByText('hunter2').count(), 0);
    } finally {
      await w.close();
    }
  });

  test('refuses a ref from before the latest snapshot', async () => {
    const w = await world({ consent: true });
    try {
      const url = fixtures.url('login.html');
      const first = await w.lane.tool({ steps: [{ do: 'open', url }, { do: 'snapshot' }] });
      const old = refOf(first, "input/text 'Username'");
      await w.lane.tool({ steps: [{ do: 'snapshot' }] });
      const res = await w.lane.raw({ op: 'batch', task: 't1', steps: [{ do: 'fill', ref: old, value: 'x' }] });
      assert.match(res.error, /stale ref/);
    } finally {
      await w.close();
    }
  });

  test('refuses pages that are not http or https', async () => {
    const w = await world({ consent: true });
    try {
      for (const url of ['file:///etc/hostname', 'chrome://version', 'javascript:alert(1)']) {
        const res = await w.lane.raw({ op: 'batch', task: 't1', steps: [{ do: 'open', url }] });
        assert.equal(res.ok, false, url);
        assert.match(res.error, /only http and https/);
      }
    } finally {
      await w.close();
    }
  });

  test('Stop ends a waiting step at once, closes Wisp’s tabs and says so', async () => {
    const w = await world({ consent: true });
    try {
      const panel = (await w.ctx.pages()).find((p) => p.url().includes('sidepanel'));
      const url = fixtures.url('login.html');
      const pending = w.lane.toolLater({
        steps: [{ do: 'open', url }, { do: 'wait_for', text: 'never appears', timeout_ms: 15000 }],
      });
      await panel.getByRole('heading', { name: 'Wisp is working' }).waitFor({ timeout: TIMEOUT });
      await panel.getByRole('button', { name: 'Stop Wisp' }).click();
      const out = await pending;
      assert.match(out, /Stop/);
      await panel.getByRole('heading', { name: 'Stopped' }).waitFor({ timeout: TIMEOUT });
      const t = await tabInfo(panel);
      assert.equal(t.urls.some((u) => u.includes('login.html')), false);
      // the rest of the turn does nothing
      const again = await w.lane.tool({ steps: [{ do: 'open', url }] });
      assert.match(again, /Stop/);
      assert.equal((await tabInfo(panel)).urls.some((u) => u.includes('login.html')), false);
      // a new turn starts clean
      await w.lane.turn('t2');
      const fresh = await w.lane.tool({ steps: [{ do: 'open', url }] });
      assert.match(fresh, /opened tab/);
    } finally {
      await w.close();
    }
  });

  test('a screenshot waits for the all-sites grant Chrome requires', async () => {
    const w = await world({ consent: true });
    try {
      const panel = (await w.ctx.pages()).find((p) => p.url().includes('sidepanel'));
      await w.lane.tool({ steps: [{ do: 'open', url: fixtures.url('done.html') }] });
      const pending = w.lane.toolLater({ steps: [{ do: 'screenshot' }] });
      await panel
        .getByRole('heading', { name: 'Wisp is waiting for your OK to take a screenshot' })
        .waitFor({ timeout: TIMEOUT });
      await panel.getByRole('button', { name: 'Allow all sites' }).waitFor();
      await panel.getByRole('button', { name: 'Stop Wisp' }).click();
      assert.match(await pending, /Stop/);
    } finally {
      await w.close();
    }
  });

  test('a site the user has not allowed waits for them, and shows what it waits for', async () => {
    const w = await world({ consent: true });
    try {
      const panel = (await w.ctx.pages()).find((p) => p.url().includes('sidepanel'));
      // localhost is not covered by the e2e build's 127.0.0.1 permission
      const url = `http://localhost:${fixtures.port}/login.html`;
      const pending = w.lane.toolLater({ steps: [{ do: 'open', url }] });
      await panel
        .getByRole('heading', { name: `Wisp is waiting for your OK on localhost:${fixtures.port}` })
        .waitFor({ timeout: TIMEOUT });
      await panel.getByRole('button', { name: `Allow localhost:${fixtures.port}` }).waitFor();
      assert.equal((await tabInfo(panel)).urls.some((u) => u.includes('localhost')), false);
      await panel.getByRole('button', { name: 'Stop Wisp' }).click();
      assert.match(await pending, /Stop/);
    } finally {
      await w.close();
    }
  });

  test('consent survives a browser restart: it reconnects without a click', async () => {
    const w = await world({ consent: true });
    try {
      assert.equal(await w.lane.paired(), true);
      await w.restart();
      const panel = await w.panel();
      await panel.getByRole('heading', { name: 'Connected' }).waitFor({ timeout: TIMEOUT });
      assert.equal(await w.lane.paired(), true);
      const out = await w.lane.tool({ steps: [{ do: 'open', url: fixtures.url('done.html') }] });
      assert.match(out, /opened tab/);
    } finally {
      await w.close();
    }
  });

  test('Disconnect withdraws consent for good', async () => {
    const w = await world({ consent: true });
    try {
      const panel = (await w.ctx.pages()).find((p) => p.url().includes('sidepanel'));
      await panel.getByRole('button', { name: 'Disconnect Wisp' }).click();
      await panel.getByRole('heading', { name: 'Wisp is off in this browser' }).waitFor({ timeout: TIMEOUT });
      await w.restart();
      const again = await w.panel();
      await again.getByRole('heading', { name: 'Wisp is off in this browser' }).waitFor();
      assert.equal(await w.lane.paired(), false);
    } finally {
      await w.close();
    }
  });

  test('tells the user what to run when the native host is not installed', async () => {
    const w = await world({ host: false });
    try {
      const panel = await w.panel();
      await panel.getByRole('button', { name: 'Connect Wisp' }).click();
      await panel
        .getByRole('heading', { name: "Wisp's native host is not installed" })
        .waitFor({ timeout: 60_000 });
      assert.match(await panel.locator('code').innerText(), /wispd browser install-host/);
    } finally {
      await w.close();
    }
  });

  test('the extension’s own id is the pinned one', async () => {
    const w = await world();
    try {
      const sw = w.ctx.serviceWorkers()[0];
      assert.equal(new URL(sw.url()).host, EXT_ID);
    } finally {
      await w.close();
    }
  });
});

describe('the side panel is accessible', () => {
  async function violations(page) {
    // evaluate, not addScriptTag: the panel's CSP forbids inline scripts
    await page.evaluate(AxeSource.source);
    return page.evaluate(async () => {
      const r = await axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice'] });
      return r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
    });
  }

  for (const scheme of ['dark', 'light']) {
    test(`has no axe violations in the ${scheme} scheme, off and connected with a log`, async () => {
      const w = await world();
      try {
        const panel = await w.panel();
        await panel.emulateMedia({ colorScheme: scheme });
        assert.deepEqual(await violations(panel), [], 'off');
        await w.connect(panel);
        assert.deepEqual(await violations(panel), [], 'connected, empty');
        const url = fixtures.url('login.html');
        const out = await w.lane.tool({ steps: [{ do: 'open', url }, { do: 'snapshot' }] });
        const pw = refOf(out, 'input/password');
        await w.lane.raw({ op: 'batch', task: 't1', steps: [{ do: 'fill', ref: pw, value: 'x' }] });
        await panel.getByText('failed').first().waitFor({ timeout: TIMEOUT });
        assert.deepEqual(await violations(panel), [], 'with a failed step');
      } finally {
        await w.close();
      }
    });
  }
});
