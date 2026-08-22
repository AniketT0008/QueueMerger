"""End-to-end smoke test for QueueMerge. Run: python3 tests/smoke_test.py
Exercises every pipeline stage against an in-memory DB and asserts basic
invariants. Not a substitute for the eval harness (queuemerge/evaluate.py)
but catches integration breaks fast (no network/API key required).
"""
import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from queuemerge.pipeline import QueueMerge  # noqa: E402
from queuemerge import db as dbm, taxonomy as tax, extraction, outbreak  # noqa: E402
from queuemerge import llm_client as lc  # noqa: E402


def test_intake_and_clustering_merges_confusable_wording():
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=False)
    qm.submit_question("Ava", "why is my loop off by one, it prints an extra blank line",
                        "for i in range(len(arr)+1):\n    print(arr[i])")
    qm.submit_question("Liam", "why does my array print an extra blank line at the end",
                        "for i in range(len(a)+1):\n    print(a[i])")
    qm.submit_question("Noah", "my function never processes the last element",
                        "for i in range(len(arr)-1):\n    process(arr[i])")

    recs = qm.recommendations()
    assert len(recs) >= 2, "expected at least 2 clusters (inclusive-boundary vs missing-last)"
    sizes = sorted(r["cluster"]["size"] for r in recs)
    assert 2 in sizes, "Ava+Liam (same root cause, different wording) should merge into one cluster"

    for r in recs:
        assert r["supm"] > 0
        assert set(r["inputs"].keys()) == {
            "cluster_size", "avg_clustering_confidence", "expected_students_unblocked",
            "node_mean_explain_minutes", "group_overhead_minutes", "expected_ta_minutes",
        }
    print("PASS: intake_and_clustering_merges_confusable_wording")


def test_supm_ranking_transparent_and_ordered():
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=False)
    for i in range(4):
        qm.submit_question(f"S{i}", "i made a copy of my list but changing one changes both",
                            "a=[1,2]\nb=a\nb.append(3)")
    qm.submit_question("Solo", "my average calculation is always giving me 0",
                        "avg = total // n")
    recs = qm.recommendations()
    assert recs == sorted(recs, key=lambda r: -r["supm"]), "recommendations must be SUPM-descending"
    print("PASS: supm_ranking_transparent_and_ordered")


def test_simulation_returns_ranked_comparison():
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=False)
    for i in range(5):
        qm.submit_question(f"S{i}", "my recursive function crashes with a recursion error",
                            "def f(n): return n*f(n-1)",
                            "RecursionError: maximum recursion depth exceeded")
    qm.submit_question("Lone", "my average calculation is always giving me 0", "avg = total // n")
    results = qm.simulate(trials=25, horizon_min=15.0)
    assert len(results) >= 1
    for r in results:
        assert r["mean_students_unblocked"] >= 0
        assert r["mean_clear_minutes"] >= 0
    print("PASS: simulation_returns_ranked_comparison")


def test_feedback_loop_updates_node_estimates():
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=False)
    qm.submit_question("S1", "i made a copy of my list but changing one changes both",
                        "a=[1,2]\nb=a\nb.append(3)")
    before = [n for n in qm.taxonomy_nodes() if n["name"] == "reference-vs-copy"][0]
    recs = qm.recommendations()
    qm.resolve_cluster(recs[0]["cluster"]["cluster_id"], minutes_spent=7.0)
    after = [n for n in qm.taxonomy_nodes() if n["name"] == "reference-vs-copy"][0]
    assert after["mean_explain_minutes"] != before["mean_explain_minutes"]
    assert after["explain_minutes_n"] == before["explain_minutes_n"] + 1
    print("PASS: feedback_loop_updates_node_estimates")


def test_bootstrap_creates_pending_node_for_unmatched_question():
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=False)
    qm.submit_question("Weird", "my quantum flux capacitor renders the wrong hologram color")
    pending = qm.pending_bootstrap_nodes()
    assert len(pending) >= 1, "an unmatched question should bootstrap a new pending node"
    qm.approve_node(pending[0]["id"], new_name="quantum-flux-thing")
    assert not qm.pending_bootstrap_nodes()
    print("PASS: bootstrap_creates_pending_node_for_unmatched_question")


