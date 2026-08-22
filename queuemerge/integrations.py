"""Optional sponsor / ops integrations. All no-ops without env config.

Ignition Hacks V.7 sponsor-friendly hooks (graceful if unused):
  - ElevenLabs  -> speak a short triage briefing for the top cluster
  - Webhook URL -> Activepieces / Discord / Slack on new outbreak alerts
  - World Labs  -> 3D explainer worlds (local API key or Cloudflare proxy)

None of these are required to run QueueMerge.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional


def elevenlabs_configured() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())


def outbreak_webhook_configured() -> bool:
    return bool(os.environ.get("OUTBREAK_WEBHOOK_URL", "").strip())


def _worldlabs_api_key() -> str:
    return (
        os.environ.get("WORLD_LABS_API_KEY", "").strip()
        or os.environ.get("WLT_API_KEY", "").strip()
    )


def worldlabs_proxy_configured() -> bool:
    return bool(os.environ.get("WORLD_LABS_PROXY_URL", "").strip())


def worldlabs_direct_configured() -> bool:
    return bool(_worldlabs_api_key())


def worldlabs_configured() -> bool:
    """True if either the secure proxy URL or a local API key is set."""
    return worldlabs_proxy_configured() or worldlabs_direct_configured()


def triage_briefing_text(cluster: dict, preset: str = "cs101") -> str:
    """Short spoken brief an agent can play before walking to the whiteboard."""
    size = cluster.get("size", 1)
    explain = (cluster.get("explanation") or "shared root cause").strip()
    wait_s = float(cluster.get("oldest_wait_seconds") or 0)
    wait_m = wait_s / 60.0
    domain = "support" if preset == "fintech" else "office hours"
    return (
        f"QueueMerge {domain} briefing. "
        f"{size} {'customers' if preset == 'fintech' else 'students'} share this root cause. "
        f"{explain} "
        f"Longest wait about {wait_m:.0f} minutes. Help this group next."
    )


def synthesize_briefing(text: str) -> Optional[bytes]:
    """Return MP3 bytes from ElevenLabs, or None if unavailable/failed."""
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key or not (text or "").strip():
        return None
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM").strip()
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = json.dumps({
        "text": text[:2500],
        "model_id": model_id,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75},
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None


def notify_outbreaks(alerts: list, course_name: str = "", preset: str = "") -> int:
    """POST each new outbreak to OUTBREAK_WEBHOOK_URL (Discord/Slack/Activepieces).

    Discord incoming webhooks accept {"content": "..."}.
    Slack incoming webhooks accept {"text": "..."}.
    Activepieces HTTP triggers accept arbitrary JSON — we send both shapes.
    Returns how many posts succeeded.
    """
    hook = os.environ.get("OUTBREAK_WEBHOOK_URL", "").strip()
    if not hook or not alerts:
        return 0
    sent = 0
    for a in alerts:
        name = a.get("node_name") or a.get("taxonomy_node_id") or "unknown"
        conf = a.get("confidence")
        conf_s = f"{conf:.0%}" if isinstance(conf, (int, float)) else "?"
        msg = (
            f"QueueMerge outbreak · preset={preset or '?'} · course={course_name or '?'} · "
            f"node={name} · confidence={conf_s}"
        )
        body = json.dumps({
            "content": msg,   # Discord
            "text": msg,      # Slack
            "source": "queuemerge",
            "preset": preset,
            "course_name": course_name,
            "alert": {
                "node_name": name,
                "confidence": conf,
                "trend": a.get("trend"),
                "recommendation": a.get("recommendation"),
            },
        }).encode("utf-8")
        req = urllib.request.Request(
            hook,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                # Cloudflare rejects urllib's default UA on discord.com (error 1010).
                "User-Agent": "QueueMerge/1.0 (+outbreak-webhook)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                if 200 <= resp.status < 300:
                    sent += 1
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            continue
    return sent


# Allowlisted text prompts (same ideas as worldlabs-proxy/worker.js).
_WORLD_PROMPTS = {
    "loop-boundary-inclusive":
        "An educational 3D computer science learning space that visually teaches an off-by-one "
        "loop bug. Numbered stepping stones 0..n-1 with one dangerous extra stone labeled n. "
        "Clean classroom-lab aesthetic, no people, no personal data.",
    "loop-boundary-exclusive-missing-last":
        "Educational 3D CS space: a loop stops one item too early; the final valid element is "
        "left unreached. Clean classroom aesthetic, no people, no personal data.",
    "index-out-of-range":
        "Educational 3D CS space for IndexError: finite array cells and a path stepping past "
        "the last valid index. Clean technical visualization, no people, no personal data.",
    "mutable-default-arg":
        "Educational 3D metaphor for mutable default arguments: several call stations share one "
        "accumulating container. Clean classroom visualization, no people, no personal data.",
    "reference-vs-copy":
        "Educational 3D metaphor for aliasing vs copy: two labels point at one shared box vs a "
        "true second copy. Clean technical environment, no people, no personal data.",
    "recursion-missing-base-case":
        "Educational 3D world for recursion without a base case: descending call frames with no "
        "exit, contrasted with a marked base-case doorway. No people, no personal data.",
    "integer-division-truncation":
        "Educational 3D visualization of integer division truncation discarding a fractional "
        "remainder. Clean math-lab aesthetic, no people, no personal data.",
    "scope-variable-shadowing":
        "Educational 3D world for variable shadowing: nested scope rooms with the same variable "
        "name. Clean technical classroom metaphor, no people, no personal data.",
    "duplicate-charge":
        "Clean fintech war-room: one checkout produces two identical settlement tickets on a "
        "statement board. Abstract banking aesthetic, no logos, no personal data, no people.",
    "unexplained-fee":
        "Clean fintech viz: a novel fee line with no matching prior purchase twin. Abstract "
        "banking aesthetic, no logos, no personal data, no people.",
    "stuck-transfer":
        "Clean fintech viz: funds leave a source vault into an in-flight corridor that never "
        "reaches the destination. Abstract banking aesthetic, no logos, no personal data.",
    "stale-account-sync":
        "Clean fintech viz: dashboard frozen on an old balance while the live feed pipe is "
        "disconnected. Abstract banking aesthetic, no logos, no personal data, no people.",
    "false-fraud-decline":
        "Clean fintech viz: a legitimate authorization blocked by an over-sensitive fraud gate. "
        "Abstract banking aesthetic, no logos, no personal data, no people.",
    "mfa-lockout":
        "Clean fintech viz: vault door locked after too many one-time code failures, recovery "
        "path nearby. Abstract security aesthetic, no logos, no personal data, no people.",
    "unauthorized-ach-pull":
        "Clean fintech viz: unexpected debit arrow leaving an account without an authorization "
        "seal. Abstract banking aesthetic, no logos, no personal data, no people.",
    "card-network-timeout":
        "Clean fintech viz: authorization signal vanishing mid-corridor with a pending hold that "
        "later dissolves. Abstract payments aesthetic, no logos, no personal data, no people.",
}


def _wl_api(path: str, method: str = "GET", body: Optional[dict] = None) -> Optional[dict]:
    key = _worldlabs_api_key()
    if not key:
        return None
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.worldlabs.ai/marble/v1/{path.lstrip('/')}",
        data=data,
        method=method,
        headers={"WLT-Api-Key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def request_worldlabs_world(
    node_name: str, poll: bool = True, max_wait_s: float = 180.0
) -> Optional[dict]:
    """Generate a World Labs explainer for a taxonomy node.

    Prefer WORLD_LABS_PROXY_URL (Cloudflare worker — key never hits the browser).
    For local hackathon testing, WORLD_LABS_API_KEY / WLT_API_KEY calls the API
    directly from this process (keep the key in .env only; do not commit it).
    """
    if not node_name:
        return None

    # ---- proxy path (production / Pages-safe) ----
    base = os.environ.get("WORLD_LABS_PROXY_URL", "").strip().rstrip("/")
    if base:
        payload = json.dumps({"node_id": node_name}).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/generate",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
            return None

    # ---- direct local path ----
    prompt = _WORLD_PROMPTS.get(node_name)
    if not prompt or not _worldlabs_api_key():
        return None

    model = os.environ.get("WORLD_LABS_MODEL", "marble-1.0-draft").strip() or "marble-1.0-draft"
    started = _wl_api("worlds:generate", method="POST", body={
        "display_name": f"QueueMerge - {node_name}"[:64],
        "model": model,
        "world_prompt": {"type": "text", "text_prompt": prompt},
        "tags": ["queuemerge", node_name[:32]],
    })
    if not started:
        return None
    op_id = started.get("operation_id")
    if not op_id:
        return started
    if not poll:
        return {"operation_id": op_id, "done": False}

    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        op = _wl_api(f"operations/{op_id}")
        if not op:
            time.sleep(3)
            continue
        if op.get("done"):
            world = op.get("response") or {}
            url = (
                world.get("world_marble_url")
                or (
                    f"https://marble.worldlabs.ai/world/{world['world_id']}"
                    if world.get("world_id") else None
                )
            )
            return {
                "done": True,
                "operation_id": op_id,
                "world": world,
                "viewer_url": url,
                "error": op.get("error"),
            }
        time.sleep(4)
    return {"operation_id": op_id, "done": False, "error": "timed out waiting for World Labs"}
