// The Wisp mark as inline SVG: a soft dot with one curved, tapered tail. The
// hero stage uses the full comet (the canvas in client/mark.ts draws the same
// shape and replaces it once it is running); the small glyph has a shorter,
// straighter tail so it holds up at navbar size. Fills come from --pop.
// public/favicon.svg is the same small glyph with the pop colour written out.
export function Mark({ size = "hero", className }: { size?: "hero" | "small"; className?: string }) {
  if (size === "small") {
    return (
      <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
        <path className="fill-primary" d="M21 6.6C14 8 8.6 14.6 4.6 25.4C11.4 21.6 17 18.2 22.2 17.6Z" />
        <circle className="fill-primary" cx="21.5" cy="12" r="6" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 360 360" aria-hidden="true" className={className}>
      <defs>
        <radialGradient id="mark-glow">
          <stop offset="0" className="mark-glow-a" />
          <stop offset="1" className="mark-glow-b" />
        </radialGradient>
      </defs>
      <circle cx="196" cy="168" r="52" fill="url(#mark-glow)" />
      <path className="fill-primary" d="M196 153C160 149 116 170 76 224C122 204 160 191 196 183Z" />
      <circle className="fill-primary" cx="196" cy="168" r="20" />
    </svg>
  );
}
