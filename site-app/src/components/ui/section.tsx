// Adapted from launch-ui (MIT, Copyright (c) 2024 Mikolaj Dobrucki): components/ui/section.tsx.
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Section({ className, ...props }: ComponentProps<"section">) {
  return <section className={cn("line-b px-4 py-16 sm:py-24", className)} {...props} />;
}

export function SectionHeading({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <div className="flex max-w-[640px] flex-col gap-4">
      <p className="text-brand text-sm font-semibold tracking-wide uppercase">{eyebrow}</p>
      <h2 className="text-3xl leading-tight font-semibold tracking-tight text-balance sm:text-5xl sm:leading-tight">{title}</h2>
      {children && <div className="text-muted-foreground text-base text-pretty sm:text-lg">{children}</div>}
    </div>
  );
}
