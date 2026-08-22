/**
 * QueueMerge -> World Labs secure proxy for Cloudflare Workers.
 *
 * Secrets/config:
 *   WORLD_LABS_API_KEY  (secret, required)
 *   ALLOWED_ORIGIN      (var, required in production, e.g. https://USER.github.io)
 *   WORLD_LABS_MODEL    (var, optional; defaults to marble-1.0-draft)
 *
 * The browser sends only a QueueMerge taxonomy node ID. The API key never leaves
 * this Worker. Prompts are allowlisted here so the public endpoint cannot be used
 * as a general arbitrary-prompt World Labs proxy.
 */

const WORLD_LABS_BASE = "https://api.worldlabs.ai/marble/v1";
const GENERATE_COOLDOWN_SECONDS = 300;

const EXPLAINER_PROMPTS = Object.freeze({
  // CS101
  "loop-boundary-inclusive": "An educational 3D computer science learning space that visually teaches an off-by-one loop bug. A row of numbered stepping stones represents valid array indices 0 through n-1, with one clearly dangerous extra stone labeled n beyond the boundary. Include visual cues contrasting < with <=, a clean classroom-lab aesthetic, no people, no personal data, readable conceptual structure.",
  "loop-boundary-exclusive-missing-last": "An educational 3D computer science learning space that explains a loop stopping one item too early. Show a sequence of numbered stations where the final valid element is visibly left unreached because the stopping gate closes early. Clean classroom-lab aesthetic, no people, no personal data, visually emphasize exclusive boundaries and the missing final item.",
  "index-out-of-range": "An educational 3D computer science learning space for index-out-of-range errors. Show a finite row of array cells with valid indices, a bright boundary marker, and a path that attempts to step beyond the last valid cell into an inaccessible zone. Clean technical visualization, no people, no personal data.",
  "mutable-default-arg": "An educational 3D programming metaphor for mutable default arguments. Show several function-call stations unexpectedly sharing one persistent container that keeps accumulating objects across visits, contrasted with separate fresh containers. Clean classroom visualization, no people, no personal data.",
  "reference-vs-copy": "An educational 3D programming metaphor for aliasing versus copying. Show two labeled pointers or paths leading to the same shared container, contrasted with a true copied second container. Mutating the shared box should visually affect both references. Clean technical learning environment, no people, no personal data.",
  "recursion-missing-base-case": "An educational 3D computer science world explaining recursion without a reachable base case. Show a repeating staircase of function-call frames descending deeper with no exit, contrasted with a clearly marked base-case doorway that would stop the descent. Clean classroom visualization, no people, no personal data.",
  "integer-division-truncation": "An educational 3D programming visualization for integer division truncation. Show quantities flowing through a division machine where the fractional remainder is visibly discarded, contrasted with floating-point division preserving it. Clean mathematical lab aesthetic, no people, no personal data.",
  "scope-variable-shadowing": "An educational 3D programming world for variable shadowing. Show nested rooms representing scopes, each containing a variable with the same name; the inner variable blocks the view of the outer binding until leaving the room. Clean technical classroom metaphor, no people, no personal data.",
  // Fintech support triage
  "duplicate-charge": "A clean fintech operations war-room visualization of a duplicate charge. Show one checkout producing two identical settlement tickets on a statement board, with arrows marking the twin posting. Abstract banking aesthetic, no logos, no personal data, no people.",
  "unexplained-fee": "A clean fintech visualization of an unexplained fee: a statement board with a novel fee line that has no matching prior purchase twin, contrasted with a legitimate purchase line. Abstract banking aesthetic, no logos, no personal data, no people.",
  "stuck-transfer": "A clean fintech visualization of a stuck transfer: funds leaving a source vault into a translucent in-flight corridor that never arrives at the destination vault. Abstract banking aesthetic, no logos, no personal data, no people.",
  "stale-account-sync": "A clean fintech visualization of stale account sync: a dashboard screen frozen on an old balance snapshot while a live feed pipe is clearly disconnected. Abstract banking aesthetic, no logos, no personal data, no people.",
  "false-fraud-decline": "A clean fintech visualization of a false fraud decline: a legitimate card authorization path blocked by an over-sensitive fraud gate despite a valid cardholder intent marker. Abstract banking aesthetic, no logos, no personal data, no people.",
  "mfa-lockout": "A clean fintech visualization of MFA lockout: a vault door with too many failed one-time code attempts, a lock engaging, and a recovery key path nearby. Abstract security aesthetic, no logos, no personal data, no people.",
  "unauthorized-ach-pull": "A clean fintech visualization of an unauthorized ACH pull: an unexpected debit arrow leaving an account vault without an authorization seal. Abstract banking aesthetic, no logos, no personal data, no people.",
  "card-network-timeout": "A clean fintech visualization of a card-network timeout: an authorization signal vanishing mid-corridor with a pending hold that later dissolves. Abstract payments aesthetic, no logos, no personal data, no people."
});

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request, env);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    const url = new URL(request.url);
    try {
      assertAllowedOrigin(request, env);
      if (!env.WORLD_LABS_API_KEY) return json({ error: "WORLD_LABS_API_KEY is not configured on the proxy." }, 500, cors);

      if (request.method === "GET" && url.pathname === "/health") {
        return json({ ok: true, provider: "World Labs", model: env.WORLD_LABS_MODEL || "marble-1.0-draft" }, 200, cors);
      }

      if (request.method === "POST" && url.pathname === "/generate") {
        return await handleGenerate(request, env, cors);
      }

      const opMatch = url.pathname.match(/^\/operations\/([A-Za-z0-9-]+)$/);
      if (request.method === "GET" && opMatch) {
        return await handleOperation(opMatch[1], env, cors);
      }

      return json({ error: "Not found." }, 404, cors);
    } catch (error) {
      const status = error?.status || 500;
      return json({ error: error?.message || "Proxy error." }, status, cors);
    }
  }
};

