import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "./api";

type SessionState = "DRAFT_TAB1" | "LOCKING" | "ACTIVE" | "SUMMARIZING" | "ENDED" | "NARRATING" | "RESETTING";

type SessionDetail = {
  session: {
    session_id: string;
    state: SessionState;
    prompt_index: number;
    last_summarized_prompt_index: number;
    tab1_locked: boolean;
  };
  tab1: {
    world_text: string;
    chapter_text: string;
    selected_agent_slots: number[];
    agent_names: Record<string, string>;
    agent_identity_text_by_slot: Record<string, string>;
    tab1_locked: boolean;
  };
  events: Array<{
    event_id: string;
    prompt_index: number;
    role: "user" | "agent" | "system";
    agent_slot: number | null;
    text: string;
    created_at: string;
  }>;
  memory_blocks: Array<{
    block_id: string;
    type: string;
    from_prompt_index: number;
    to_prompt_index: number;
    json_payload: Record<string, unknown>;
  }>;
  narrative_drafts: Array<{ draft_id: string; chapter_text: string }>;
};

const AGENT_COLORS: Record<number, string> = {
  1: "#ff4a4a",
  2: "#ff9f43",
  3: "#ffd93d",
  4: "#3ddc84",
  5: "#45aaf2",
  6: "#6c5ce7",
  7: "#b56cff",
};

function defaultAgentName(slot: number): string {
  const defaults: Record<number, string> = {
    1: "Agent Red",
    2: "Agent Orange",
    3: "Agent Yellow",
    4: "Agent Green",
    5: "Agent Blue",
    6: "Agent Indigo",
    7: "Agent Violet",
  };
  return defaults[slot] ?? `Agent ${slot}`;
}

type TranscriptLine = {
  key: string;
  text: string;
  color: string;
};

