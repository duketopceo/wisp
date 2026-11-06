// Page sections. Layouts adapted from launch-ui (MIT, Copyright (c) 2024
// Mikolaj Dobrucki) components/sections/{navbar,hero,items,faq,cta,footer};
// content is Wisp's (see ../../content.ts). Interactive pieces work without
// JavaScript: the FAQ is <details>, the copy and theme buttons stay disabled
// or hidden until the small client module enables them.
import {
  ArrowUpRightIcon,
  BookOpenIcon,
  ChevronDownIcon,
  CopyIcon,
  EyeIcon,
  HourglassIcon,
  MoonIcon,
  PenLineIcon,
  ShieldCheckIcon,
  SunIcon,
  UsersIcon,
} from "lucide-react";

import { costs, faq, features, hero, INSTALL, REPO, steps, trust, VERSION } from "@/content";

import { Badge } from "../ui/badge";
import { Button, LinkButton } from "../ui/button";
import { Glow } from "../ui/glow";
import { Item, ItemDescription, ItemIcon, ItemTitle } from "../ui/item";
import { Section, SectionHeading } from "../ui/section";

const FLAME = "/assets/wisp-flame";

function Github(props: { className?: string }) {
  // launch-ui components/logos/github.tsx
  return (
    <svg viewBox="0 0 438.549 438.549" aria-hidden="true" {...props}>
      <path fill="currentColor" d="M409.132 114.573c-19.608-33.596-46.205-60.194-79.798-79.8-33.598-19.607-70.277-29.408-110.063-29.408-39.781 0-76.472 9.804-110.063 29.408-33.596 19.605-60.192 46.204-79.8 79.8C9.803 148.168 0 184.854 0 224.63c0 47.78 13.94 90.745 41.827 128.906 27.884 38.164 63.906 64.572 108.063 79.227 5.14.954 8.945.283 11.419-1.996 2.475-2.282 3.711-5.14 3.711-8.562 0-.571-.049-5.708-.144-15.417a2549.81 2549.81 0 01-.144-25.406l-6.567 1.136c-4.187.767-9.469 1.092-15.846 1-6.374-.089-12.991-.757-19.842-1.999-6.854-1.231-13.229-4.086-19.13-8.559-5.898-4.473-10.085-10.328-12.56-17.556l-2.855-6.57c-1.903-4.374-4.899-9.233-8.992-14.559-4.093-5.331-8.232-8.945-12.419-10.848l-1.999-1.431c-1.332-.951-2.568-2.098-3.711-3.429-1.142-1.331-1.997-2.663-2.568-3.997-.572-1.335-.098-2.43 1.427-3.289 1.525-.859 4.281-1.276 8.28-1.276l5.708.853c3.807.763 8.516 3.042 14.133 6.851 5.614 3.806 10.229 8.754 13.846 14.842 4.38 7.806 9.657 13.754 15.846 17.847 6.184 4.093 12.419 6.136 18.699 6.136 6.28 0 11.704-.476 16.274-1.423 4.565-.952 8.848-2.383 12.847-4.285 1.713-12.758 6.377-22.559 13.988-29.41-10.848-1.14-20.601-2.857-29.264-5.14-8.658-2.286-17.605-5.996-26.835-11.14-9.235-5.137-16.896-11.516-22.985-19.126-6.09-7.614-11.088-17.61-14.987-29.979-3.901-12.374-5.852-26.648-5.852-42.826 0-23.035 7.52-42.637 22.557-58.817-7.044-17.318-6.379-36.732 1.997-58.24 5.52-1.715 13.706-.428 24.554 3.853 10.85 4.283 18.794 7.952 23.84 10.994 5.046 3.041 9.089 5.618 12.135 7.708 17.705-4.947 35.976-7.421 54.818-7.421s37.117 2.474 54.823 7.421l10.849-6.849c7.419-4.57 16.18-8.758 26.262-12.565 10.088-3.805 17.802-4.853 23.134-3.138 8.562 21.509 9.325 40.922 2.279 58.240 15.036 16.18 22.559 35.787 22.559 58.817 0 16.178-1.958 30.497-5.853 42.966-3.9 12.471-8.941 22.457-15.125 29.979-6.191 7.521-13.901 13.85-23.131 18.986-9.232 5.14-18.182 8.85-26.84 11.136-8.662 2.286-18.415 4.004-29.263 5.146 9.894 8.562 14.842 22.077 14.842 40.539v60.237c0 3.422 1.19 6.279 3.572 8.562 2.379 2.279 6.136 2.95 11.276 1.995 44.163-14.653 80.185-41.062 108.068-79.226 27.88-38.161 41.825-81.126 41.825-128.906-.01-39.771-9.818-76.454-29.414-110.049z" />
    </svg>
  );
}

