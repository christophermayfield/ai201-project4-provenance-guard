# Provenance Guard

A backend system that any creative-sharing platform could plug into to classify
submitted content (poem, story excerpt, blog post) as likely AI-generated or
human-written, score its confidence, surface a plain-language **transparency
label**, and handle **appeals** from creators who believe they were
misclassified. Every decision is written to a structured **audit log**.

This is an attribution *estimate*, not proof. The design philosophy, signal
rationale, thresholds, and edge cases are documented in [`planning.md`](planning.md).

---

## How it works

```
text ──▶ Signal 1 (Groq LLM)        ┐
         Signal 2 (stylometry)      ├─▶ weighted combine ─▶ confidence ─▶ label ─▶ audit log ─▶ response
                                    ┘        (0.70/0.30)      (0..1)     (3 bands)
```

### Detection signals (ensemble)

| Signal | Type | Weight | What it measures |
| ------ | ---- | ------ | ---------------- |
| `groq_authenticity` | LLM (Groq) | 0.70 | Stylistic AI-likeness: bland/risk-averse tone, flawless-but-hollow grammar, hallucinated specifics, missing personal voice. Returns a structured JSON assessment. |
| `stylometry` | Local heuristic | 0.30 | Combines **sentence-length burstiness**, **type-token ratio** (lexical diversity), and **mean word length** into one score. No external calls. |

Each signal returns a float in `[0.0, 1.0]` (0 = human-like, 1 = AI-like). The
combined `confidence` is the weighted average (currently an uncalibrated
identity mapping — see planning.md).

#### Why these two signals

The two signals were chosen to be **methodologically independent**, so they fail
in different ways rather than reinforcing the same blind spot:

- **`groq_authenticity` (LLM)** captures *semantic/stylistic* properties that are
  effectively impossible to compute with cheap math — bland "textbook" tone,
  flawless-but-hollow phrasing, hallucinated specifics, and the absence of lived
  personal voice. It's the stronger discriminator (hence weight **0.70**),
  especially on short or terse human writing where statistics are noisy.
- **`stylometry` (local heuristic)** is the deliberate counterweight: it's free,
  deterministic, runs offline, and is fully explainable (every sub-metric is
  inspectable). It reliably catches *mechanical* tells — uniform rhythm, heavy
  repetition, high formality — and keeps the system partly functional even if the
  LLM provider is down or rate-limited.

Using one LLM signal **plus** one statistical signal gives more genuine signal
diversity than, say, two LLM prompts (which share the same failure modes and
cost). In independent testing the two **agreed in direction** on clear cases but
**diverged on terse human prose** — exactly the kind of complementary behavior an
ensemble should have.

**What I'd change for a real deployment:** (1) *calibrate* the confidence on a
labeled human/AI corpus (Platt/isotonic) so a "0.7" means an actual 70%
AI-rate; (2) drive the false-positive estimate from **signal agreement** rather
than the current `1 − confidence` proxy; (3) make weights **content-type aware**
(down-weight stylometry for poetry); (4) add retries/caching/a circuit breaker
around Groq; (5) move the audit log to a real datastore behind auth.

### Confidence → label thresholds

| Confidence | Label | Tone |
| ---------- | ----- | ---- |
| `0.00 – 0.39` | `likely_human` | positive (`≤ 0.20`) / caution |
| `0.40 – 0.59` | `uncertain` | neutral |
| `0.60 – 1.00` | `likely_ai` | warning (`≥ 0.80`) / caution |

A false-positive guardrail (`false_positive_probability = 1 − confidence`)
re-files a borderline `likely_ai` (≈0.60–0.70) back to `uncertain`, to bias
against falsely accusing human authors.

#### Why this scoring approach

- **Weighted average**, not a black box: it's transparent and tunable, and lets
  the stronger signal (the LLM) carry more influence (0.70 vs 0.30) — a split
  chosen because in testing the LLM was the more reliable discriminator on hard
  (terse human) cases.
