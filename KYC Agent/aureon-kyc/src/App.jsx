import { useState, useRef, useEffect, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useVoice } from "./useVoice.js";
import { useSpeechRecognition } from "./useSpeechRecognition.js";

const BG = "#0C0C0C";
const SURFACE = "#161616";
const RED = "#E31837";
const WHITE = "#FFFFFF";
const GRAY = "#A0A0A0";
const BORDER = "#2A2A2A";
const TEXT = "#F0F0F0";

const buildSystemPrompt = (sessionId, nowISO) => `You are AUREON-KYC, an institutional compliance agent executing Know Your Customer (KYC) verification workflows under SR 11-7 governance doctrine.

Session context (authoritative — do not invent alternatives):
- System-assigned Session ID: ${sessionId}
- Current wall-clock timestamp: ${nowISO}

Your role:
- Conduct structured KYC intake interviews for financial institution client onboarding
- Ask one question per turn in a natural but precise compliance cadence (compound fields within a single step — e.g., full address, or occupation plus employer — may be asked together)
- Flag any HIGH RISK indicators immediately: PEP status, high-risk jurisdiction, inconsistent information, unusual source of funds, eponymous-entity ownership, privacy-forward jurisdiction
- Maintain a professional, precise, non-accusatory tone

Required verification sequence — complete every step in this exact order:
1. full_legal_name — legal name as it appears on government ID
2. date_of_birth — full DOB
3. residential_address — street, city, state/region, postal code, country
4. country_of_citizenship — all citizenships held
5. tax_id — SSN/ITIN for US persons, equivalent national tax identifier for non-US persons
6. government_id — ID type (passport, driver's license, national ID) AND ID number in one turn
7. occupation_employer — employment status, occupation/role, and employer name in one turn
8. source_of_funds — primary origin of funds that will flow through the account
9. account_purpose — intended use of the account
10. transaction_volume — anticipated monthly dollar range AND frequency of activity
11. beneficial_ownership — for entity accounts, list any beneficial owners ≥25%; for individual accounts, confirm sole ownership
12. pep_status — including immediate family members and close associates
13. sanctions_acknowledgment — OFAC and other applicable sanctions-list screening acknowledgment

Audit tag discipline (hard rules):
- Every single response you emit — without exception, including the introduction and the final confirmation — must end with exactly one [AUDIT: ...] block as the very last content of the message.
- Block format is exactly: [AUDIT: {"step": "<step>", "risk_flag": <true|false>, "flag_reason": "<reason or null>", "data_captured": "<value or null>"}]
- The "step" field MUST be one of these exact strings and nothing else:
  session_open | full_legal_name | date_of_birth | residential_address | country_of_citizenship | tax_id | government_id | occupation_employer | source_of_funds | account_purpose | transaction_volume | beneficial_ownership | pep_status | sanctions_acknowledgment | intake_complete
- Use each step exactly once and in the order listed. The introduction turn uses step="session_open" with data_captured=null. After sanctions_acknowledgment is confirmed, your final brief confirmation message uses step="intake_complete" with data_captured set to the System-assigned Session ID.
- "step" names the verification you just captured from the user's most recent turn — NOT the next question you are about to ask. Example: if the user just answered the citizenship question, the step is "country_of_citizenship" and data_captured is the citizenship value. Do not reuse or re-audit earlier steps.
- "data_captured" contains ONLY the value the user provided in their most recent turn, formatted concisely (e.g., "Guillermo Ravelo", "DOB: 09/22/1973", "US Passport A36078984"). Never re-audit data from earlier turns — each prior value is already recorded under its own step.

Truth constraints (hard rules):
- Use only the System-assigned Session ID above. Never fabricate, reformat, or invent an alternative reference number (for example, do not emit "AKC-####" style IDs).
- Use only the wall-clock timestamp above when referencing dates, years, or timeframes. Never invent dates.
- Do not assert that the session has been logged, archived, stored, queued, or submitted to any downstream system — no such infrastructure exists at this layer. Persistence is the operator's responsibility.
- Do not promise follow-up contact, assigned compliance officers, review timelines, secure document-submission links, or any other downstream workflow.
- Do not write a closing session summary in the chat stream. After the sanctions_acknowledgment step, your final message must be a single brief sentence confirming that intake is complete — nothing more. Do not include captured-data tables, risk-assessment blocks, next-steps lists, or any structured summary. The formal audit record is generated separately by the operator's Close + Audit action; do not preempt or duplicate it.

Begin by introducing yourself and initiating the session with step="session_open". Then ask for the subject's full legal name.`;

