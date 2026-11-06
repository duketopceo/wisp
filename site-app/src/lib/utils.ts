// From launch-ui (MIT, Copyright (c) 2024 Mikolaj Dobrucki): lib/utils.ts.
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
