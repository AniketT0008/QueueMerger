"""Pipeline stage 6: misconception outbreak detection (background job).

Compares the *rate* of incoming questions mapping to each taxonomy node
against an expected baseline rate for that node, using a one-sided Poisson
test rather than a raw count threshold (explicitly required by the spec, to
avoid alert fatigue -- e.g. 6 questions on a node that normally gets 5/hr
right before a deadline is not an outbreak, but 6 questions on a node that
normally gets 0.3/hr is).

Baseline: an EWMA of the node's own historical rate, seeded from a small
course-wide default until enough history accumulates. This is intentionally
simple (no external calendar of "point in course timeline") but is a real,
adaptive baseline rather than a fixed constant.
"""
import math
from collections import defaultdict
from queuemerge import db as dbm

WINDOW_MIN = 10.0          # current window size for the "is this an outbreak" check
BASELINE_HALF_LIFE_MIN = 60.0  # EWMA half-life for the rolling baseline
ALPHA = 0.02                # significance threshold for the Poisson upper-tail test
MIN_WINDOW_COUNT = 3        # never fire on fewer than this many in-window questions
DISMISS_COOLDOWN_MIN = 20.0  # don't re-fire on the same node this soon after a TA dismissal


def _poisson_upper_tail_p(observed: int, expected: float) -> float:
    """P(X >= observed | X ~ Poisson(expected)), via direct summation.
    expected is capped away from 0 to avoid div-by-zero on a totally new node."""
    expected = max(expected, 0.05)
    if observed == 0:
        return 1.0
    # P(X < observed) = sum_{k=0}^{observed-1} e^-l l^k/k!
    p_less = 0.0
    term = math.exp(-expected)
    p_less += term
    for k in range(1, observed):
        term *= expected / k
        p_less += term
    return max(0.0, 1.0 - p_less)


def _ewma_baseline(counts_per_window: list) -> float:
    """Exponentially-weighted moving average over a list of historical
    window counts, oldest first, decaying toward the WINDOW_MIN-scaled
    half-life."""
    if not counts_per_window:
        return 0.5
    decay = math.log(2) / max(1.0, BASELINE_HALF_LIFE_MIN / WINDOW_MIN)
    weight = 1.0
    total_w = 0.0
    acc = 0.0
    for c in reversed(counts_per_window):
        acc += c * weight
        total_w += weight
        weight *= math.exp(-decay)
    return acc / total_w if total_w > 0 else 0.5


