import { Epoch } from './epoch';
import { RULE } from './fieldrule';
import type { BatchResult, Command, Step, StepResult } from './protocol';
import { pageAct } from './page/act';
import { pageScroll, pageWait } from './page/misc';
import { pageSnapshot } from './page/snapshot';
import { ALL_SITES, WAIT_MAX_MS, checkSteps, hostOf, originPattern, safeUrl } from './steps';

export type LaneApi = Pick<typeof chrome, 'tabs' | 'tabGroups' | 'scripting' | 'permissions'>;

/** What survives a service-worker restart. */
export interface LaneState {
  groups: Record<string, number>;
  tabs: Record<string, number[]>;
  kept: Record<string, true>;
  current: Record<string, number>;
  epoch: number;
}

export interface LogEntry {
  task: string;
  op: string;
  host: string;
  ok: boolean;
  error?: string;
}

export interface SiteGrant {
  host: string;
  pattern: string;
}

export interface LaneEnv {
  api: LaneApi;
  save(state: LaneState): void | Promise<void>;
  log(entry: LogEntry): void;
  /** The site the lane is waiting for the user to allow, or null. */
  needGrant(site: SiteGrant | null): void;
  sleep(ms: number): Promise<void>;
  grantWaitMs: number;
}

export const emptyState = (): LaneState => ({
  groups: {},
  tabs: {},
  kept: {},
  current: {},
  epoch: 0,
});

const LOAD_WAIT_MS = 15000;
const CLICK_LOAD_WAIT_MS = 1500;
const LOAD_POLL_MS = 100;

class StepError extends Error {}

export class Lane {
  stopped = false;
  private epoch: Epoch;
  private wake: (() => void) | null = null;

  constructor(
    private env: LaneEnv,
    private state: LaneState = emptyState(),
  ) {
    this.epoch = new Epoch(state.epoch);
  }

  // -- control ---------------------------------------------------------------

  /** Stop: end waits now, close the lane's tabs (kept ones stay). */
  async stop(): Promise<void> {
    this.stopped = true;
    this.wake?.();
    for (const task of Object.keys(this.state.groups)) await this.endTask(task);
    await this.persist();
  }

  async execute(cmd: Command): Promise<BatchResult> {
    if (cmd.resume) this.stopped = false;
    if (cmd.op === 'end_task') {
      await this.endTask(String(cmd.task ?? ''));
      return { ok: true, results: [] };
    }
    const why = checkSteps(cmd.steps);
    if (why) return { ok: false, error: why, results: [] };
    const task = String(cmd.task ?? 'task');
    const results: StepResult[] = [];
    for (const step of cmd.steps ?? []) {
      if (this.stopped) return { ok: false, error: 'stopped', results };
      try {
        const r = await this.runStep(task, step);
        results.push({ ok: true, ...r });
        this.env.log({ task, op: step.do, host: this.hostFor(step), ok: true });
      } catch (e) {
        const error = e instanceof Error ? e.message : String(e);
        results.push({ ok: false, error });
        this.env.log({ task, op: step.do, host: this.hostFor(step), ok: false, error });
        await this.persist();
        return { ok: false, error, results };
      }
    }
    await this.persist();
    return { ok: true, results };
  }

  private hostFor(step: Step): string {
    return step.do === 'open' ? hostOf(String(step.url ?? '')) : '';
  }

  private persist(): void | Promise<void> {
    this.state.epoch = this.epoch.n;
    return this.env.save(this.state);
  }

  // -- steps -----------------------------------------------------------------

