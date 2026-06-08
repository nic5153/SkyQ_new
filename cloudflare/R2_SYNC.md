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