export function App() {
  const [sessionId, setSessionId] = useState<string>("");
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [tab, setTab] = useState<1 | 2 | 3>(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const [worldText, setWorldText] = useState("");
  const [chapterText, setChapterText] = useState("");
  const [agentCount, setAgentCount] = useState(1);
  const [agentNames, setAgentNames] = useState<Record<number, string>>({ 1: "Agent Red" });
  const [agentDefs, setAgentDefs] = useState<Record<number, string>>({ 1: "" });

  const [activeAgentSlot, setActiveAgentSlot] = useState(1);
  const [userPrompt, setUserPrompt] = useState("");
  const [narrativeDef, setNarrativeDef] = useState("");

  async function newSession() {
    setLoading(true);
    setError("");
    try {
      const created = await api<{ session_id: string }>("/session", { method: "POST" });
      setSessionId(created.session_id);
      await refresh(created.session_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function refresh(id = sessionId) {
    if (!id) return;
    const data = await api<SessionDetail>(`/session/${id}`);
    setDetail(data);
    setWorldText(data.tab1.world_text);
    setChapterText(data.tab1.chapter_text);
    const slots = data.tab1.selected_agent_slots;
    setAgentCount(slots.length || 1);
    const names: Record<number, string> = {};
    const defs: Record<number, string> = {};
    for (const slot of slots) {
      names[slot] = data.tab1.agent_names[String(slot)] ?? defaultAgentName(slot);
      defs[slot] = data.tab1.agent_identity_text_by_slot[String(slot)] ?? "";
    }
    setAgentNames(names);
    setAgentDefs(defs);
    setNarrativeDef(data.session.state === "DRAFT_TAB1" ? "" : narrativeDef);
    if (!slots.includes(activeAgentSlot)) setActiveAgentSlot(slots[0] ?? 1);
  }

  useEffect(() => {
    void newSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function saveTab1() {
    if (!sessionId) return;
    setLoading(true);
    setError("");
    try {
      const slots = Array.from({ length: agentCount }, (_, i) => i + 1);
      await api(`/session/${sessionId}/tab1`, {
        method: "PUT",
        body: JSON.stringify({
          world_text: worldText,
          chapter_text: chapterText,
          selected_agent_slots: slots,
          agent_names: Object.fromEntries(slots.map((s) => [s, agentNames[s] ?? defaultAgentName(s)])),
          agent_identity_text_by_slot: Object.fromEntries(slots.map((s) => [s, agentDefs[s] ?? ""])),
        }),
      });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function lockAndGoTab2() {
    await saveTab1();
    if (!sessionId) return;
    setLoading(true);
    try {
      await api(`/session/${sessionId}/lock`, { method: "POST" });
      await refresh();
      setTab(2);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function submitPrompt(e: FormEvent) {
    e.preventDefault();
    if (!sessionId || !userPrompt.trim()) return;
    setLoading(true);
    setError("");
    try {
      await api(`/session/${sessionId}/prompt`, {
        method: "POST",
        body: JSON.stringify({ agent_slot: activeAgentSlot, user_text: userPrompt }),
      });
      setUserPrompt("");
      await refresh();
      const slots = detail?.tab1.selected_agent_slots ?? [1];
      const idx = slots.indexOf(activeAgentSlot);
      const next = slots[(idx + 1) % slots.length] ?? slots[0];
      setActiveAgentSlot(next);
    } catch (e2) {
      setError((e2 as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function endChapter() {
    if (!sessionId) return;
    setLoading(true);
    try {
      await api(`/session/${sessionId}/end`, { method: "POST" });
      await refresh();
      setTab(3);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function saveNarrativeAgent() {
    if (!sessionId) return;
    setLoading(true);
    try {
      await api(`/session/${sessionId}/narrative-agent`, {
        method: "PUT",
        body: JSON.stringify({ narrative_agent_definition_text: narrativeDef }),
      });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function buildNarrative() {
    if (!sessionId) return;
    setLoading(true);
    try {
      await saveNarrativeAgent();
      await api(`/session/${sessionId}/build-narrative`, { method: "POST" });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function resetChapter() {
    if (!sessionId) return;
    if (!window.confirm("Warning, resetting the chapter will delete all cells from the Story Engine.")) return;
    setLoading(true);
    try {
      await api(`/session/${sessionId}/reset`, { method: "POST" });
      await refresh();
      setTab(1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function downloadChapter() {
    const chapterText = detail?.narrative_drafts?.at(-1)?.chapter_text ?? "";
    const blob = new Blob([chapterText], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `chapter-${sessionId || "draft"}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  const transcriptModel = useMemo(() => {
    if (!detail) return { lines: [] as TranscriptLine[], charCount: 0 };
    const lines: TranscriptLine[] = [];
    for (const ev of detail.events) {
      if (ev.role === "user") {
        lines.push({
          key: ev.event_id,
          text: `${ev.prompt_index}) ${ev.text}`,
          color: "#ffffff",
        });
      }
      if (ev.role === "agent") {
        const name = detail.tab1.agent_names[String(ev.agent_slot ?? 0)] ?? defaultAgentName(ev.agent_slot ?? 0);
        lines.push({
          key: ev.event_id,
          text: `${name}: ${ev.text}`,
          color: AGENT_COLORS[ev.agent_slot ?? 0] ?? "#9ca3af",
        });
      }
      if (ev.prompt_index === detail.session.last_summarized_prompt_index && ev.role === "agent") {
        lines.push({
          key: `${ev.event_id}-boundary`,
          text: "-------------",
          color: "#9ca3af",
        });
      }
    }

    const maxChars = 60000;
    const out: TranscriptLine[] = [];
    let total = 0;
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i].text;
      if (total + line.length + 1 > maxChars) break;
      out.push(lines[i]);
      total += line.length + 1;
    }
    return { lines: out.reverse(), charCount: total };
  }, [detail]);

  const slots = Array.from({ length: agentCount }, (_, i) => i + 1);

  return (
    <div className="page">
      <header>
        <h1>Story Engine MVP</h1>
        <div>Session: {sessionId || "(creating...)"}</div>
        <div>State: {detail?.session.state ?? "..."}</div>
      </header>

      <nav className="tabs">
        <button onClick={() => setTab(1)}>Tab1</button>
        <button onClick={() => setTab(2)} disabled={!detail?.session.tab1_locked}>Tab2</button>
        <button onClick={() => setTab(3)} disabled={!detail?.session.tab1_locked}>Tab3</button>
      </nav>

      {error && <pre className="error">{error}</pre>}

      {tab === 1 && (
        <section className="panel tab1">
          <label>World/Tone</label>
          <textarea value={worldText} onChange={(e) => setWorldText(e.target.value.slice(0, 5000))} disabled={detail?.session.tab1_locked} />
          <label>Chapter/Scene</label>
          <textarea value={chapterText} onChange={(e) => setChapterText(e.target.value.slice(0, 5000))} disabled={detail?.session.tab1_locked} />
          <label>Agents</label>
          <select value={agentCount} onChange={(e) => setAgentCount(Number(e.target.value))} disabled={detail?.session.tab1_locked}>
            {[1, 2, 3, 4, 5, 6, 7].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <div className="agent-grid">
            {slots.map((slot) => (
              <div key={slot} className="agent-card" style={{ borderColor: AGENT_COLORS[slot] }}>
                <input
                  value={agentNames[slot] ?? defaultAgentName(slot)}
                  onChange={(e) => setAgentNames({ ...agentNames, [slot]: e.target.value })}
                  disabled={detail?.session.tab1_locked}
                />
                <textarea
                  value={agentDefs[slot] ?? ""}
                  onChange={(e) => setAgentDefs({ ...agentDefs, [slot]: e.target.value.slice(0, 5000) })}
                  disabled={detail?.session.tab1_locked}
                />
              </div>
            ))}
          </div>
          {!detail?.session.tab1_locked && <button onClick={() => void saveTab1()} disabled={loading}>Save Tab1</button>}
          {!detail?.session.tab1_locked && <button onClick={() => void lockAndGoTab2()} disabled={loading}>Start Chapter (Lock Tab1)</button>}
          {detail?.session.tab1_locked && <button onClick={() => void resetChapter()} disabled={loading}>Reset Chapter</button>}
        </section>
      )}

      {tab === 2 && (
        <section className="panel tab2">
          <label>Context Transcript ({transcriptModel.charCount}/60000)</label>
          <div className="transcript">
            {transcriptModel.lines.map((line) => (
              <div key={line.key} style={{ color: line.color }}>{line.text}</div>
            ))}
          </div>
          <div className="agent-picker">
            {(detail?.tab1.selected_agent_slots ?? [1]).map((slot) => (
              <button
                key={slot}
                onClick={() => setActiveAgentSlot(slot)}
                style={{ borderColor: AGENT_COLORS[slot], color: activeAgentSlot === slot ? AGENT_COLORS[slot] : "#fff" }}
              >
                {detail?.tab1.agent_names[String(slot)] ?? defaultAgentName(slot)}
              </button>
            ))}
          </div>
          <form className="prompt-form" onSubmit={submitPrompt} style={{ borderColor: AGENT_COLORS[activeAgentSlot] ?? "#666" }}>
            <textarea
              value={userPrompt}
              onChange={(e) => setUserPrompt(e.target.value)}
              disabled={detail?.session.state !== "ACTIVE"}
              style={{ borderColor: AGENT_COLORS[activeAgentSlot] ?? "#666" }}
            />
            <button type="submit" disabled={loading || detail?.session.state !== "ACTIVE"}>Send Prompt</button>
          </form>
          <button onClick={() => void endChapter()} disabled={loading || detail?.session.state !== "ACTIVE"}>End Chapter</button>
        </section>
      )}

      {tab === 3 && (
        <section className="panel tab3">
          <label>Structured Memory (Tab3 Cell 1)</label>
          <pre className="memory">
            {(detail?.memory_blocks ?? []).map((b) => `${b.type} [${b.from_prompt_index}-${b.to_prompt_index}]\n${JSON.stringify(b.json_payload, null, 2)}`).join("\n\n")}
          </pre>
          <label>Narrative Agent Definition (Tab3 Cell 2)</label>
          <textarea value={narrativeDef} onChange={(e) => setNarrativeDef(e.target.value.slice(0, 5000))} />
          <button onClick={() => void saveNarrativeAgent()} disabled={loading}>Save Narrative Agent</button>
          <button onClick={() => void buildNarrative()} disabled={loading || detail?.session.state !== "ENDED"}>Build Narrative</button>
          <label>Narrative Draft (Tab3 Cell 3)</label>
          <pre className="draft">{detail?.narrative_drafts?.at(-1)?.chapter_text ?? ""}</pre>
          <button onClick={downloadChapter} disabled={!(detail?.narrative_drafts?.at(-1)?.chapter_text ?? "").trim()}>Download Chapter</button>
        </section>
      )}
    </div>
  );
}
