// Checks on the built extension. Run after `npm run build` (and
// `npm run build:e2e` for the last test): `npm run check:build`.
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { join } from 'node:path';
import { test } from 'node:test';

const root = new URL('..', import.meta.url).pathname;
const prod = join(root, '.output', 'chrome-mv3');
const e2e = join(root, '.output', 'chrome-mv3-e2e');
const e2eAll = join(root, '.output', 'chrome-mv3-e2e-all');
const json = (p) => JSON.parse(readFileSync(p, 'utf8'));
const snapshot = json(join(root, 'tests', 'manifest.snapshot.json'));

test('the built manifest equals the committed snapshot, key for key', () => {
  assert.deepEqual(json(join(prod, 'manifest.json')), snapshot);
});

test('the snapshot asks for no debugger and no required host access', () => {
  assert.ok(!snapshot.permissions.includes('debugger'));
  assert.equal(snapshot.host_permissions, undefined);
  assert.deepEqual(snapshot.optional_host_permissions, ['<all_urls>']);
});

test('the service worker has no remote URL, eval or network call of its own', () => {
  const src = readFileSync(join(prod, 'background.js'), 'utf8');
  assert.deepEqual(src.match(/https?:\/\/[A-Za-z0-9./_-]+/g) ?? [], []);
  for (const bad of ['eval(', 'new Function', 'fetch(', 'XMLHttpRequest', 'WebSocket', 'importScripts']) {
    assert.ok(!src.includes(bad), `background.js contains ${bad}`);
  }
});

test('the side panel stays under 200 kB gzipped', () => {
  const dir = join(prod, 'chunks');
  const bytes = readdirSync(dir)
    .filter((f) => f.endsWith('.js'))
    .reduce((n, f) => n + gzipSync(readFileSync(join(dir, f))).length, 0);
  assert.ok(bytes < 200 * 1024, `side panel js is ${bytes} bytes gzipped`);
});

test('the e2e build differs from production only by the fixture origin', { skip: !existsSync(e2e) }, () => {
  const t = json(join(e2e, 'manifest.json'));
  assert.deepEqual(t.host_permissions, ['http://127.0.0.1/*']);
  delete t.host_permissions;
  assert.deepEqual(t, snapshot);
});

test('the all-sites e2e build differs from production only by host access', { skip: !existsSync(e2eAll) }, () => {
  const t = json(join(e2eAll, 'manifest.json'));
  assert.deepEqual(t.host_permissions, ['<all_urls>']);
  delete t.host_permissions;
  assert.deepEqual(t, snapshot);
});
