import { ALL_SITES } from '../steps';
import type { UiState } from '../state';

export type Tone = 'red' | 'amber' | 'green' | 'gray';
export type ActionId = 'connect' | 'retry' | 'grant-site' | 'grant-all';

export interface Headline {
  tone: Tone;
  title: string;
  why: string;
  action?: { id: ActionId; label: string };
  /** A command the user can run, shown to copy. */
  command?: string;
}

/**
 * What the panel says first: what changed, what to do next, what is
 * blocked. One place, so every state has a sentence and an action.
 */
export function describe(ui: UiState): Headline {
  if (!ui.consent) {
    return {
      tone: 'gray',
      title: 'Wisp is off in this browser',
      why: 'Wisp cannot read or act on any page until you connect it.',
      action: { id: 'connect', label: 'Connect Wisp' },
    };
  }
  const link = ui.link;
  if (link.kind === 'unavailable') {
    switch (link.code) {
      case 'host_missing':
        return {
          tone: 'red',
          title: "Wisp's native host is not installed",
          why: 'Chrome could not find the helper that connects this extension to Wisp.',
          action: { id: 'retry', label: 'Try again' },
          command: 'wispd browser install-host --dev',
        };
      case 'host_forbidden':
        return {
          tone: 'red',
          title: 'Wisp does not know this extension',
          why: "The native host's allowed list does not include this extension's id.",
          action: { id: 'retry', label: 'Try again' },
          command: 'wispd browser status',
        };
      case 'wisp_unavailable':
        return {
          tone: 'red',
          title: 'Wisp is not running, or its browser lane is off',
          why: 'The helper started, but wispd is not listening for the browser.',
          action: { id: 'retry', label: 'Try again' },
          command: 'wispd config set browser.lane extension',
        };
      default:
        return {
          tone: 'red',
          title: 'Wisp could not be reached',
          why: link.message || 'The connection to Wisp ended.',
          action: { id: 'retry', label: 'Try again' },
          command: 'wispd browser status',
        };
    }
  }
  if (link.kind !== 'connected') {
    return {
      tone: 'amber',
      title: 'Connecting to Wisp',
      why: 'This takes a moment. Wisp has not been given access to anything yet.',
    };
  }
  if (ui.pendingGrant && ui.pendingGrant.pattern === ALL_SITES) {
    return {
      tone: 'amber',
      title: 'Wisp is waiting for your OK to take a screenshot',
      why: 'Chrome only lets an extension capture a tab if it may use every site. Wisp still asks before it opens each one.',
      action: { id: 'grant-all', label: 'Allow all sites' },
    };
  }
  if (ui.pendingGrant) {
    return {
      tone: 'amber',
      title: `Wisp is waiting for your OK on ${ui.pendingGrant.host}`,
      why: 'It needs to open or read this site. Nothing happens on it until you allow it.',
      action: { id: 'grant-site', label: `Allow ${ui.pendingGrant.host}` },
    };
  }
  if (ui.stopped) {
    return {
      tone: 'gray',
      title: 'Stopped',
      why: "Wisp's tabs are closed and nothing else will run this turn. Your next request starts clean.",
    };
  }
  if (ui.running) {
    return {
      tone: 'green',
      title: 'Wisp is working',
      why: 'Its tabs are in the Wisp group beside yours. Press Stop to end it.',
    };
  }
  return {
    tone: 'green',
    title: 'Connected',
    why: 'Waiting for a task. Ask Wisp to do something in your browser.',
  };
}

/** Roughly 140 characters, whole words where possible. */
export function truncate(s: string, max = 140): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1).trimEnd() + '\u2026';
}