def test_outbreak_detection_fires_on_real_spike():
    conn = dbm.connect()
    course_id = tax.get_or_create_course(conn, "OutbreakSmoke")
    tax.seed_default_taxonomy(conn, course_id)
    base_t = 1_000_000.0
    for i in range(14):
        extraction.intake_question(
            conn, course_id, f"S{i}", "my recursive function crashes with a recursion error",
            "def f(n): return n*f(n-1)", "RecursionError: maximum recursion depth exceeded",
            prefer_gemini=False, created_at=base_t + i * 30,
        )
    alerts = outbreak.check_outbreaks(conn, course_id)
    assert len(alerts) == 1
    assert alerts[0]["node_name"] == "recursion-missing-base-case"
    assert alerts[0]["confidence"] > 0.9
    print("PASS: outbreak_detection_fires_on_real_spike")


def test_outbreak_alert_persists_across_renders_and_dismiss_has_cooldown():
    """Regression test for a real bug found via UI testing: a naive banner
    that only shows check_outbreaks()'s return value (newly-fired alerts)
    flashes once then vanishes even though the outbreak is still open, and
    a naive dismiss lets the same still-elevated rate instantly re-fire a
    new alert. open_outbreak_alerts() must show it persistently; dismissal
    must be respected for a cooldown window."""
    conn = dbm.connect()
    course_id = tax.get_or_create_course(conn, "OutbreakPersistSmoke")
    tax.seed_default_taxonomy(conn, course_id)
    base_t = 2_000_000.0
    for i in range(14):
        extraction.intake_question(
            conn, course_id, f"S{i}", "my recursive function crashes with a recursion error",
            "def f(n): return n*f(n-1)", "RecursionError: maximum recursion depth exceeded",
            prefer_gemini=False, created_at=base_t + i * 5,
        )
    first = outbreak.check_outbreaks(conn, course_id)
    assert len(first) == 1

    second_scan = outbreak.check_outbreaks(conn, course_id)
    assert second_scan == [], "must not re-fire a duplicate alert for an already-open node"

    with dbm.cursor(conn) as cur:
        open_rows = cur.execute(
            "SELECT * FROM outbreak_alerts WHERE course_id = ? AND status = 'open'", (course_id,)
        ).fetchall()
    assert len(open_rows) == 1, "the alert must remain visible via the open-alerts view"

    outbreak.dismiss_alert(conn, open_rows[0]["id"])
    immediate_rescan = outbreak.check_outbreaks(conn, course_id)
    assert immediate_rescan == [], "dismissing must not let the same condition instantly re-fire"
    print("PASS: outbreak_alert_persists_across_renders_and_dismiss_has_cooldown")


def test_empty_queue_does_not_crash():
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=False)
    assert qm.recommendations() == []
    assert qm.longest_waiting_single() is None
    assert qm.simulate(trials=10) == []
    assert qm.check_outbreaks() == []
    assert qm.open_outbreak_alerts() == []
    print("PASS: empty_queue_does_not_crash")


def test_cluster_ids_stable_across_pure_rerender():
    """Regression test for a real bug found via UI testing: recommendations()
    used to rebuild clusters (assigning new DB row ids) on every call, which
    meant a Streamlit rerun with no actual mutation (e.g. clicking Simulate)
    silently broke every button's key before the click could be processed.
    cluster_id must stay stable across repeated recommendations() calls as
    long as nothing mutates the queue in between."""
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=False)
    qm.submit_question("S1", "i keep getting index out of range", "x = data[len(data)]",
                        "IndexError: list index out of range")
    ids_1 = [r["cluster"]["cluster_id"] for r in qm.recommendations()]
    ids_2 = [r["cluster"]["cluster_id"] for r in qm.recommendations()]
    ids_3 = [r["cluster"]["cluster_id"] for r in qm.recommendations()]
    assert ids_1 == ids_2 == ids_3, "cluster_id must not churn across non-mutating re-renders"
    print("PASS: cluster_ids_stable_across_pure_rerender")


