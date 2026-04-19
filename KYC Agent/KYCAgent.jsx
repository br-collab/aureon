import { useState, useRef, useEffect } from "react";

const BG = "#0C0C0C";
const SURFACE = "#161616";
const SURFACE2 = "#1E1E1E";
const RED = "#E31837";
const WHITE = "#FFFFFF";
const GRAY = "#A0A0A0";
const BORDER = "#2A2A2A";
const TEXT = "#F0F0F0";

const SYSTEM_PROMPT = `You are AUREON-KYC, an institutional compliance agent executing Know Your Customer (KYC) verification workflows under SR 11-7 governance doctrine.

Your role:
- Conduct structured KYC intake interviews for financial institution client onboarding
- Ask questions one at a time in a natural but precise compliance cadence
- Verify in sequence: full legal name, date of birth, country of citizenship, government ID type and number, source of funds, purpose of account, beneficial ownership (if entity), PEP (Politically Exposed Person) status, sanctions screening acknowledgment
- Flag any HIGH RISK indicators immediately: PEP status, high-risk jurisdiction, inconsistent information, unusual source of funds
- Maintain a professional, precise, non-accusatory tone
- After each response, append this exact block:
  [AUDIT: {"step": "<step name>", "risk_flag": <true/false>, "flag_reason": "<reason or null>", "data_captured": "<field or null>"}]

Begin by introducing yourself and initiating the session. Ask for full legal name first.`;

const parseAudit = (text) => {
  const m = text.match(/\[AUDIT:\s*({.*?})\]/s);
  if (m) { try { return JSON.parse(m[1]); } catch { return null; } }
  return null;
};
const clean = (text) => text.replace(/\[AUDIT:.*?\]/s, "").trim();

const callAPI = async (messages, system) => {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: "claude-sonnet-4-20250514", max_tokens: 1000, system: system || SYSTEM_PROMPT, messages }),
  });
  return res.json();
};

