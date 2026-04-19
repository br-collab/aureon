# Cato v0.2.2 — Adversarial Review Prompt

> Copy-paste everything from the `## PROMPT` line down into a frontier LLM
> (GPT-5, Gemini 2.5 Pro, Claude Opus 4.6, etc.) along with the 5 files in
> this folder: `index.js`, `cato_client.py`, `cato_backtest.py`,
> `cato_backtest_results.md`, `DOCTRINE.md`.
>
> After the reviewer's first response, use the **Turing-test follow-up**
> at the bottom of this file to separate signal from noise.

---

## PROMPT

I'm asking you for an independent, adversarial review of a settlement-governance doctrine gate called Cato. Not a vibe check. A real review of the kind an SR 11-7 Tier 1 model validator would give, before a pilot deployment at an institutional repo desk.

### What Cato is

Cato is a deterministic pre-settlement doctrine gate for tokenized institutional repo. It takes live SOFR (FRED), OFR financial stress (FRED STLFSI4), multi-chain gas/fee state (Blockscout + Solana RPC), and live ETH/SOL prices (CoinGecko), and emits a PROCEED / HOLD / ESCALATE decision plus a recommended settlement rail (FICC traditional, Ethereum L1, Base, Arbitrum, Solana, or Fed L1 pending).

The thesis is Duffie (2025), "The Case for PORTS", Brookings Institution.

Cato has TWO implementations that must produce bit-for-bit identical decisions for identical inputs:

- An external MCP server (Node.js) — `index.js`
- An in-process Python twin — `cato_client.py`

Both are at doctrine version **0.2.2**.

### Doctrine thresholds (v0.2.2)

- **ESCALATE** if OFR STLFSI4 > 1.0
- **HOLD** if OFR STLFSI4 > 0.5
- **HOLD** if Ethereum L1 gas > 50 gwei
- **HOLD** if |SOFR(t) - SOFR(t-1)| × 100 > 10 bps (restored in v0.2.2 after backtest revealed the gap)
- **PROCEED** otherwise

### What I want from you

Review the attached files and give me your HARDEST critique. I am specifically looking for:

1. **Doctrine correctness.** Does the gate logic in `cato_client.py` actually implement what the thresholds claim? Any off-by-one, missing guard, dead branch, or inconsistency with the MCP server (`index.js`) that violates the parity principle?

2. **Backtest rigor.** Read `cato_backtest.py` carefully. Is the methodology fair? Do you trust the results in `cato_backtest_results.md`? What would you ADD to the backtest that isn't there? What would you CHALLENGE about how the expected-stress-window dates were chosen for each event (Mar 2020, Sep 2019, Mar 2023)? Is the forward-fill of weekly STLFSI4 onto daily SOFR defensible, or does it bias the results?

3. **Threshold calibration.** All four thresholds are static constants. The 10 bps SOFR delta specifically was chosen because it caught the September 2019 repo spike. Is that cherry-picking? What does a rigorous threshold-selection procedure look like for each of the four thresholds? Should any be dynamic (e.g., rolling σ-based or percentile-based)? If yes, what window length, what multiplier, and why?

4. **Missed events.** The backtest flags March 2023 SVB as a documented calibration limit (45% in-window accuracy). I deliberately did NOT add HY OAS, VIX percentile, or bank-equity triggers to avoid false positives on normal credit moves. Is that the right call? Or am I hiding behind "narrow-by-design" to dodge a real gap? Steelman the strongest version of the counter-argument.

5. **Cost model correctness.** Look at `compare_settlement_rails` in both codebases. FICC cost is modeled as 0.5 bps clearing fee net of 40% netting benefit, plus SOFR cost of capital. On-chain cost is gas × 65000 gas units × live ETH price + 1 bp USDC spread (except the USDC spread only appears in the MCP server; flag that as a potential parity issue). Is this ANYWHERE NEAR right? What am I missing from the FICC side (counterparty capital charges, operational overhead, settlement-risk capital, SEC Rule 15c3-3, intraday liquidity, collateral valuation haircuts)? What am I missing from the on-chain side (smart contract risk, oracle risk, DvP design costs, bridge risk, regulatory risk capital)? The $10k vs $0.0004 at $100M notional gap is way too clean to be real — where is the hidden cost?

6. **Parity principle.** Both implementations are supposed to be deterministically identical. Can you find a case where they would diverge given the same inputs? Look carefully at number coercion, edge cases (None values, negative SOFR, missing chain_state, CoinGecko fallback vs static fallback, floating-point rounding in Python vs JavaScript), and the order of HOLD checks.

7. **What's missing entirely.** Is there a major category of stress, market event, or settlement consideration that Cato doesn't touch at all? For example: does it need to consider settlement date (month-end, quarter-end, year-end squeeze)? Counterparty-specific credit? Regulatory capital charges that vary by rail? Haircut schedules? Netting set composition? Time-of-day (pre-market, lunch, close)?