def test_gemini_extractor_missing_key_raises_and_pipeline_falls_back():
    import os
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GEMINI_API_KEYS", None)
    from queuemerge.llm_client import GeminiExtractor
    try:
        GeminiExtractor()
        raise AssertionError("expected RuntimeError with no API key set")
    except RuntimeError:
        pass
    # pipeline itself must still work end-to-end with prefer_gemini=True
    # and no key configured (falls back to heuristic per-question).
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=True)
    qid = qm.submit_question("Fallback", "i keep getting index out of range",
                              "x = data[len(data)]", "IndexError: list index out of range")
    assert qid is not None
    recs = qm.recommendations()
    assert len(recs) >= 1
    print("PASS: gemini_extractor_missing_key_raises_and_pipeline_falls_back")


def test_pending_bootstrap_node_cannot_cannibalize_real_match():
    """Regression test for a real bug: a pending (unapproved) bootstrapped
    taxonomy node's auto-generated keywords come straight from one
    off-taxonomy question's own words (e.g. "list", "always", "seems") --
    a short, generic list like that has a much smaller score-normalization
    denominator than a curated node's longer, specific keyword list, so a
    couple of coincidental common-word hits could previously outscore a
    real match against a properly curated node entirely. Concretely: a
    genuine "recursion missing base case" question (which legitimately
    matches the curated node on the literal phrase "base case") was being
    misclassified into an unrelated pending bootstrap node just because it
    also happened to contain "always" and "seems". Fixed by discounting
    match weight for is_bootstrapped-and-not-yet-approved nodes
    (llm_client.HeuristicExtractor.BOOTSTRAP_PENDING_WEIGHT_DISCOUNT) so
    they can't outrank approved/curated nodes; this also measurably
    improved end-to-end extraction accuracy on the eval harness's
    synthetic session from 82.5% to 90% (see eval_report/report.md)."""
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=False)

    # Force a pending bootstrap node with short, generic auto-keywords.
    qm.submit_question(
        "Off1", "my list always seems to be doing something weird with zero values",
        "weird = []", None,
    )
    pending = qm.pending_bootstrap_nodes()
    assert len(pending) == 1, "expected exactly one pending bootstrap node"

    # A genuine recursion-missing-base-case question that happens to share
    # two generic words ("always", "seems") with the bootstrap node above,
    # but legitimately matches the curated node on "base case".
    qid = qm.submit_question(
        "Real1",
        "im not sure why my function always seems to keep going, "
        "i think i forgot the base case",
    )
    with dbm.cursor(qm.conn) as cur:
        row = cur.execute(
            "SELECT taxonomy_node_id FROM questions WHERE id = ?", (qid,)
        ).fetchone()
    node = tax.get_node(qm.conn, row["taxonomy_node_id"])
    assert node["name"] == "recursion-missing-base-case", (
        f"expected the curated 'recursion-missing-base-case' node, got "
        f"'{node['name']}' (bootstrapped={bool(node['is_bootstrapped'])}) -- "
        f"pending bootstrap node cannibalized a real match"
    )
    print("PASS: pending_bootstrap_node_cannot_cannibalize_real_match")


