# "Generate now" button setup

A button on maxime-droux.com/plan that triggers the weekly news workflow on
demand. It works through a tiny free Cloudflare Worker that holds a GitHub key.

## 1. Create a GitHub token (grants only "run this repo's actions")

1. On github.com, signed in as **maximedroux55-hue**: avatar (top right) →
   **Settings** → **Developer settings** (bottom of the left menu) →
   **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Name: `news button`. Expiration: 1 year (or your choice).
3. **Resource owner:** maximedroux55-hue.
4. **Repository access:** Only select repositories → choose **Test**.
5. **Permissions** → Repository permissions → **Actions: Read and write**.
   (Leave everything else as is.)
6. **Generate token** and copy it (starts with `github_pat_...`). You will paste
   it into Cloudflare next, then you can forget it.

## 2. Create the Cloudflare Worker

1. Go to **dash.cloudflare.com**, sign up or log in (free).
2. Left menu: **Workers & Pages** → **Create application** → **Create Worker**.
3. Name it `md-news-button` → **Deploy** (deploys a placeholder).
4. **Edit code**, delete the placeholder, paste the contents of `worker.js`
   (in this folder), then **Deploy** again.
5. Open the Worker's **Settings** → **Variables and Secrets** → **Add**:
   - Type: **Secret**
   - Name: `GITHUB_TOKEN`
   - Value: the `github_pat_...` token from step 1
   - **Save / Deploy**.
6. Copy the Worker's URL, shown at the top (looks like
   `https://md-news-button.<your-name>.workers.dev`).

## 3. Send the Worker URL to Claude

Paste that `…workers.dev` URL back in the chat. Claude wires the button on
maxime-droux.com/plan to it. From then on, one tap regenerates the week's posts.

## 4. Updating it to save facts typed into the database page

The **+** beside a company on maxime-droux.com/digest/archive.html lets you type
in a fact the scraper could not find. Saving it writes to corrections.json, and
the Worker does the writing, so the page never carries a key.

That needs one more permission than the run button, because it writes a file
rather than starting a job.

1. **Give the token file access.** github.com → avatar → **Settings** →
   **Developer settings** → **Personal access tokens** → **Fine-grained tokens**
   → click **news button** → **Repository permissions** → set
   **Contents: Read and write** (keep Actions: Read and write) →
   **Update token** at the bottom.
   The token value does not change, so Cloudflare needs no new secret.
2. **Update the Worker code.** dash.cloudflare.com → **Workers & Pages** →
   **md-news-button** → **Edit code**. Select everything in the editor, delete
   it, paste the current `button/worker.js` from this repo, then **Deploy**.

Nothing else changes: same Worker, same URL, same secret. The run button keeps
working, `POST /correction` is what the database page uses, and
`POST /submission` is what the upload page at maxime-droux.com/submit uses.

## Uploading a Crunchbase export

`POST /submission` writes a `.csv` into `deeptech-news/submissions/`, which the
scraper reads on every run. It is deliberately narrow:

- Only `.csv`, and only a funding-rounds export: the header must carry
  `Organization Name`, `Funding Type` and `Announced Date`, or it is refused.
  A file that is read on every run and quietly produces nothing is worse than
  one rejected at the door.
- The filename is rebuilt rather than trusted, and always lands in
  `deeptech-news/submissions/`. A name off a browser can carry `../` and would
  otherwise choose where in the repository the file goes.
- 256 KB ceiling. A month of Swiss rounds is about 10 KB.
- Uploading twice on one day replaces that day's file rather than failing.

Same Origin allowlist as everything else, so the endpoint only answers requests
from maxime-droux.com.
