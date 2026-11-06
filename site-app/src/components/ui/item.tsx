// Adapted from launch-ui (MIT, Copyright (c) 2024 Mikolaj Dobrucki): components/ui/item.tsx.
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Item({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("text-foreground flex flex-col gap-3 p-5", className)} {...props} />;
}

export function ItemTitle({ className, ...props }: ComponentProps<"h3">) {
  return <h3 className={cn("text-base leading-snug font-semibold tracking-tight", className)} {...props} />;
}

export function ItemDescription({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("text-muted-foreground flex flex-col gap-2 text-sm text-pretty", className)} {...props} />;
}

export function ItemIcon({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("text-brand flex items-center self-start", className)} {...props} />;
}
