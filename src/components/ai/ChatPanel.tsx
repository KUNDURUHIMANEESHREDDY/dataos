"use client";

import { useState, useRef, useEffect } from "react";
import { useSpatialStore } from "@/hooks/useSpatialStore";
import { api } from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  evidence?: any[];
}

export default function ChatPanel() {
  const open = useSpatialStore((s) => s.chatOpen);
  const setOpen = useSpatialStore((s) => s.setChatOpen);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (!open) return null;

  async function handleSend() {
    const q = input.trim();
    if (!q || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setLoading(true);

    try {
      const res = await api.askDataOS(q);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.answer || res.response || JSON.stringify(res),
          evidence: res.evidence || res.sources || [],
        },
      ]);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed right-4 bottom-20 z-[90] w-96 animate-slide-up">
      <div className="glass-heavy rounded-2xl overflow-hidden flex flex-col h-[480px] shadow-[var(--shadow-glass-xl)]">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border-subtle)]">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-gradient-to-br from-[var(--color-dataset)] to-[var(--color-entity)] flex items-center justify-center">
              <span className="text-white text-[9px] font-bold">AI</span>
            </div>
            <span className="font-display font-semibold text-sm">Ask DataOS</span>
          </div>
          <button
            onClick={() => setOpen(false)}
            className="text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)] transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && (
            <div className="text-center text-sm text-[var(--color-text-tertiary)] py-8">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-[var(--color-dataset)] to-[var(--color-entity)] flex items-center justify-center mx-auto mb-3">
                <span className="text-white text-sm font-bold">AI</span>
              </div>
              Ask questions about your data.
              <br />
              <span className="text-[10px] mt-1 block">
                Try: &ldquo;What datasets are available?&rdquo;
              </span>
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${
                  msg.role === "user"
                    ? "bg-[var(--color-dataset)] text-white"
                    : "glass-inset text-[var(--color-text-primary)]"
                }`}
              >
                <div className="whitespace-pre-wrap">{msg.content}</div>
                {msg.evidence && msg.evidence.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-[var(--color-border-subtle)] space-y-1">
                    <div className="text-[10px] font-medium text-[var(--color-text-tertiary)]">
                      Sources
                    </div>
                    {msg.evidence.slice(0, 3).map((e: any, j: number) => (
                      <div key={j} className="text-[10px] text-[var(--color-text-secondary)]">
                        {e.name || e.source || `Source ${j + 1}`}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="glass-inset rounded-xl px-3 py-2 text-sm text-[var(--color-text-tertiary)]">
                <div className="flex gap-1">
                  <span className="animate-bounce" style={{ animationDelay: "0ms" }}>·</span>
                  <span className="animate-bounce" style={{ animationDelay: "150ms" }}>·</span>
                  <span className="animate-bounce" style={{ animationDelay: "300ms" }}>·</span>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <div className="p-3 border-t border-[var(--color-border-subtle)]">
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="Ask about your data..."
              className="flex-1 glass-input rounded-lg px-3 py-2 text-sm outline-none"
            />
            <button
              onClick={handleSend}
              disabled={loading || !input.trim()}
              className="px-3 py-2 rounded-lg bg-[var(--color-dataset)] text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-40"
            >
              →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
