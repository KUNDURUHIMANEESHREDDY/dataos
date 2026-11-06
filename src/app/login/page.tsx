"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { safeNextPath } from "@/lib/auth-navigation.mjs";

export default function LoginPage() {
  const router = useRouter();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextPath] = useState(() => {
    if (typeof window === "undefined") return "/dataspace";
    return safeNextPath(new URLSearchParams(window.location.search).get("next"));
  });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api.login(login.trim(), password);
      router.replace(nextPath);
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 401
          ? "The username/email or password is incorrect."
          : cause instanceof Error
            ? cause.message
            : "Unable to sign in. Please try again.",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-[var(--color-canvas)] px-4 py-10">
      <section className="w-full max-w-md rounded-2xl border border-[var(--color-border-subtle)] bg-white/90 p-7 shadow-xl sm:p-9">
        <div className="mb-8">
          <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--color-dataset)] to-[var(--color-entity)] text-sm font-bold text-white">D</div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-text-tertiary)]">DataOS workspace</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--color-text-primary)]">Sign in</h1>
          <p className="mt-2 text-sm leading-6 text-[var(--color-text-secondary)]">Use your DataOS account to open your private dataspace.</p>
        </div>

        <form onSubmit={submit} className="space-y-5">
          <div>
            <label htmlFor="login" className="mb-2 block text-sm font-medium text-[var(--color-text-primary)]">Username or email</label>
            <input
              id="login"
              name="login"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={login}
              onChange={(event) => setLogin(event.target.value)}
              className="w-full rounded-lg border border-[var(--color-border-subtle)] bg-white px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-entity)] focus:ring-2 focus:ring-[var(--color-entity)]/15"
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-2 block text-sm font-medium text-[var(--color-text-primary)]">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              minLength={8}
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-lg border border-[var(--color-border-subtle)] bg-white px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-entity)] focus:ring-2 focus:ring-[var(--color-entity)]/15"
            />
          </div>

          {error && <p role="alert" aria-live="polite" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">{error}</p>}

          <button
            type="submit"
            disabled={pending}
            className="w-full rounded-lg bg-[var(--color-entity)] px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-entity)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? "Signing in…" : "Continue to DataOS"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-[var(--color-text-secondary)]">
          New to DataOS?{" "}
          <Link href="/register" className="font-semibold text-[var(--color-entity)] underline-offset-4 hover:underline">Create an account</Link>
        </p>
      </section>
    </main>
  );
}