- **A real `uncertain` band** instead of forcing a binary AI/human call. If the
  signals are mixed, saying so is more honest — and more useful to a reviewer —
  than a coin-flip label.
- **An ethical guardrail**: a false "AI" label on a human's genuine work is more
  harmful than a missed AI flag, so the false-positive guardrail deliberately
  downgrades shaky `likely_ai` calls to `uncertain`.
- **What I'd change for real:** calibrate the score against labeled data (today
  it's an honest, documented *uncalibrated* identity mapping), and replace the
  `1 − confidence` false-positive proxy with one based on inter-signal
  disagreement.

#### Worked examples (meaningful variation, not a constant)

Actual outputs from Milestone 4 testing — the scorer produces a wide spread, not
a fixed number:

**High-confidence case** — a polished, uniform paragraph:

> "Effective time management is essential for productivity. By prioritizing tasks and setting clear goals, individuals can optimize their workflow. It is important to minimize distractions and maintain focus. Consistent habits contribute significantly to long-term success and personal growth."

| field | value |
| ----- | ----- |
| `groq_authenticity` | 0.80 |
| `stylometry` | 0.86 |
| **confidence** | **0.818** (band: strong) |
| **label** | **likely_ai** |

**Lower-confidence (and lower-scoring) case** — a casual, irregular anecdote:

> "I bombed it. Spilled coffee on my one good shirt in the lobby, then blanked on the founder's name mid-handshake. My roommate swears it builds character. My landlord, who wants rent on Tuesday, disagrees."

| field | value |
| ----- | ----- |
| `groq_authenticity` | 0.10 |
| `stylometry` | 0.26 |
| **confidence** | **0.149** (band: strong) |
| **label** | **likely_human** |

The two confidence scores (**0.818** vs **0.149**) differ by ~0.67 — clear
evidence the scoring varies with the input.

**Bonus — the `uncertain` band + guardrail in action.** A flat-but-impersonal
sentence where the signals disagree (`groq 0.80`, `stylometry 0.46`) aggregates
to **confidence 0.698**. That's above the `0.60` AI threshold, but
`false_positive_probability = 0.302 > 0.30`, so the guardrail re-files it to
**`uncertain`** rather than risk a false AI accusation.

---

## Setup

