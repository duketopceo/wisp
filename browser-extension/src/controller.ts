import type { Lane, LogEntry, SiteGrant } from './lane';
import type { LinkState } from './native';
import type { BatchResult, Command, ToHost } from './protocol';
import { LOG_MAX, initialUi, isPanelMessage } from './state';
import type { UiState } from './state';

export interface LinkLike {
  start(): void;
  stop(): void;
  send(msg: ToHost): boolean;
}

export interface ControllerDeps {
  makeLink(handlers: {
    onCommand(cmd: Command): void;
    onState(s: LinkState): void;
  }): LinkLike;
  lane: Pick<Lane, 'execute' | 'stop'>;
  getConsent(): Promise<boolean>;
  setConsent(on: boolean): Promise<void>;
  loadUi(): Promise<UiState | null>;
  saveUi(ui: UiState): void | Promise<void>;
  badge(ui: UiState): void;
}

/**
 * The service worker's brain, free of chrome.* so it can be tested:
 * consent, the link, routing commands to the lane, Stop, and the state
 * the side panel draws.
 */
export class Controller {
  ui: UiState = initialUi();
  private link: LinkLike;
  private seq = 0;

  constructor(private d: ControllerDeps) {
    this.link = d.makeLink({
      onCommand: (cmd) => void this.onCommand(cmd),
      onState: (s) => {
        this.ui.link = s;
        this.publish();
      },
    });
  }

  /** On every worker start: restore what the panel showed, and reconnect
   *  when the user connected the extension before the restart. */
  async init(): Promise<void> {
    const prev = await this.d.loadUi();
    this.ui = initialUi();
    if (prev) {
      this.ui.log = prev.log.slice(-LOG_MAX);
      this.seq = this.ui.log.reduce((m, r) => Math.max(m, r.n), 0);
    }
    this.ui.consent = await this.d.getConsent();
    this.publish();
    if (this.ui.consent) this.link.start();
  }

  logEntry(e: LogEntry): void {
    this.seq += 1;
    this.ui.log = [...this.ui.log, { ...e, n: this.seq }].slice(-LOG_MAX);
    this.publish();
  }

  needGrant(site: SiteGrant | null): void {
    this.ui.pendingGrant = site;
    this.publish();
  }

  /** Stop from the panel, the toolbar shortcut or a message. */
  async stop(): Promise<void> {
    this.ui.stopped = true;
    this.ui.running = false;
    this.ui.pendingGrant = null;
    this.link.send({ t: 'stop' });
    this.publish();
    await this.d.lane.stop();
  }

  async onMessage(raw: unknown): Promise<void> {
    if (!isPanelMessage(raw)) return;
    switch (raw.type) {
      case 'connect':
        await this.d.setConsent(true);
        this.ui.consent = true;
        this.publish();
        this.link.start();
        return;
      case 'retry':
        if (this.ui.consent) this.link.start();
        return;
      case 'disconnect':
        await this.d.setConsent(false);
        this.ui.consent = false;
        this.link.stop();
        await this.stop();
        this.ui.stopped = false;
        this.publish();
        return;
      case 'stop':
        await this.stop();
    }
  }

  private async onCommand(cmd: Command): Promise<void> {
    if (cmd.resume) this.ui.stopped = false;
    this.ui.running = true;
    this.publish();
    let res: BatchResult;
    try {
      res = await this.d.lane.execute(cmd);
    } catch (e) {
      res = { ok: false, error: e instanceof Error ? e.message : String(e), results: [] };
    }
    this.ui.running = false;
    if (res.error === 'stopped') this.ui.stopped = true;
    this.link.send({ t: 'result', id: cmd.id, ...res });
    this.publish();
  }

  private publish(): void {
    void this.d.saveUi(this.ui);
    this.d.badge(this.ui);
  }
}