const parseAudit = (text) => {
  const m = text.match(/\[AUDIT:\s*({.*?})\]/s);
  if (m) { try { return JSON.parse(m[1]); } catch { return null; } }
  return null;
};
const clean = (text) => text.replace(/\[AUDIT:.*?\]/gs, "").trim();

const callAPI = async (messages, system) => {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, system }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`proxy ${res.status}: ${detail || res.statusText}`);
  }
  return res.json();
};

export default function App() {
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

  const systemPrompt = useMemo(
    () => buildSystemPrompt(sessionId, sessionStart.toISOString()),
    [sessionId, sessionStart],
  );

  const voice = useVoice(true);
  const speech = useSpeechRecognition({
    onTranscript: (text) => setInput(text),
  });

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
      const data = await callAPI([{ role: "user", content: "Begin KYC session." }], systemPrompt);
      const raw = data.content?.[0]?.text || "";
      const audit = parseAudit(raw);
      const cleaned = clean(raw);
      setMessages([{ role: "assistant", content: cleaned, ts: new Date() }]);
      if (audit) setAuditLog([{ ...audit, ts: new Date() }]);
      voice.speak(cleaned);
    } catch (err) {
      console.error(err);
      setMessages([{ role: "assistant", content: "Connection failed. Check server + API key.", ts: new Date() }]);
    }
    setLoading(false);
    setTimeout(() => inputRef.current?.focus(), 100);
  };

  const send = async () => {
    if (!input.trim() || loading) return;
    if (speech.listening) speech.stop();
    const userMsg = { role: "user", content: input.trim(), ts: new Date() };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setInput("");
    setLoading(true);
    try {
      const data = await callAPI(updated.map(m => ({ role: m.role, content: m.content })), systemPrompt);
      const raw = data.content?.[0]?.text || "";
      const audit = parseAudit(raw);
      const cleaned = clean(raw);
      setMessages(p => [...p, { role: "assistant", content: cleaned, ts: new Date() }]);
      if (audit) setAuditLog(p => [...p, { ...audit, ts: new Date() }]);
      voice.speak(cleaned);
    } catch (err) {
      console.error(err);
      setMessages(p => [...p, { role: "assistant", content: "Transmission error. Retry.", ts: new Date() }]);
    }
    setLoading(false);
    setTimeout(() => inputRef.current?.focus(), 100);
  };

  const closeSession = async () => {
    setClosed(true);
    setLoading(true);
    voice.cancel();
    if (speech.listening) speech.stop();
    const transcript = messages.map(m => `[${m.role === "assistant" ? "AUREON-KYC" : "SUBJECT"}]: ${m.content}`).join("\n\n");
    try {
      const data = await callAPI([{
        role: "user",
        content: `Produce a formal KYC Audit Summary.\n\nSystem-assigned Session ID: ${sessionId} — use this exact ID in the audit record, do not generate or invent an alternative reference number.\nSession Start (wall-clock): ${sessionStart.toISOString()}\nSession End (wall-clock): ${new Date().toISOString()}\nRisk Flags: ${auditLog.filter(a => a.risk_flag).length}\n\nTranscript:\n${transcript}\n\nAudit Log:\n${JSON.stringify(auditLog, null, 2)}\n\nSections: Executive Summary | Data Captured | Risk Assessment | Compliance Determination | Recommended Next Action`,
      }], "You are an institutional compliance documentation officer. Write a formal, factual KYC audit summary for a compliance review audience. Use clear section headers. Be precise and concise. This session summary is presented to the operator for review. Persistence and downstream handling are the operator's responsibility. Do not assert that the session has been logged, archived, stored, or queued for compliance review — no such systems exist at this layer. Do not promise follow-up contact, review windows, or timelines. Use only the System-assigned Session ID and wall-clock timestamps supplied in the user message; never fabricate reference numbers or dates.");
      setSummary(data.content?.[0]?.text || "Generation failed.");
    } catch (err) {
      console.error(err);
      setSummary("Audit generation failed.");
    }
    setLoading(false);
  };

  const risks = auditLog.filter(a => a.risk_flag).length;
  const elapsed = Math.floor((new Date() - sessionStart) / 1000);
  const timer = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;
  const agentMsgCount = messages.filter(m => m.role === "assistant").length;

  return (
    <div style={{ fontFamily: "Arial, Helvetica, sans-serif", background: BG, minHeight: "100vh", display: "flex", flexDirection: "column", color: TEXT }}>

      <div style={{ background: BG, borderBottom: `1px solid ${BORDER}`, padding: "0 32px", height: 56, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 0 }}>
          <div style={{ width: 4, height: 32, background: RED, marginRight: 14 }} />
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: WHITE, letterSpacing: "0.04em", lineHeight: 1.1 }}>AUREON</div>
            <div style={{ fontSize: 10, color: GRAY, letterSpacing: "0.1em", textTransform: "uppercase" }}>KYC Compliance Platform</div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {voice.supported && (
            <button
              onClick={voice.toggle}
              aria-label={voice.enabled ? "Mute voice" : "Unmute voice"}
              title={voice.voice ? `${voice.voice.name} — ${voice.voice.lang}` : "Voice"}
              style={{
                background: "transparent",
                color: voice.enabled ? WHITE : GRAY,
                border: `1px solid ${voice.enabled ? BORDER : "#1E1E1E"}`,
                padding: "4px 10px",
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              {voice.enabled ? "Sound On" : "Sound Off"}
            </button>
          )}
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

      <div style={{ height: 2, background: RED }} />

      {started && (
        <div style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}`, padding: "7px 32px", display: "flex", gap: 32, alignItems: "center" }}>
          {[
            ["Session ID", sessionId],
            ["Initiated", sessionStart.toLocaleString()],
            ["Doctrine", "SR 11-7 / FinCEN / BSA"],
            ["HITL Gates", "Active"],
            ["Voice", !voice.supported ? "Unsupported" : !voice.enabled ? "Muted" : (voice.voice?.name || "en-US")],
          ].map(([k, v]) => (
            <div key={k} style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
              <span style={{ fontSize: 10, color: GRAY, textTransform: "uppercase", letterSpacing: "0.08em" }}>{k}</span>
              <span style={{ fontSize: 11, color: WHITE, fontWeight: 600 }}>{v}</span>
            </div>
          ))}
        </div>
      )}

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
                  {i + 1}. {a.step} {a.risk_flag ? "\u2691" : "\u2713"}
                </span>
              ))}
            </div>
          )}

          {!closed ? (
            <div style={{ background: SURFACE, borderTop: `1px solid ${BORDER}`, padding: "16px 32px", display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && send()}
                  placeholder={speech.listening ? "Listening — speak now, then click MIC again to stop..." : "Enter your response..."}
                  style={{ flex: 1, background: BG, border: `1px solid ${speech.listening ? RED : BORDER}`, padding: "11px 16px", fontSize: 14, color: WHITE, outline: "none", fontFamily: "inherit", transition: "border-color 120ms linear" }}
                />
                {speech.supported && (
                  <button
                    onClick={() => {
                      if (!speech.listening) voice.cancel();
                      speech.toggle(input);
                    }}
                    disabled={loading}
                    aria-label={speech.listening ? "Stop dictation" : "Start dictation"}
                    title={speech.error ? `Mic error: ${speech.error}` : (speech.listening ? "Click to stop listening" : "Dictate your answer")}
                    style={{
                      background: speech.listening ? RED : "transparent",
                      color: speech.listening ? WHITE : GRAY,
                      border: `1px solid ${speech.listening ? RED : BORDER}`,
                      padding: "0 14px",
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      cursor: "pointer",
                      fontFamily: "inherit",
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      opacity: loading ? 0.35 : 1,
                    }}
                  >
                    {speech.listening && (
                      <span style={{ width: 6, height: 6, background: WHITE, borderRadius: "50%", animation: "fade 1s infinite" }} />
                    )}
                    {speech.listening ? "Listening" : "Mic"}
                  </button>
                )}
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
                {speech.supported
                  ? "MIC dictates into the field — review, correct, then SUBMIT. ENTER also submits."
                  : "ENTER to submit — CLOSE + AUDIT finalizes session and generates compliance record"}
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
                <div className="audit-markdown" style={{ background: BG, border: `1px solid ${BORDER}`, padding: "20px 24px", fontSize: 13, lineHeight: 1.8, color: TEXT, maxHeight: 360, overflowY: "auto" }}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary}</ReactMarkdown>
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
