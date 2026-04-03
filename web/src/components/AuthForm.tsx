"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import { track } from "@/lib/analytics";

interface Props {
  mode: "login" | "signup";
}

export default function AuthForm({ mode }: Props) {
  const router = useRouter();
  const { login, signup } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "login") {
        await login(email, password);
        track.loggedIn();
      } else {
        await signup(email, password);
        track.signedUp();
      }
      router.push(mode === "signup" ? "/profile" : "/");
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Something went wrong";
      setError(msg);
      if (mode === "login") track.loginFailed(msg);
      else track.signupFailed(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto mt-24 max-w-sm animate-fade-up">
      <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-3">
        {mode === "login" ? "Welcome back" : "Get started"}
      </p>
      <h1 className="text-2xl font-bold tracking-tighter text-gray-900">
        {mode === "login" ? "Log in" : "Create account"}
      </h1>
      <form onSubmit={handleSubmit} className="mt-8 space-y-5">
        <div>
          <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>
        <div>
          <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-full bg-gray-900 px-4 py-3 text-sm font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98] disabled:opacity-50"
        >
          {loading ? "..." : mode === "login" ? "Log in" : "Sign up"}
        </button>
      </form>
      <p className="mt-6 text-sm text-gray-500">
        {mode === "login" ? (
          <>
            Don&apos;t have an account?{" "}
            <Link href="/signup" className="text-emerald-600 hover:text-emerald-700">
              Sign up
            </Link>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <Link href="/login" className="text-emerald-600 hover:text-emerald-700">
              Log in
            </Link>
          </>
        )}
      </p>
    </div>
  );
}