function Logo({ className }: { className?: string }) {
  return (
    <a href="#main" className={`inline-flex items-center gap-2 text-xl font-bold tracking-tight ${className ?? ""}`} aria-label="Wisp home">
      <img src={`${FLAME}/wisp-flame-32.png`} width={28} height={28} alt="" className="flame-mark" />
      wisp
    </a>
  );
}

export function Navbar() {
  return (
    <header data-stage="dark" className="bg-background/70 text-foreground sticky top-0 z-50 border-b border-foreground/10 backdrop-blur-lg">
      <a href="#main" className="bg-foreground text-background absolute top-2 left-2 -translate-y-24 rounded-md px-3 py-2 focus:translate-y-0">Skip to content</a>
      <nav aria-label="Primary" className="max-w-container mx-auto flex h-16 items-center justify-between gap-4 px-4">
        <Logo />
        <div className="flex items-center gap-1 text-sm sm:gap-2">
          <a href="#how" className="hover:text-primary hidden px-3 py-2 sm:inline">How it works</a>
          <a href="#trust" className="hover:text-primary hidden px-3 py-2 md:inline">Trust</a>
          <a href="#faq" className="hover:text-primary hidden px-3 py-2 md:inline">FAQ</a>
          <a href={REPO} className="hover:text-primary inline-flex items-center gap-1.5 px-3 py-2">
            <Github className="size-4" /><span>GitHub</span>
          </a>
          <Button id="theme-toggle" variant="ghost" size="icon" aria-label="Switch to light theme" hidden>
            <SunIcon className="theme-sun" /><MoonIcon className="theme-moon" />
          </Button>
          <LinkButton href="#install" size="sm" className="ml-1">Install</LinkButton>
        </div>
      </nav>
    </header>
  );
}

export function Hero() {
  return (
    <section data-stage="dark" aria-labelledby="hero-title" className="bg-background text-foreground relative isolate overflow-hidden">
      {/* ThreeUI ribbon field mounts here after first paint; the frame below is the fallback. */}
      <div id="hero-bg" data-hero="static" aria-hidden="true" className="hero-frame absolute inset-0 -z-10" />
      <div className="from-background/0 to-background pointer-events-none absolute inset-x-0 bottom-0 -z-10 h-24 bg-linear-to-b" />
      <div className="max-w-container mx-auto grid min-h-[min(760px,92svh)] items-center gap-10 px-4 pt-16 pb-20 md:grid-cols-[minmax(0,1fr)_minmax(0,360px)] md:pt-20">
        <div className="flex min-w-0 flex-col items-start gap-6 sm:gap-8">
          <Badge className="animate-appear">
            <span className="bg-primary size-1.5 rounded-full" aria-hidden="true" />
            <span className="text-muted-foreground">{hero.badge}</span>
            <a href={`${REPO}/releases/tag/${VERSION}`} className="text-primary inline-flex items-center gap-1">Notes<ArrowUpRightIcon className="size-3" /></a>
          </Badge>
          <h1 id="hero-title" className="animate-appear text-5xl leading-[1.02] font-semibold tracking-tight text-balance sm:text-7xl lg:text-8xl">
            {hero.titleLead}<br />{hero.titleTail} <span className="from-primary to-brand-foreground bg-linear-to-r bg-clip-text text-transparent">{hero.titleAccent}</span>
          </h1>
          <p className="animate-appear text-muted-foreground max-w-[600px] text-lg font-medium text-pretty [animation-delay:100ms] sm:text-xl">{hero.description}</p>
          <div className="animate-appear flex flex-wrap gap-3 [animation-delay:200ms]">
            <LinkButton href="#install">Install on Omarchy<ArrowUpRightIcon /></LinkButton>
            <LinkButton href={REPO} variant="glow"><Github className="size-4" />Source on GitHub</LinkButton>
          </div>
          <p className="text-muted-foreground text-sm">Omarchy / Hyprland is the full-app target. macOS and Windows support is experimental.</p>
        </div>
        <div className="relative order-first mx-auto md:order-none">
          <picture id="flame">
            <source media="(prefers-reduced-motion: reduce)" srcSet={`${FLAME}/wisp-flame-512.png`} />
            <img src={`${FLAME}/idle-256.webp`} width={256} height={256} alt="The Wisp flame, a small translucent blue flame with a bright heart." className="flame-mark size-40 object-contain sm:size-56 md:size-72" />
          </picture>
        </div>
      </div>
    </section>
  );
}

