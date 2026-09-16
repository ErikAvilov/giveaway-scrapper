import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export function Button({
  className,
  variant = "default",
  size = "sm",
  ...props
}: ComponentProps<"button"> & {
  variant?: "default" | "secondary" | "ghost" | "danger" | "outline";
  size?: "sm" | "xs" | "md" | "lg" | "fill";
}) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
        size === "xs" && "h-8 px-2.5 text-sm",
        size === "sm" && "h-10 px-3 text-sm",
        size === "md" && "h-11 px-4 text-base",
        size === "lg" && "h-12 px-4 text-base",
        size === "fill" && "h-full min-h-11 w-full px-2 text-sm leading-tight",
        variant === "default" &&
          "border-zinc-900 bg-zinc-900 text-zinc-50 hover:bg-zinc-800 dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white",
        variant === "secondary" &&
          "border-zinc-300 bg-zinc-100 text-zinc-900 hover:bg-zinc-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800",
        variant === "outline" &&
          "border-zinc-300 bg-transparent text-zinc-800 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-900",
        variant === "ghost" &&
          "border-transparent bg-transparent text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-900",
        variant === "danger" &&
          "border-red-800 bg-red-700 text-white hover:bg-red-600",
        className,
      )}
      {...props}
    />
  );
}
