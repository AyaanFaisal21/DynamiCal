import { useEffect, useRef, useState } from "react";
import { api, type AppStatus, type ChatMessage } from "../api";
import type { Notify } from "../App";

interface Props {
  status: AppStatus | null;
  notify: Notify;
  onChanged: () => void;
}

const WRITE_TOOLS = new Set(["create_block", "create_task", "complete_task"]);
const SUGGESTIONS = ["What do I have tomorrow?", "Anything due this week?", "When can I study for my next exam?", "What is waiting for my review?"];

export default function ChatPanel({ status, notify, onChanged }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.chat().then(setMessages).catch(() => undefined);
  }, []);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [messages, sending]);

  const send = async (message: string) => {
    const trimmed = message.trim();
    if (!trimmed || sending) return;
    setText("");
    setSending(true);
    const temp: ChatMessage = { id: -Date.now(), role: "user", content: trimmed, tool_calls: null, created_at: new Date().toISOString() };
    setMessages((m) => [...m, temp]);
    try {
      const reply = await api.send(trimmed);
      setMessages((m) => [...m, reply]);
      if (reply.tool_calls?.some((c) => WRITE_TOOLS.has(c.name))) onChanged();
    } catch (err) {
      notify((err as Error).message, true);
    } finally {
      setSending(false);
    }
  };

  const clear = async () => {
    await api.clearChat().catch(() => undefined);
    setMessages([]);
  };

  const llmOff = status !== null && !status.llm.enabled;

  return (
    <div className="chat">
      <div className="log" ref={logRef}>
        {llmOff && (
          <div className="card small">
            <p style={{ margin: 0 }}>
              No model is configured, so chat can only list a day's events. Set <code>LLM_PROVIDER</code> in <code>.env</code> to <code>gemini</code> or <code>local</code> for full answers.
            </p>
          </div>
        )}
        {messages.length === 0 && (
          <div className="empty">
            <div style={{ marginBottom: 10 }}>Ask about your days, deadlines, and free time.</div>
            <div className="inline-list">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="btn small" onClick={() => void send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} style={{ display: "contents" }}>
            <div className={"msg " + m.role}>{m.content}</div>
            {m.tool_calls && m.tool_calls.length > 0 && (
              <div className="tools">
                {m.tool_calls.map((c, i) => (
                  <span key={i} title={JSON.stringify(c.args)}>
                    {c.name.replaceAll("_", " ")}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {sending && <div className="msg assistant muted">Thinking…</div>}
      </div>
      <div className="composer">
        <textarea
          value={text}
          placeholder="Ask about your calendar…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(text);
            }
          }}
          rows={1}
        />
        <button className="btn primary" onClick={() => void send(text)} disabled={sending || !text.trim()}>
          Send
        </button>
        <button className="btn ghost" onClick={() => void clear()} title="Clear the conversation" disabled={!messages.length}>
          Clear
        </button>
      </div>
    </div>
  );
}