const ICONS = { eye: EyeIcon, pen: PenLineIcon, book: BookOpenIcon, hourglass: HourglassIcon, users: UsersIcon, shield: ShieldCheckIcon };

export function Features() {
  return (
    <Section id="what" aria-labelledby="what-title">
      <div className="max-w-container mx-auto flex flex-col gap-12">
        <div id="what-title"><SectionHeading eyebrow="What Wisp does" title="Less switching. More doing." /></div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => {
            const Icon = ICONS[f.icon];
            return (
              <Item key={f.title} className="glass-2 rounded-xl">
                <ItemTitle className="flex items-center gap-3">
                  <ItemIcon><Icon className="size-5" strokeWidth={1.5} /></ItemIcon>{f.title}
                </ItemTitle>
                <ItemDescription>
                  <p>{f.body}{f.href && <> <a className="text-foreground underline underline-offset-4 hover:text-primary" href={f.href}>{f.cite}</a></>}</p>
                </ItemDescription>
              </Item>
            );
          })}
        </div>
      </div>
    </Section>
  );
}

export function Steps() {
  return (
    <Section id="how" aria-labelledby="how-title" className="relative overflow-hidden">
      <Glow className="top-1/2" />
      <div className="max-w-container relative mx-auto flex flex-col gap-12">
        <div id="how-title"><SectionHeading eyebrow="How it works" title="Hold, speak, release." /></div>
        <ol className="grid gap-4 md:grid-cols-3">
          {steps.map((s, i) => (
            <li key={s.title} className="glass-2 flex flex-col gap-3 rounded-xl p-6">
              <span className="text-primary font-mono text-sm">0{i + 1}</span>
              <h3 className="text-lg font-semibold tracking-tight">
                {i === 0 ? <>Hold <kbd className="bg-muted rounded border px-1.5 py-0.5 text-sm">Super</kbd> + <kbd className="bg-muted rounded border px-1.5 py-0.5 text-sm">D</kbd> and speak</> : s.title}
              </h3>
              <p className="text-muted-foreground text-sm text-pretty">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </Section>
  );
}

export function Trust() {
  return (
    <Section id="trust" aria-labelledby="trust-title">
      <div className="max-w-container mx-auto grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div id="trust-title"><SectionHeading eyebrow="Trust" title="What leaves your machine.">
          <p>{trust.lead}</p>
        </SectionHeading></div>
        <div className="flex flex-col gap-4">
          <ul className="flex flex-col gap-3">
            {trust.points.map((p) => (
              <li key={p} className="flex gap-3 text-pretty"><ShieldCheckIcon className="text-flame mt-1 size-4 shrink-0" strokeWidth={1.75} aria-hidden="true" /><span>{p}</span></li>
            ))}
          </ul>
          <a href={trust.href} className="text-primary inline-flex items-center gap-1 font-semibold underline-offset-4 hover:underline">{trust.linkText}<ArrowUpRightIcon className="size-4" /></a>
        </div>
      </div>
    </Section>
  );
}

export function CostCard() {
  const pending = costs.status !== "measured";
  return (
    <Section id="cost" aria-labelledby="cost-title">
      <div className="max-w-container mx-auto flex flex-col gap-10">
        <div id="cost-title"><SectionHeading eyebrow="Cost" title="What a day costs.">
          {pending && <p>Per-day numbers from the maintainer’s own ledger are not published yet; below are the limits the code ships with.</p>}
        </SectionHeading></div>
        <div className="glass-2 overflow-x-auto rounded-xl">
          <table className="w-full min-w-[520px] text-left text-sm">
            <thead className="text-muted-foreground"><tr><th className="p-4 font-medium">What</th><th className="p-4 font-medium">Number</th><th className="p-4 font-medium">Where it comes from, and when</th></tr></thead>
            <tbody>
              {costs.items.map((it) => (
                <tr key={it.label} className="border-t">
                  <td className="p-4">{it.label}</td>
                  <td className="p-4 font-mono font-semibold whitespace-nowrap">{it.value}</td>
                  <td className="text-muted-foreground p-4">{it.source}, {it.as_of}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {costs.note && <p className="text-muted-foreground max-w-[720px] text-sm">{costs.note} <a className="underline underline-offset-4" href={`${REPO}/blob/master/docs/COSTS.md`}>docs/COSTS.md</a></p>}
      </div>
    </Section>
  );
}

export function Install() {
  return (
    <Section id="install" aria-labelledby="install-title" className="relative overflow-hidden">
      <Glow className="-top-10" />
      <div className="max-w-container relative mx-auto flex flex-col gap-8">
        <div id="install-title"><SectionHeading eyebrow="Install" title="Give your desktop a little Wisp.">
          <p>Omarchy / Hyprland is the full-app target. macOS and Windows support is experimental.</p>
        </SectionHeading></div>
        <div className="glass-4 flex flex-col gap-3 rounded-xl p-3 sm:flex-row sm:items-center">
          <code id="install-code" className="min-w-0 flex-1 overflow-x-auto px-3 py-2 text-sm whitespace-nowrap">{INSTALL}</code>
          <Button id="copy-install" variant="default" size="lg" disabled><CopyIcon />Copy command</Button>
        </div>
        <p id="copy-status" role="status" aria-live="polite" className="text-muted-foreground min-h-5 text-sm"></p>
        <div className="text-muted-foreground grid gap-4 text-pretty md:grid-cols-2 [&_a]:text-foreground [&_a]:underline [&_a]:underline-offset-4 [&_code]:text-foreground">
          <p>Linux candidate <a href={`${REPO}/releases/tag/${VERSION}`}>{VERSION}</a>, for x86_64 and ARM64. Requires Python 3.11.4+, curl and independently installed GitHub CLI. Review the <a href={`${REPO}/blob/${VERSION}/scripts/bootstrap/install.py`}>bootstrap source</a> first; it is not self-authenticating. Native payload attestations are verified before extraction.</p>
          <p>After installation, run <code>~/.local/bin/wispd onboard</code>. It guides setup without putting provider keys in shell history.</p>
          <p>Start with the <a href={`${REPO}/blob/master/docs/INSTALL.md`}>installation guide</a>. Presets: <code>wispd config preset cloud</code>, <code>wispd config preset local</code>, or <code>wispd config preset safe</code>. These set defaults, not credentials or downloaded models. A local preset alone does not make every data path local.</p>
          <p>Early-stage software, with real-desktop evaluation still ahead. Follow the <a href={`${REPO}/blob/master/ROADMAP.md`}>roadmap</a> for readiness gates and current work.</p>
        </div>
      </div>
    </Section>
  );
}

export function Faq() {
  return (
    <Section id="faq" aria-labelledby="faq-title">
      <div className="mx-auto flex max-w-[800px] flex-col gap-10">
        <div id="faq-title"><SectionHeading eyebrow="FAQ" title="Questions and answers" /></div>
        <div className="divide-y border-y">
          {faq.map((item) => (
            <details key={item.q} className="group">
              <summary className="flex items-center justify-between gap-4 py-5 text-left text-base font-semibold hover:text-primary">
                {item.q}<ChevronDownIcon className="faq-chevron text-muted-foreground size-4 shrink-0 transition-transform" aria-hidden="true" />
              </summary>
              <div className="text-muted-foreground flex flex-col gap-2 pb-5 text-pretty">{item.a.map((p) => <p key={p}>{p}</p>)}</div>
            </details>
          ))}
        </div>
      </div>
    </Section>
  );
}

export function Footer() {
  return (
    <footer className="px-4 py-12">
      <div className="max-w-container text-muted-foreground mx-auto flex flex-col gap-6 text-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-2">
          <Logo className="text-foreground" />
          <span>wisp.observer · Cloudflare Workers</span>
        </div>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2 [&_a:hover]:text-foreground">
          <a href={REPO}>Source &amp; documentation</a>
          <a href="/plain/">Plain version (no JavaScript)</a>
          <a href="/light/">Guiding-light preview</a>
          <a href="/credits.txt">Credits</a>
          <a href={`${REPO}/blob/master/LICENSE`}>AGPL-3.0</a>
        </nav>
      </div>
    </footer>
  );
}