  private async runStep(task: string, step: Step): Promise<Record<string, unknown>> {
    const { api } = this.env;
    switch (step.do) {
      case 'open': {
        const url = String(step.url ?? '');
        if (!safeUrl(url)) throw new StepError('only http and https pages can be opened');
        await this.ensureGranted(url);
        if (this.stopped) throw new StepError('stopped');
        const tab = await api.tabs.create({ url, active: false });
        if (tab.id === undefined) throw new StepError('the browser did not open a tab');
        if (tab.incognito) {
          await api.tabs.remove(tab.id);
          throw new StepError('private windows are not supported');
        }
        (this.state.tabs[task] ??= []).push(tab.id);
        this.state.current[task] = tab.id;
        await this.ensureGroup(task, tab.id);
        await this.waitLoaded(tab.id, LOAD_WAIT_MS);
        await this.persist();
        return { tab: tab.id };
      }
      case 'snapshot': {
        const id = await this.tabOf(task, step);
        const epoch = this.epoch.next();
        const [r] = await api.scripting.executeScript({
          target: { tabId: id },
          func: pageSnapshot,
          args: [epoch, RULE],
        });
        if (!r) throw new StepError('the page returned nothing');
        return { ...r.result, tab: id };
      }
      case 'click':
      case 'fill': {
        const p = this.epoch.parse(step.ref);
        if (!p.ok) throw new StepError(p.error);
        const id = await this.tabOf(task, step);
        const [a] = await api.scripting.executeScript({
          target: { tabId: id },
          func: pageAct,
          args: [p.epoch, p.index, step.do, String(step.value ?? ''), RULE],
        });
        if (!a?.result?.ok) throw new StepError(a?.result?.error ?? 'the page returned nothing');
        if (step.do === 'click') await this.waitLoaded(id, CLICK_LOAD_WAIT_MS);
        return {};
      }
      case 'scroll': {
        const id = await this.tabOf(task, step);
        const [s] = await api.scripting.executeScript({
          target: { tabId: id },
          func: pageScroll,
          args: [Number(step.dy) || 400],
        });
        return { ...(s?.result ?? {}) };
      }
      case 'wait_for': {
        const id = await this.tabOf(task, step);
        const limit = Math.min(Number(step.timeout_ms) || 5000, WAIT_MAX_MS);
        let waited = 0;
        while (waited < limit) {
          if (this.stopped) throw new StepError('stopped');
          const [w] = await api.scripting.executeScript({
            target: { tabId: id },
            func: pageWait,
            args: [String(step.text ?? ''), String(step.selector ?? '')],
          });
          if (w?.result) return { waited_ms: waited };
          await this.env.sleep(250);
          waited += 250;
        }
        throw new StepError('wait_for timed out');
      }
      case 'screenshot': {
        const id = await this.tabOf(task, step);
        // Chrome captures a tab only for an extension holding <all_urls>
        // (or activeTab, which a background tab never has), so a
        // screenshot asks for all sites even when every page was allowed
        // one by one.
        await this.ensurePattern(ALL_SITES, 'all sites');
        if (this.stopped) throw new StepError('stopped');
        return { png: await this.shot(id) };
      }
      case 'keep': {
        const id = await this.tabOf(task, step);
        this.state.kept[String(id)] = true;
        await api.tabs.ungroup([id]);
        await this.persist();
        return {};
      }
      case 'done':
        await this.endTask(task);
        return {};
      default:
        throw new StepError(`unknown step ${step.do}`);
    }
  }

  /** A tab of this task, its page allowed by the user. */
  private async tabOf(task: string, step: Step): Promise<number> {
    const id = step.tab !== undefined ? Number(step.tab) : this.state.current[task];
    if (!id) throw new StepError('no tab yet: open a page first');
    if (!(this.state.tabs[task] ?? []).includes(id)) {
      throw new StepError(`tab ${id} is not one of Wisp's tabs`);
    }
    const tab = await this.env.api.tabs.get(id);
    if (tab.incognito) throw new StepError('private windows are not supported');
    if (tab.url && safeUrl(tab.url)) await this.ensureGranted(tab.url);
    return id;
  }

