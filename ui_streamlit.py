"""QueueMerge TA-facing UI (Streamlit).

Run with:  streamlit run ui_streamlit.py
"""
import html
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
from queuemerge.pipeline import QueueMerge
from queuemerge import taxonomy as tax
from queuemerge import integrations as integ


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


st.set_page_config(
    page_title="QueueMerge",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    pass

try:
    for _name in (
        "GEMINI_API_KEYS", "GEMINI_API_KEY",
        "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID",
        "OUTBREAK_WEBHOOK_URL", "WORLD_LABS_PROXY_URL",
        "WORLD_LABS_API_KEY", "WLT_API_KEY", "WORLD_LABS_MODEL",
    ):
        if _name in st.secrets and st.secrets[_name]:
            os.environ.setdefault(_name, str(st.secrets[_name]))
except Exception:
    pass

st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap" rel="stylesheet">
    <style>
    :root {
        --board: #1E3A34;
        --board-deep: #16302c;
        --chalk: #F2EFE6;
        --stub-amber: #C47A12;
        --stub-face: #F7E7C4;
        --ink: #1C1917;
        --resolved: #2F6B3A;
        --wrong: #9B2C2C;
        --muted: #A8B5AF;
        --line: rgba(242, 239, 230, 0.18);
        --font-display: "Fraunces", Georgia, serif;
        --font-body: "Source Serif 4", Georgia, serif;
    }
    html, body, [data-testid="stAppViewContainer"] {
        background:
          radial-gradient(ellipse 70% 40% at 10% 0%, rgba(196, 122, 18, 0.16), transparent 55%),
          linear-gradient(180deg, #2a4a43 0%, var(--board) 32%, var(--board-deep) 100%) !important;
        color: var(--chalk);
        font-family: var(--font-body) !important;
    }
    [data-testid="stHeader"] { background: transparent !important; }
    [data-testid="stToolbar"] { right: 1rem; }
    .block-container { padding-top: 1.25rem !important; max-width: 1100px !important; }
    [data-testid="stSidebar"] {
        background: #18332e !important;
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] * { color: var(--chalk) !important; }
    [data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small {
        color: var(--muted) !important;
    }
    div[data-testid="stMarkdownContainer"] p,
    div[data-testid="stMarkdownContainer"] li { color: var(--chalk); }
    .stCaption, [data-testid="stCaptionContainer"] { color: var(--muted) !important; }
    label { color: var(--chalk) !important; }
    .stTextInput input, .stTextArea textarea, .stNumberInput input {
        background: rgba(242, 239, 230, 0.06) !important;
        color: var(--chalk) !important;
        border: 1px solid var(--line) !important;
        border-radius: 6px !important;
    }
    .stButton > button {
        border-radius: 4px !important;
        font-family: var(--font-body) !important;
        font-weight: 600 !important;
        border: 1.5px solid transparent !important;
    }
    .stButton > button[kind="primary"] {
        background: var(--stub-amber) !important;
        color: var(--ink) !important;
        border-color: #9a5f0c !important;
        box-shadow: 0 2px 0 #9a5f0c !important;
    }
    .stButton > button[kind="secondary"] {
        background: transparent !important;
        color: var(--chalk) !important;
        border: 1.5px dashed rgba(242, 239, 230, 0.45) !important;
    }
    div[data-testid="stExpander"] {
        background: rgba(242, 239, 230, 0.05);
        border: 1px solid var(--line);
        border-radius: 8px;
    }
    [data-testid="stStatusWidget"],
    [data-testid="stToolbar"],
    .stAppDeployButton,
    div[data-testid="stDecoration"] {
        display: none !important;
    }
    .qm-hero {
        margin: 0 0 18px;
        padding: 18px 20px 16px;
        border: 1.5px dashed rgba(242, 239, 230, 0.35);
        border-radius: 4px;
        background: rgba(0,0,0,0.12);
    }
    .qm-brand {
        margin: 0;
        font-family: var(--font-display);
        font-size: clamp(2rem, 4vw, 2.6rem);
        font-weight: 700;
        letter-spacing: -0.02em;
        color: var(--chalk);
        line-height: 1.15;
    }
    .qm-brand-mark {
        display: inline-block;
        margin-left: 12px;
        padding: 3px 10px;
        border: 1px dashed rgba(242, 239, 230, 0.45);
        font-family: var(--font-display);
        font-size: 13px;
        font-weight: 600;
        color: rgba(242, 239, 230, 0.9);
        transform: rotate(-2deg);
        vertical-align: middle;
        white-space: nowrap;
    }
    .qm-lede {
        color: var(--muted);
        font-size: 1.05rem;
        line-height: 1.5;
        max-width: 40rem;
        margin: 10px 0 0;
    }
    .qm-lede b { color: var(--chalk); font-weight: 600; }
    .qm-hooks {
        display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 0;
    }
    .qm-hook {
        font-size: 12px; font-weight: 600; letter-spacing: 0.02em;
        padding: 5px 10px; border-radius: 3px;
        border: 1px solid var(--line);
        color: var(--muted);
        background: rgba(0,0,0,0.15);
    }
    .qm-hook.on {
        color: var(--ink);
        background: var(--stub-face);
        border-color: var(--stub-amber);
    }
    .qm-steps { display:flex; flex-wrap:wrap; gap:8px; margin: 0 0 20px; }
    .qm-step {
        font-size: 13px; color: var(--chalk);
        background: rgba(242, 239, 230, 0.08);
        border: 1px solid var(--line);
        padding: 7px 12px; border-radius: 3px;
    }
    .qm-step b { color: var(--stub-face); }
    .qm-stat-row { display:flex; gap:10px; margin: 8px 0 16px; flex-wrap:wrap; }
    .qm-stat {
        flex:1; min-width:120px; border-radius: 4px; padding:12px 14px;
        background: rgba(242, 239, 230, 0.07);
        border: 1px solid var(--line);
    }
    .qm-stat .qm-stat-label { font-size:11px; color:var(--muted); margin:0 0 2px; letter-spacing:0.04em; text-transform:uppercase; }
    .qm-stat .qm-stat-value { font-family: var(--font-display); font-size:22px; font-weight:700; margin:0; color: var(--chalk); }
    .qm-alert {
        display:flex; align-items:flex-start; gap:10px; border-radius:4px;
        padding:12px 14px; background: rgba(155, 44, 44, 0.22);
        border: 1px solid rgba(240, 149, 149, 0.45);
        color: #F7C9C9; font-size:14px; margin-bottom:8px;
    }
    .qm-card {
        display:flex; gap:16px; align-items:stretch; border-radius: 3px;
        padding: 0; margin-bottom: 8px; overflow: hidden;
        background: var(--chalk);
        color: var(--ink);
        box-shadow: 0 10px 28px rgba(30, 58, 52, 0.22);
        border: 1px solid #d4cfc3;
    }
    .qm-card.qm-first { box-shadow: 0 12px 32px rgba(196, 122, 18, 0.28); border-color: var(--stub-amber); }
    .qm-ticket {
        flex-shrink:0; width: 78px; min-height: 88px;
        background: var(--stub-face);
        border-right: 2px dashed #c9a66a;
        color: var(--stub-amber);
        display:flex; flex-direction:column;
        align-items:center; justify-content:center; line-height:1;
        position: relative;
    }
    .qm-ticket::after {
        content:""; position:absolute; right:-6px; top:50%; width:10px; height:10px;
        margin-top:-5px; border-radius:50%; background: var(--board);
    }
    .qm-ticket .qm-ticket-val { font-family: var(--font-display); font-size:20px; font-weight:700; }
    .qm-ticket .qm-ticket-lbl { font-size:10px; letter-spacing:0.08em; text-transform:uppercase; margin-top:4px; color:#8a5a0e; }
    .qm-card-body { flex:1; min-width:0; padding: 14px 16px 14px 8px; }
    .qm-card-rank {
        font-size:11px; letter-spacing:0.06em; text-transform:uppercase;
        color: #6b655c; font-weight:700;
    }
    .qm-card-rank.hot { color: var(--stub-amber); }
    .qm-card-explain { font-size:16px; margin:4px 0 6px; line-height:1.4; font-weight:600; }
    .qm-card-meta { font-size:13px; color:#5c574f; }
    .qm-pending {
        display:flex; align-items:center; gap:8px; font-size:13px;
        color: var(--stub-face); margin-bottom:4px;
    }
    .qm-empty {
        border: 1.5px dashed rgba(242, 239, 230, 0.35); border-radius: 4px;
        padding: 28px 22px; margin: 8px 0 16px; background: rgba(0,0,0,0.14);
        text-align: left;
    }
    .qm-empty h3 {
        margin:0 0 8px; font-size:1.45rem;
        font-family: var(--font-display); color: var(--chalk);
    }
    .qm-empty p { margin:0; color:var(--muted); font-size:15px; line-height:1.5; max-width:36rem; }
    h5, .stMarkdown h5 { color: var(--chalk) !important; font-family: var(--font-display) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_engine(db_path: str, preset: str, epoch: int):
    """One engine per (db_path, preset, epoch). Bump epoch to reset the demo queue."""
    preset = tax.normalize_preset(preset)
    return QueueMerge(
        db_path=db_path,
        course_name=tax.PRESET_COURSE_NAMES[preset],
        taxonomy_preset=preset,
        seed_taxonomy=True,
        prefer_gemini=True,
    )


DB_PATH = os.environ.get("QUEUEMERGE_DB_PATH", ":memory:")

SAMPLES_BY_PRESET = {
    "cs101": [
        ("Ava", "why is my loop off by one, prints an extra blank line",
         "for i in range(len(arr)+1):\n    print(arr[i])", None),
        ("Liam", "why does my array print an extra blank line at the end",
         "for i in range(len(a)+1):\n    print(a[i])", None),
        ("Noah", "my function never processes the last element of the list",
         "for i in range(len(arr)-1):\n    process(arr[i])", None),
        ("Emma", "i made a copy of my list but changing one changes both",
         "a = [1,2,3]\nb = a\nb.append(4)", None),
        ("Mia", "my recursive function crashes with a recursion error",
         "def fact(n):\n    return n * fact(n-1)",
         "RecursionError: maximum recursion depth exceeded"),
        ("Ethan", "i keep getting index out of range and don't know why",
         "x = data[len(data)]", "IndexError: list index out of range"),
        ("Zoe", "my program just hangs forever when two threads both wait on each other's lock",
         "t1.acquire(lock_a)\nt1.acquire(lock_b)  # meanwhile t2 does the reverse order",
         None),
    ],
    "fintech": [
        ("Priya", "I was charged twice for the same checkout — two identical charges on my statement",
         None, None),
        ("Jordan", "merchant billed me twice for one order, same amount twice",
         None, None),
        ("Sam", "there's a mystery fee on my statement I never authorized — what is this fee?",
         None, None),
        ("Riley", "I sent an ACH but the transfer is still pending and the destination never credited",
         None, None),
        ("Casey", "my app shows a stale balance and transactions are not showing after refresh",
         None, None),
        ("Morgan", "my card declined for fraud on a purchase I definitely authorized",
         None, None),
        ("Alex", "my OpenSea NFT royalty payout failed and the smart-contract event never indexed",
         None, None),
    ],
}

# Keep the historical name for anything that imported SAMPLES from this module.
SAMPLES = SAMPLES_BY_PRESET["cs101"]


def _load_samples(engine, preset: str):
    for s in SAMPLES_BY_PRESET[preset]:
        engine.submit_question(*s, prefer_gemini=False)


def _fresh_engine(preset: str):
    """Bump epoch so Load / Reset always starts from a clean in-memory queue."""
    st.session_state["engine_epoch"] = int(st.session_state.get("engine_epoch", 0)) + 1
    st.session_state.pop("sim_target", None)
    return get_engine(DB_PATH, preset, st.session_state["engine_epoch"])


if "taxonomy_preset" not in st.session_state:
    st.session_state["taxonomy_preset"] = "cs101"
if "engine_epoch" not in st.session_state:
    st.session_state["engine_epoch"] = 0

with st.sidebar:
    st.subheader("Domain preset")
    preset_keys = list(tax.TAXONOMY_PRESETS.keys())
    labels = [tax.PRESET_LABELS[k] for k in preset_keys]
    current = st.session_state["taxonomy_preset"]
    try:
        current_idx = preset_keys.index(current)
    except ValueError:
        current_idx = 0
    chosen_label = st.radio(
        "Same engine, different root-cause taxonomy",
        options=labels,
        index=current_idx,
        help="Switching starts a fresh course/session for that domain. "
             "CS101 and Fintech nodes never mix.",
    )
    chosen_preset = preset_keys[labels.index(chosen_label)]
    if chosen_preset != st.session_state["taxonomy_preset"]:
        st.session_state["taxonomy_preset"] = chosen_preset
        st.session_state["engine_epoch"] = int(st.session_state.get("engine_epoch", 0)) + 1
        st.session_state.pop("sim_target", None)
        st.rerun()

    preset = st.session_state["taxonomy_preset"]
    qm = get_engine(DB_PATH, preset, st.session_state["engine_epoch"])

    st.divider()
    st.subheader("Quick start")
    st.caption("Instant offline demo. Load replaces the current queue so it stays clean.")
    load_label = (
        "▶ Load 7 sample questions"
        if preset == "cs101"
        else "▶ Load 7 fintech tickets"
    )
    if st.button(load_label, type="primary", use_container_width=True):
        qm = _fresh_engine(preset)
        _load_samples(qm, preset)
        st.success("Demo queue loaded. Help the top amber ticket first.")
        st.rerun()
    if st.button("Reset queue", use_container_width=True):
        _fresh_engine(preset)
        st.info("Queue cleared.")
        st.rerun()

    st.divider()
    st.subheader("Add one student" if preset == "cs101" else "Add one ticket")
    st.caption("Typed questions use Gemini when a key is configured; otherwise the offline matcher.")
    with st.form("intake_form", clear_on_submit=True):
        name = st.text_input(
            "Student name" if preset == "cs101" else "Customer name",
            placeholder="e.g. Ava" if preset == "cs101" else "e.g. Priya",
        )
        text = st.text_area(
            "What are they stuck on?" if preset == "cs101" else "What went wrong?",
            placeholder="Describe the bug or question…" if preset == "cs101"
            else "Describe the billing / transfer / login issue…",
        )
        with st.expander("Optional details"):
            code = st.text_area("Code snippet" if preset == "cs101" else "Reference / receipt IDs")
            error = st.text_input("Error message" if preset == "cs101" else "Decline / error code")
        submitted = st.form_submit_button(
            "Add to queue" if preset == "cs101" else "Add ticket",
            use_container_width=True,
        )
        if submitted:
            if not (name or "").strip() or not (text or "").strip():
                st.error("Name and question text are required.")
            else:
                qm.submit_question(name, text, code or None, error or None)
                st.success(f"Added {name.strip()} to the queue.")
                st.rerun()

    st.divider()
    with st.expander("What do the buttons mean?"):
        st.markdown(
            """
- **Mark resolved** — you finished helping this group; they leave the queue.
- **Mark misclustered** — these students don’t share a root cause; split them apart.
- **Simulate** — compare “help this cluster” vs other choices before you commit.
- **Explanation Memory** — save a teaching note so it resurfaces next time this misconception appears.
- **SUPM** — students unblocked ÷ TA minutes (higher = help this group sooner).
- **Domain preset** — CS101 office hours or Fintech support triage; same pipeline, separate taxonomy.
- **Brief me / 3D world** — optional ElevenLabs + World Labs hooks (only appear if keys are configured).
            """
        )

preset = st.session_state["taxonomy_preset"]
qm = get_engine(DB_PATH, preset, st.session_state["engine_epoch"])
preset_badge = tax.PRESET_LABELS[preset]

_hooks = []
_hooks.append(("Gemini", bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEYS"))))
_hooks.append(("World Labs", integ.worldlabs_configured()))
_hooks.append(("Discord outbreaks", integ.outbreak_webhook_configured()))
_hooks.append(("ElevenLabs", integ.elevenlabs_configured()))
_hooks_html = "".join(
    f'<span class="qm-hook {"on" if on else ""}">{_esc(label)}{" · live" if on else ""}</span>'
    for label, on in _hooks
)

st.markdown(
    f"""
    <div class="qm-hero">
      <h1 class="qm-brand">QueueMerge <span class="qm-brand-mark">{_esc(preset_badge)}</span></h1>
      <p class="qm-lede">Group the queue by <b>shared root cause</b>, rank by how many people
      you unblock per minute (<b>SUPM</b>), then help the top ticket first.</p>
      <div class="qm-hooks">{_hooks_html}</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="qm-steps">'
    '<span class="qm-step"><b>1.</b> Sidebar → Load 7 samples</span>'
    '<span class="qm-step"><b>2.</b> Help the amber ticket first</span>'
    '<span class="qm-step"><b>3.</b> Resolve · save a teaching note · optional 3D world</span>'
    '</div>',
    unsafe_allow_html=True,
)

# Outbreaks first — urgent
qm.check_outbreaks()
open_alerts = qm.open_outbreak_alerts()
if open_alerts:
    st.markdown("##### Needs attention")
    for a in open_alerts:
        col1, col2 = st.columns([6, 1])
        with col1:
            st.markdown(
                f'<div class="qm-alert">🔥 <div><b>Outbreak: {_esc(a["node_name"])}</b> '
                f'(confidence {a["confidence"]:.0%}, trend {_esc(a["trend"])}) — '
                f'{_esc(a["recommendation"])}</div></div>',
                unsafe_allow_html=True,
            )
        with col2:
            if st.button("Dismiss", key=f"dismiss_alert_{a['alert_id']}"):
                qm.dismiss_outbreak_alert(a["alert_id"])
                st.rerun()

pending = qm.pending_bootstrap_nodes()
if pending:
    with st.expander(
        f"New misconception labels to approve ({len(pending)})",
        expanded=False,
    ):
        st.caption(
            "A question didn’t match the course taxonomy, so QueueMerge proposed a new label. "
            "Rename if you want, then approve."
        )
        for n in pending:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(
                    f'<div class="qm-pending">🆕 <b>{_esc(n["name"])}</b> — {_esc(n["description"])}</div>',
                    unsafe_allow_html=True,
                )
            with col2:
                new_name = st.text_input("Rename (optional)", key=f"rename_{n['id']}")
                if st.button("Approve", key=f"approve_{n['id']}"):
                    qm.approve_node(n["id"], new_name or None)
                    st.rerun()

recs = qm.recommendations()

st.markdown("##### Queue by root cause")
if not recs:
    load_hint = (
        "Load 7 sample questions"
        if preset == "cs101"
        else "Load 7 fintech tickets"
    )
    st.markdown(
        f'<div class="qm-empty"><h3>Queue is empty</h3>'
        f"<p>Hit <b>{load_hint}</b> in the left sidebar — clustering, SUPM ranking, "
        "and ticket stubs appear in under a second.</p></div>",
        unsafe_allow_html=True,
    )
else:
    total_students = sum(r["cluster"]["size"] for r in recs)
    who = "Students" if preset == "cs101" else "Tickets"
    avg_supm = sum(r["supm"] for r in recs) / len(recs)
    longest_wait_min = max(r["cluster"].get("oldest_wait_seconds", 0) for r in recs) / 60.0

    st.markdown(
        f"""
        <div class="qm-stat-row">
          <div class="qm-stat"><p class="qm-stat-label">Groups waiting</p><p class="qm-stat-value">{len(recs)}</p></div>
          <div class="qm-stat"><p class="qm-stat-label">{who} waiting</p><p class="qm-stat-value">{total_students}</p></div>
          <div class="qm-stat"><p class="qm-stat-label">Avg SUPM</p><p class="qm-stat-value">{avg_supm:.2f}</p></div>
          <div class="qm-stat"><p class="qm-stat-label">Longest wait</p><p class="qm-stat-value">{longest_wait_min:.0f}m</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Amber stub = SUPM (people unblocked per TA-minute). Higher → help that group next."
    )

    for i, r in enumerate(recs):
        c = r["cluster"]
        wait_min = c.get("oldest_wait_seconds", 0) / 60.0
        rank_label = "Help this next" if i == 0 else f"#{i + 1} in line"
        rank_cls = "qm-card-rank hot" if i == 0 else "qm-card-rank"
        card_cls = "qm-card qm-first" if i == 0 else "qm-card"
        people = "student(s)" if preset == "cs101" else "ticket(s)"

        st.markdown(
            f"""
            <div class="{card_cls}">
              <div class="qm-ticket">
                <span class="qm-ticket-val">{_esc(f"{r['supm']:.2f}")}</span>
                <span class="qm-ticket-lbl">supm</span>
              </div>
              <div class="qm-card-body">
                <div class="{rank_cls}">{_esc(rank_label)}</div>
                <div class="qm-card-explain">{_esc(c['explanation'])}</div>
                <div class="qm-card-meta">{_esc(c['size'])} {people} · longest wait {wait_min:.1f}m</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("Why this score? (SUPM inputs)"):
            st.caption("Transparent inputs used to compute students-unblocked per TA-minute.")
            st.json(r["inputs"])

        action_cols = st.columns([1.2, 1, 1, 1, 1.1])
        if action_cols[0].button(
            "Compare: help this next",
            key=f"sim_{c['cluster_id']}",
            help="Run a quick what-if simulation before you commit.",
        ):
            st.session_state["sim_target"] = c["cluster_id"]

        minutes = action_cols[1].number_input(
            "Minutes spent",
            min_value=0.5,
            max_value=60.0,
            value=float(r["inputs"]["expected_ta_minutes"]),
            step=0.5,
            key=f"min_{c['cluster_id']}",
            help="How long you spent explaining this group.",
        )
        if action_cols[2].button(
            "✓ Mark resolved",
            key=f"resolve_{c['cluster_id']}",
            type="primary" if i == 0 else "secondary",
        ):
            qm.resolve_cluster(c["cluster_id"], minutes_spent=minutes, label="resolved")
            st.rerun()
        if action_cols[3].button(
            "Wrong group",
            key=f"misclustered_{c['cluster_id']}",
            help="These students do not share a root cause.",
        ):
            qm.mark_misclustered(c["cluster_id"])
            st.rerun()

        # Optional sponsor hooks (hidden unless env configured)
        extra = action_cols[4]
        if integ.elevenlabs_configured() and extra.button(
            "🔊 Brief me",
            key=f"tts_{c['cluster_id']}",
            help="ElevenLabs spoken triage briefing (optional sponsor integration).",
        ):
            audio = integ.synthesize_briefing(
                integ.triage_briefing_text(c, preset=preset)
            )
            if audio:
                st.session_state[f"tts_audio_{c['cluster_id']}"] = audio
            else:
                st.warning("ElevenLabs briefing failed — check ELEVENLABS_API_KEY.")
        if f"tts_audio_{c['cluster_id']}" in st.session_state:
            st.audio(st.session_state[f"tts_audio_{c['cluster_id']}"], format="audio/mp3")

        if integ.worldlabs_configured() and i == 0:
            tid = c.get("taxonomy_node_id")
            node_name = None
            if tid is not None:
                n = next((n for n in qm.taxonomy_nodes() if n["id"] == tid), None)
                node_name = n["name"] if n else None
            with st.expander("🌐 3D World Labs explainer", expanded=True):
                st.caption(
                    "Marble world for this root cause · "
                    "[Starter kit](https://worldlabs.notion.site/Starter-Kit-30d8950a1bef806e90a5e030c6382297)"
                )
                if st.button("Generate 3D world", key=f"wl_{c['cluster_id']}", type="primary") and node_name:
                    with st.spinner("Generating World Labs world (can take 1–3 minutes)…"):
                        wl = integ.request_worldlabs_world(node_name)
                    if not wl:
                        st.error("World Labs request failed — check WORLD_LABS_API_KEY / credits.")
                    else:
                        url = wl.get("viewer_url")
                        world = wl.get("world") or {}
                        if not url and isinstance(world, dict):
                            url = world.get("world_marble_url") or (
                                f"https://marble.worldlabs.ai/world/{world['world_id']}"
                                if world.get("world_id") else None
                            )
                        if url:
                            st.success("World ready")
                            st.link_button("Open in Marble →", url, type="primary")
                            st.code(url)
                        elif wl.get("operation_id") and not wl.get("done"):
                            st.info(
                                f"Still generating · operation `{wl['operation_id']}`. "
                                "Try again in a minute, or open the World Labs dashboard."
                            )
                        elif wl.get("error"):
                            st.error(str(wl["error"]))
                        else:
                            st.write(wl)

        with st.expander("Explanation Memory — what worked last time"):
            notes = qm.explanation_memory(c["cluster_id"], limit=5)
            if notes:
                st.caption("Past TA notes for this same misconception, ranked by usefulness votes.")
                for note in notes:
                    note_cols = st.columns([7, 1])
                    with note_cols[0]:
                        st.write(note["note_text"])
                        st.caption(f"{note['upvotes']} usefulness vote(s)")
                    with note_cols[1]:
                        if st.button("👍 +1", key=f"upvote_note_{note['id']}"):
                            qm.upvote_explanation_note(note["id"])
                            st.rerun()
            else:
                st.caption("No saved explanation yet. After you help this group, write what worked.")

            with st.form(f"memory_note_form_{c['cluster_id']}", clear_on_submit=True):
                note_text = st.text_area(
                    "Save a teaching move",
                    key=f"memory_note_text_{c['cluster_id']}",
                    placeholder="Example: Draw indices 0..n-1 first, then contrast len(arr) with the last valid index.",
                )
                save_note = st.form_submit_button("Save note")
                if save_note and note_text.strip():
                    qm.add_explanation_note(c["cluster_id"], note_text)
                    st.rerun()

    if st.session_state.get("sim_target"):
        st.subheader("What if I help this next?")
        st.caption("Short forward simulation comparing a few choices.")
        with st.spinner("Simulating…"):
            results = qm.simulate(top_n_clusters=3, trials=40, horizon_min=20.0)
        for r in results:
            st.write(
                f"**{r['label']}** → clears ~{r['mean_students_unblocked']} students in "
                f"~{r['mean_clear_minutes']} min; projected median wait for everyone else "
                f"~{r['mean_median_wait_min']} min."
            )
        if st.button("Close comparison"):
            st.session_state["sim_target"] = None
            st.rerun()

with st.expander("Course taxonomy (advanced)"):
    st.caption(
        f"Misconception labels for preset **{preset_badge}**. Pending ones need your approval. "
        "Switching presets uses a different course — notes do not cross domains."
    )
    for n in qm.taxonomy_nodes():
        status = "approved" if n["approved"] else "pending approval"
        st.write(
            f"**{n['name']}** ({status}) — {n['description']} "
            f"| mean explain time: {n['mean_explain_minutes']:.1f}m "
            f"| confidence weight: {n['confidence_weight']:.2f}"
        )
