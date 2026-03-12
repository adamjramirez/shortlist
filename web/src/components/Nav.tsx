"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

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
        className={`text-sm ${
          active
            ? "font-medium text-gray-900"
            : "text-gray-600 hover:text-gray-900"
        }`}
      >
        {label}
      </Link>
    );
  }

  return (
    <nav className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <Link href="/" className="text-lg font-semibold text-gray-900">
            Shortlist
          </Link>
          {/* Desktop nav links */}
          <div className="hidden sm:flex items-center gap-6">
            {navLink("/", "Dashboard")}
            {navLink("/profile", "Profile")}
            {navLink("/history", "History")}
          </div>
        </div>
        {/* Desktop right side */}
        <div className="hidden sm:flex items-center gap-4">
          <span className="text-sm text-gray-500 truncate max-w-[200px]">{user.email}</span>
          <button
            onClick={logout}
            className="text-sm text-gray-600 hover:text-gray-900"
          >
            Log out
          </button>
        </div>
        {/* Mobile hamburger */}
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          className="sm:hidden p-1 text-gray-600 hover:text-gray-900"
          aria-label="Menu"
        >
          {menuOpen ? (
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          ) : (
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          )}
        </button>
      </div>
      {/* Mobile menu */}
      {menuOpen && (
        <div className="sm:hidden border-t border-gray-100 px-4 py-3 flex flex-col space-y-3">
          {navLink("/", "Dashboard")}
          {navLink("/profile", "Profile")}
          {navLink("/history", "History")}
          <div className="pt-3 border-t border-gray-100">
            <p className="text-xs text-gray-400 truncate">{user.email}</p>
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
