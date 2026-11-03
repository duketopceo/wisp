import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../src/ui/App';
import type { Actions } from '../src/ui/App';
import { describe as describeUi, truncate } from '../src/ui/model';
import { initialUi } from '../src/state';
import type { UiState } from '../src/state';

const ui = (patch: Partial<UiState> = {}): UiState => ({ ...initialUi(), consent: true, ...patch });
const connected = { kind: 'connected' } as const;
const actions = (): Actions => ({
  connect: vi.fn(),
  retry: vi.fn(),
  disconnect: vi.fn(),
  stop: vi.fn(),
  allowSite: vi.fn(),
  allowAll: vi.fn(),
});
const html = (u: UiState) => renderToStaticMarkup(<App ui={u} actions={actions()} />);

describe('describe(): one sentence and one next step for every state', () => {
  it('off: gray, with Connect', () => {
    const h = describeUi(initialUi());
    expect(h.tone).toBe('gray');
    expect(h.action).toEqual({ id: 'connect', label: 'Connect Wisp' });
  });

  it('connecting: amber and no action', () => {
    const h = describeUi(ui({ link: { kind: 'connecting' } }));
    expect(h.tone).toBe('amber');
    expect(h.action).toBeUndefined();
  });

  it.each([
    ['host_missing', 'wispd browser install-host --dev'],
    ['host_forbidden', 'wispd browser status'],
    ['wisp_unavailable', 'wispd config set browser.lane extension'],
    ['host_exited', 'wispd browser status'],
  ])('unavailable %s: red, a command to run, and Try again', (code, command) => {
    const h = describeUi(ui({ link: { kind: 'unavailable', code, message: 'm' } }));
    expect(h.tone).toBe('red');
    expect(h.command).toBe(command);
    expect(h.action).toEqual({ id: 'retry', label: 'Try again' });
  });

  it('waiting for a site: amber, names the host, offers to allow it', () => {
    const h = describeUi(ui({ link: connected, pendingGrant: { host: 'a.test', pattern: 'https://a.test/*' } }));
    expect(h.tone).toBe('amber');
    expect(h.title).toBe('Wisp is waiting for your OK on a.test');
    expect(h.action).toEqual({ id: 'grant-site', label: 'Allow a.test' });
  });

  it('waiting for all sites (screenshots): says why and offers only the one button', () => {
    const u = ui({ link: connected, pendingGrant: { host: 'all sites', pattern: '<all_urls>' } });
    const h = describeUi(u);
    expect(h.title).toBe('Wisp is waiting for your OK to take a screenshot');
    expect(h.action).toEqual({ id: 'grant-all', label: 'Allow all sites' });
    expect(html(u).match(/Allow all sites/g)).toHaveLength(1);
  });

  it('stopped beats running; running is green; idle is green', () => {
    expect(describeUi(ui({ link: connected, stopped: true, running: true })).title).toBe('Stopped');
    expect(describeUi(ui({ link: connected, running: true })).title).toBe('Wisp is working');
    expect(describeUi(ui({ link: connected })).title).toBe('Connected');
  });

  it('truncates long text with an ellipsis and leaves short text alone', () => {
    expect(truncate('short')).toBe('short');
    const t = truncate('x'.repeat(300), 20);
    expect(t).toHaveLength(20);
    expect(t.endsWith('\u2026')).toBe(true);
  });
});

describe('App', () => {
  it('shows Connect and a disabled Stop before consent', () => {
    const out = html(initialUi());
    expect(out).toContain('Connect Wisp');
    expect(out).toMatch(/<button[^>]*class="stop"[^>]*disabled/);
    expect(out).not.toContain('Disconnect Wisp');
  });

  it('enables Stop and offers Disconnect when connected', () => {
    const out = html(ui({ link: connected }));
    expect(out).not.toMatch(/<button[^>]*class="stop"[^>]*disabled/);
    expect(out).toContain('Disconnect Wisp');
  });

  it('has an empty state that says what, why and what next', () => {
    const out = html(ui({ link: connected }));
    expect(out).toContain('Wisp&#x27;s steps appear here as it works.');
    expect(out).toContain('Nothing has run yet.');
    expect(out).toContain('Ask Wisp to do something in your browser.');
  });

  it('lists steps newest first, with host, result and a truncated error', () => {
    const out = html(
      ui({
        link: connected,
        log: [
          { n: 1, task: 't', op: 'open', host: 'a.test', ok: true },
          { n: 2, task: 't', op: 'fill', host: '', ok: false, error: 'refused: sensitive field ' + 'x'.repeat(300) },
        ],
      }),
    );
    expect(out.indexOf('fill')).toBeLessThan(out.indexOf('open'));
    expect(out).toContain('a.test');
    expect(out).toContain('failed');
    expect(out).toContain('refused: sensitive field');
    expect(out).not.toContain('x'.repeat(200));
  });

  it('escapes page-controlled text', () => {
    const out = html(
      ui({
        link: connected,
        log: [{ n: 1, task: 't', op: 'open', host: '<img src=x onerror=alert(1)>', ok: true }],
      }),
    );
    expect(out).not.toContain('<img');
    expect(out).toContain('&lt;img');
  });

  it('the grant prompt offers this site and all sites', () => {
    const out = html(ui({ link: connected, pendingGrant: { host: 'a.test', pattern: 'https://a.test/*' } }));
    expect(out).toContain('Allow a.test');
    expect(out).toContain('Allow all sites');
  });

  it('marks a red state as an alert for screen readers', () => {
    const out = html(ui({ link: { kind: 'unavailable', code: 'host_missing', message: '' } }));
    expect(out).toContain('role="alert"');
    expect(out).toContain('wispd browser install-host --dev');
  });
});
