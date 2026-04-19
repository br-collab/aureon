import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 8787;
const API_KEY = process.env.ANTHROPIC_API_KEY;
const DEFAULT_MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-4-6";
const DEFAULT_MAX_TOKENS = Number(process.env.ANTHROPIC_MAX_TOKENS || 1000);

if (!API_KEY) {
  console.warn("[aureon-kyc] ANTHROPIC_API_KEY not set — /api/chat will return 500 until it is.");
}

app.use(cors());
app.use(express.json({ limit: "1mb" }));

app.get("/healthz", (_req, res) => {
  res.json({ ok: true, model: DEFAULT_MODEL, hasKey: Boolean(API_KEY) });
});

app.post("/api/chat", async (req, res) => {
  if (!API_KEY) {
    return res.status(500).json({ error: "server missing ANTHROPIC_API_KEY" });
  }
  const { messages, system, model, max_tokens } = req.body ?? {};
  if (!Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: "messages must be a non-empty array" });
  }

  try {
    const upstream = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: model || DEFAULT_MODEL,
        max_tokens: Number.isFinite(max_tokens) ? max_tokens : DEFAULT_MAX_TOKENS,
        system,
        messages,
      }),
    });
    const text = await upstream.text();
    res.status(upstream.status).type("application/json").send(text);
  } catch (err) {
    console.error("[aureon-kyc] upstream error:", err);
    res.status(502).json({ error: "upstream_failure", detail: String(err) });
  }
});

const distDir = path.join(__dirname, "dist");
if (fs.existsSync(distDir)) {
  app.use(express.static(distDir));
  app.get("*", (_req, res) => res.sendFile(path.join(distDir, "index.html")));
} else {
  console.log("[aureon-kyc] dist/ not built — run `npm run build` for production mode.");
}

app.listen(PORT, () => {
  console.log(`[aureon-kyc] listening on :${PORT} (model=${DEFAULT_MODEL})`);
});
