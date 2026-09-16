"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  return (
    <div className="flex min-h-screen">
      <Sidebar pathname={pathname} />
      <main className="min-w-0 flex-1 overflow-auto">{children}</main>
    </div>
  );
}
