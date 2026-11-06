// Every claim on the homepage, in one place. Copy and facts come from the
// previous homepage (site-3d/index.html), the no-script page (site/) and the
// README; nothing here is a new feature claim.
import costsJson from "../../site/costs.json";

export const REPO = "https://github.com/duketopceo/wisp";
export const VERSION = "v1.0.0-rc.2";
export const JOB = "Wisp is a voice teacher and doer for Omarchy that points at your screen.";
export const INSTALL = `f=$(mktemp) && curl -fsSL https://wisp.observer/install.py -o "$f" && python3 "$f" --version ${VERSION}`;

export const hero = {
  badge: `Linux release candidate ${VERSION}`,
  titleLead: "Your voice.",
  titleTail: "A little more",
  titleAccent: "reach.",
  description: `${JOB} Ask a question, find a control, or take the next step.`,
};

export const features = [
  { icon: "eye", title: "Answers about your screen",
    body: "Ask about what is on your screen and Wisp answers out loud, pointing the cursor buddy at the thing it means.",
    href: `${REPO}/blob/master/README.md#using-it`, cite: "README" },
  { icon: "pen", title: "Draw to ask",
    body: "A circle or scribble you draw while you hold the key becomes part of the question.",
    href: `${REPO}/blob/master/wisp/scribble.py`, cite: "code" },
  { icon: "book", title: "Knows your Omarchy",
    body: "Answers Omarchy questions from your own install (version, theme, your rebound keys) rather than a manual.",
    href: `${REPO}/blob/master/wisp/omarchy_tutor.py`, cite: "code" },
  { icon: "hourglass", title: "Long jobs in the background",
    body: "Hands a long job to a background helper and tells you when it finishes.",
    href: `${REPO}/blob/master/README.md#using-it`, cite: "README" },
  { icon: "users", title: "Knows where you are",
    body: "Personal and work browser profiles give a request its context.",
    href: undefined, cite: undefined },
  { icon: "shield", title: "Keeps the sensitive step yours",
    body: "Confirmation gates protect sensitive actions. Review the trust model before enabling execution.",
    href: `${REPO}/blob/master/docs/TRUST.md`, cite: "trust model" },
] as const;

export const steps = [
  { title: "Hold Super + D and speak",
    body: "Hold the key, say what you want, then release. Nothing is sent between key presses." },
  { title: "Wisp looks and answers",
    body: "It uses screen context to explain what you’re seeing, point out a control, or work through a task. The companion shows listening, thinking, acting, and confirmation states." },
  { title: "You approve what matters",
    body: "Confirmation gates protect sensitive actions: Wisp does the step for you and asks first when it matters." },
] as const;

export const trust = {
  lead: "There is no analytics, no account and no Wisp server: each request goes from your machine to a provider you choose, with your key.",
  points: [
    "Nothing is sent between key presses.",
    "With a cloud model, the screenshot for the turn that needs it goes to that provider. screenshots = \"false\" or a local model keeps it on your machine.",
    "Error reporting is off by default.",
    "This page loads nothing from any other host and has no analytics.",
  ],
  href: `${REPO}/blob/master/docs/TRUST.md`,
  linkText: "What leaves your machine: every host, what it gets and who holds the key",
};

type CostItem = { label: string; value: string; source: string; as_of: string; kind?: string };
type Costs = { status: string; note?: string; items: CostItem[] };

export const costs: Costs = (() => {
  const c = costsJson as Costs;
  for (const it of c.items) {
    for (const key of ["label", "value", "source", "as_of"] as const) {
      if (!it[key]) throw new Error(`cost item missing ${key}: ${JSON.stringify(it)}`);
    }
  }
  return c;
})();

export const faq = [
  { q: "What does Wisp run on?",
    a: [`Omarchy / Hyprland is the full-app target. The Linux candidate ${VERSION} is for x86_64 and ARM64. macOS and Windows support is experimental.`] },
  { q: "What do I need before installing?",
    a: ["Python 3.11.4+, curl and an independently installed GitHub CLI for the bootstrap. Wisp itself needs whisper.cpp with a model, plus a model provider key or a local model server."] },
  { q: "Is the install command safe to run?",
    a: ["The bootstrap is not self-authenticating, so review its source first. It requires the independently trusted gh verifier and the exact release identity, and native payload attestations are verified before extraction."] },
  { q: "Can it run with local models?",
    a: ["Yes. wispd config preset local sets local defaults, but presets set defaults, not credentials or downloaded models. A local preset alone does not make every data path local; the trust page lists each one."] },
  { q: "What does it cost?",
    a: ["The model bill is the only cost. Wisp ships with a daily and a monthly spend cap, and local models are recorded at $0.00 and never gated."] },
  { q: "Is it finished?",
    a: ["No. Wisp is early-stage software, with real-desktop evaluation still ahead. The roadmap tracks readiness gates and current work."] },
] as const;
