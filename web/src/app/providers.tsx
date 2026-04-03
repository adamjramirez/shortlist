"use client";

import { useEffect } from "react";
import { AuthProvider } from "@/lib/auth-context";
import { initPostHog } from "@/lib/posthog";
import Nav from "@/components/Nav";

export function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    initPostHog();
  }, []);

  return (
    <AuthProvider>
      <Nav />
      <main className="mx-auto max-w-[1200px] px-6 pt-20 pb-6">{children}</main>
    </AuthProvider>
  );
}
