# SkyQ Cloudflare Submission Worker

This Worker hosts the observer upload form for SkyQ and stores accepted target sheets in Cloudflare R2.

Observer uploads should only require:

```text
name,ra,dec
```

The Worker accepts `.csv`, `.tsv`, and `.txt` sheets. For `.txt` and `.tsv` style files, tabs, single spaces, and padded whitespace are accepted as delimiters.

SkyQ computes all observability columns later on the cluster.

## Cloudflare Setup

0. Install Node.js LTS if `npm` is not available:

```powershell
winget install OpenJS.NodeJS.LTS
```

After installation, close and reopen PowerShell, then verify:

```powershell
node --version
npm --version
npx --version
```

1. Install dependencies:

```bash
npm install
```

2. Log in to the TTU Cloudflare account:

```bash
npx wrangler login
```

3. Create the R2 buckets:

```bash
npx wrangler r2 bucket create skyq-submissions
npx wrangler r2 bucket create skyq-submissions-dev
```

4. Deploy:

```bash
npm run deploy
```

The form will be available at the Worker URL unless you attach a custom route in Cloudflare.

## Temporary Presentation Demo

The Worker also includes a two-page demo site for presentations:

```text
https://skyq-submission-worker.nic5153mcclure.workers.dev/demo/plan
https://skyq-submission-worker.nic5153mcclure.workers.dev/demo/submit
https://skyq-submission-worker.nic5153mcclure.workers.dev/sample.csv
```

`/demo/plan` shows a sample observing-plan table with SkyQ categories and product links. `/demo/submit` shows the live observer upload workflow and posts to the same `/submit` endpoint used by the production form.

After each HPCC SkyQ run publishes the completed table, the demo plan page loads:

```text
https://skyq-submission-worker.nic5153mcclure.workers.dev/observing-plan.csv
```

The publish metadata is available at:

```text
https://skyq-submission-worker.nic5153mcclure.workers.dev/observing-plan-manifest.json
```

## Optional Turnstile

Create a Turnstile widget in Cloudflare, then set:

```toml
[vars]
TURNSTILE_SITE_KEY = "your_public_site_key"
```

Set the secret with:

```bash
npx wrangler secret put TURNSTILE_SECRET_KEY
```

The Worker automatically enforces Turnstile when `TURNSTILE_SECRET_KEY` exists.

## Embed In The Observatory Website

The Worker supports both standalone HTML form submissions and website-driven JSON submissions.

For an observatory website using `fetch()`, add the site origin to `wrangler.toml`:

```toml
[vars]
ALLOWED_ORIGINS = "https://observatory.example.edu"
```

Then redeploy.

Example website form:

```html
<form id="skyq-form">
  <input name="observer_name" required>
  <input name="observer_email" type="email" required>
  <input name="program">
  <input name="target_file" type="file" accept=".csv,.tsv,.txt" required>
  <textarea name="notes"></textarea>
  <button type="submit">Submit Targets</button>
</form>
<output id="skyq-result"></output>

<script>
const form = document.querySelector("#skyq-form");
const result = document.querySelector("#skyq-result");

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const response = await fetch("https://skyq-submission-worker.nic5153mcclure.workers.dev/submit", {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "X-Requested-With": "fetch"
    },
    body: new FormData(form)
  });

  const data = await response.json();
  result.textContent = data.messages.join(" ");
});
</script>
```

Plain HTML forms can also post directly to `/submit`, but they will navigate to the Worker's success/error page:

```html
<form method="post" enctype="multipart/form-data" action="https://skyq-submission-worker.nic5153mcclure.workers.dev/submit">
```

## Stored R2 Layout

Uploads are written as:

```text
incoming/YYYY/MM/DD/TIMESTAMP_filename.csv
incoming/YYYY/MM/DD/TIMESTAMP_filename.csv.metadata.json
```

The metadata file records observer name, email, program, notes, original filename, stored R2 key, and the estimated target count.

## Verify Recent Submissions

Wrangler 4 does not currently provide an `r2 object list` command. Use the Cloudflare Dashboard, the R2 API, or SkyQ's protected admin route.

Set an admin token:

```bash
npx wrangler secret put ADMIN_TOKEN
```

Redeploy, then open:

```text
https://YOUR_WORKER_URL/admin/submissions?token=YOUR_ADMIN_TOKEN
```

This returns recent objects under `incoming/` from the `skyq-submissions` R2 bucket.

## Local Dev

Run:

```bash
npm run dev
```

Local secrets can go in `.dev.vars`, which is ignored by Git.

## Later Cluster Sync

The cluster-side sync should pull new `incoming/` R2 objects into:

```text
data/inbox/
```

Then SkyQ's existing automation can validate them again, move accepted files into `data/raw/`, and generate the observing plan.
