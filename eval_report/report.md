# QueueMerge Evaluation Report (cs101)

Synthetic session: 40 questions over 60 minutes, seed=7, preset=`cs101`, taxonomy = 8 root causes, scripted outbreak on `reference-vs-copy` starting at t=25.0 min.

## 1. FIFO baseline vs QueueMerge

| Metric | FIFO | QueueMerge |
|---|---|---|
| Avg wait (min) | 68.79 | 18.41 |
| Median wait (min) | 65.03 | 12.47 |
| Total wait (student-min) | 2751.7 | 736.3 |
| Resolved by session end (of 40) | 13 | 28 |
| Time to fully clear queue (min) | 195.9 | 95.6 |

QueueMerge reduced average wait by **73.2%** vs strict FIFO on this synthetic session (single TA, both policies use the same arrival stream and the same ground-truth per-cause explanation times).

## 2. Clustering precision / recall vs ground-truth root cause

Overall accuracy: **0.9**  |  Macro precision: **0.741**  |  Macro recall: **0.936**

| Root cause | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| candidate-function-remember-values | 0.0 | n/a | n/a | 0 |
| candidate-sum-always-missing | 0.0 | n/a | n/a | 0 |
| index-out-of-range | 0.67 | 1.0 | 0.8 | 4 |
| integer-division-truncation | 1.0 | 1.0 | 1.0 | 3 |
| loop-boundary-exclusive-missing-last | 1.0 | 0.8 | 0.89 | 5 |
| loop-boundary-inclusive | n/a | 0.0 | n/a | 2 |
| mutable-default-arg | 1.0 | 0.75 | 0.86 | 4 |
| recursion-missing-base-case | 1.0 | 1.0 | 1.0 | 2 |
| reference-vs-copy | 1.0 | 1.0 | 1.0 | 19 |
| scope-variable-shadowing | 1.0 | 1.0 | 1.0 | 1 |

(Evaluated with the heuristic extractor for reproducibility; the Gemini extractor is the intended production path and is expected to score higher on the harder confusable pairs, e.g. `loop-boundary-inclusive` vs `loop-boundary-exclusive-missing-last`.)

## 3. Outbreak detection lead time vs naive count-threshold baseline

- True scripted outbreak start: t = 25.0 min
- QueueMerge (statistical, rate-vs-baseline) detected at: t = 31.109 min
- Naive raw-count threshold (>=5 in a 10-min window) detected at: t = 34.247 min

QueueMerge detected the outbreak **3.1 minutes earlier** than the naive threshold on this run.


### False-positive / alert-fatigue control

Ran 5 synthetic sessions with **no** scripted outbreak (uniform root-cause mix, natural random variation only):

- Naive raw-count threshold falsely fired in **2/5** sessions
- QueueMerge's baseline-relative statistical test falsely fired in **4/5** sessions

At this significance level (alpha=0.02) the statistical test is more sensitive than the fixed threshold in both directions on these small synthetic sessions: it catches the real outbreak sooner (section above) but can also fire on ordinary variance more often in a no-outbreak control. Alpha is tunable; a real deployment would calibrate it against a semester of historical sessions rather than the ~5 synthetic runs here. The steady-popular-node control below is the more targeted test of the actual claim (baseline-relative vs raw-count), since it isolates 'popular' from 'random variance'.


### Steady-popular-node control (the case a raw-count threshold gets wrong)

Ran 5 sessions where one root cause is simply popular all session (steady elevated rate from t=0, not a spike). Once QueueMerge's baseline for that node is established (after its first ~2 windows):

- Naive raw-count threshold fired on the steady-popular node in **3/5** sessions (it can't tell 'popular' from 'spiking')
- QueueMerge fired on it (after baseline established) in **2/5** sessions

On this small sample the gap is directional rather than dramatic -- the mechanism (compare to the node's own history, not a fixed number) is sound, but 5 runs of a 60-minute synthetic session isn't enough to make a strong statistical claim either way. The harness (`python -m queuemerge.evaluate`) is reusable with more seeds and longer sessions once real historical queue logs are available.