def test_explanation_memory_resurfaces_across_later_cluster_and_restart():
    """A teaching note must survive the transient cluster that created it.
    This is the core novelty of Explanation Memory: notes attach to the
    misconception node, so a later cluster for the same root cause can reuse
    them. Persisting the SQLite DB also carries them across app restarts.
    """
    fd, path = tempfile.mkstemp(prefix="queuemerge-memory-", suffix=".sqlite3")
    os.close(fd)
    try:
        qm = QueueMerge(db_path=path, course_name="MemorySmoke", seed_taxonomy=True,
                        prefer_gemini=False)
        qm.submit_question(
            "First",
            "why is my loop off by one and printing one extra item",
            "for i in range(len(arr)+1): print(arr[i])",
        )
        first_cluster = qm.recommendations()[0]["cluster"]["cluster_id"]
        note_id = qm.add_explanation_note(
            first_cluster,
            "Draw indices 0..n-1 first, then contrast len(arr) with the final valid index.",
        )
        assert qm.upvote_explanation_note(note_id) == 1
        assert qm.upvote_explanation_note(note_id) == 2
        qm.resolve_cluster(first_cluster, minutes_spent=4.0)
        qm.conn.close()

        # New QueueMerge object, same on-disk course DB: simulates a later app
        # run/semester with a brand-new cluster row for the same misconception.
        qm2 = QueueMerge(db_path=path, course_name="MemorySmoke", seed_taxonomy=True,
                         prefer_gemini=False)
        qm2.submit_question(
            "Later",
            "my array prints one extra line at the end",
            "for i in range(len(a)+1): print(a[i])",
        )
        later_cluster = qm2.recommendations()[0]["cluster"]["cluster_id"]
        assert later_cluster != first_cluster
        notes = qm2.explanation_memory(later_cluster)
        assert len(notes) == 1
        assert notes[0]["id"] == note_id
        assert notes[0]["upvotes"] == 2
        assert "0..n-1" in notes[0]["note_text"]
        qm2.conn.close()
    finally:
        if os.path.exists(path):
            os.remove(path)
    print("PASS: explanation_memory_resurfaces_across_later_cluster_and_restart")


def test_gemini_key_loading_supports_single_and_multi_env_forms():
    """GEMINI_API_KEYS (comma-separated) and GEMINI_API_KEY (singular) can
    each be set alone, or together -- in which case GEMINI_API_KEYS entries
    come first and GEMINI_API_KEY is appended only if it's a new key, so
    existing single-key setups keep working unchanged when someone adds a
    second key later."""
    saved = os.environ.get("GEMINI_API_KEY"), os.environ.get("GEMINI_API_KEYS")
    try:
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GEMINI_API_KEYS", None)
        assert lc._load_gemini_keys() == []

        os.environ["GEMINI_API_KEYS"] = "k1, k2 ,k3"
        assert lc._load_gemini_keys() == ["k1", "k2", "k3"]

        os.environ.pop("GEMINI_API_KEYS")
        os.environ["GEMINI_API_KEY"] = "solo"
        assert lc._load_gemini_keys() == ["solo"]

        os.environ["GEMINI_API_KEYS"] = "k1,k2"
        os.environ["GEMINI_API_KEY"] = "k1"  # duplicate -> deduped
        assert lc._load_gemini_keys() == ["k1", "k2"]

        os.environ["GEMINI_API_KEY"] = "k3"  # unique -> appended
        assert lc._load_gemini_keys() == ["k1", "k2", "k3"]
    finally:
        for name, val in zip(("GEMINI_API_KEY", "GEMINI_API_KEYS"), saved):
            if val is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = val
    print("PASS: gemini_key_loading_supports_single_and_multi_env_forms")


def _fake_gemini_response(node_id=1):
    class R:
        text = json.dumps({"node_id": node_id, "confidence": 0.9,
                            "matched_cues": [], "sub_step": "x"})
    return R()


def test_gemini_extractor_round_robins_across_configured_keys():
    """Successful calls should rotate through every configured key in
    order rather than always hitting the first one -- this is what
    actually spreads request volume (and therefore free-tier quota use)
    across multiple keys, not just failover."""
    ext = lc.GeminiExtractor(api_key="placeholder")
    ext.keys = ["A", "B", "C"]
    ext._next_index = 0
    used_keys = []

    class FakeModel:
        def __init__(self, *a, **kw):
            pass

        def generate_content(self, *a, **kw):
            return _fake_gemini_response()

    with mock.patch("google.generativeai.configure",
                     side_effect=lambda api_key: used_keys.append(api_key)), \
         mock.patch("google.generativeai.GenerativeModel", FakeModel):
        for _ in range(6):
            ext.extract("q", None, None, [{"id": 1, "name": "n", "description": "d"}])

    assert used_keys == ["A", "B", "C", "A", "B", "C"], used_keys
    print("PASS: gemini_extractor_round_robins_across_configured_keys")