  /** The proof screenshot. The tab must be showing to be captured, so the
   *  user's own tab is put back afterwards. */
  private async shot(id: number): Promise<string> {
    const { tabs } = this.env.api;
    const target = await tabs.get(id);
    const [prev] = await tabs.query({ active: true, windowId: target.windowId });
    if (prev?.id !== id) await tabs.update(id, { active: true });
    try {
      const data = await tabs.captureVisibleTab(target.windowId, { format: 'png' });
      return data.replace(/^data:image\/png;base64,/, '');
    } finally {
      if (prev?.id !== undefined && prev.id !== id) await tabs.update(prev.id, { active: true });
    }
  }

  // -- tab group and tabs ------------------------------------------------------

  private async ensureGroup(task: string, tabId: number): Promise<void> {
    const { tabs, tabGroups } = this.env.api;
    const existing = this.state.groups[task];
    const id = await tabs.group(
      existing === undefined ? { tabIds: [tabId] } : { tabIds: [tabId], groupId: existing },
    );
    if (existing === undefined) {
      this.state.groups[task] = id;
      await tabGroups.update(id, { title: 'Wisp', color: 'purple', collapsed: false });
    }
  }

  async endTask(task: string): Promise<void> {
    const ids = (this.state.tabs[task] ?? []).filter((t) => !this.state.kept[String(t)]);
    for (const id of ids) {
      try {
        await this.env.api.tabs.remove(id);
      } catch {
        // already closed by the user: nothing left to do
      }
    }
    delete this.state.groups[task];
    delete this.state.tabs[task];
    delete this.state.current[task];
    await this.persist();
  }

  /** Wait for the tab to finish loading, up to `ms`. The update event can
   *  fire before anyone listens (the tab loads while it is being grouped),
   *  so the status is polled as well as listened for. */
  private async waitLoaded(tabId: number, ms: number): Promise<void> {
    const { tabs } = this.env.api;
    let listener: ((id: number, info: chrome.tabs.OnUpdatedInfo) => void) | undefined;
    let poke: (() => void) | undefined;
    tabs.onUpdated.addListener(
      (listener = (id, info) => {
        if (id === tabId && info.status === 'complete') poke?.();
      }),
    );
    try {
      for (let waited = 0; waited < ms; waited += LOAD_POLL_MS) {
        let t: chrome.tabs.Tab;
        try {
          t = await tabs.get(tabId);
        } catch {
          return; // the user closed it
        }
        if (t.status === 'complete') return;
        await Promise.race([
          new Promise<void>((r) => (poke = r)),
          this.env.sleep(LOAD_POLL_MS),
        ]);
      }
    } finally {
      tabs.onUpdated.removeListener(listener);
    }
  }

  // -- the user's say over which sites -----------------------------------------

  /** Wait for the user to allow this page's site, from the side panel. */
  private async ensureGranted(url: string): Promise<void> {
    await this.ensurePattern(originPattern(url), hostOf(url));
  }

  /** Wait until `pattern` is granted, showing `label` in the panel. */
  private async ensurePattern(pattern: string, label: string): Promise<void> {
    const { permissions } = this.env.api;
    if (await permissions.contains({ origins: [pattern] })) return;
    this.env.needGrant({ host: label, pattern });
    let listener: (() => void) | undefined;
    const granted = new Promise<void>((resolve) => {
      listener = () => {
        void permissions.contains({ origins: [pattern] }).then((ok) => ok && resolve());
      };
      permissions.onAdded.addListener(listener);
      listener(); // a grant made between the check above and the listener
    });
    const stopped = new Promise<void>((resolve) => {
      this.wake = resolve;
    });
    try {
      const winner = await Promise.race([
        granted.then(() => 'granted'),
        stopped.then(() => 'stopped'),
        this.env.sleep(this.env.grantWaitMs).then(() => 'timeout'),
      ]);
      if (winner === 'stopped') throw new StepError('stopped');
      if (winner === 'timeout') {
        throw new StepError(`not allowed: ${label} was not granted in the side panel`);
      }
    } finally {
      this.wake = null;
      if (listener) permissions.onAdded.removeListener(listener);
      this.env.needGrant(null);
    }
  }
}
