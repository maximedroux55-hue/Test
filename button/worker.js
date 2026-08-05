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

    // Saving a fact typed into the database page. The page used to hand Max
    // the whole corrections file to copy, open on GitHub, paste and commit,
    // which is several minutes on a phone and needs a GitHub login. This
    // writes it for him: one tap.
    if (new URL(request.url).pathname.replace(/\/+$/, "") === "/correction") {
      return saveCorrection(request, env, cors);
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

const CORRECTIONS = "deeptech-news/corrections.json";

// Only what the database page offers, so a forged request cannot write
// arbitrary keys into the file the whole pipeline trusts.
const FIELDS = new Set([
  "description", "category", "stage", "amount", "amount_note", "lead_investor",
  "investors", "founders", "spinoff_origin", "location", "legal_seat",
  "website", "founded", "employees", "total_raised", "valuation",
  "use_of_funds",
]);

async function saveCorrection(request, env, cors) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "expected JSON" }, 400, cors);
  }

  const company = String(body.company || "").trim();
  if (!company || company.length > 120) {
    return json({ ok: false, error: "company required" }, 400, cors);
  }
  const wanted = {};
  for (const [key, value] of Object.entries(body.fields || {})) {
    // An empty string is meaningful: it clears a wrong value.
    if (FIELDS.has(key) && typeof value === "string" && value.length <= 500) {
      wanted[key] = value.trim();
    }
  }
  if (!Object.keys(wanted).length) {
    return json({ ok: false, error: "nothing to change" }, 400, cors);
  }

  const api = `https://api.github.com/repos/${REPO}/contents/${CORRECTIONS}`;
  const headers = {
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    Accept: "application/vnd.github+json",
    "User-Agent": "md-news-button",
    "Content-Type": "application/json",
  };

  const read = await fetch(`${api}?ref=${encodeURIComponent(REF)}`, { headers });
  if (!read.ok) {
    return json({ ok: false, error: `could not read the file (${read.status})` },
                502, cors);
  }
  const meta = await read.json();
  let file;
  try {
    // atob gives bytes; the file has accents in it (Neuchâtel), so decode UTF-8
    // properly rather than mangling them on every save.
    const bytes = Uint8Array.from(atob(meta.content.replace(/\n/g, "")),
                                  (c) => c.charCodeAt(0));
    file = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return json({ ok: false, error: "corrections.json will not parse" }, 500, cors);
  }
  file.companies = file.companies || {};
  file.companies[company] = { ...(file.companies[company] || {}), ...wanted };

  const text = JSON.stringify(file, null, 2) + "\n";
  const encoded = btoa(String.fromCharCode(...new TextEncoder().encode(text)));
  const write = await fetch(api, {
    method: "PUT",
    headers,
    body: JSON.stringify({
      message: `${company}: ${Object.keys(wanted).join(", ")} from the database page`,
      content: encoded,
      sha: meta.sha,   // fails rather than clobbering if the file moved on
      branch: REF,
    }),
  });
  if (!write.ok) {
    const detail = await write.text();
    return json({ ok: false, status: write.status, error: detail.slice(0, 300) },
                502, cors);
  }
  return json({ ok: true, company, fields: Object.keys(wanted) }, 200, cors);
}

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...cors, "content-type": "application/json" },
  });
}
