// First-paint module: theme toggle, copy button, and the decision to load the
// live comet. Everything here is optional; the page works without it.
const root = document.documentElement;
let recolor: () => void = () => {};

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
    recolor();
  });
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => recolor());

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

// The live comet is a nicety: skip it for reduced motion, data saver and
// low-power devices, and only fetch it after the page has painted. The SVG still
// in the stage stays when anything here is skipped or fails.
const host = document.querySelector<HTMLElement>("#hero-mark");
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const nav = navigator as Navigator & { connection?: { saveData?: boolean }; deviceMemory?: number };
const lowPower = nav.connection?.saveData === true
  || (nav.hardwareConcurrency ?? 8) <= 2
  || (nav.deviceMemory ?? 8) <= 2;

// data-ready marks that the decision is made (tests and screenshots wait on it);
// data-mark is "live" only once the canvas has drawn its first frame.
if (host && (lowPower || reduced.matches)) host.dataset.ready = "true";
if (host && !lowPower) {
  let mark: { stop: () => void; recolor: () => void } | null = null;
  const still = () => { mark?.stop(); mark = null; host.dataset.mark = "still"; };
  const start = async () => {
    if (mark || reduced.matches) { host.dataset.ready = "true"; return; }
    try {
      const { mountMark } = await import("./mark");
      if (!reduced.matches) {
        mark = mountMark(host, { onLive: () => { host.dataset.mark = "live"; }, onLost: still });
        recolor = () => mark?.recolor();
      }
    } catch {
      still(); // module or canvas failed: keep the designed still
    } finally {
      host.dataset.ready = "true";
    }
  };
  reduced.addEventListener("change", () => {
    if (reduced.matches) still(); else void start();
  });
  const later = () => ("requestIdleCallback" in window
    ? requestIdleCallback(() => void start(), { timeout: 1500 })
    : setTimeout(() => void start(), 200));
  if (document.readyState === "complete") later();
  else addEventListener("load", later, { once: true });
}
