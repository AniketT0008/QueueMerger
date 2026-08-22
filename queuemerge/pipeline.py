"""QueueMerge orchestrator. This is the single entry point the Streamlit UI
and the evaluation harness both use, so pipeline behavior can't drift
between "what the TA sees" and "what gets measured".
"""
from queuemerge import db as dbm
from queuemerge import taxonomy as tax
from queuemerge import extraction
from queuemerge import clustering
from queuemerge import supm as supm_mod
from queuemerge import simulation
from queuemerge import outbreak
from queuemerge import feedback
from queuemerge import memory


class QueueMerge:
    def __init__(self, db_path: str = ":memory:", course_name: str = None,
                 seed_taxonomy: bool = True, prefer_gemini: bool = True,
                 taxonomy_preset: str = "cs101"):
        self.conn = dbm.connect(db_path)
        self.prefer_gemini = prefer_gemini
        self.taxonomy_preset = tax.normalize_preset(taxonomy_preset)
        if course_name is None:
            course_name = tax.PRESET_COURSE_NAMES.get(
                self.taxonomy_preset, f"{self.taxonomy_preset} Demo"
            )
        self.course_name = course_name
        self.course_id = tax.get_or_create_course(self.conn, course_name)
        if seed_taxonomy and not tax.has_taxonomy(self.conn, self.course_id):
            tax.seed_taxonomy(self.conn, self.course_id, preset=self.taxonomy_preset)

    # ---- intake -----------------------------------------------------
    def submit_question(self, student_name: str, text: str, code: str = None,
                         error: str = None, created_at: float = None,
                         prefer_gemini: bool = None) -> int:
        if not (student_name or "").strip():
            raise ValueError("student_name is required")
        if not (text or "").strip():
            raise ValueError("question text is required")
        use_gemini = self.prefer_gemini if prefer_gemini is None else prefer_gemini
        qid = extraction.intake_question(
            self.conn, self.course_id, student_name.strip(), text.strip(), code, error,
            prefer_gemini=use_gemini, created_at=created_at,
        )
        self.refresh_clusters()  # keep the queue view current for the next render
        return qid

    # ---- clustering + recommendations --------------------------------
    def refresh_clusters(self) -> list:
        return clustering.rebuild_clusters(self.conn, self.course_id)

    def recommendations(self, refresh: bool = False) -> list:
        """Ranked SUPM recommendations over the current active clusters.
        Does NOT rebuild clusters by default -- rebuilding assigns brand
        new DB row ids to every cluster, which breaks any UI widget keyed
        on a cluster_id across a rerun (e.g. a 'Simulate' button click
        would silently do nothing, since its key would no longer match
        any rendered button after the rebuild). Callers that mutate the
        queue (submit_question, resolve_cluster, mark_misclustered) already
        call refresh_clusters() themselves when the queue actually
        changes; pass refresh=True only if you explicitly need a rebuild
        (e.g. after externally inserting questions, as the eval harness does)."""
        if refresh:
            self.refresh_clusters()
        clusters = clustering.get_active_clusters(self.conn, self.course_id)
        return supm_mod.rank_recommendations(self.conn, self.course_id, clusters)

    def longest_waiting_single(self) -> dict:
        with dbm.cursor(self.conn) as cur:
            row = cur.execute(
                "SELECT * FROM questions WHERE course_id = ? AND status = 'waiting' "
                "ORDER BY created_at ASC LIMIT 1", (self.course_id,)
            ).fetchone()
        return dict(row) if row else None

    # ---- simulation ---------------------------------------------------
    def simulate(self, top_n_clusters: int = 3, trials: int = 150,
                 horizon_min: float = 20.0) -> list:
        ranked = self.recommendations()
        top_clusters = [r["cluster"] for r in ranked[:top_n_clusters]]
        single = self.longest_waiting_single()
        return simulation.compare_choices(
            self.conn, self.course_id, top_clusters, single,
            horizon_min=horizon_min, trials=trials,
        )

    # ---- outbreak monitor ----------------------------------------------
    def check_outbreaks(self) -> list:
        """Runs the detector; returns only NEWLY-fired alerts this call
        (background-job semantics, to avoid re-firing on every scan). For
        a persistent UI banner showing everything currently open, use
        open_outbreak_alerts() instead -- see its docstring for why these
        are separate methods."""
        new_alerts = outbreak.check_outbreaks(self.conn, self.course_id)
        if new_alerts:
            try:
                from queuemerge import integrations
                # Enrich with names for webhook payload
                named = []
                for a in new_alerts:
                    item = dict(a)
                    node = tax.get_node(self.conn, a["taxonomy_node_id"])
                    if node:
                        item["node_name"] = node["name"]
                    named.append(item)
                integrations.notify_outbreaks(
                    named,
                    course_name=self.course_name,
                    preset=self.taxonomy_preset,
                )
            except Exception:
                pass
        return new_alerts

    def open_outbreak_alerts(self) -> list:
        """All currently-open alerts for this course, regardless of when
        they fired. A UI banner should call THIS for display (after also
        calling check_outbreaks() once per render to pick up new ones) --
        using check_outbreaks()'s return value alone for a banner is a bug:
        it would flash once on the render where the alert first fires and
        then silently disappear on every subsequent render, even though
        the outbreak is still open, because check_outbreaks() correctly
        doesn't re-report alerts it already recorded."""
        with dbm.cursor(self.conn) as cur:
            rows = cur.execute(
                "SELECT oa.*, tn.name AS node_name FROM outbreak_alerts oa "
                "JOIN taxonomy_nodes tn ON tn.id = oa.taxonomy_node_id "
                "WHERE oa.course_id = ? AND oa.status = 'open' ORDER BY oa.fired_at DESC",
                (self.course_id,),
            ).fetchall()
        out = []
        for r in rows:
            r = dict(r)
            out.append({
                "alert_id": r["id"],
                "taxonomy_node_id": r["taxonomy_node_id"],
                "node_name": r["node_name"],
                "confidence": r["confidence"],
                "trend": r["trend"],
                "observed_rate_per_min": r["observed_rate"],
                "baseline_rate_per_min": r["baseline_rate"],
                "estimated_minutes_saved": r["estimated_minutes_saved"],
                "recommendation": (
                    f"Pause 1-on-1s on '{r['node_name']}' and run a 5-minute whole-room "
                    f"clarification -- projected to save ~{r['estimated_minutes_saved']} "
                    f"TA-minutes over the rest of this session vs continuing 1-on-1."
                ),
            })
        return out

    def dismiss_outbreak_alert(self, alert_id: int) -> None:
        outbreak.dismiss_alert(self.conn, alert_id)

    # ---- feedback loop --------------------------------------------------
    def resolve_cluster(self, cluster_id: int, minutes_spent: float,
                         label: str = "resolved") -> None:
        feedback.record_feedback(self.conn, cluster_id, label, minutes_spent)
        self.refresh_clusters()

    def mark_misclustered(self, cluster_id: int) -> None:
        feedback.record_feedback(self.conn, cluster_id, "misclustered")
        self.refresh_clusters()

    # ---- explanation memory ---------------------------------------------
    def explanation_memory(self, cluster_id: int, limit: int = 5) -> list:
        """Reusable past explanations for this cluster's misconception node."""
        return memory.notes_for_cluster(self.conn, cluster_id, limit=limit)

    def add_explanation_note(self, cluster_id: int, note_text: str) -> int:
        return memory.add_note(self.conn, cluster_id, note_text)

    def upvote_explanation_note(self, note_id: int) -> int:
        return memory.upvote_note(self.conn, note_id)

    # ---- taxonomy admin -------------------------------------------------
    def pending_bootstrap_nodes(self) -> list:
        return [n for n in tax.list_nodes(self.conn, self.course_id) if n["is_bootstrapped"] and not n["approved"]]

    def approve_node(self, node_id: int, new_name: str = None) -> None:
        tax.approve_node(self.conn, node_id, new_name)

    def taxonomy_nodes(self) -> list:
        return tax.list_nodes(self.conn, self.course_id)
