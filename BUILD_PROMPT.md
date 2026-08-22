# Build Prompt: QueueMerge — Office-Hour Compression Engine

Use this as a single prompt to hand to an AI coding assistant (or to scope your own build). It defines the problem, the required novelty, the architecture, and the deliverables.

---

## Prompt

You are building **QueueMerge**, an office-hour queue system that compresses a crowded queue of individual student questions into a small number of *root-cause groups*, so a TA/instructor can resolve many students at once instead of one-by-one.

### Problem statement

Right before assignments and exams, office-hour queues explode. Standard queue tools (Google Form + spreadsheet, QueueTip, WebSTAC, OHQueue, etc.) just serialize students into a line — even when 5–15 of them are stuck on the same underlying misconception. Teaching guidance already tells instructors to "batch similar questions," but today that batching is manual, ad hoc, and depends on a TA eyeballing the queue. QueueMerge automates the batching and, critically, batches by *cause*, not by surface wording.

### Core novelty (must all be implemented, not just mentioned)

Build these four capabilities as first-class, testable features:

1. **Root-cause clustering** — Group students by the underlying misconception driving their question, not by lexical/topic similarity. Two students asking differently-worded questions ("why is my loop off by one" / "why does my array print an extra blank line") should cluster together if both trace back to the same root cause (e.g., "boundary condition in loop termination"). Two students asking similarly-worded questions should be split apart if the diagnosis differs.
   - Pipeline: (a) extract a *candidate misconception tag* per question via structured LLM extraction against a course-specific misconception taxonomy, not free-text embedding similarity alone; (b) cluster on the tag/taxonomy node plus supporting evidence (code snippet, error message, which sub-step they're stuck on); (c) require the clustering step to output a human-readable causal explanation for each group ("these 6 students all assume the loop should run len(arr) times inclusive").
   - Must degrade gracefully: if no taxonomy exists yet for a course, bootstrap one live from the incoming queue and let the instructor approve/rename clusters.

2. **Counterfactual simulation** — Before a TA picks who to help next, simulate the queue forward under each candidate choice ("help Group A next" vs "help Group B next" vs "help the single longest-waiting student") and show the projected effect on total queue state: how many students get unblocked, how many new arrivals are likely to join and how they'd cluster, and projected wait times for everyone else.
   - This must be a real forward simulation over a queue-state model (arrivals process + service-time distribution + resolution-propagates-to-cluster logic), not just a static priority score.
   - Output: a short ranked comparison ("Helping Group A next clears 7 students in ~9 min and drops median wait by 4 min; helping the longest-waiting single student clears 1 student in ~6 min and drops median wait by 40s").

3. **Students-unblocked-per-TA-minute (SUPM) optimization** — The core ranking metric for what to work on next is not FIFO or raw group size, but *expected students unblocked ÷ expected TA-minutes spent*, estimated per group from the group's size, the (predicted) explanation time for its root cause, and confidence in the clustering. Ties/edge cases (e.g., a lone struggling student vs. a large low-confidence cluster) must be resolved transparently, with the score and its inputs shown to the TA, not hidden.

4. **Misconception outbreak detection** — Continuously monitor the *rate* at which incoming questions map to each taxonomy node. When a node's inflow rate crosses a threshold (statistically, e.g., a spike vs. its baseline/expected rate for this point in the course timeline, not just a raw count), fire an "outbreak" alert recommending a *group intervention* (e.g., "pause 1-on-1s, do a 5-minute whole-room clarification on X") instead of continuing to drain the queue one cluster at a time. Must include: outbreak confidence, trend (still climbing vs. plateauing), and an estimate of 1-on-1 time saved by intervening now vs. later.

### System requirements

- **Data model**: students, questions (raw text + optional code/error paste), misconception taxonomy (course-scoped, hierarchical), clusters (dynamic, with membership history), TA sessions/actions, outcome labels (resolved / still stuck / escalated).
- **Pipeline stages**: intake → misconception extraction → clustering/re-clustering → SUPM scoring → counterfactual simulation on demand → outbreak monitor (background job) → TA-facing recommendation feed.
- **TA-facing UI**: queue view grouped by cluster (not by student), each cluster showing size, root-cause explanation, SUPM score, wait stats; a "what if I help this next" simulation trigger; an outbreak banner when triggered.
- **Feedback loop**: TA marks a cluster resolved/partially resolved/misclustered → this retrains/reweights the taxonomy and clustering confidence for the course over time.
- **Evaluation harness**: replay historical queue logs (or synthetic ones) and report (a) baseline FIFO total wait/throughput vs QueueMerge, (b) clustering precision/recall against human-labeled root causes, (c) outbreak detection lead time vs a naive count-threshold baseline.

### Explicitly avoid

- Don't ship clustering that's just embedding cosine-similarity on question text and call it "root-cause" — that's surface clustering, not causal. Root-cause tags must come from a taxonomy-grounded extraction step with an explanation, and be auditable.
- Don't ship a "priority score" that's really just group size or wait time in disguise — SUPM must genuinely divide by estimated TA-minutes, and that estimate must be visible.
- Don't fire outbreak alerts on raw counts alone — must compare against an expected baseline rate to avoid alert fatigue.

### Deliverables

1. Architecture diagram + data model.
2. Working prototype (backend pipeline + minimal TA UI) covering all four novelty features above.
3. Evaluation report comparing QueueMerge against FIFO baseline on a sample/synthetic dataset.
4. A short write-up of what's genuinely novel here relative to existing office-hour queue tools and existing "batch similar questions" teaching advice, for use in a paper/pitch.

---

*End of prompt. Paste this whole block into your coding agent (e.g., Claude Code) to scope and build the system, or use it as-is to draft a project/research proposal.*