Requires Python 3.12+ and a [Groq API key](https://console.groq.com/keys).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_key_here
# optional overrides:
# GROQ_MODEL=llama-3.3-70b-versatile
# PORT=5050
```

Run the dev server:

```bash
PYTHONPATH=. python wsgi.py
# serving on http://localhost:5050
```

> Note: the app defaults to port **5050** because macOS reserves 5000 for the
> AirPlay Receiver. Override with the `PORT` env var.

---

## API

Submission/appeal endpoints are at the root; supporting endpoints are versioned
under `/api/v1`.

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `POST` | `/submit` | Classify a submission, return attribution + label |
| `POST` | `/appeal` | Contest a result by `content_id` |
| `GET`  | `/appeals` | Reviewer queue (optional `?status=`) |
| `GET`  | `/log` | Recent audit entries (optional `?limit=`) |
| `GET`  | `/api/v1/signals` | Signal catalogue |
| `GET`  | `/api/v1/health` | Liveness check |

### `POST /submit`

```bash
curl -s -X POST http://localhost:5050/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "The sun dipped below the horizon, painting the sky in hues of amber and rose. I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet.", "creator_id": "test-user-1"}'
```

```json
{
  "content_id": "c_f390f53c8679",
  "creator_id": "test-user-1",
  "status": "classified",
  "attribution": {
    "label": "likely_human",
    "confidence": 0.149,
    "confidence_band": "strong",
    "palette_color": "#e8602f",
    "false_positive_probability": 0.851,
    "signals": [
      {"id": "groq_authenticity", "score": 0.1, "weight": 0.7, "explanation": "...", "indicators": ["personal anecdote", "conversational tone"]},
      {"id": "stylometry", "score": 0.26, "weight": 0.3, "explanation": "Bursty rhythm and varied vocabulary, typical of human writing.", "metrics": {"sentence_length_cv": 0.59, "type_token_ratio": 0.85, "mean_word_length": 4.5}}
    ]
  },
  "transparency_label": {
    "text": "Likely human-written. This content shows the natural variation, voice, and specificity typical of human writing. No strong AI indicators were detected.",
    "tone": "positive"
  },
  "meta": {"model": "llama-3.3-70b-versatile", "scoring": "ensemble (2 signals, uncalibrated)", "analyzed_at": "..."}
}
```

Validation: `text` and `creator_id` required (`400`); text must be 50–20,000
chars (`422` / `413`); Groq failures surface as `502`.

### `POST /appeal`

```bash
curl -s -X POST http://localhost:5050/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "c_f390f53c8679", "reason": "This is my own writing.", "claimed_origin": "human"}'
```

```json
{
  "appeal_id": "a_cb538ca63450",
  "content_id": "c_f390f53c8679",
  "status": "under_review",
  "previous_status": "classified",
  "message": "Appeal received and under review."
}
```

Transitions the original result `classified → under_review` and logs an
`appeal_received` event. Unknown `content_id` → `404`.

### `GET /appeals` (reviewer queue)

```bash
curl -s "http://localhost:5050/appeals?status=under_review"
```

Each item joins the appeal to its original analysis (label, confidence, both
signal scores) so a reviewer can judge the call.

### Transparency label variants

The three exact label texts (written in planning.md before the UI):

- **Likely AI** (`≥ 0.80`): *"Likely AI-generated. This content shows strong, consistent indicators of AI generation across multiple signals. Treat attribution claims with caution and verify independently where it matters."*
- **Uncertain**: *"Inconclusive. The signals are mixed and we can't reliably attribute this content. This is an estimate, not proof — please use your own judgment and additional context before drawing conclusions."*
- **Likely human** (`≤ 0.20`): *"Likely human-written. This content shows the natural variation, voice, and specificity typical of human writing. No strong AI indicators were detected."*

---

## Rate limiting

`POST /submit` is rate-limited **per IP** with Flask-Limiter (in-memory store).
Every submission triggers a Groq LLM call, so the limits protect both cost and
availability. Limits are tiered:

| Window | Limit | Reasoning |
| ------ | ----- | --------- |
| per minute | **10** | A real creator submits a piece, reads the result, tweaks, and resubmits — a few times a minute at most. 10/min leaves head-room for quick iteration while stopping a script from firing dozens of requests per second. |
| per hour | **100** | Covers an intense editing session (e.g. revising a manuscript chapter-by-chapter) without throttling a legitimate user, but caps sustained automated traffic. |
| per day | **500** | A hard ceiling on per-IP daily cost/abuse. Far above any single human's realistic daily output, well below what a flooding script would attempt. |

Exceeding any tier returns `429` with `{"error": {"code": "rate_limited"}}`.
Limits are configurable via the `SUBMIT_RATE_LIMIT` env var (Flask-Limiter
syntax, e.g. `"10 per minute; 100 per hour; 500 per day"`). The
`/api/v1/analyze` endpoint is separately limited at `10/minute`.

> The tiered design matters: a single per-minute limit either throttles real
> iteration (if low) or allows hours of abuse (if high). Layering minute/hour/day
> windows bounds both burst and sustained load.

### Evidence

12 consecutive `POST /submit` requests from one IP against the `10 per minute`
limit — the first 10 succeed, the rest are throttled:

```
POST /submit  (limit: 10 per minute)
request  1: 200
request  2: 200
request  3: 200
request  4: 200
request  5: 200
request  6: 200
request  7: 200
request  8: 200
request  9: 200
request 10: 200
request 11: 429
request 12: 429
```

Each `429` carries `{"error": {"code": "rate_limited", "message": "Rate limit exceeded."}}`.

---

## Audit log

Every submission and appeal appends a structured JSON line to
`data/audit_log.jsonl`. Each `analysis_completed` entry captures everything
required — **timestamp, content_id, attribution, confidence, both individual
signal scores** (`llm_score`, `stylometry_score`), and **`appeal_filed`** (the
`/log` view cross-references appeal events so each classification shows whether
an appeal has since been filed). View recent entries:

```bash
curl -s "http://localhost:5050/log?limit=3"
```

```json
{
  "entries": [
    {
      "event_type": "appeal_received",
      "appeal_id": "a_26b950da2027",
      "content_id": "c_da80a8e89d84",
      "timestamp": "2026-06-29T07:12:04.670915+00:00",
      "reason": "I wrote this for work.",
      "claimed_origin": "human",
      "previous_status": "classified",
      "status": "under_review"
    },
    {
      "event_type": "analysis_completed",
      "content_id": "c_f9879180c9d6",
      "timestamp": "2026-06-29T07:12:04.669091+00:00",
      "creator_id": "bob",
      "attribution": "likely_human",
      "confidence": 0.1837,
      "llm_score": 0.1,
      "stylometry_score": 0.3789,
      "status": "classified",
      "appeal_filed": false
    },
    {
      "event_type": "analysis_completed",
      "content_id": "c_da80a8e89d84",
      "timestamp": "2026-06-29T07:12:04.186593+00:00",
      "creator_id": "alice",
      "attribution": "likely_ai",
      "confidence": 0.7581,
      "llm_score": 0.8,
      "stylometry_score": 0.6605,
      "status": "classified",
      "appeal_filed": true
    }
  ]
}
```

> The `/log` and `/appeals` endpoints are unauthenticated for documentation and
> grading visibility. In production they would sit behind reviewer auth.

---

## Project layout

```
provenance_guard/
  __init__.py      app factory, rate limiting, error handlers
  api.py           routes (/submit, /appeal, /appeals, /log, /api/v1/*)
  signals.py       signal 2: stylometric heuristics
  groq_signal.py   signal 1: Groq LLM assessment
  scoring.py       ensemble combine, thresholds, label generation
  audit.py         append-only JSONL audit log
  chunking.py      sentence/token splitting
  config.py        weights, thresholds, label copy, limits
scripts/           independent verification harnesses (signals, scoring, labels)
wsgi.py            entrypoint
planning.md        full design doc (signals, uncertainty, appeals, edge cases)
```

### Verification harnesses

Run any of these to independently exercise a component:

```bash
PYTHONPATH=. python scripts/try_groq_signal.py   # signal 1 on sample inputs
PYTHONPATH=. python scripts/try_signal2.py       # signal 2 + agreement vs signal 1
PYTHONPATH=. python scripts/verify_scoring.py     # thresholds + guardrail (no network)
PYTHONPATH=. python scripts/verify_labels.py      # label text vs spec (no network)
PYTHONPATH=. python scripts/demo_scoring.py       # 3-category coverage + variation
```

---

## Known limitations

**Specific failure case — formulaic/technical human writing (legal clauses,
scientific abstracts, recipes, structured documentation).** This is content the
system will likely mislabel as AI, and it's a direct consequence of *how the
signals work*, not a data problem:

- The `stylometry` signal treats **low sentence-length variance** and **high mean
  word length** as AI tells. But technical/legal prose is *supposed* to be
  uniform, dense, and impersonal — so its burstiness sub-score and word-length
  sub-score both push toward AI.
- The `groq_authenticity` signal keys on "bland, risk-averse, impersonal tone,"
  which is precisely the correct register for an abstract or a statute — so it
  also leans AI.
- Because **both** signals respond to the same surface property (impersonal
  uniformity) on this genre, the ensemble doesn't save us: they reinforce instead
  of cross-check, and a human-authored abstract can score `likely_ai`.

The same mechanism explains the **repetitive-poem** edge case (low burstiness +
low lexical diversity → AI), confirmed in testing where both signals flagged a
simple repetitive poem. The fix is content-type-aware weighting (down-weight
stylometry, and prompt the LLM to expect genre conventions) — noted but not yet
implemented.

Other limitations:

- **Uncalibrated confidence** — the score is a weighted aggregate with an
  identity calibration; numbers are directional, not probabilities fit to data.
- **Single-shot LLM signal** — `groq_authenticity` depends on Groq availability;
  failures surface as `502`.
- **No persistence beyond the JSONL log** and **no auth** on `/log` / `/appeals`
  — appropriate for this project's scope, not production.

---

## Spec reflection

**How the spec helped.** Writing the *Uncertainty Representation* threshold table
and the *Transparency Label Variants* (verbatim text) in `planning.md` **before**
coding gave the implementation an exact target. Verification became "assert the
code matches the spec" rather than guesswork — and that's literally what caught
two bugs: `verify_labels.py` flagged a hyphen where the spec used an em dash, and
`verify_scoring.py` exposed a false-positive guardrail that silently overrode the
documented thresholds. Without the spec's concrete numbers and strings, neither
divergence would have been detectable.

**How the implementation diverged.** The spec/architecture diagram described a
versioned `POST /api/v1/analyze` keyed on `request_id` with **four** separate
detection signals. The build instead centers on a root **`POST /submit`** keyed on
`content_id` (needed by the appeal flow) with **two** signals. Why: (1) the
incremental build was organized around `/submit`; (2) one strong LLM judgment
folds three of the four planned stylistic signals (tone, hollow-grammar,
personal-voice) into a single call, so pairing it with one independent
statistical signal gave better *signal diversity per unit of effort* than four
overlapping heuristics. The signal originally specced as `rhythm_consistency` was
also renamed `stylometry` once it grew from one metric to three.

---

## AI usage

This project was built with heavy use of an AI coding assistant, with each
generated piece verified against the spec before being trusted. Two specific
instances:

1. **Confidence scoring (Milestone 4).** I directed the AI to generate the logic
   that combines both signals per the threshold table. It produced
   reasonable-looking code, but its `false_positive_probability` proxy peaked at
   the decision boundary — so the `FP > 0.30` guardrail silently downgraded
   *almost every* `likely_ai` result (anything below ~0.95) to `uncertain`,
   contradicting the spec's threshold table. My `verify_scoring.py` harness
   caught it; **I overrode** the proxy with `1 − confidence`, so the guardrail now
   only trims the genuinely borderline 0.60–0.70 band.

2. **Second signal (stylometry).** I directed the AI to implement a multi-metric
   stylometric function (variance, type-token ratio, mean word length). It
   produced a clean implementation with a **direction bug**: it mapped *high* mean
   word length to a *low* (human-like) score, so formal AI text looked human.
   Running it on the same inputs as signal 1 (`try_signal2.py`) surfaced the
   inverted result; **I revised** the helper into explicit
   `_logistic_low_is_ai` / `_logistic_high_is_ai` functions and applied the
   correct direction per metric.

In both cases the pattern was the same: let the AI draft, then verify against the
spec with a dedicated harness, and correct where the output looked plausible but
diverged.

---

## Portfolio walkthrough

> _Recording link: **[add your video URL here]**_

A short (~2 minute) screen recording giving a quick end-to-end tour. The detailed
evidence lives in the sections above; the video is just a narrated demo. Suggested
flow:

1. **Submit a clearly-AI paragraph** (`curl …/submit`) → point out `confidence`,
   the `likely_ai` label, and both signal scores in the response.
2. **Submit a casual human paragraph** → show the score drop to `likely_human`
   (meaningful variation).
3. **File an appeal** on the first one (`curl …/appeal`) → show the status flip to
   `under_review`, then `GET /appeals` to show the reviewer queue.
4. **`GET /log`** → show the structured audit entries with `appeal_filed`.
5. Talk through one design decision — e.g. *why* the false-positive guardrail
   biases toward `uncertain`, or why one LLM + one statistical signal.
