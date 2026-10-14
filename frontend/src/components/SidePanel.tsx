import { useEffect, useState } from "react";
import { api, type AppStatus, type CalEvent } from "../api";
import type { Notify } from "../App";
import ChatPanel from "./ChatPanel";
import ReviewPanel from "./ReviewPanel";
import TodoPanel from "./TodoPanel";
import InboxPanel from "./InboxPanel";

export type Tab = "chat" | "review" | "todo" | "inbox";

interface Props {
  tab: Tab;
  onTab: (t: Tab) => void;
  status: AppStatus | null;
  anchor: Date;
  refreshKey: number;
  onOpenEvent: (id: number) => void;
  onChanged: () => void;
  notify: Notify;
}

export default function SidePanel(p: Props) {
  const [proposals, setProposals] = useState<CalEvent[]>([]);

  useEffect(() => {
    api.proposals().then(setProposals).catch(() => undefined);
  }, [p.refreshKey]);

  const tabs: { id: Tab; label: string }[] = [
    { id: "chat", label: "Chat" },
    { id: "review", label: proposals.length ? `Review (${proposals.length})` : "Review" },
    { id: "todo", label: "To-do" },
    { id: "inbox", label: "Inbox" },
  ];

  return (
    <aside className="side">
      <div className="tabs">
        {tabs.map((t) => (
          <button key={t.id} className={p.tab === t.id ? "on" : ""} onClick={() => p.onTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      {p.tab === "chat" && <ChatPanel status={p.status} notify={p.notify} onChanged={p.onChanged} />}
      {p.tab === "review" && <ReviewPanel proposals={proposals} onOpenEvent={p.onOpenEvent} onChanged={p.onChanged} notify={p.notify} />}
      {p.tab === "todo" && <TodoPanel anchor={p.anchor} status={p.status} refreshKey={p.refreshKey} onOpenEvent={p.onOpenEvent} onChanged={p.onChanged} notify={p.notify} />}
      {p.tab === "inbox" && <InboxPanel refreshKey={p.refreshKey} onOpenEvent={p.onOpenEvent} onChanged={p.onChanged} notify={p.notify} />}
    </aside>
  );
}
