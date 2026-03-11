"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";

export default function Nav() {
  const { user, logout } = useAuth();

  if (!user) return null;

  return (
    <nav className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <Link href="/" className="text-lg font-semibold text-gray-900">
            Shortlist
          </Link>
          <Link
            href="/"
            className="text-sm text-gray-600 hover:text-gray-900"
          >
            Dashboard
          </Link>
          <Link
            href="/profile"
            className="text-sm text-gray-600 hover:text-gray-900"
          >
            Profile
          </Link>
          <Link
            href="/history"
            className="text-sm text-gray-600 hover:text-gray-900"
          >
            History
          </Link>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">{user.email}</span>
          <button
            onClick={logout}
            className="text-sm text-gray-600 hover:text-gray-900"
          >
            Log out
          </button>
        </div>
      </div>
    </nav>
  );
}
