# Putting a login in front of /people/

The directory is served by GitHub Pages, which has no login of its own. A
password typed into the page itself would be decoration: the browser receives
the whole file before any check runs, so View Source or a one-line `curl`
gets past it. Real protection has to sit *in front* of the file, which means
something other than GitHub Pages answers the request first.

Cloudflare Access does that, free for up to 50 people. Visitors hit a
Cloudflare login, and the file is never sent until they pass. This closes
`/people/` only. The landing page, digest, plan, reports and submit pages stay
public and indexed exactly as they are today.

Budget about 30 minutes, plus waiting for the nameserver change to take
effect (usually under an hour, occasionally a day).

## Before you start

The domain currently points straight at GitHub:

- `maxime-droux.com` A records to 185.199.108.153, .109.153, .110.153, .111.153
- `www.maxime-droux.com` CNAME to maximedroux55-hue.github.io

Step 1 moves the domain's DNS to Cloudflare, so those records have to come
across intact. **If you receive any email at @maxime-droux.com, write down the
MX records first** and check they survive the import. Losing MX records is the
one mistake in this process that has consequences beyond the website.

## 1. Add the domain to Cloudflare

1. **dash.cloudflare.com**, same account as the news button worker.
   **Add a domain** → type `maxime-droux.com` → select the **Free** plan.
2. Cloudflare scans your current DNS and shows what it found. **Check the list
   against the records above** before continuing: the four A records on the
   apex, the `www` CNAME, and any MX or TXT records you rely on. Add anything
   missing by hand now.
3. Set the apex record and the `www` record to **Proxied** (the cloud icon
   turns orange). Proxied is what puts Cloudflare in the request path; without
   it Access has nothing to enforce.
4. Cloudflare gives you two nameservers. Go to whoever you bought the domain
   from, find the nameserver setting, and replace what is there with those two.
   Save.
5. Wait for Cloudflare to say **Active**. The site keeps working throughout.
6. Once active: **SSL/TLS** → **Overview** → set the mode to **Full (strict)**.
   If the site starts returning error 526, GitHub has not finished reissuing
   its certificate; drop to **Full**, wait a day, then set Full (strict) again.

Nothing about the site has changed yet. It is the same pages, now served
through Cloudflare.

## 2. Close /people/

1. Left menu: **Zero Trust**. First time through it asks you to pick a team
   name (any word, it becomes `yourteam.cloudflareaccess.com`) and a plan:
   choose **Free**. A card may be requested for verification and is not
   charged on the free plan.
2. **Access** → **Applications** → **Add an application** → **Self-hosted**.
3. Fill in:
   - **Application name:** People directory
   - **Session duration:** 1 month (how long before you sign in again; short
     durations get irritating fast on a phone)
   - **Public hostname:** subdomain empty, domain `maxime-droux.com`,
     **path** `people`
4. Next, add a policy:
   - **Policy name:** Me
   - **Action:** Allow
   - **Include** → selector **Emails** → add `md@climbventures.com`, plus any
     other address you want to be able to open it.
5. On the identity step, leave **One-time PIN** enabled. That emails you a code
   when you sign in and needs no other account. Add Google as well if you
   prefer a tap over a code.
6. **Save**.

## 3. Check it

Open a private window and go to `https://maxime-droux.com/people/`. You should
get a Cloudflare sign-in page, not the directory. Enter an allowed address,
collect the code from your inbox, and the directory loads.

Then check `https://maxime-droux.com/` in the same window. It should load with
no login at all. If it asks for one, the Access application has too broad a
path; go back and confirm the path field says `people`.

## What this does and does not do

- Requests for `/people/` and anything under it are refused before the file is
  sent. That is genuine protection, not a client-side trick.
- The page's source is still readable in the public repository. That does not
  matter: the file contains no contacts. Every person, photo and note lives in
  your browser's local storage and has never been on the server.
- The news button worker is unaffected. It runs on its own `workers.dev`
  hostname and its origin allowlist still matches.
- Your bookmark keeps working. After the first sign-in, a cookie carries you
  through for the session duration you set.

## If you would rather not move the DNS

Two lesser options. Making the repository private stops people reading the
source on GitHub but does not put a login on the site. And you can leave things
as they are: the directory page is public but empty, so a visitor who finds it
sees an empty address book, not yours.
