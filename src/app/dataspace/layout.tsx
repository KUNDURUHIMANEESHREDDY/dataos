"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { ApiError, api } from "@/lib/api";

export default function DataspaceLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"checking" | "ready" | "error">("checking");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setStatus("checking");
    setError(null);

    api.authMe().then((session) => {
      if (!active) return;
      if (!session?.authenticated && !String(session?.detail || "").includes("JWT auth is not configured")) {
        router.replace("/login?next=%2Fdataspace");
        return;
      }
      setStatus("ready");
    }).catch((cause) => {
      if (!active) return;
      if (cause instanceof ApiError && cause.status === 401) {
        router.replace("/login?next=%2Fdataspace");
        return;
      }
      setError(cause instanceof Error ? cause.message : "Unable to verify your DataOS session.");
      setStatus("error");
    });

    return () => {
      active = false;
    };
  }, [attempt, router]);

  if (status === "ready") return children;

  if (status === "error") {
    return (
      <main className="min-h-screen flex items-center justify-center bg-[var(--color-canvas)] px-4">
        <section className="w-full max-w-md rounded-2xl border border-[var(--color-border-subtle)] bg-white p-7 shadow-lg">
          <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Session check unavailable</h1>
          <p role="alert" className="mt-2 text-sm text-[var(--color-text-secondary)]">{error}</p>
          <button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
            className="mt-5 rounded-lg bg-[var(--color-entity)] px-4 py-2 text-sm font-semibold text-white"
          >
            Try again
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-[var(--color-canvas)]" role="status" aria-live="polite">
      <div className="rounded-xl border border-[var(--color-border-subtle)] bg-white px-5 py-4 text-sm text-[var(--color-text-secondary)] shadow-sm">
        Checking your DataOS session…
      </div>
    </main>
  );
}
