# QueueMerge — Submission

> Copy/paste sections of this directly into your Devpost submission form.

## A note on the rubric

I searched for IgnitionHacks v.7's specific published rubric and couldn't
find a public page for it (v.7's Devpost listing doesn't appear to be
indexed yet at the time of writing). The most recent confirmed rubric I
could verify is from **Ignition Hacks v.6**, which judges on four criteria:

1. **Technical Implementation** — functionality, complexity, code quality
2. **Uniqueness** — is the idea original, or something judges can just find
   online already?
3. **Teamwork** — did everyone contribute, and work well together?
4. **Q&A** — how clearly the team explains and defends the project live

Everything below is written to score well against those four criteria
specifically, since it's the best-verified proxy available. **Double-check
the actual v.7 rubric on Devpost before submitting** in case it's changed
weighting or added a criterion — if it has, the content below still
applies, you'd just want to re-check emphasis.

## What your project does

QueueMerge is a queue compression engine for **office hours and adjacent
support desks**. Instead of putting every person in a single
first-come-first-served line, it groups tickets that share the same underlying
root cause — not just similar-sounding wording — and lets an agent resolve
all of them with one explanation. The same pipeline runs on two taxonomy
presets (CS101 Office Hours and Fintech Support Triage) switched from the UI.

## The problem it addresses

Before assignments and exams, office-hour queues explode. It's common for
five or more students to be stuck on the exact same conceptual bug (e.g. an
off-by-one loop error) while a TA works through them one at a time, giving
the same explanation over and over. Existing queue tools sort students into
a line; grouping by shared misconception is usually done manually, if at
all, and only when a TA happens to notice the pattern themselves.

## How the solution works

QueueMerge runs each incoming question through a six-stage pipeline:

1. **Root-cause extraction** — an LLM (Gemini) reads the incoming question,
   code/IDs, and error message and maps it to a node in the active domain
   taxonomy preset (CS101: e.g. "loop-boundary-inclusive" vs.
   "index-out-of-range"; Fintech: e.g. "duplicate-charge" vs.
   "unexplained-fee") — not just a keyword match on the surface text.
   If Gemini is unavailable, an offline deterministic keyword/pattern
   matcher takes over automatically, per-question, so the system never
   goes down.
2. **Clustering** — waiting questions are grouped by shared root cause, then
   split further by specific evidence sub-step when there's enough support,
   so "same node, different specific cause" doesn't get lumped together.
3. **SUPM scoring (students-unblocked-per-TA-minute)** — every cluster gets
   a transparent score: expected students unblocked (cluster size
   discounted by clustering confidence) divided by expected TA minutes
   (the node's running time estimate + small group overhead). The TA sees
   the full arithmetic, not a black-box number.
4. **Counterfactual simulation** — on demand, a Monte Carlo forward
   simulation projects what happens to the whole queue (wait times,
   students unblocked, time to clear) under each candidate "help this
   group next" choice, so the recommendation isn't just a static score.
5. **Outbreak detection** — a background statistical monitor compares each
   misconception's live arrival rate to its own historical baseline
   (Poisson upper-tail test, not a fixed count threshold) and flags when a
   node is spiking, recommending a single group intervention instead of
   many 1-on-1 repeats.
6. **Explanation Memory** — TAs can save the explanation or teaching move that
   worked for a root cause. Those notes are stored against the misconception
   taxonomy node rather than a temporary cluster ID, so they automatically
   resurface when the same misconception appears in a later cluster. Notes are
   ranked by usefulness votes and can persist across app restarts/semesters when
   the SQLite database is stored on disk.

A feedback loop closes it out: when a TA marks a cluster resolved,
partially resolved, or misclustered, the taxonomy node's time estimate and
confidence weight update (EWMA), so later scores and simulations get more
accurate over the course of a session.

## Key technologies / tools used

- **Python** — core pipeline (`queuemerge/`)
- **SQLite** — data model (courses, taxonomy nodes, questions, clusters,
  outbreak alerts, feedback events, reusable explanation-memory notes)
- **Google Gemini API** (`gemini-3.6-flash` + fallbacks, via `google-generativeai`) —
  structured root-cause extraction, with a deterministic offline fallback
  extractor so the app runs with zero configuration
- **Streamlit** — live TA / agent UI (Cloud-deployed)
- **GitHub Pages** — static interactive chalkboard demo (`demo_site/`)
- **Monte Carlo simulation** (`queuemerge/simulation.py`) — counterfactual
  "what if I help this group next" comparisons
- **Matplotlib** — evaluation report charts
- **python-dotenv** — local `.env` key loading (no secrets in source)

## Notable features / technical decisions

- **Root-cause clustering, not text-similarity clustering.** Two
  differently-worded questions with the same underlying bug merge into one
  cluster; two similarly-worded questions with opposite bugs (e.g. an
  off-by-one that runs one iteration too many vs. one that stops one short)
  correctly stay apart. The seed taxonomy deliberately includes these
  confusable pairs to stress-test this.
- **Transparent scoring.** SUPM's full arithmetic (cluster size, confidence
  discount, minutes estimate, group overhead) is shown in the UI, not
  hidden behind a single number — a TA can see exactly why one cluster
  outranks another.