async function handleGenerate(request, env, cors) {
  const body = await request.json().catch(() => ({}));
  const nodeId = String(body.node_id || "");
  const prompt = EXPLAINER_PROMPTS[nodeId];
  if (!prompt) return json({ error: "Unsupported QueueMerge misconception node." }, 400, cors);

  const limited = await isRateLimited(request);
  if (limited) {
    return json({ error: `Please wait ${Math.ceil(GENERATE_COOLDOWN_SECONDS / 60)} minutes before starting another 3D world from this connection.` }, 429, cors);
  }

  const payload = {
    display_name: `QueueMerge - ${humanize(nodeId)}`.slice(0, 64),
    model: env.WORLD_LABS_MODEL || "marble-1.0-draft",
    world_prompt: { type: "text", text_prompt: prompt },
    permission: { allow_id_access: true, allowed_readers: [], allowed_writers: [], public: true },
    tags: ["queuemerge", "education", nodeId.slice(0, 32)]
  };

  const upstream = await fetch(`${WORLD_LABS_BASE}/worlds:generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "WLT-Api-Key": env.WORLD_LABS_API_KEY
    },
    body: JSON.stringify(payload)
  });
  const data = await safeJson(upstream);
  if (!upstream.ok) return json({ error: worldLabsError(data, upstream.status) }, upstream.status, cors);

  await markRateLimit(request);
  return json(data.done && data.response
    ? { world: data.response }
    : { operation_id: data.operation_id, done: Boolean(data.done) }, 200, cors);
}

async function handleOperation(operationId, env, cors) {
  const upstream = await fetch(`${WORLD_LABS_BASE}/operations/${encodeURIComponent(operationId)}`, {
    headers: { "WLT-Api-Key": env.WORLD_LABS_API_KEY }
  });
  const data = await safeJson(upstream);
  if (!upstream.ok) return json({ error: worldLabsError(data, upstream.status) }, upstream.status, cors);
  return json({
    done: Boolean(data.done),
    error: data.error || null,
    metadata: data.metadata || null,
    world: data.done ? (data.response || null) : null
  }, 200, cors);
}

async function isRateLimited(request) {
  const key = rateLimitKey(request);
  return Boolean(await caches.default.match(key));
}

async function markRateLimit(request) {
  const key = rateLimitKey(request);
  await caches.default.put(key, new Response("1", {
    headers: { "Cache-Control": `public, max-age=${GENERATE_COOLDOWN_SECONDS}` }
  }));
}

function rateLimitKey(request) {
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  return new Request(`https://queuemerge.internal/rate/${encodeURIComponent(ip)}`);
}

function assertAllowedOrigin(request, env) {
  const expected = String(env.ALLOWED_ORIGIN || "").replace(/\/$/, "");
  const origin = String(request.headers.get("Origin") || "").replace(/\/$/, "");
  if (!expected) return;
  if (origin !== expected) {
    const error = new Error("Origin not allowed.");
    error.status = 403;
    throw error;
  }
}

function corsHeaders(request, env) {
  const expected = String(env.ALLOWED_ORIGIN || "").replace(/\/$/, "");
  const origin = String(request.headers.get("Origin") || "").replace(/\/$/, "");
  const allowed = expected && origin === expected ? origin : (expected ? expected : "*");
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
    "Cache-Control": "no-store"
  };
}

function humanize(id) {
  return id.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function worldLabsError(data, status) {
  return data?.detail?.message || data?.detail || data?.error?.message || data?.message || `World Labs API error (${status}).`;
}

async function safeJson(response) {
  const text = await response.text();
  if (!text) return {};
  try { return JSON.parse(text); }
  catch (_) { return { message: text.slice(0, 500) }; }
}

function json(value, status, cors) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { ...cors, "Content-Type": "application/json; charset=utf-8" }
  });
}