def test_gemini_extractor_fails_over_to_next_key_on_rate_limit():
    """A rate-limit/quota-shaped failure on one key should transparently
    retry the same request on the next configured key, rather than
    immediately falling all the way back to the heuristic extractor."""
    ext = lc.GeminiExtractor(api_key="placeholder")
    ext.keys = ["A", "B", "C"]
    ext._next_index = 0
    call_log = []

    class FlakyModel:
        def __init__(self, *a, **kw):
            pass

        def generate_content(self, *a, **kw):
            if call_log[-1] in ("A", "B"):
                raise Exception("429 Resource has been exhausted (check quota).")
            return _fake_gemini_response()

    with mock.patch("google.generativeai.configure",
                     side_effect=lambda api_key: call_log.append(api_key)), \
         mock.patch("google.generativeai.GenerativeModel", FlakyModel):
        result = ext.extract("q", None, None, [{"id": 1, "name": "n", "description": "d"}])

    assert call_log == ["A", "B", "C"], call_log
    assert result["node_id"] == 1
    print("PASS: gemini_extractor_fails_over_to_next_key_on_rate_limit")


def test_gemini_extractor_raises_after_every_key_exhausted():
    """If every configured key is rate-limited, the extractor should raise
    (not silently return junk) so extraction.py's fallback chain can hand
    off to the heuristic extractor for that question."""
    ext = lc.GeminiExtractor(api_key="placeholder")
    ext.keys = ["A", "B"]
    ext._next_index = 0

    class AllFailModel:
        def __init__(self, *a, **kw):
            pass

        def generate_content(self, *a, **kw):
            raise Exception("429 quota exceeded")

    raised = False
    with mock.patch("google.generativeai.configure"), \
         mock.patch("google.generativeai.GenerativeModel", AllFailModel):
        try:
            ext.extract("q", None, None, [{"id": 1, "name": "n", "description": "d"}])
        except Exception as e:
            raised = True
            assert "quota" in str(e).lower()
    assert raised
    print("PASS: gemini_extractor_raises_after_every_key_exhausted")


def test_gemini_extractor_non_key_error_does_not_burn_every_key():
    """A malformed-response error isn't key-related -- every key would hit
    it identically, so the extractor should raise immediately on the first
    key rather than wastefully retrying the same broken response on every
    configured key."""
    ext = lc.GeminiExtractor(api_key="placeholder")
    ext.keys = ["A", "B", "C"]
    ext._next_index = 0
    attempts = []

    class BadJSONModel:
        def __init__(self, *a, **kw):
            pass

        def generate_content(self, *a, **kw):
            attempts.append(1)

            class R:
                text = "not json at all {{{"
            return R()

    raised = False
    with mock.patch("google.generativeai.configure"), \
         mock.patch("google.generativeai.GenerativeModel", BadJSONModel):
        try:
            ext.extract("q", None, None, [{"id": 1, "name": "n", "description": "d"}])
        except Exception:
            raised = True
    assert raised
    assert len(attempts) == 1, f"expected 1 attempt, got {len(attempts)}"
    print("PASS: gemini_extractor_non_key_error_does_not_burn_every_key")


def test_empty_question_text_is_rejected():
    qm = QueueMerge(seed_taxonomy=True, prefer_gemini=False)
    try:
        qm.submit_question("Nobody", "   ")
        raise AssertionError("expected ValueError for blank question text")
    except ValueError:
        pass
    try:
        qm.submit_question("", "why index error")
        raise AssertionError("expected ValueError for blank student name")
    except ValueError:
        pass
    assert qm.recommendations() == []
    print("PASS: empty_question_text_is_rejected")


