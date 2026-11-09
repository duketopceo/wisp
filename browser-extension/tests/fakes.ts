import type { LaneApi, LaneEnv, LaneState, LogEntry, SiteGrant } from '../src/lane';
import { emptyState } from '../src/lane';

type Fn = (...a: never[]) => unknown;

/** A scripted stand-in for the chrome.* calls the lane uses. It records
 *  calls and has no clock, no network and no randomness. */
export class FakeChrome {
  calls: string[] = [];
  tabs = new Map<number, { id: number; url: string; incognito: boolean; windowId: number; status: string }>();
  nextId = 100;
  activeTab = 1;
  granted = new Set<string>();
  addedListeners = new Set<() => void>();
  updatedListeners = new Set<(id: number, info: { status?: string }) => void>();
  removeFails = new Set<number>();
  incognitoNext = false;
  injected: { tabId: number; func: Fn; args: unknown[] }[] = [];
  /** answers for injected page functions, by function identity */
  page = new Map<Fn, (args: unknown[], tabId: number) => unknown>();
  groupOf = new Map<number, number>();
  nextGroup = 500;

  constructor() {
    this.tabs.set(1, { id: 1, url: 'https://user.test/', incognito: false, windowId: 9, status: 'complete' });
  }

  grant(pattern: string): void {
    this.granted.add(pattern);
    this.addedListeners.forEach((cb) => cb());
  }

  api(): LaneApi {
    const self = this;
    const rec = (s: string): void => void self.calls.push(s);
    return {
      tabs: {
        async create(p: { url: string; active: boolean }) {
          rec(`tabs.create ${p.url} active=${p.active}`);
          const id = self.nextId++;
          const t = { id, url: p.url, incognito: self.incognitoNext, windowId: 9, status: 'complete' };
          self.tabs.set(id, t);
          return t;
        },
        async get(id: number) {
          const t = self.tabs.get(id);
          if (!t) throw new Error(`No tab with id: ${id}`);
          return t;
        },
        async remove(id: number) {
          rec(`tabs.remove ${id}`);
          if (self.removeFails.has(id)) throw new Error('No tab');
          self.tabs.delete(id);
        },
        async update(id: number, p: { active?: boolean }) {
          rec(`tabs.update ${id} active=${p.active}`);
          if (p.active) self.activeTab = id;
        },
        async query() {
          return [self.tabs.get(self.activeTab)];
        },
        async group(p: { tabIds: number[]; groupId?: number }) {
          rec(`tabs.group ${p.tabIds.join(',')} group=${p.groupId ?? 'new'}`);
          const g = p.groupId ?? self.nextGroup++;
          p.tabIds.forEach((t) => self.groupOf.set(t, g));
          return g;
        },
        async ungroup(ids: number[]) {
          rec(`tabs.ungroup ${ids.join(',')}`);
          ids.forEach((t) => self.groupOf.delete(t));
        },
        async captureVisibleTab() {
          rec(`tabs.capture active=${self.activeTab}`);
          return 'data:image/png;base64,QUJD';
        },
        onUpdated: {
          addListener: (cb: (id: number, info: { status?: string }) => void) => void self.updatedListeners.add(cb),
          removeListener: (cb: (id: number, info: { status?: string }) => void) => void self.updatedListeners.delete(cb),
        },
      },
      tabGroups: {
        async update(id: number, p: { title?: string }) {
          rec(`tabGroups.update ${id} ${p.title}`);
        },
      },
      scripting: {
        async executeScript(inj: { target: { tabId: number }; func: Fn; args: unknown[] }) {
          self.injected.push({ tabId: inj.target.tabId, func: inj.func, args: inj.args });
          const h = self.page.get(inj.func);
          if (!h) throw new Error('no page handler');
          return [{ result: h(inj.args, inj.target.tabId) }];
        },
      },
      permissions: {
        async contains(p: { origins: string[] }) {
          return p.origins.every((o) => self.granted.has(o));
        },
        onAdded: {
          addListener: (cb: () => void) => void self.addedListeners.add(cb),
          removeListener: (cb: () => void) => void self.addedListeners.delete(cb),
        },
      },
    } as unknown as LaneApi;
  }
}

export interface Harness {
  chrome: FakeChrome;
  logs: LogEntry[];
  grants: (SiteGrant | null)[];
  saved: LaneState[];
  env: LaneEnv;
}

export function harness(opts: { sleep?: (ms: number) => Promise<void>; grantWaitMs?: number } = {}): Harness {
  const chrome = new FakeChrome();
  const logs: LogEntry[] = [];
  const grants: (SiteGrant | null)[] = [];
  const saved: LaneState[] = [];
  const env: LaneEnv = {
    api: chrome.api(),
    save: (s) => void saved.push(structuredClone(s)),
    log: (e) => void logs.push(e),
    needGrant: (g) => void grants.push(g),
    // never resolves unless a test says so: no real time passes
    sleep: opts.sleep ?? (() => new Promise<void>(() => {})),
    grantWaitMs: opts.grantWaitMs ?? 1000,
  };
  return { chrome, logs, grants, saved, env };
}

export { emptyState };

/** Let queued work run until `cond` holds. Bounded, so a bug fails the
 *  test instead of hanging it. */
export async function until(cond: () => boolean, tries = 100): Promise<void> {
  for (let i = 0; i < tries; i++) {
    if (cond()) return;
    await new Promise<void>((r) => setTimeout(r, 0));
  }
  throw new Error('condition never became true');
}
