// Cloudflare Worker: triggers the "Swiss DeepTech news digest" GitHub Actions
// workflow when the button on maxime-droux.com/plan is tapped.
//
// It holds the GitHub token as a Worker secret (GITHUB_TOKEN), so the token
// never appears on the public page. It only accepts requests coming from Max's
// own site (Origin allowlist), so a random visitor to the Worker URL cannot
// trigger runs from another site. Worst case if abused is an extra digest run.
//
// Setup: paste this into a Cloudflare Worker, then add a secret named
// GITHUB_TOKEN (a fine-grained GitHub token with Actions: read and write on the
// maximedroux55-hue/Test repo). See button/SETUP.md.

const REPO = "maximedroux55-hue/Test";
const WORKFLOW = "news-digest.yml";
const REF = "claude/questions-9a5egd"; // branch the workflow lives on

const ALLOWED_ORIGINS = [
  "https://maxime-droux.com",
  "https://www.maxime-droux.com",
  "https://maximedroux55-hue.github.io",
];

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const allow = ALLOWED_ORIGINS.includes(origin) ? origin : "";
    const cors = {
      "Access-Control-Allow-Origin": allow || "null",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
      "Vary": "Origin",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: cors });
    }
    if (request.method !== "POST") {
      return json({ ok: false, error: "use POST" }, 405, cors);
    }
    if (!allow) {
      return json({ ok: false, error: "forbidden origin" }, 403, cors);
    }
    if (!env.GITHUB_TOKEN) {
      return json({ ok: false, error: "missing GITHUB_TOKEN secret" }, 500, cors);
    }

    const resp = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "md-news-button",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: REF }),
      }
    );

    const ok = resp.status === 204; // GitHub returns 204 No Content on success
    const detail = ok ? "" : await resp.text();
    return json({ ok, status: resp.status, detail }, ok ? 200 : 502, cors);
  },
};

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...cors, "content-type": "application/json" },
  });
}