def test_fintech_preset_seeds_correctly():
    qm = QueueMerge(taxonomy_preset="fintech", prefer_gemini=False)
    names = {n["name"] for n in qm.taxonomy_nodes()}
    expected = {
        "duplicate-charge", "unexplained-fee", "stuck-transfer", "stale-account-sync",
        "false-fraud-decline", "mfa-lockout", "unauthorized-ach-pull", "card-network-timeout",
    }
    assert names == expected, names
    # CS101 nodes must not appear in a fintech course
    assert "loop-boundary-inclusive" not in names
    # Default / omitted preset still CS101
    qm_cs = QueueMerge(prefer_gemini=False)
    assert qm_cs.taxonomy_preset == "cs101"
    assert any(n["name"] == "loop-boundary-inclusive" for n in qm_cs.taxonomy_nodes())
    print("PASS: fintech_preset_seeds_correctly")


def test_fintech_intake_cluster_supm_simulate_e2e():
    qm = QueueMerge(taxonomy_preset="fintech", prefer_gemini=False)
    samples = [
        ("Priya", "I was charged twice for the same checkout — two identical charges on my statement"),
        ("Jordan", "merchant billed me twice for one order, same amount twice"),
        ("Sam", "there's a mystery fee on my statement I never authorized — what is this fee?"),
        ("Riley", "I sent an ACH but the transfer is still pending and the destination never credited"),
        ("Casey", "my app shows a stale balance and transactions are not showing after refresh"),
        ("Morgan", "my card declined for fraud on a purchase I definitely authorized"),
    ]
    for name, text in samples:
        qm.submit_question(name, text, prefer_gemini=False)
    recs = qm.recommendations()
    assert len(recs) >= 3, f"expected several fintech clusters, got {len(recs)}"
    assert recs == sorted(recs, key=lambda r: -r["supm"])
    assert all(r["supm"] > 0 for r in recs)
    sim = qm.simulate(top_n_clusters=3, trials=20, horizon_min=15.0)
    assert len(sim) >= 1
    assert sim[0]["mean_students_unblocked"] >= 0
    print("PASS: fintech_intake_cluster_supm_simulate_e2e")


def test_fintech_confusable_pairs_do_not_conflate():
    """duplicate-charge vs unexplained-fee share charge/statement vocabulary;
    stuck-transfer vs stale-account-sync share pending/balance vocabulary.
    Same-wording-family questions on DIFFERENT root causes must stay apart;
    same-cause differently-worded questions must merge."""
    qm = QueueMerge(taxonomy_preset="fintech", prefer_gemini=False)
    qm.submit_question(
        "A", "I was charged twice — two identical charges posted twice on my statement",
        prefer_gemini=False,
    )
    qm.submit_question(
        "B", "merchant billed me twice, duplicate transaction same amount twice",
        prefer_gemini=False,
    )
    qm.submit_question(
        "C", "mystery fee / unexplained fee on my statement I never authorized",
        prefer_gemini=False,
    )
    qm.submit_question(
        "D", "ACH stuck transfer still pending, destination never credited, funds left my account",
        prefer_gemini=False,
    )
    qm.submit_question(
        "E", "stale balance, account not syncing, transactions not showing after refresh",
        prefer_gemini=False,
    )

    # Map each question to its extracted node via DB
    with dbm.cursor(qm.conn) as cur:
        rows = cur.execute(
            "SELECT s.name AS student_name, q.taxonomy_node_id "
            "FROM questions q JOIN students s ON s.id = q.student_id ORDER BY q.id"
        ).fetchall()
    by_student = {}
    for r in rows:
        node = tax.get_node(qm.conn, r["taxonomy_node_id"])
        by_student[r["student_name"]] = node["name"]

    assert by_student["A"] == "duplicate-charge", by_student
    assert by_student["B"] == "duplicate-charge", by_student
    assert by_student["C"] == "unexplained-fee", by_student
    assert by_student["D"] == "stuck-transfer", by_student
    assert by_student["E"] == "stale-account-sync", by_student
    assert by_student["A"] != by_student["C"], "confusable charge pair must not collapse"
    assert by_student["D"] != by_student["E"], "confusable pending/balance pair must not collapse"

    # Clustering: A+B same cluster size contribution; C separate
    recs = qm.recommendations()
    node_sizes = {}
    for r in recs:
        # explanation usually mentions the node; safer to look up via questions in cluster
        cid = r["cluster"]["cluster_id"]
        with dbm.cursor(qm.conn) as cur:
            qrows = cur.execute(
                "SELECT taxonomy_node_id FROM questions WHERE cluster_id = ?", (cid,)
            ).fetchall()
        if not qrows:
            # cluster membership via rebuild stores differently — use size + node from first question
            continue
        nname = tax.get_node(qm.conn, qrows[0]["taxonomy_node_id"])["name"]
        node_sizes[nname] = r["cluster"]["size"]
    # At least verify recommendations include a size-2 group (A+B) and singles
    sizes = sorted(r["cluster"]["size"] for r in recs)
    assert 2 in sizes, f"A+B should merge; sizes={sizes} assignments={by_student}"
    print("PASS: fintech_confusable_pairs_do_not_conflate")


