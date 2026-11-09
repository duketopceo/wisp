import { Controller } from '../src/controller';
import { Lane, emptyState } from '../src/lane';
import type { LaneState } from '../src/lane';
import { NativeLink } from '../src/native';
import type { Port } from '../src/native';
import { HOST_NAME } from '../src/protocol';
import { CONSENT_KEY, LANE_KEY, UI_KEY } from '../src/state';
import type { UiState } from '../src/state';

const GRANT_WAIT_MS = 90_000;

const BADGE: Record<string, { text: string; color: string }> = {
  connected: { text: 'ON', color: '#2e7d32' },
  connecting: { text: '...', color: '#b26a00' },
  unavailable: { text: '!', color: '#c62828' },
  off: { text: '', color: '#616161' },
};

export default defineBackground(() => {
  const version = chrome.runtime.getManifest().version;
  let controller: Controller | undefined;
  let lane: Lane | undefined;

  const ready = (async () => {
    const saved = (await chrome.storage.session.get(LANE_KEY))[LANE_KEY] as LaneState | undefined;
    lane = new Lane(
      {
        api: chrome,
        save: (s) => chrome.storage.session.set({ [LANE_KEY]: s }),
        log: (e) => controller?.logEntry(e),
        needGrant: (g) => controller?.needGrant(g),
        sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
        grantWaitMs: GRANT_WAIT_MS,
      },
      saved ?? emptyState(),
    );
    const c = new Controller({
      makeLink: (handlers) =>
        new NativeLink(
          () => chrome.runtime.connectNative(HOST_NAME) as unknown as Port,
          handlers,
          {
            set: (fn, ms) => setTimeout(fn, ms),
            clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
          },
          () => chrome.runtime.lastError?.message,
          version,
        ),
      lane,
      getConsent: async () => (await chrome.storage.local.get(CONSENT_KEY))[CONSENT_KEY] === true,
      setConsent: (on) => chrome.storage.local.set({ [CONSENT_KEY]: on }),
      loadUi: async () =>
        ((await chrome.storage.session.get(UI_KEY))[UI_KEY] as UiState | undefined) ?? null,
      saveUi: (ui) => chrome.storage.session.set({ [UI_KEY]: ui }),
      badge: (ui) => {
        const b = BADGE[ui.consent ? ui.link.kind : 'off'] ?? BADGE.off!;
        void chrome.action.setBadgeText({ text: b.text });
        void chrome.action.setBadgeBackgroundColor({ color: b.color });
      },
    });
    controller = c;
    await c.init();
    return c;
  })();

  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

  chrome.runtime.onMessage.addListener((msg, sender) => {
    // only this extension's own pages may drive it
    if (sender.id !== chrome.runtime.id) return;
    void ready.then((c) => c.onMessage(msg));
  });

  chrome.commands.onCommand.addListener((name) => {
    if (name === 'stop') void ready.then((c) => c.stop());
  });
});
