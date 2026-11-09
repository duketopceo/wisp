// Adapted from launch-ui (MIT, Copyright (c) 2024 Mikolaj Dobrucki):
// components/ui/button.tsx and link-button.tsx. Radix Slot dropped: the page
// is rendered once at build time, so links and buttons are plain elements.
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-semibold disabled:pointer-events-none disabled:opacity-50 active:scale-button-pressed [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "border-2 border-foreground bg-primary text-primary-foreground hover:bg-foreground hover:text-background",
        outline: "border border-foreground/40 bg-transparent hover:bg-muted",
        ghost: "hover:bg-muted",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-11 rounded-md px-5 text-base",
        icon: "size-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

type Variants = VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, ...props }: ComponentProps<"button"> & Variants) {
  return <button className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export function LinkButton({ className, variant, size = "lg", ...props }: ComponentProps<"a"> & Variants) {
  return <a className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}
