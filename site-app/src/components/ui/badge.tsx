// Adapted from launch-ui (MIT, Copyright (c) 2024 Mikolaj Dobrucki): components/ui/badge.tsx.
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Badge({ className, ...props }: ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border border-foreground/15 bg-background/40 px-3 py-1 text-xs font-semibold backdrop-blur-sm",
        className,
      )}
      {...props}
    />
  );
}
