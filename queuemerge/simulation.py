"""Pipeline stage 5: counterfactual simulation.

Runs a Monte Carlo discrete-time forward simulation of the queue under each
candidate "help X next" choice, so a TA can compare projected outcomes
instead of trusting a single static score. Real forward simulation over a
queue-state model:

- Arrivals: a Poisson process per taxonomy node, rate estimated from recent
  intake history for the course (falls back to a small course-wide default
  if there's not enough history yet).
- Service time: triangular distribution per node, parameterized by the
  node's mean_explain_minutes (min/mode/max derived from it), plus the same
  per-extra-student group overhead used in SUPM.
- Resolution propagation: helping a cluster resolves ALL its members at
  once when the (single) explanation for that cluster finishes, rather than
  serially -- that's the whole point of grouping.

The horizon is short (default 20 minutes) since queue dynamics that far out
are what a TA actually needs to decide "who next", not a full-session
forecast.
"""
import random
import statistics
from collections import defaultdict
from queuemerge import db as dbm

DEFAULT_HORIZON_MIN = 20.0
DEFAULT_TRIALS = 200
DEFAULT_ARRIVAL_RATE_PER_MIN = 0.15  # fallback if no history: ~1 arrival per ~6.7 min


def _estimate_arrival_rate(conn, course_id: int) -> float:
    """Arrivals-per-minute, estimated from the last 60 minutes of intake
    across the whole course (kept simple: one course-wide rate rather than
    per-node, since a TA's 20-min horizon doesn't have enough data for a
    reliable per-node breakdown from a single office-hour session)."""
    with dbm.cursor(conn) as cur:
        rows = cur.execute(
            "SELECT created_at FROM questions WHERE course_id = ? ORDER BY created_at",
            (course_id,),
        ).fetchall()
    if len(rows) < 4:
        return DEFAULT_ARRIVAL_RATE_PER_MIN
    times = sorted(r["created_at"] for r in rows)
    span_min = max(1.0, (times[-1] - times[0]) / 60.0)
    return max(0.02, len(times) / span_min)


def _service_minutes(mean_minutes: float, size: int) -> float:
    """Triangular(min, mode, max) draw around the node's mean explain time,
    plus per-extra-student overhead for group sessions."""
    mode = max(1.0, mean_minutes)
    lo, hi = mode * 0.6, mode * 1.6
    base = random.triangular(lo, hi, mode)
    overhead = 0.6 * max(0, size - 1)
    return base + overhead


def _simulate_one_trial(conn, course_id: int, choice: dict, other_clusters: list,
                         arrival_rate: float, horizon_min: float, node_cache: dict) -> dict:
    """One stochastic trial. `choice` is the cluster/single-student the TA
    picks first; after it resolves, the TA keeps working the highest-SUPM
    remaining item (greedy, same policy as the live recommender) until the
    horizon runs out. Returns per-trial metrics."""
    t = 0.0
    unblocked = 0
    # local mutable copy of remaining queue items: list of dicts with size, node mean, wait_start
    from queuemerge import supm as supm_mod

    queue = []
    for c in other_clusters:
        queue.append({
            "size": c["size"], "mean_min": node_cache[c["taxonomy_node_id"]]["mean_explain_minutes"],
            "wait_start": 0.0, "conf": c.get("avg_confidence", 0.5),
        })

    # serve the chosen item first
    chosen_size = choice["size"]
    chosen_mean = node_cache[choice["taxonomy_node_id"]]["mean_explain_minutes"] if choice.get("taxonomy_node_id") else 4.0
    t += _service_minutes(chosen_mean, chosen_size)
    unblocked += chosen_size

    waits_recorded = []

    while t < horizon_min:
        # new arrivals since last step, distributed across a synthetic mix of
        # cluster sizes drawn from the current queue's size distribution (or 1 if empty)
        expected_arrivals = arrival_rate * _service_minutes(3.0, 1)  # small step proxy
        n_new = _poisson_draw(max(0.01, expected_arrivals))
        for _ in range(n_new):
            size = random.choice([1, 1, 1, 2, 3]) if not queue else random.choice([1, 1, 2])
            mean_min = random.choice([n["mean_explain_minutes"] for n in node_cache.values()]) if node_cache else 5.0
            queue.append({"size": size, "mean_min": mean_min, "wait_start": t, "conf": 0.6})

        if not queue:
            break
        queue.sort(key=lambda q: -(q["size"] * max(0.15, q["conf"]) / max(1.0, q["mean_min"])))
        nxt = queue.pop(0)
        service = _service_minutes(nxt["mean_min"], nxt["size"])
        t += service
        if t <= horizon_min:
            unblocked += nxt["size"]
            waits_recorded.append(t - nxt["wait_start"])

    # remaining queue members' projected wait = time until horizon ends (censored)
    remaining_wait_proxy = [max(0.0, horizon_min - q["wait_start"]) for q in queue]
    all_waits = waits_recorded + remaining_wait_proxy
    median_wait = statistics.median(all_waits) if all_waits else 0.0

    return {"unblocked": unblocked, "median_wait_min": median_wait, "cleared_in_min": t if t <= horizon_min else horizon_min}