def check_outbreaks(conn, course_id: int) -> list:
    """Scans recent question history per taxonomy node, compares the most
    recent WINDOW_MIN-minute window's count to the EWMA baseline of prior
    windows, and returns newly-fired alerts (also persisted to
    outbreak_alerts). Idempotent-ish: won't re-fire an alert for the same
    node while an 'open' alert already exists for it."""
    with dbm.cursor(conn) as cur:
        rows = cur.execute(
            "SELECT taxonomy_node_id, created_at FROM questions "
            "WHERE course_id = ? AND taxonomy_node_id IS NOT NULL", (course_id,)
        ).fetchall()
        open_alert_nodes = {
            r["taxonomy_node_id"] for r in cur.execute(
                "SELECT DISTINCT taxonomy_node_id FROM outbreak_alerts "
                "WHERE course_id = ? AND status = 'open'", (course_id,)
            ).fetchall()
        }
        recently_dismissed_nodes = {
            r["taxonomy_node_id"] for r in cur.execute(
                "SELECT DISTINCT taxonomy_node_id FROM outbreak_alerts "
                "WHERE course_id = ? AND status = 'dismissed' AND dismissed_at >= ?",
                (course_id, dbm.now() - DISMISS_COOLDOWN_MIN * 60.0),
            ).fetchall()
        }
    suppressed_nodes = open_alert_nodes | recently_dismissed_nodes

    if not rows:
        return []

    by_node = defaultdict(list)
    for r in rows:
        by_node[r["taxonomy_node_id"]].append(r["created_at"])

    now = max(r["created_at"] for r in rows)
    win_sec = WINDOW_MIN * 60.0
    new_alerts = []

    with dbm.cursor(conn) as cur:
        node_rows = cur.execute(
            "SELECT * FROM taxonomy_nodes WHERE course_id = ?", (course_id,)
        ).fetchall()
    node_names = {n["id"]: n["name"] for n in node_rows}

    # Course-wide fallback baseline: average per-node arrivals-per-window
    # across ALL nodes' full history so far, excluding the current (most
    # recent) window from each node so a node's own spike can't inflate its
    # own baseline. Used only for nodes that don't yet have >=2 prior
    # windows of their own history (cold start) -- using a node's *own*
    # current count to derive its baseline is circular and was firing
    # false positives in testing.
    total_prior = 0
    total_prior_windows = 0
    for _nid, _times in by_node.items():
        _times = sorted(_times)
        _cutoff = now - win_sec
        _prior = [t for t in _times if t < _cutoff]
        if _prior:
            _span_windows = max(1, int((_cutoff - _prior[0]) // win_sec) + 1)
            total_prior += len(_prior)
            total_prior_windows += _span_windows
    course_fallback_baseline = (total_prior / total_prior_windows) if total_prior_windows > 0 else 1.0

    for node_id, times in by_node.items():
        times = sorted(times)
        earliest = times[0]
        n_windows = max(1, int((now - earliest) // win_sec))
        window_counts = []
        for w in range(n_windows):
            w_start = earliest + w * win_sec
            w_end = w_start + win_sec
            c = sum(1 for t in times if w_start <= t < w_end)
            window_counts.append(c)

        current_window_start = now - win_sec
        current_count = sum(1 for t in times if t >= current_window_start)
        prior_counts = window_counts[:-1] if len(window_counts) > 1 else []
        if len(prior_counts) >= 2:
            baseline = _ewma_baseline(prior_counts)
        else:
            # cold start: don't use this node's own (possibly spiking) count
            # to set its own bar -- use the course-wide average instead.
            baseline = course_fallback_baseline

        if current_count < MIN_WINDOW_COUNT:
            continue

        p = _poisson_upper_tail_p(current_count, baseline)
        if p < ALPHA and node_id not in suppressed_nodes:
            prev_window_count = window_counts[-2] if len(window_counts) >= 2 else baseline
            if current_count > prev_window_count * 1.05:
                trend = "climbing"
            elif current_count < prev_window_count * 0.95:
                trend = "plateauing"
            else:
                trend = "plateauing"

            observed_rate = current_count / WINDOW_MIN
            baseline_rate = baseline / WINDOW_MIN
            excess_rate = max(0.0, observed_rate - baseline_rate)
            # if untreated, project this excess continuing for the rest of a
            # 50-min remaining session block vs a 5-min group intervention now
            remaining_session_min = 50.0
            node = next((n for n in node_rows if n["id"] == node_id), None)
            explain_min = node["mean_explain_minutes"] if node else 5.0
            projected_extra_1on1s = excess_rate * remaining_session_min
            time_saved = max(0.0, projected_extra_1on1s * explain_min - 5.0)

            confidence = round(1.0 - p, 3)
            with dbm.cursor(conn) as cur:
                cur.execute(
                    "INSERT INTO outbreak_alerts (course_id, taxonomy_node_id, fired_at, "
                    "confidence, trend, observed_rate, baseline_rate, estimated_minutes_saved, "
                    "status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')",
                    (course_id, node_id, dbm.now(), confidence, trend, round(observed_rate, 3),
                     round(baseline_rate, 3), round(time_saved, 1)),
                )
                alert_id = cur.lastrowid

            new_alerts.append({
                "alert_id": alert_id,
                "taxonomy_node_id": node_id,
                "node_name": node_names.get(node_id, f"node-{node_id}"),
                "confidence": confidence,
                "trend": trend,
                "observed_rate_per_min": round(observed_rate, 3),
                "baseline_rate_per_min": round(baseline_rate, 3),
                "estimated_minutes_saved": round(time_saved, 1),
                "recommendation": (
                    f"Pause 1-on-1s on '{node_names.get(node_id, node_id)}' and run a "
                    f"5-minute whole-room clarification -- projected to save ~{round(time_saved, 1)} "
                    f"TA-minutes over the rest of this session vs continuing 1-on-1."
                ),
            })

    return new_alerts


def dismiss_alert(conn, alert_id: int) -> None:
    with dbm.cursor(conn) as cur:
        cur.execute("UPDATE outbreak_alerts SET status = 'dismissed', dismissed_at = ? WHERE id = ?",
                    (dbm.now(), alert_id))