- **Statistical outbreak detection, not a raw-count threshold.** A node
  that normally gets 5 questions/hour hitting 6 isn't an outbreak; a node
  that normally gets 0.3/hour hitting 6 is. The detector compares against
  each node's own adaptive baseline (EWMA) via a Poisson significance
  test, with a real evaluation harness comparing it against a naive
  threshold baseline (see `eval_report/report.md`).
- **Graceful degradation, not a hard dependency on an LLM.** Every Gemini
  call is wrapped so a missing key, network failure, rate limit, or
  malformed response falls through to a deterministic heuristic extractor
  automatically, per-question — a mid-session API outage doesn't take the
  queue down.
- **Explanation Memory, not just queue history.** A resolved cluster can leave
  behind a reusable teaching note for its misconception node. When that root
  cause returns later, QueueMerge surfaces the prior explanations and their
  usefulness votes automatically. A regression test proves the note survives a
  different cluster ID and a fresh app instance backed by the same SQLite file.
- **A real evaluation harness**, not just a demo script:
  `python -m queuemerge.evaluate` replays a synthetic 40-question session
  and reports (1) QueueMerge vs. a strict FIFO baseline on wait time and
  throughput, (2) clustering precision/recall/F1 against synthetic ground
  truth, and (3) outbreak-detection lead time vs. a naive threshold. Full
  numbers are checked into `eval_report/report.md` — including a real bug
  the harness caught and its measured fix impact (82.5% → 90% extraction
  accuracy; see the README's "Design notes" bug log).
- **Regression tests from real bugs**, not just happy-path examples. The suite
  now has twelve smoke tests. Three lock in fixes for bugs found during
  development (unstable cluster IDs, outbreak-alert persistence/cooldown, and
  pending bootstrap nodes cannibalizing curated matches). A fourth dedicated
  test proves Explanation Memory survives resolution, re-clustering, and a
  fresh app instance using the same SQLite file. See the README for the full
  postmortems.

## Track(s) / Category(ies) — Ignition Hacks 2026

Fill these on the Devpost form from **this year's exact list**. Suggested
selections for QueueMerge (eligible because the product actually demonstrates
them):

### Category (theme)
- **FinTech** — primary category claim if you need one of FinTech / Environment / Art:
  sidebar **Fintech Support Triage** preset (duplicate charges, stuck transfers,
  false fraud declines, MFA lockouts, etc.) runs on the same clustering/SUPM/
  simulation/outbreak pipeline as CS101.
- Environment / Art — **do not claim** unless you build something that fits;
  QueueMerge is not an environment or art project.

### Track(s)
Pick whatever Ignition lists this year that you are eligible for. Natural fits:
- Education / EdTech (if offered) — CS101 office-hours preset is the original use case
- AI / ML or Best Use of Gemini / Google AI (if offered) — structured extraction + fallback
- Productivity / Developer tools (if offered)

Check team-composition rules (solo, first-timer, etc.) before selecting.

## Live links for judges

- **GitHub (public):** https://github.com/AniketT0008/QueueMerger
- **Static demo (Pages):** https://anikett0008.github.io/QueueMerger/
- **Live Streamlit app:** https://queuemerger-aaurranskplmeavmvsdjqy.streamlit.app/

Core demo needs **no API keys**. Optional sponsor hooks (ElevenLabs / Discord
webhook / World Labs) are documented in the README and stay hidden unless
configured — do not rely on them for judging.

## Ignition Hacks 2026 submission checklist

- [ ] Demo video ≤ 3 min — show Streamlit **and/or** Pages demo working; say problem + features
- [ ] Project description pasted (see sections above)
- [ ] Track(s) selected
- [ ] Category selected (**FinTech**)
- [x] Public GitHub link: https://github.com/AniketT0008/QueueMerger
- [x] README has setup (`pip install -r requirements.txt`, `streamlit run ui_streamlit.py`)
- [x] Code on `main` runs for judges (heuristic works with zero API key)

## Talking points for Q&A (since that's a scored criterion)

Be ready to speak to, in your own words:

- **Why root-cause clustering and not just semantic similarity search?**
  Two questions can be worded almost identically and have opposite root
  causes (the seed taxonomy's two "loop boundary" nodes are deliberately
  confusable for this reason) — surface similarity gets these wrong in
  both directions.
- **What happens if the LLM is wrong or unavailable?** Every Gemini call is
  wrapped in a fallback to a deterministic offline extractor, per-question,
  not just at startup — a rate limit or outage mid-session degrades
  gracefully instead of breaking the queue.
- **How do you know the numbers are real?** `eval_report/report.md` is
  regenerated by an actual harness run against synthetic ground truth, not
  hand-picked — including a documented bug it caught (bootstrap-node
  keyword cannibalization) and the measured before/after accuracy impact
  of fixing it (82.5% → 90%).
- **What's the honest limitation?** Root-cause tags are LLM-inferred, not
  verified against real instructor-labeled ground truth (no deployment has
  that yet), and the counterfactual simulation runs on reasonable-but-
  assumed parameters rather than measured ones from a real course. Both
  are called out explicitly in the README's "Design notes / where the
  corners were cut" section — naming this proactively tends to read better
  to judges than waiting to be asked.