def test_fintech_explanation_memory_scoped_to_preset_course():
    """Notes attach to (course_id, taxonomy_node_id). CS101 and Fintech use
    different courses, so a fintech note must not appear under CS101 (and
    vice versa) even if node *names* coincidentally overlapped someday."""
    fd, path = tempfile.mkstemp(prefix="queuemerge-preset-mem-", suffix=".sqlite3")
    os.close(fd)
    try:
        ft = QueueMerge(db_path=path, taxonomy_preset="fintech", prefer_gemini=False)
        ft.submit_question(
            "Priya", "charged twice — two identical charges on my statement",
            prefer_gemini=False,
        )
        ft_cluster = ft.recommendations()[0]["cluster"]["cluster_id"]
        note_id = ft.add_explanation_note(
            ft_cluster, "Ask for merchant descriptor + auth code; check twin settlement."
        )
        ft_course = ft.course_id
        with dbm.cursor(ft.conn) as cur:
            row = cur.execute(
                "SELECT taxonomy_node_id FROM clusters WHERE id = ?", (ft_cluster,)
            ).fetchone()
        ft_node_id = row["taxonomy_node_id"]
        ft.conn.close()

        cs = QueueMerge(db_path=path, taxonomy_preset="cs101", prefer_gemini=False)
        assert cs.course_id != ft_course
        cs.submit_question(
            "Ava", "why is my loop off by one, prints an extra blank line",
            "for i in range(len(arr)+1): print(arr[i])", prefer_gemini=False,
        )
        cs_cluster = cs.recommendations()[0]["cluster"]["cluster_id"]
        notes = cs.explanation_memory(cs_cluster)
        assert notes == [], "CS101 cluster must not see fintech Explanation Memory notes"

        ft2 = QueueMerge(db_path=path, taxonomy_preset="fintech", prefer_gemini=False)
        assert ft2.course_id == ft_course
        ft2.submit_question(
            "Jordan", "merchant billed me twice, duplicate charge same amount twice",
            prefer_gemini=False,
        )
        later = ft2.recommendations()[0]["cluster"]["cluster_id"]
        notes2 = ft2.explanation_memory(later)
        assert any(n["id"] == note_id for n in notes2), notes2
        with dbm.cursor(ft2.conn) as cur:
            n1 = cur.execute(
                "SELECT id FROM taxonomy_nodes WHERE course_id = ? AND name = ?",
                (ft_course, "duplicate-charge"),
            ).fetchone()["id"]
        assert n1 == ft_node_id
        ft2.conn.close()
        cs.conn.close()
    finally:
        if os.path.exists(path):
            os.remove(path)
    print("PASS: fintech_explanation_memory_scoped_to_preset_course")