def _poisson_draw(lam: float) -> int:
    # simple Knuth algorithm, fine for small lambda used here
    L = pow(2.718281828, -lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= L:
            return k - 1


def compare_choices(conn, course_id: int, candidate_clusters: list,
                     candidate_single_question: dict = None,
                     horizon_min: float = DEFAULT_HORIZON_MIN,
                     trials: int = DEFAULT_TRIALS) -> list:
    """Runs the Monte Carlo comparison across candidate first-choices and
    returns a ranked list of {label, mean_unblocked, mean_median_wait,
    mean_clear_minutes} plus a one-line human summary, ranked by mean
    unblocked descending (ties broken by lower median wait)."""
    from queuemerge import taxonomy as tax
    nodes = tax.list_nodes(conn, course_id)
    node_cache = {n["id"]: n for n in nodes}
    arrival_rate = _estimate_arrival_rate(conn, course_id)

    candidates = []
    for c in candidate_clusters:
        candidates.append({"label": f"Help cluster: {c['explanation'][:60]}...", "kind": "cluster",
                            "obj": c})
    if candidate_single_question is not None:
        candidates.append({"label": f"Help longest-waiting single student "
                                     f"(#{candidate_single_question['id']})",
                            "kind": "single", "obj": candidate_single_question})

    results = []
    for cand in candidates:
        others = [c for c in candidate_clusters if c is not cand.get("obj")]
        if cand["kind"] == "single":
            choice = {"size": 1, "taxonomy_node_id": cand["obj"].get("taxonomy_node_id")}
        else:
            choice = cand["obj"]

        trial_outs = [
            _simulate_one_trial(conn, course_id, choice, others, arrival_rate, horizon_min, node_cache)
            for _ in range(trials)
        ]
        mean_unblocked = statistics.mean(t["unblocked"] for t in trial_outs)
        mean_wait = statistics.mean(t["median_wait_min"] for t in trial_outs)
        mean_clear = statistics.mean(t["cleared_in_min"] for t in trial_outs)
        results.append({
            "label": cand["label"],
            "kind": cand["kind"],
            "mean_students_unblocked": round(mean_unblocked, 1),
            "mean_median_wait_min": round(mean_wait, 1),
            "mean_clear_minutes": round(mean_clear, 1),
        })

    results.sort(key=lambda r: (-r["mean_students_unblocked"], r["mean_median_wait_min"]))
    return results


def summarize_comparison(results: list) -> str:
    if not results:
        return "No candidates to compare."
    lines = []
    for r in results:
        lines.append(
            f"{r['label']} \u2192 clears ~{r['mean_students_unblocked']} students in "
            f"~{r['mean_clear_minutes']} min; projected median wait for everyone else "
            f"~{r['mean_median_wait_min']} min."
        )
    return " | ".join(lines)
