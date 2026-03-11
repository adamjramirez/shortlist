"use client";

import { AuthProvider } from "@/lib/auth-context";
import Nav from "@/components/Nav";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <Nav />
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </AuthProvider>
  );
}
