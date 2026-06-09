# Sync Cloudflare R2 Submissions Into SkyQ

SkyQ can pull submitted target sheets from the Cloudflare R2 bucket into `data/inbox/` before building the master table.

## 1. Install Python Dependency

In the SkyQ Python environment:

```bash
pip install boto3
```

or install all SkyQ dependencies:

```bash
pip install -r requirements.txt
```

## 2. Create R2 API Credentials

In Cloudflare:

```text
R2 Object Storage -> Manage R2 API Tokens -> Create API token
```

Use permissions that can list/read objects from the `skyq-submissions` bucket.

Save:

```text
Access Key ID
Secret Access Key
Account ID
```

## 3. Set Environment Variables

PowerShell local test:

```powershell
$env:SKYQ_ENABLE_R2_SYNC="1"
$env:CLOUDFLARE_ACCOUNT_ID="your_account_id"
$env:R2_ACCESS_KEY_ID="your_access_key_id"
$env:R2_SECRET_ACCESS_KEY="your_secret_access_key"
$env:R2_BUCKET="skyq-submissions"
$env:R2_PREFIX="incoming/"
```

Cluster shell:

```bash
export SKYQ_ENABLE_R2_SYNC=1
export CLOUDFLARE_ACCOUNT_ID="your_account_id"
export R2_ACCESS_KEY_ID="your_access_key_id"
export R2_SECRET_ACCESS_KEY="your_secret_access_key"
export R2_BUCKET="skyq-submissions"
export R2_PREFIX="incoming/"
```

Do not commit these values. On the cluster, put them in a private source file such as `skyq_source.sh`.

## 4. Run Sync Alone

```bash
python -m queue_merge.r2_sync
```

New target sheets are downloaded into:

```text
data/inbox/
```

Metadata JSON files are downloaded into:

```text
reports/r2_submissions/
```

Downloaded object keys are tracked in:

```text
data/r2_sync_state.json
```

so repeated runs do not pull the same object twice.

## 5. Full Pipeline

With `SKYQ_ENABLE_R2_SYNC=1`, the normal SkyQ run performs:

```text
R2 incoming/ -> data/inbox/
data/inbox/ validation -> data/raw/
data/raw/ -> data/master.csv
data/master.csv -> data/observing_plan.csv
observer product pages and plots
```

Run:

```bash
python -u -m bin.runscript
```

## 6. Publish The Completed Observing Plan To The Website

To update the website after each HPCC run, enable publishing:

```bash
export SKYQ_ENABLE_R2_PUBLISH=1
export R2_PUBLISH_PREFIX="published/"
```

The same R2 credentials used for sync are used for publishing. The pipeline publishes the completed table to:

```text
published/latest/observing_plan.csv
published/latest/manifest.json
published/archive/observing_plan_YYYYMMDDTHHMMSSZ.csv
published/latest/products/
```

The Cloudflare Worker serves the latest completed table at:

```text
https://skyq-submission-worker.nic5153mcclure.workers.dev/observing-plan.csv
https://skyq-submission-worker.nic5153mcclure.workers.dev/observing-plan-manifest.json
```

If `data/products/latest/observing_plan_with_products.csv` exists, SkyQ publishes that enriched table. Otherwise it publishes `data/observing_plan.csv`.

The product HTML pages and plots are published under `published/latest/products/` and served by the Worker as:

```text
https://skyq-submission-worker.nic5153mcclure.workers.dev/products/latest/pages/TARGET.html
https://skyq-submission-worker.nic5153mcclure.workers.dev/products/latest/altitude_airmass/PLOT.png
https://skyq-submission-worker.nic5153mcclure.workers.dev/products/latest/sky_path/PLOT.png
```

The observing plan table links to the per-target HTML page only. That page contains all plots, finding charts, and external catalog links.

## 7. Trigger SkyQ When New Submissions Arrive

Cloudflare R2 cannot directly run `sbatch` on the HPCC cluster, so SkyQ includes an HPCC-side trigger. The trigger checks R2 for new submitted target sheets and submits the normal pipeline only when new files are present.

Run one check manually:

```bash
python -u -m bin.trigger_skyq
```

Dry-run a check without submitting:

```bash
python -u -m bin.trigger_skyq --dry-run
```

After first cloning SkyQ on the cluster, mark existing R2 submissions as already seen if you do not want old uploads to trigger a fresh run:

```bash
python -u -m bin.trigger_skyq --mark-seen
```

Force a submission even if no new files are detected:

```bash
python -u -m bin.trigger_skyq --force
```

The trigger submits:

```bash
sbatch runscript_skyq.sbatch
```

It will not submit a duplicate if a `skyq` job is already pending or running.

For continuous polling through Slurm:

```bash
sbatch runscript_skyq_trigger.sbatch
```

By default, the watcher checks every 300 seconds. To change that interval:

```bash
export SKYQ_TRIGGER_CHECK_SECONDS=120
sbatch runscript_skyq_trigger.sbatch
```

Trigger state is tracked in:

```text
data/r2_trigger_state.json
```

Trigger reports are written to:

```text
reports/trigger_latest.txt
reports/trigger_YYYYMMDD_HHMMSS.txt
```
