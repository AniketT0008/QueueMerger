# QueueMerge


## Contributors

- [AniketT0008](https://github.com/AniketT0008)
- [jeevanpartapsingh21-a11y](https://github.com/jeevanpartapsingh21-a11y)

Office-hour queue compression engine. Groups a crowded queue of individual
student questions into root-cause clusters so a TA can resolve many students
at once instead of one by one. Full build prompt this implements is in
`BUILD_PROMPT.md` (the original spec).

## What's here

- `queuemerge/` — the pipeline (intake → extraction → clustering → SUPM
  scoring → counterfactual simulation → outbreak monitor → feedback loop)
- `ui_streamlit.py` — TA-facing UI
- `tests/smoke_test.py` — end-to-end integration tests, no API key needed
- `eval_report/` — evaluation harness output (report.md + 2 charts), already
  generated once so you can read it without running anything
- `ARCHITECTURE.md` — pipeline diagram + full data model
- `NOVELTY_WRITEUP.md` — what's actually novel vs. existing tools, including the added Explanation Memory feature
- `demo_site/index.html` — self-contained interactive browser demo (no backend/API key required)

## Setup

```bash
pip install -r requirements.txt
```

Everything works with **zero configuration** — the misconception extractor
falls back to a deterministic, offline, keyword/pattern-based matcher
(`HeuristicExtractor` in `queuemerge/llm_client.py`) whenever Gemini isn't
available.

To use real LLM extraction (the intended production path), either export
the key for your shell session:

```bash
export GEMINI_API_KEY="your-key-here"   # free tier: https://aistudio.google.com/apikey
```

or copy `.env.example` to `.env` and put your key there (picked up
automatically via `python-dotenv` — see `queuemerge/llm_client.py`):

```bash
cp .env.example .env
# then edit .env and paste your key in
```

**Multiple Gemini keys (optional).** `GeminiExtractor` supports rotating
across more than one key, useful for spreading requests over several
free-tier keys instead of hitting one key's rate limit:

```bash
export GEMINI_API_KEYS="key_one,key_two,key_three"   # comma-separated, no spaces
```

Each extraction call round-robins to the next key. If a call fails with a
rate-limit/quota/invalid-key-shaped error, it automatically retries the
same request on the next configured key before falling back to the
heuristic extractor — so one exhausted key degrades to "try the next key,"
not straight to "give up on Gemini entirely." `GEMINI_API_KEY` (singular)
still works exactly as before if you only have one key; you don't need to
switch to the plural form unless you actually have more than one.

`.env` is git-ignored, so your key never ends up in the repo. **Never commit
a real API key to a public GitHub repo** — if one is ever pushed by
accident, revoke it immediately at https://aistudio.google.com/apikey and
issue a new one.

The extractor tries Gemini first per-question and falls back to the
heuristic matcher on any failure (missing key, network error, rate limit,
malformed response) — this fallback is per-question, not just at startup, so
a mid-session Gemini outage degrades gracefully instead of breaking the
queue.

## Run the TA UI

```bash
streamlit run ui_streamlit.py
```

**Design:** clusters render as chalkboard ticket-stub cards — amber SUPM
stub on the left, chalk/board theme, queue-overview strip up top (groups,
people waiting, avg SUPM, longest wait), and semantic color coding —
red only for outbreak/urgent, amber reserved for SUPM. Theme lives in
`.streamlit/config.toml` + CSS in `ui_streamlit.py`.

Use the sidebar **Domain preset** to switch between **CS101 Office Hours** and
**Fintech Support Triage** — same clustering / SUPM / simulation / outbreak /
Explanation Memory engine, separate taxonomies (switching starts a fresh course
so nodes never mix). Then add questions one at a time, or click the **Load 7**
button for a quick demo that shows clustering, SUPM ranking, Explanation
Memory, and a taxonomy-bootstrap approval flow (the 7th sample is deliberately
off-taxonomy — thread-deadlock for CS101, NFT royalty payout for Fintech — and
will show up as pending approval). The sample loader uses the **offline heuristic**
extractor on purpose so the live demo stays instant; typed sidebar questions
still use Gemini when keys are configured.

To see the outbreak banner, submit ~8+ questions that hit the same taxonomy
node in quick succession — e.g. resubmit one of the recursion-error samples
several times with slightly different names. Dismissing an alert won't let
it instantly re-fire on the same node — there's a 20-minute cooldown.

## Two taxonomy presets, same engine

Sidebar **Domain preset** switches between:

| Preset | Example root causes |
|--------|---------------------|
| **CS101 Office Hours** | loop-boundary inclusive/exclusive, IndexError, recursion base case, … |
| **Fintech Support Triage** | duplicate-charge, unexplained-fee, stuck-transfer, stale-account-sync, false-fraud-decline, MFA lockout, … |

Same clustering → SUPM → simulation → outbreak → Explanation Memory pipeline.
Each preset seeds its own course so taxonomies and memory notes never mix.
Eval harness (`python -m queuemerge.evaluate`) writes `eval_report/report.md`
(CS101) and `eval_report/report_fintech.md` with real precision/recall/F1.

## Optional sponsor integrations (Ignition Hacks V.7)

All optional — the core app runs without them. Set in `.env` or Streamlit secrets:

| Env var | What it unlocks |
|---------|-----------------|
| `ELEVENLABS_API_KEY` | **Brief me** button — spoken triage briefing (ElevenLabs) |
| `OUTBREAK_WEBHOOK_URL` | POST to Discord/Slack/**Activepieces** when an outbreak fires |
| `WORLD_LABS_API_KEY` | **Generate 3D world** locally (Marble API; see [World Labs Starter Kit](https://worldlabs.notion.site/Starter-Kit-30d8950a1bef806e90a5e030c6382297)) |
| `WORLD_LABS_PROXY_URL` | Same button via Cloudflare `worldlabs-proxy/` (safer for public deploys) |

Redeem sponsor codes from the Ignition Hacker Package, then paste keys locally
(never commit them). Base44 / Mobbin / Scrimba / Render credits are useful for
your workflow but are not wired into the product runtime.

## Explanation Memory (added novelty)

Queue compression solves the current office-hour rush, but a normal queue tool
forgets everything once the cluster is resolved. QueueMerge now stores reusable
TA explanation notes against the **misconception taxonomy node**, not the
transient cluster row. When the same root cause appears later, the best past
notes automatically resurface, ranked by usefulness votes.

This matters because cluster IDs intentionally change as the live queue is
rebuilt, while the misconception node is stable. The regression test
`test_explanation_memory_resurfaces_across_later_cluster_and_restart` proves a
note written on one cluster resurfaces on a different later cluster and after a
new `QueueMerge` instance opens the same on-disk SQLite database.

The Streamlit demo defaults to `:memory:` for privacy. To make institutional
memory persistent across restarts/semesters, point it at a local SQLite file:

```bash
QUEUEMERGE_DB_PATH=.data/queuemerge.sqlite3 streamlit run ui_streamlit.py
```

No database or real student data is included in this repository/ZIP.

## Browser demo (no install)

Open `demo_site/index.html` in a browser. It is a self-contained interactive
front-end preview with sample clusters, SUPM inputs, simulation output, and an
Explanation Memory panel where you can add notes and upvote them. It does not
pretend to run the Python backend; the real end-to-end app is the Streamlit
command above.

## Run the evaluation harness

```bash
python -m queuemerge.evaluate
```

Regenerates `eval_report/report.md` and the two PNG charts from a fresh
synthetic session (deterministic, seed=7). Reports:

1. FIFO baseline vs QueueMerge — total/average wait, throughput
2. Clustering precision/recall/F1 per root cause vs. synthetic ground truth
3. Outbreak detection lead time vs. a naive raw-count-threshold baseline,
   plus two control scenarios (false-positive/alert-fatigue check, and a
   "steady popular node vs. real spike" check)

The report's numbers are real output from a real run, including the parts
that aren't flattering — quote these on slides, don't bury them:
- heuristic **`loop-boundary-inclusive` recall can be 0.0** on the synthetic set
  (confusable with the exclusive-boundary sibling)
- overall accuracy ~**90%** is heuristic-path only; Gemini is the intended upgrade
- outbreak detector can **false-fire more than a naive count threshold** on
  small no-outbreak controls (see report §3) — lead time is better on the
  scripted spike, but alert fatigue is not magically solved

## Run the smoke tests

```bash
python3 tests/smoke_test.py
```

18 end-to-end tests covering: clustering merges confusable-wording-same-cause
questions, SUPM ranking is transparent and correctly ordered, simulation
returns a real comparison, the feedback loop updates node estimates, live
taxonomy bootstrapping + approval works, outbreak detection fires on a real
spike, outbreak alerts persist across renders with a dismiss cooldown,
empty-queue edge cases don't crash, empty question text is rejected,
cluster IDs stay stable across non-mutating re-renders, the Gemini→heuristic
fallback chain works with no API key set, a pending bootstrap node can't
cannibalize a real match against a curated node, Explanation Memory survives
resolution/re-clustering and resurfaces after a fresh app instance when the
SQLite DB persists to disk, plus multi-key Gemini load/round-robin/failover
guards.

Four tests are especially important regression/behavior guards: three protect
real bugs found during development, and the fourth proves the new Explanation
Memory behavior across re-clustering and a fresh app instance:

1. **Unstable cluster IDs across reruns.** `recommendations()` originally
   rebuilt clusters (new DB row IDs) on every call, including pure
   re-renders. Since Streamlit reruns the whole script on any interaction,
   this silently broke every cluster action button — a click's key
   wouldn't match any button in the next render, so nothing would happen.
   Fixed by making cluster rebuilds explicit (only on actual queue
   mutations), not implicit on every read.
2. **Vanishing / instantly-refiring outbreak banner.** The UI originally
   showed `check_outbreaks()`'s return value directly, which is
   newly-fired-alerts-only (correct for a background job, wrong for a
   persistent banner) — it flashed once then disappeared. And dismissing
   an alert let the same still-elevated rate instantly fire a new one.
   Fixed with a separate `open_outbreak_alerts()` view for display and a
   20-minute dismiss cooldown.
3. **Pending bootstrap nodes could cannibalize real matches.** (Scoring-level
   bug, found by directly probing `HeuristicExtractor.extract()`.) A live
   auto-bootstrapped taxonomy node (created when a question doesn't match
   anything existing) gets its keyword list straight from that one
   question's own words — short and generic (e.g. `["list", "always",
   "seems", "weird"]`). Because the heuristic matcher's score is
   normalized by keyword-list length, that short generic list had a much
   smaller denominator than a curated node's longer, specific list — so a
   couple of coincidental common-word hits could beat a real match
   entirely. Concretely: a genuine "recursion, no base case" question
   (which legitimately matches on the literal phrase `"base case"`) was
   getting misclassified into an unrelated pending bootstrap node just
   because it also happened to contain "always" and "seems". Fixed by
   discounting match weight for any node that's `is_bootstrapped` and not
   yet TA-approved (`HeuristicExtractor.BOOTSTRAP_PENDING_WEIGHT_DISCOUNT`
   in `llm_client.py`) so pending nodes can't outrank curated ones; once a
   TA approves a bootstrap node it competes at full strength like any
   other. Regression test: `test_pending_bootstrap_node_cannot_cannibalize_real_match`
   in `tests/smoke_test.py`. **Measured impact:** this one fix took the
   eval harness's end-to-end extraction accuracy on the same synthetic
   session from **82.5% → 90%** (macro recall 85.8% → 93.6%) — see
   `eval_report/report.md`, regenerated fresh from this fixed code.
4. **Explanation Memory must outlive a cluster.** A note written for a
   misconception is attached to its taxonomy node, then verified to resurface
   after the source cluster is resolved, a new cluster row is created, and a
   fresh `QueueMerge` instance opens the same persisted SQLite database.

## Design notes / where the corners were cut

This is a working prototype, not a production system. Specifically:

- **Single-course, single-TA-at-a-time model.** No multi-TA coordination
  (two TAs both starting the same cluster) — a real deployment would need a
  claim/lock mechanism on clusters.
- **Clustering rebuilds from scratch on every refresh** rather than doing
  incremental re-clustering. Simple and correct, but means it's O(waiting
  questions) per refresh rather than O(delta) — fine at office-hour scale
  (tens of students), not fine at thousands.
- **The counterfactual simulator's arrival-rate estimate is course-wide, not
  per-node** (see `simulation.py`'s docstring) — a single 20-minute office
  hour usually doesn't have enough data for a reliable per-node breakdown.
- **The outbreak monitor's baseline window (10 min) and significance level
  (alpha=0.02) are the values that worked well on synthetic data of this
  scale** — a real deployment should calibrate these against a semester of
  historical logs, which the harness in `evaluate.py` is structured to
  support (swap `generate_session` for a real log loader).