def test_fintech_pending_bootstrap_cannot_cannibalize_curated_match():
    """Longer fintech keyword lists must not lose to a short pending bootstrap
    node's generic single-word cues (account/charge/pending) — same failure
    mode as the CS101 regression, on the denser taxonomy."""
    qm = QueueMerge(taxonomy_preset="fintech", prefer_gemini=False)
    qm.submit_question(
        "Off1",
        "my account charge pending always seems weird with zero values",
        prefer_gemini=False,
    )
    pending = qm.pending_bootstrap_nodes()
    assert len(pending) >= 1, "expected a bootstrap from the off-taxonomy ticket"

    qid = qm.submit_question(
        "Real1",
        "I was charged twice for the same checkout — two identical charges posted twice",
        prefer_gemini=False,
    )
    with dbm.cursor(qm.conn) as cur:
        row = cur.execute(
            "SELECT taxonomy_node_id FROM questions WHERE id = ?", (qid,)
        ).fetchone()
    node = tax.get_node(qm.conn, row["taxonomy_node_id"])
    assert node["name"] == "duplicate-charge", (
        f"expected curated duplicate-charge, got {node['name']} "
        f"(bootstrapped={bool(node['is_bootstrapped'])})"
    )
    print("PASS: fintech_pending_bootstrap_cannot_cannibalize_curated_match")


def test_optional_integrations_noop_without_keys():
    """Sponsor hooks must stay silent when env vars are unset so judges can
    run the core demo with zero configuration."""
    from queuemerge import integrations as integ
    saved = {k: os.environ.get(k) for k in (
        "ELEVENLABS_API_KEY", "OUTBREAK_WEBHOOK_URL", "WORLD_LABS_PROXY_URL",
        "WORLD_LABS_API_KEY", "WLT_API_KEY",
    )}
    try:
        for k in saved:
            os.environ.pop(k, None)
        assert integ.elevenlabs_configured() is False
        assert integ.outbreak_webhook_configured() is False
        assert integ.worldlabs_proxy_configured() is False
        assert integ.worldlabs_direct_configured() is False
        assert integ.worldlabs_configured() is False
        assert integ.synthesize_briefing("hello") is None
        assert integ.notify_outbreaks([{"node_name": "x", "confidence": 0.9}]) == 0
        assert integ.request_worldlabs_world("duplicate-charge") is None
        brief = integ.triage_briefing_text(
            {"size": 2, "explanation": "duplicate charge", "oldest_wait_seconds": 600},
            preset="fintech",
        )
        assert "customers" in brief and "duplicate charge" in brief
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("PASS: optional_integrations_noop_without_keys")


if __name__ == "__main__":
    test_intake_and_clustering_merges_confusable_wording()
    test_supm_ranking_transparent_and_ordered()
    test_simulation_returns_ranked_comparison()
    test_feedback_loop_updates_node_estimates()
    test_bootstrap_creates_pending_node_for_unmatched_question()
    test_outbreak_detection_fires_on_real_spike()
    test_outbreak_alert_persists_across_renders_and_dismiss_has_cooldown()
    test_empty_queue_does_not_crash()
    test_cluster_ids_stable_across_pure_rerender()
    test_gemini_extractor_missing_key_raises_and_pipeline_falls_back()
    test_pending_bootstrap_node_cannot_cannibalize_real_match()
    test_explanation_memory_resurfaces_across_later_cluster_and_restart()
    test_gemini_key_loading_supports_single_and_multi_env_forms()
    test_gemini_extractor_round_robins_across_configured_keys()
    test_gemini_extractor_fails_over_to_next_key_on_rate_limit()
    test_gemini_extractor_raises_after_every_key_exhausted()
    test_gemini_extractor_non_key_error_does_not_burn_every_key()
    test_empty_question_text_is_rejected()
    test_fintech_preset_seeds_correctly()
    test_fintech_intake_cluster_supm_simulate_e2e()
    test_fintech_confusable_pairs_do_not_conflate()
    test_fintech_explanation_memory_scoped_to_preset_course()
    test_fintech_pending_bootstrap_cannot_cannibalize_curated_match()
    test_optional_integrations_noop_without_keys()
    print("\nALL 24 SMOKE TESTS PASSED")
