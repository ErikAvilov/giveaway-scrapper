import Link from "next/link";
import { cn } from "@/lib/utils";
import {
  Activity,
  Database,
  Gift,
  LayoutDashboard,
  Radio,
} from "lucide-react";

const links = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/giveaways", label: "Giveaways", icon: Gift },
  { href: "/sources", label: "Sources", icon: Radio },
  { href: "/crawl-runs", label: "Crawl runs", icon: Activity },
];

export function Sidebar({ pathname }: { pathname: string }) {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="border-b border-zinc-200 px-4 py-4 dark:border-zinc-800">
        <div className="flex items-center gap-2.5">
          <Database className="h-5 w-5 text-zinc-500" />
          <div>
            <div className="text-base font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              Giveaways
            </div>
            <div className="text-xs uppercase tracking-wider text-zinc-500">
              Admin
            </div>
          </div>
        </div>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {links.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2.5 text-sm font-medium",
                active
                  ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50"
                  : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-zinc-200 px-4 py-3 text-xs text-zinc-500 dark:border-zinc-800">
        Local · Neon
      </div>
    </aside>
  );
}