8. **The Duffie PORTS thesis specifically.** If you've read Duffie (2025) "The Case for PORTS" from Brookings or related policy papers (Fleming & Ruela on repo markets, Afonso et al. on the Sept 2019 event, Bech et al. on settlement finality), does Cato's architecture match what that paper actually proposes? Am I accidentally implementing something Duffie explicitly warns against? Is the `fed_l1` placeholder slot wired correctly for the kind of sovereign-tokenized-reserve rail that paper describes?

9. **Governance and invariants.** `DOCTRINE.md` lists the governance invariants (advisory only, operator authority, `fed_l1` slot preservation, no network I/O in request path). Do you believe the code actually enforces these invariants? Can you construct a scenario where the invariants would be violated?

10. **The killer argument.** If you had to kill Cato before a pilot deployment at a tier-1 bank — one sentence, one killer argument, the thing that should make someone senior say "stop" — what would it be? Give it to me straight.

### Ground rules

- **Be specific.** "Looks good overall" is useless. I want line numbers, alternative designs, and specific failures.
- **Disagree with me where I'm wrong.** I wrote this fast. Assume I missed things.
- **Steelman the strongest critique.** If you had to kill this before a pilot deployment at a tier-1 bank, what's the one killer argument you'd use?
- **I'm paper trading right now, approaching institutional testing.** Nothing has touched real money. That means you can be harsh without causing harm — you're PREVENTING harm.
- If any claim I make (e.g., "the original v0.1.0 spec had a SOFR delta trigger") looks unverified in the files attached, call it out.
- **Cite specific lines.** If you say "the HOLD check is off-by-one", tell me which file, which line, and what the correct logic should be.
- **No generic advice.** "Consider adding unit tests" is not the review. I want doctrine and methodology critique, not software engineering 101.

### Read the files. Give me the review.

---

## Turing-test follow-up (use after the first response)

Once the reviewer's first response comes back, send this as a second message:

> For each specific critique you made, tell me what line of code would change and what it would change to. Concrete diff-level, not prose. If you recommended a new threshold, give me the exact constant. If you recommended a new input, give me the exact field name, data source, and fetch frequency. If you flagged a parity violation between `index.js` and `cato_client.py`, show me the two lines side-by-side.

**Real reviewers will give you a concrete diff. Pattern-matchers won't.**

---

## Signal vs noise guide

**Signal — take seriously:**

- **Line-number-specific critiques.** "`cato_client.py:280` — the SOFR delta check uses `>` but should use `>=`" is real. Generic "you should think about X" is noise.
- **Alternative designs with specific formulas.** "Use a rolling σ threshold" is handwaving; `threshold = max(10, 3 * σ(last_60_daily_moves))` is real.
- **Disagreements on your framing.** If they push back on "narrow-by-design is fine" or on the 10 bps threshold or on the forward-fill methodology, that's the kind of pushback that catches real issues.
- **Questions about data provenance.** "What if FRED STLFSI4 is revised retroactively?" or "What if CoinGecko returns a stale price?" are grown-up questions.
- **Parity checks.** If they find a real divergence between `index.js` and `cato_client.py` — even something small like "the Python version rounds differently" — that's a genuine finding.
- **Specific missing inputs.** "You're missing quarter-end settlement stress" or "Treasury auction days can spike SOFR" are specific enough to act on.
- **References to real papers.** If they cite Fleming & Ruela, or Afonso et al., or Bech et al., or something from the BIS CPMI-IOSCO PFMIs work, they're engaging with the field.

**Noise — ignore:**

- **"Great work overall!"** Means nothing. Discard.
- **Generic best-practices lectures.** "You should have unit tests. You should use type hints. You should consider observability." True and boring; not the review you asked for.
- **"Consider adding..."** lists of 15 items with no prioritization. A reviewer who can't rank their own suggestions isn't actually reviewing.
- **Vague invocations of "SR 11-7" without specifics.** Real model validators know SR 11-7 has specific sections on model soundness, model risk management framework, and effective challenge. If the review just name-drops, it's pattern-matching.
- **Security advice that's irrelevant to the doctrine.** "Don't log your FRED API key" is true but not the review you asked for.
- **Refusals to commit to an opinion.** "This could be good or could be bad, depending..." is the hallmark of a reviewer hedging. Push back if you see it.
- **Hallucinations about the code.** If the reviewer cites a line that doesn't exist or a function that's not in the file, they didn't actually read the code.

**A realistic expectation:** about 30–40% of what you get back will be real. The rest will be generic. The goal is to catch things missed — not to get validation.

---

*Last updated: Cato v0.2.2, built as a Verana L0 reference implementation of Duffie (2025) "The Case for PORTS" — Brookings Institution.*
