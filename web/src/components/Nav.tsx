"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { List, X } from "@phosphor-icons/react";

export default function Nav() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  if (!user) return null;

  function navLink(href: string, label: string) {
    const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
    return (
      <Link
        href={href}
        onClick={() => setMenuOpen(false)}
        className={`text-sm transition-colors ${
          active
            ? "font-medium text-gray-900"
            : "text-gray-500 hover:text-gray-900"
        }`}
      >
        {label}
      </Link>
    );
  }

  return (
    <nav className="fixed top-0 inset-x-0 z-40 backdrop-blur-xl bg-gray-50/80 border-b border-gray-200/50 shadow-[inset_0_-1px_0_rgba(255,255,255,0.8)]">
      <div className="mx-auto flex max-w-[1200px] items-center justify-between px-6 py-3">
        <div className="flex items-center gap-8">
          <Link href="/" className="text-lg font-semibold tracking-tight text-gray-900">
            Shortlist
          </Link>
          <div className="hidden sm:flex items-center gap-6">
            {navLink("/", "Dashboard")}
            {navLink("/profile", "Profile")}
            {navLink("/history", "History")}
          </div>
        </div>
        <div className="hidden sm:flex items-center gap-4">
          <span className="font-mono text-xs text-gray-400 truncate max-w-[200px]">{user.email}</span>
          <button
            onClick={logout}
            className="rounded-full border border-gray-300 px-4 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-white"
          >
            Log out
          </button>
        </div>
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          className="sm:hidden p-1.5 text-gray-600 hover:text-gray-900"
          aria-label="Menu"
        >
          {menuOpen ? <X size={22} weight="bold" /> : <List size={22} weight="bold" />}
        </button>
      </div>
      {menuOpen && (
        <div className="sm:hidden border-t border-gray-200/50 px-6 py-4 flex flex-col space-y-3 bg-gray-50/95 backdrop-blur-xl">
          {navLink("/", "Dashboard")}
          {navLink("/profile", "Profile")}
          {navLink("/history", "History")}
          <div className="pt-3 border-t border-gray-200/50">
            <p className="font-mono text-xs text-gray-400 truncate">{user.email}</p>
            <button
              onClick={() => { setMenuOpen(false); logout(); }}
              className="mt-2 text-sm text-gray-600 hover:text-gray-900"
            >
              Log out
            </button>
          </div>
        </div>
      )}
    </nav>
  );
}