export default function KYCAgent() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [started, setStarted] = useState(false);
  const [auditLog, setAuditLog] = useState([]);
  const [closed, setClosed] = useState(false);
  const [summary, setSummary] = useState(null);
  const [showSummary, setShowSummary] = useState(false);
  const [sessionId] = useState(() => `KYC-${Date.now().toString(36).toUpperCase()}`);
  const [sessionStart] = useState(() => new Date());
  const [, setTick] = useState(0);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);
  useEffect(() => {
    if (!started || closed) return;
    const t = setInterval(() => setTick(p => p + 1), 1000);
    return () => clearInterval(t);
  }, [started, closed]);

  const start = async () => {
    setStarted(true);
    setLoading(true);
    try {
      const data = await callAPI([{ role: "user", content: "Begin KYC session." }]);
      const raw = data.content?.[0]?.text || "";
      const audit = parseAudit(raw);
      setMessages([{ role: "assistant", content: clean(raw), ts: new Date() }]);
      if (audit) setAuditLog([{ ...audit, ts: new Date() }]);
    } catch { setMessages([{ role: "assistant", content: "Connection failed. Check API.", ts: new Date() }]); }
    setLoading(false);
    setTimeout(() => inputRef.current?.focus(), 100);
  };

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg = { role: "user", content: input.trim(), ts: new Date() };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setInput("");
    setLoading(true);
    try {
      const data = await callAPI(updated.map(m => ({ role: m.role, content: m.content })));
      const raw = data.content?.[0]?.text || "";
      const audit = parseAudit(raw);
      setMessages(p => [...p, { role: "assistant", content: clean(raw), ts: new Date() }]);
      if (audit) setAuditLog(p => [...p, { ...audit, ts: new Date() }]);
    } catch { setMessages(p => [...p, { role: "assistant", content: "Transmission error. Retry.", ts: new Date() }]); }
    setLoading(false);
    setTimeout(() => inputRef.current?.focus(), 100);
  };

  const closeSession = async () => {
    setClosed(true);
    setLoading(true);
    const transcript = messages.map(m => `[${m.role === "assistant" ? "AUREON-KYC" : "SUBJECT"}]: ${m.content}`).join("\n\n");
    try {
      const data = await callAPI([{
        role: "user",
        content: `Produce a formal KYC Audit Summary.\n\nSession ID: ${sessionId}\nStart: ${sessionStart.toISOString()}\nEnd: ${new Date().toISOString()}\nRisk Flags: ${auditLog.filter(a => a.risk_flag).length}\n\nTranscript:\n${transcript}\n\nAudit Log:\n${JSON.stringify(auditLog, null, 2)}\n\nSections: Executive Summary | Data Captured | Risk Assessment | Compliance Determination | Recommended Next Action`,
      }], "You are an institutional compliance documentation officer. Write a formal, factual KYC audit summary for a compliance review audience. Use clear section headers. Be precise and concise.");
      setSummary(data.content?.[0]?.text || "Generation failed.");
    } catch { setSummary("Audit generation failed."); }
    setLoading(false);
  };

  const risks = auditLog.filter(a => a.risk_flag).length;
  const elapsed = Math.floor((new Date() - sessionStart) / 1000);
  const timer = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;
  const agentMsgCount = messages.filter(m => m.role === "assistant").length;

  return (
    <div style={{ fontFamily: "Arial, Helvetica, sans-serif", background: BG, minHeight: "100vh", display: "flex", flexDirection: "column", color: TEXT }}>

      {/* Header */}
      <div style={{ background: BG, borderBottom: `1px solid ${BORDER}`, padding: "0 32px", height: 56, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 0 }}>
          <div style={{ width: 4, height: 32, background: RED, marginRight: 14 }} />
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: WHITE, letterSpacing: "0.04em", lineHeight: 1.1 }}>AUREON</div>
            <div style={{ fontSize: 10, color: GRAY, letterSpacing: "0.1em", textTransform: "uppercase" }}>KYC Compliance Platform</div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {started && !closed && <span style={{ fontSize: 12, color: GRAY, fontVariantNumeric: "tabular-nums" }}>{timer}</span>}
          {risks > 0 && (
            <span style={{ background: RED, color: WHITE, fontSize: 11, fontWeight: 700, padding: "4px 12px", letterSpacing: "0.06em" }}>
              {risks} RISK FLAG{risks > 1 ? "S" : ""}
            </span>
          )}
          {started && (
            <span style={{ fontSize: 11, color: closed ? GRAY : "#4CAF50", letterSpacing: "0.08em", fontWeight: 600 }}>
              {closed ? "CLOSED" : "LIVE"}
            </span>
          )}
        </div>
      </div>

      {/* Red rule */}
      <div style={{ height: 2, background: RED }} />

      {/* Session bar */}
      {started && (
        <div style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}`, padding: "7px 32px", display: "flex", gap: 32, alignItems: "center" }}>
          {[
            ["Session ID", sessionId],
            ["Initiated", sessionStart.toLocaleString()],
            ["Doctrine", "SR 11-7 / FinCEN / BSA"],
            ["HITL Gates", "Active"],
            ["Voice", "Ready / Disabled"],
          ].map(([k, v]) => (
            <div key={k} style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
              <span style={{ fontSize: 10, color: GRAY, textTransform: "uppercase", letterSpacing: "0.08em" }}>{k}</span>
              <span style={{ fontSize: 11, color: WHITE, fontWeight: 600 }}>{v}</span>
            </div>
          ))}
        </div>
      )}

      {/* Landing */}
      {!started ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
          <div style={{ maxWidth: 440, width: "100%" }}>
            <div style={{ marginBottom: 32 }}>
              <div style={{ fontSize: 11, color: GRAY, letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: 10 }}>Ravelo Strategic Solutions</div>
              <div style={{ fontSize: 32, fontWeight: 700, color: WHITE, lineHeight: 1.1, marginBottom: 14 }}>KYC Compliance<br />Agent</div>
              <div style={{ width: 40, height: 2, background: RED, marginBottom: 20 }} />
              <div style={{ fontSize: 13, color: GRAY, lineHeight: 1.7 }}>
                Institutional-grade Know Your Customer intake with real-time risk screening, HITL governance gates, and automated audit trail generation.
              </div>
            </div>

            <div style={{ borderTop: `1px solid ${BORDER}`, marginBottom: 28 }}>
              {[
                ["Compliance framework", "SR 11-7 / FinCEN / BSA"],
                ["Risk screening", "PEP · Sanctions · Jurisdiction"],
                ["HITL gates", "Active"],
                ["Audit trail", "Enabled — session-locked"],
                ["Voice input", "Pre-built · Disabled"],
              ].map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${BORDER}` }}>
                  <span style={{ fontSize: 12, color: GRAY }}>{k}</span>
                  <span style={{ fontSize: 12, color: WHITE, fontWeight: 600 }}>{v}</span>
                </div>
              ))}
            </div>

            <button
              onClick={start}
              style={{ width: "100%", background: RED, color: WHITE, border: "none", padding: "15px 0", fontSize: 13, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", cursor: "pointer" }}
            >
              Initialize KYC Session
            </button>
            <div style={{ fontSize: 10, color: "#555", marginTop: 14, lineHeight: 1.6, textAlign: "center" }}>
              All interactions are logged and produce a tamper-resistant compliance record.<br />
              By proceeding you acknowledge this session is subject to regulatory review.
            </div>
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>

          {/* Messages */}
          <div style={{ flex: 1, overflowY: "auto", padding: "28px 32px", display: "flex", flexDirection: "column", gap: 24, minHeight: 380 }}>
            {messages.map((m, i) => {
              const isAgent = m.role === "assistant";
              const auditIdx = Math.floor(i / 2);
              const entry = isAgent ? auditLog[auditIdx] : null;
              return (
                <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: isAgent ? "flex-start" : "flex-end", gap: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 10, color: isAgent ? RED : GRAY, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                      {isAgent ? "Aureon-KYC" : "Subject"}
                    </span>
                    <span style={{ fontSize: 10, color: "#444" }}>{m.ts.toLocaleTimeString()}</span>
                    {entry && (
                      <span style={{
                        fontSize: 10, fontWeight: 600, padding: "2px 8px",
                        background: entry.risk_flag ? "rgba(227,24,55,0.12)" : "rgba(76,175,80,0.1)",
                        color: entry.risk_flag ? RED : "#4CAF50",
                        border: `1px solid ${entry.risk_flag ? "rgba(227,24,55,0.3)" : "rgba(76,175,80,0.3)"}`,
                        letterSpacing: "0.05em",
                      }}>
                        {entry.risk_flag ? `FLAG: ${entry.flag_reason}` : "CLEAR"}
                      </span>
                    )}
                    {entry?.data_captured && (
                      <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", background: "rgba(255,255,255,0.05)", color: GRAY, border: `1px solid ${BORDER}`, letterSpacing: "0.05em" }}>
                        {entry.data_captured}
                      </span>
                    )}
                  </div>
                  <div style={{
                    maxWidth: "68%",
                    background: isAgent ? SURFACE : "#1A1A2E",
                    border: `1px solid ${isAgent ? BORDER : "#2A2A4A"}`,
                    padding: "13px 17px",
                    fontSize: 14,
                    lineHeight: 1.7,
                    color: TEXT,
                  }}>
                    {m.content}
                  </div>
                </div>
              );
            })}

            {loading && (
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, padding: "12px 16px", display: "flex", gap: 5, alignItems: "center" }}>
                  {[0, 1, 2].map(d => (
                    <div key={d} style={{ width: 6, height: 6, background: RED, animation: `fade 1s ${d * 0.2}s infinite` }} />
                  ))}
                </div>
                <span style={{ fontSize: 11, color: GRAY, letterSpacing: "0.06em" }}>Processing...</span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Audit strip */}
          {auditLog.length > 0 && (
            <div style={{ background: SURFACE, borderTop: `1px solid ${BORDER}`, padding: "8px 32px", display: "flex", gap: 6, overflowX: "auto", alignItems: "center" }}>
              <span style={{ fontSize: 10, color: GRAY, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", whiteSpace: "nowrap", marginRight: 8 }}>Steps</span>
              {auditLog.map((a, i) => (
                <span key={i} style={{
                  fontSize: 10, fontWeight: 600, padding: "3px 10px", whiteSpace: "nowrap",
                  background: a.risk_flag ? "rgba(227,24,55,0.1)" : "rgba(255,255,255,0.04)",
                  color: a.risk_flag ? RED : GRAY,
                  border: `1px solid ${a.risk_flag ? "rgba(227,24,55,0.3)" : BORDER}`,
                  letterSpacing: "0.04em",
                }}>
                  {i + 1}. {a.step} {a.risk_flag ? "⚑" : "✓"}
                </span>
              ))}
            </div>
          )}

          {/* Input */}
          {!closed ? (
            <div style={{ background: SURFACE, borderTop: `1px solid ${BORDER}`, padding: "16px 32px", display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && send()}
                  placeholder="Enter your response..."
                  style={{ flex: 1, background: BG, border: `1px solid ${BORDER}`, padding: "11px 16px", fontSize: 14, color: WHITE, outline: "none", fontFamily: "inherit" }}
                />
                <button
                  onClick={send}
                  disabled={loading || !input.trim()}
                  style={{ background: RED, color: WHITE, border: "none", padding: "0 24px", fontSize: 12, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", cursor: "pointer", opacity: loading || !input.trim() ? 0.35 : 1 }}
                >
                  Submit
                </button>
                <button
                  onClick={closeSession}
                  disabled={loading || messages.length < 4}
                  style={{ background: "transparent", color: GRAY, border: `1px solid ${BORDER}`, padding: "0 16px", fontSize: 11, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", cursor: "pointer", opacity: messages.length < 4 ? 0.25 : 1 }}
                >
                  Close + Audit
                </button>
              </div>
              <div style={{ fontSize: 10, color: "#3A3A3A", letterSpacing: "0.05em" }}>
                ENTER to submit — CLOSE + AUDIT finalizes session and generates compliance record
              </div>
            </div>
          ) : (
            <div style={{ background: SURFACE, borderTop: `1px solid ${BORDER}`, padding: "16px 32px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: showSummary && summary ? 16 : 0 }}>
                <div style={{ flex: 1, display: "flex", gap: 28 }}>
                  <span style={{ fontSize: 11, color: GRAY, letterSpacing: "0.05em" }}>
                    CLOSED: <strong style={{ color: WHITE }}>{new Date().toLocaleString()}</strong>
                  </span>
                  <span style={{ fontSize: 11, color: risks > 0 ? RED : "#4CAF50", fontWeight: 700, letterSpacing: "0.05em" }}>
                    {risks} RISK FLAG{risks !== 1 ? "S" : ""} RECORDED
                  </span>
                  <span style={{ fontSize: 11, color: GRAY }}>
                    {agentMsgCount} STEPS COMPLETED
                  </span>
                </div>
                <button
                  onClick={() => setShowSummary(s => !s)}
                  style={{ background: RED, color: WHITE, border: "none", padding: "9px 20px", fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", cursor: "pointer" }}
                >
                  {showSummary ? "Hide" : "View"} Audit Record
                </button>
              </div>
              {showSummary && loading && (
                <div style={{ padding: "12px 0", fontSize: 12, color: GRAY, letterSpacing: "0.06em" }}>GENERATING AUDIT RECORD...</div>
              )}
              {showSummary && summary && (
                <div style={{ background: BG, border: `1px solid ${BORDER}`, padding: "20px 24px", fontSize: 13, lineHeight: 1.8, color: TEXT, whiteSpace: "pre-wrap", maxHeight: 360, overflowY: "auto" }}>
                  {summary}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <style>{`
        @keyframes fade { 0%, 100% { opacity: 0.15; } 50% { opacity: 1; } }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: ${BG}; }
        ::-webkit-scrollbar-thumb { background: #2A2A2A; }
        input::placeholder { color: #3A3A3A; }
        button:hover { opacity: 0.82 !important; }
      `}</style>
    </div>
  );
}
