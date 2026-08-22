# QueueMerge — What's Actually Novel

## The gap in existing tools

Standard office-hour queue tools (Google Form + spreadsheet, QueueTip, WebSTAC,
OHQueue) serialize students into a line. Teaching guidance already tells TAs to
"batch similar questions," but that batching is manual: a TA has to notice the
pattern by eye while also fielding the current question, under time pressure,
right when the queue is at its most crowded — exactly when they have the least
slack to do it well.

QueueMerge automates the batching. The specific claims below are about what's
different from (a) existing queue tools and (b) the "batch similar questions"
advice itself, not just "software exists."

## 1. Root cause, not surface wording

Existing "smart" queue tools that do any grouping at all do it via text
similarity — questions with overlapping words end up near each other. This
fails in both directions that matter for office hours:

- **False splits**: "why is my loop off by one" and "why does my array print
  an extra blank line" share almost no vocabulary but are the same bug.
- **False merges**: "my loop skips the last item" and "my loop runs one extra
  time" share most of their vocabulary (loop, item/element, off-by-one framing)
  but are *opposite* bugs requiring opposite fixes.

QueueMerge's extraction step is grounded in a **domain taxonomy preset** of
root causes (CS101 office hours *or* Fintech support triage — same engine,
switched from the sidebar), not a bag of words — it produces a specific node
ID plus a human-readable causal explanation ("6 students all assume the loop
should run len(arr) times inclusive"), auditable per question, not a
similarity score. Fintech uses the same discrimination test with its own
confusable pairs (`duplicate-charge` vs `unexplained-fee`; `stuck-transfer`
vs `stale-account-sync`).

## 2. Forward simulation, not a static priority number

"Help the biggest group" or "help whoever's waited longest" are both static
heuristics — they don't account for how the queue will actually evolve. A TA
picking between two similarly-sized groups benefits from seeing the actual
projected effect: how many students clear, how the wait distribution for
everyone else shifts, and how new arrivals are likely to be absorbed. That
requires an actual forward model of the queue (arrivals + service time +
batch-resolution propagation), not a formula evaluated once at decision time.

## 3. A ranking metric that's honest about its own inputs

It would be easy to build a "priority score" that's really just cluster size
or wait time with a different name on it. SUPM (students unblocked per
TA-minute) is a genuine ratio — divide by an estimated cost, not just look at
benefit — and every input to that ratio (cluster size, confidence discount,
per-node time estimate, group overhead) is surfaced to the TA rather than
buried in an opaque score. This matters specifically for the edge case the
spec calls out: a lone struggling student vs. a large low-confidence cluster
is a real judgment call, and QueueMerge shows its work instead of resolving
it silently.

## 4. Outbreak detection relative to a baseline, not a raw count

"5 questions on the same thing" means something completely different at 9am
on a normal Tuesday than at 11pm the night before a deadline, when overall
volume is already 10x higher. A fixed count threshold either fires
constantly during crunch time (alert fatigue, gets ignored) or misses real
spikes during quiet periods. Comparing a node's *current* rate to its *own*
adaptive baseline — and requiring statistical significance, not just "more
than N" — is what makes an outbreak alert something a TA can actually trust
enough to act on (pause 1-on-1s, do a whole-room clarification).

## 5. Explanation Memory: the queue learns how the misconception was taught

Most queue systems are intentionally ephemeral: once a student leaves the line,
the teaching interaction disappears. QueueMerge now keeps a lightweight
institutional memory of **which explanations or teaching moves worked for each
root-cause misconception**. A TA can save a note while handling a cluster; when
the same taxonomy node appears in a later cluster, those notes resurface
automatically, ranked by usefulness votes.

The implementation is deliberately keyed to the stable taxonomy node rather
than a cluster ID. That is important because QueueMerge rebuilds live clusters
as the queue changes. The memory therefore survives re-clustering, resolution,
and, with an on-disk SQLite database, application restarts or later semesters.
A regression test proves this exact cross-cluster/cross-restart behavior.

This extends the product from **queue compression** into **teaching-memory
accumulation**: the system not only recognizes that a misconception has returned,
it can recover the explanation pattern that previously helped instructors deal
with it.

## Honest caveats

- The evaluation report (`eval_report/report.md`) uses the heuristic
  extractor for reproducibility. It's weaker than Gemini would be on the
  hardest confusable pairs (e.g. two "loop boundary" nodes in opposite
  directions) — this is disclosed in the report, not hidden.
- The outbreak-detection false-positive control is directional, not
  conclusive, on 5 synthetic runs — also disclosed rather than oversold.
- "Root cause" here means "which node in a human-authored taxonomy," not
  causal inference in the philosophical sense. The novelty claim is about
  grounding in a structured taxonomy with an auditable explanation, not
  about solving causal discovery.
