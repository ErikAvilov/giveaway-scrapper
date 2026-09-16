import type { ComponentProps } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide",
  {
    variants: {
      variant: {
        default: "border-zinc-300 bg-zinc-100 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300",
        france: "border-sky-700/40 bg-sky-50 text-sky-800 dark:border-sky-500/40 dark:bg-sky-950 dark:text-sky-300",
        free: "border-emerald-700/40 bg-emerald-50 text-emerald-800 dark:border-emerald-500/40 dark:bg-emerald-950 dark:text-emerald-300",
        purchase: "border-amber-700/40 bg-amber-50 text-amber-900 dark:border-amber-500/40 dark:bg-amber-950 dark:text-amber-300",
        social: "border-violet-700/40 bg-violet-50 text-violet-800 dark:border-violet-500/40 dark:bg-violet-950 dark:text-violet-300",
        danger: "border-red-700/40 bg-red-50 text-red-800 dark:border-red-500/40 dark:bg-red-950 dark:text-red-300",
        warn: "border-orange-700/40 bg-orange-50 text-orange-900 dark:border-orange-500/40 dark:bg-orange-950 dark:text-orange-300",
        muted: "border-zinc-400/40 bg-zinc-50 text-zinc-500 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-400",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
