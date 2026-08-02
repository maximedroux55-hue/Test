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
