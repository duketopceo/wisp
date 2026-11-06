// First-paint module: theme toggle, copy button, and the decision to load the
// WebGL hero. Everything here is optional; the page works without it.
const root = document.documentElement;

function theme(): "light" | "dark" {
  const set = root.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const toggle = document.querySelector<HTMLButtonElement>("#theme-toggle");
if (toggle) {
  const paint = () => {
    const now = theme();
    toggle.setAttribute("aria-label", now === "dark" ? "Switch to light theme" : "Switch to dark theme");
    toggle.querySelector<SVGElement>(".theme-sun")?.toggleAttribute("hidden", now !== "dark");
    toggle.querySelector<SVGElement>(".theme-moon")?.toggleAttribute("hidden", now === "dark");
  };
  toggle.hidden = false;
  paint();
  toggle.addEventListener("click", () => {
    const next = theme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("wisp-theme", next); } catch { /* private mode: not remembered */ }
    paint();
  });
}

const copy = document.querySelector<HTMLButtonElement>("#copy-install");
const code = document.querySelector<HTMLElement>("#install-code");
const status = document.querySelector<HTMLElement>("#copy-status");
if (copy && code && status) {
  copy.disabled = false;
  copy.addEventListener("click", async () => {
    try {
      if (!navigator.clipboard) throw new Error("no clipboard");
      await navigator.clipboard.writeText(code.textContent ?? "");
      status.textContent = "Command copied. Review the bootstrap source before running it.";
    } catch {
      const range = document.createRange();
      range.selectNodeContents(code);
      getSelection()?.removeAllRanges();
      getSelection()?.addRange(range);
      status.textContent = "Clipboard unavailable. Select and copy the highlighted command.";
    }
  });
}

// The WebGL hero is a nicety: skip it for reduced motion, data saver and
// low-power devices, and only fetch it after the page has painted.
const host = document.querySelector<HTMLElement>("#hero-bg");
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const nav = navigator as Navigator & { connection?: { saveData?: boolean }; deviceMemory?: number };
const lowPower = nav.connection?.saveData === true
  || (nav.hardwareConcurrency ?? 8) <= 2
  || (nav.deviceMemory ?? 8) <= 2;

// data-ready marks that the hero decision is made (tests and screenshots wait on it).
if (host && (lowPower || reduced.matches)) host.dataset.ready = "true";
if (host && !lowPower) {
  let stop: (() => void) | null = null;
  const start = async () => {
    if (stop || reduced.matches) { host.dataset.ready = "true"; return; }
    try {
      const { mountRibbonField } = await import("./hero");
      if (!reduced.matches) stop = mountRibbonField(host, { onLost: () => { stop = null; } });
    } catch {
      host.dataset.hero = "static"; // module failed: keep the designed frame
    } finally {
      host.dataset.ready = "true";
    }
  };
  reduced.addEventListener("change", () => {
    if (reduced.matches) { stop?.(); stop = null; } else { void start(); }
  });
  const later = () => ("requestIdleCallback" in window
    ? requestIdleCallback(() => void start(), { timeout: 1500 })
    : setTimeout(() => void start(), 200));
  if (document.readyState === "complete") later();
  else addEventListener("load", later, { once: true });
}
