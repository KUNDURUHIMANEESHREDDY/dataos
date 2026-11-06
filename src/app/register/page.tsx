"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api.register({ username: username.trim(), email: email.trim(), password });
      await api.login(email.trim(), password);
      router.replace("/dataspace");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create your account. Please try again.");
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
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--color-text-primary)]">Create your account</h1>
          <p className="mt-2 text-sm leading-6 text-[var(--color-text-secondary)]">Your account starts with viewer access. An administrator can grant additional capabilities.</p>
        </div>

        <form onSubmit={submit} className="space-y-5">
          <div>
            <label htmlFor="username" className="mb-2 block text-sm font-medium text-[var(--color-text-primary)]">Username</label>
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              minLength={3}
              maxLength={64}
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="w-full rounded-lg border border-[var(--color-border-subtle)] bg-white px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-entity)] focus:ring-2 focus:ring-[var(--color-entity)]/15"
            />
          </div>
          <div>
            <label htmlFor="email" className="mb-2 block text-sm font-medium text-[var(--color-text-primary)]">Email</label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="w-full rounded-lg border border-[var(--color-border-subtle)] bg-white px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-entity)] focus:ring-2 focus:ring-[var(--color-entity)]/15"
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-2 block text-sm font-medium text-[var(--color-text-primary)]">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="new-password"
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
            {pending ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-[var(--color-text-secondary)]">
          Already registered?{" "}
          <Link href="/login" className="font-semibold text-[var(--color-entity)] underline-offset-4 hover:underline">Sign in</Link>
        </p>
      </section>
    </main>
  );
}
