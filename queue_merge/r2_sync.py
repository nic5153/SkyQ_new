import json
import os
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path.cwd()
INBOX_DIR = PROJECT_DIR / "data" / "inbox"
STATE_PATH = PROJECT_DIR / "data" / "r2_sync_state.json"
METADATA_DIR = PROJECT_DIR / "reports" / "r2_submissions"

SUPPORTED_SUFFIXES = {".csv", ".tsv", ".txt"}
REQUIRED_ENV = [
        "CLOUDFLARE_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
]


def sync_enabled():
        return os.environ.get("SKYQ_ENABLE_R2_SYNC", "").lower() in {"1", "true", "yes", "on"}


def missing_env():
        return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def load_state():
        if not STATE_PATH.exists():
                return {"downloaded": {}}

        with STATE_PATH.open("r", encoding="utf-8") as handle:
                return json.load(handle)


def save_state(state):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

        with STATE_PATH.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)


def object_suffix(key):
        path = Path(key)
        suffixes = path.suffixes

        if key.endswith(".metadata.json"):
                return ".metadata.json"

        return suffixes[-1].lower() if suffixes else ""


def is_target_sheet(key):
        return object_suffix(key) in SUPPORTED_SUFFIXES


def is_metadata(key):
        return key.endswith(".metadata.json")


def safe_filename_from_key(key):
        name = Path(key).name
        return "".join(char if char.isalnum() or char in "._-" else "_" for char in name)


def unique_path(directory, filename):
        path = directory / filename

        if not path.exists():
                return path

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return directory / f"{path.stem}_{stamp}{path.suffix}"


def build_s3_client():
        try:
                import boto3
        except ImportError as exc:
                raise RuntimeError(
                        "R2 sync requires boto3. Install it with `pip install boto3` "
                        "in the SkyQ environment."
                ) from exc

        account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        access_key_id = os.environ["R2_ACCESS_KEY_ID"]
        secret_access_key = os.environ["R2_SECRET_ACCESS_KEY"]
        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

        if len(access_key_id) != 32:
                raise RuntimeError(
                        "R2_ACCESS_KEY_ID does not look like an R2 S3 Access Key ID. "
                        "Create an R2 API token from Cloudflare R2 Object Storage -> "
                        "Manage R2 API Tokens, then use its Access Key ID, not a "
                        "Cloudflare API token ID."
                )

        return boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name="auto",
        )


def list_objects(client, bucket, prefix):
        paginator = client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                        yield item


def download_object(client, bucket, key, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, key, str(destination))


def sync_r2_submissions():
        if not sync_enabled():
                print("[r2] Sync disabled. Set SKYQ_ENABLE_R2_SYNC=1 to enable.", flush=True)
                return {
                        "enabled": False,
                        "downloaded_files": 0,
                        "downloaded_metadata": 0,
                }

        missing = missing_env()

        if missing:
                raise RuntimeError(f"R2 sync missing required environment variables: {', '.join(missing)}")

        bucket = os.environ.get("R2_BUCKET", "skyq-submissions")
        prefix = os.environ.get("R2_PREFIX", "incoming/")
        client = build_s3_client()
        state = load_state()
        downloaded = state.setdefault("downloaded", {})

        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        METADATA_DIR.mkdir(parents=True, exist_ok=True)

        downloaded_files = 0
        downloaded_metadata = 0
        seen_objects = 0

        for item in list_objects(client, bucket, prefix):
                seen_objects += 1
                key = item["Key"]
                etag = str(item.get("ETag", "")).strip('"')
                state_key = f"{key}:{etag}"

                if downloaded.get(key) == etag:
                        continue

                if is_metadata(key):
                        metadata_path = unique_path(METADATA_DIR, safe_filename_from_key(key))
                        download_object(client, bucket, key, metadata_path)
                        downloaded[key] = etag
                        downloaded_metadata += 1
                        print(f"[r2] Downloaded metadata {key} -> {metadata_path}", flush=True)
                        continue

                if not is_target_sheet(key):
                        print(f"[r2] Skipping unsupported object: {key}", flush=True)
                        downloaded[key] = etag
                        continue

                inbox_path = unique_path(INBOX_DIR, safe_filename_from_key(key))
                download_object(client, bucket, key, inbox_path)
                downloaded[key] = etag
                downloaded_files += 1
                print(f"[r2] Downloaded target sheet {key} -> {inbox_path}", flush=True)

        state["last_sync_utc"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        save_state(state)

        print(
                f"[r2] Sync complete: {downloaded_files} target files, "
                f"{downloaded_metadata} metadata files, {seen_objects} objects seen",
                flush=True,
        )

        return {
                "enabled": True,
                "bucket": bucket,
                "prefix": prefix,
                "objects_seen": seen_objects,
                "downloaded_files": downloaded_files,
                "downloaded_metadata": downloaded_metadata,
        }


if __name__ == "__main__":
        print(sync_r2_submissions())
