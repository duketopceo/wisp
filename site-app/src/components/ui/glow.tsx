// Adapted from launch-ui (MIT, Copyright (c) 2024 Mikolaj Dobrucki): components/ui/glow.tsx.
import { cn } from "@/lib/utils";

export function Glow({ className }: { className?: string }) {
  return (
    <div aria-hidden="true" className={cn("pointer-events-none absolute w-full", className)}>
      <div className="from-brand-foreground/40 to-brand-foreground/0 absolute left-1/2 h-[200px] w-[60%] -translate-x-1/2 scale-[2.5] rounded-[50%] bg-radial from-10% to-60% opacity-25 sm:h-[360px] dark:opacity-60" />
      <div className="from-brand/30 to-brand/0 absolute left-1/2 h-[100px] w-[40%] -translate-x-1/2 scale-200 rounded-[50%] bg-radial from-10% to-60% opacity-25 sm:h-[200px] dark:opacity-70" />
    </div>
  );
}
