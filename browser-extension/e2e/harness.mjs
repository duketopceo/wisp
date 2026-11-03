// Shared setup for the browser e2e: a fixture web server, wispd's lane in
// Python, and Chromium with the built extension and the real native host.
// No network beyond 127.0.0.1; nothing here depends on the clock.
import { spawn, spawnSync } from 'node:child_process';
import { chromium } from 'playwright';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

export const EXT_ID = 'cbbeeaamnkogifjkglfcklifijjnjpma';
const here = new URL('.', import.meta.url).pathname;
const extDirs = {
  site: join(here, '..', '.output', 'chrome-mv3-e2e'),
  all: join(here, '..', '.output', 'chrome-mv3-e2e-all'),
};
const repo = join(here, '..', '..');

export function serveFixtures() {
  const server = createServer((req, res) => {
    const name = (req.url ?? '/').split('?')[0].replace(/^\/+/, '') || 'login.html';
    if (!/^[a-z]+\.html$/.test(name) || !readdirSync(join(here, 'fixtures')).includes(name)) {
      res.writeHead(404).end('not found');
      return;
    }
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    res.end(readFileSync(join(here, 'fixtures', name)));
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({ port, url: (p) => `http://127.0.0.1:${port}/${p}`, close: () => server.close() });
    });
  });
}

/** A scratch home whose XDG dirs the Python side and the browser share. */
export function scratch() {
  const root = mkdtempSync(join(tmpdir(), 'wispe2e-'));
  const dirs = {
    root,
    home: join(root, 'home'),
    run: join(root, 'run'),
    data: join(root, 'data'),
    profile: join(root, 'profile'),
    shots: join(root, 'shots'),
  };
  for (const d of [dirs.home, dirs.run, dirs.data, dirs.profile, dirs.shots]) mkdirSync(d, { recursive: true });
  mkdirSync(join(dirs.home, '.config', 'chromium'), { recursive: true });
  return { ...dirs, env: { ...process.env, HOME: dirs.home, XDG_RUNTIME_DIR: dirs.run, XDG_DATA_HOME: dirs.data, XDG_CONFIG_HOME: join(dirs.home, '.config') }, remove: () => rmSync(root, { recursive: true, force: true }) };
}

/** wispd browser install-host, run for real, then placed where Chromium
 *  looks for a user-level host in this profile. */
export function installHost(s) {
  const r = spawnSync('python3', [join(repo, 'wispd'), 'browser', 'install-host', '--dev', '--browser', 'chromium'], { env: s.env, encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`install-host failed: ${r.stderr}`);
  const from = join(s.home, '.config', 'chromium', 'NativeMessagingHosts');
  cpSync(from, join(s.profile, 'NativeMessagingHosts'), { recursive: true });
}

export async function startLane(s) {
  const p = spawn('python3', [join(here, 'lane_server.py'), s.shots], { env: s.env, stdio: ['pipe', 'pipe', 'inherit'] });
  const rl = createInterface({ input: p.stdout });
  const waiting = new Map();
  let nextId = 1;
  let ready;
  const readyP = new Promise((r) => (ready = r));
  rl.on('line', (line) => {
    const m = JSON.parse(line);
    if (m.ready) ready(m);
    else waiting.get(m.id)?.(m);
  });
  const ask = (body) =>
    new Promise((resolve) => {
      const id = nextId++;
      waiting.set(id, resolve);
      p.stdin.write(JSON.stringify({ id, ...body }) + '\n');
    });
  await readyP;
  return {
    tool: async (arg) => (await ask({ tool: typeof arg === 'string' ? arg : JSON.stringify(arg) })).out,
    toolLater: (arg) => ask({ tool: typeof arg === 'string' ? arg : JSON.stringify(arg) }).then((m) => m.out),
    raw: async (cmd) => (await ask({ raw: cmd })).value,
    paired: async () => (await ask({ ctl: 'paired' })).value,
    stop: async () => (await ask({ ctl: 'stop' })).value,
    turn: async (t) => (await ask({ ctl: 'turn', turn: t })).value,
    close: () => {
      p.stdin.end();
      p.kill();
    },
  };
}

/** `hosts`: 'site' (127.0.0.1 only) or 'all' (every site, for screenshots). */
export async function launchBrowser(s, hosts = 'site') {
  const extDir = extDirs[hosts];
  const ctx = await chromium.launchPersistentContext(s.profile, {
    channel: 'chromium',
    headless: true,
    env: s.env,
    args: [`--disable-extensions-except=${extDir}`, `--load-extension=${extDir}`],
  });
  if (ctx.serviceWorkers().length === 0) await ctx.waitForEvent('serviceworker');
  return ctx;
}

export async function openPanel(ctx) {
  const page = await ctx.newPage();
  await page.goto(`chrome-extension://${EXT_ID}/sidepanel.html`);
  return page;
}

/** The titles of the open tabs, and the active one, as the browser sees them. */
export const tabInfo = (panel) =>
  panel.evaluate(async () => {
    const tabs = await chrome.tabs.query({});
    const groups = await chrome.tabGroups.query({});
    return {
      urls: tabs.map((t) => t.url ?? ''),
      active: tabs.filter((t) => t.active).map((t) => t.id),
      grouped: tabs.filter((t) => t.groupId !== -1).map((t) => t.url ?? ''),
      groupTitles: groups.map((g) => g.title),
    };
  });
