import json
import mimetypes
import os
from datetime import datetime
from html import escape
from pathlib import Path

from queue_merge.r2_sync import build_s3_client, missing_env


PROJECT_DIR = Path.cwd()
DEFAULT_PLAN_PATH = PROJECT_DIR / "data" / "observing_plan.csv"
ENRICHED_PLAN_PATH = PROJECT_DIR / "data" / "products" / "latest" / "observing_plan_with_products.csv"
PRODUCT_DIR = PROJECT_DIR / "data" / "products" / "latest"
PUBLISHED_PLAN_PATH = PROJECT_DIR / "reports" / "published_observing_plan.csv"

PRODUCT_COLUMNS = {
        "product_page_html": "Open observing page",
        "altitude_airmass_plot": "Altitude/airmass plot",
        "sky_path_plot": "Sky-path plot",
}

PRODUCT_LINK_COLUMNS = {
        "product_page_link_html": ("product_page_html", "Open observing page"),
        "altitude_airmass_plot_link_html": ("altitude_airmass_plot", "Altitude/airmass plot"),
        "sky_path_plot_link_html": ("sky_path_plot", "Sky-path plot"),
}


def publish_enabled():
        return os.environ.get("SKYQ_ENABLE_R2_PUBLISH", "").lower() in {"1", "true", "yes", "on"}


def plan_source_path():
        if ENRICHED_PLAN_PATH.exists():
                return ENRICHED_PLAN_PATH

        return DEFAULT_PLAN_PATH


def upload_file(client, bucket, key, path, content_type):
        with path.open("rb") as handle:
                client.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=handle,
                        ContentType=content_type,
                        CacheControl="no-store",
                )


def content_type_for_path(path):
        content_type, _ = mimetypes.guess_type(path.name)
        return content_type or "application/octet-stream"


def product_url(value):
        text = str(value or "").replace("\\", "/")
        marker = "data/products/latest/"

        if not text:
                return ""

        if text.startswith("http://") or text.startswith("https://") or text.startswith("/products/latest/"):
                return text

        if text.startswith(marker):
                return "/products/latest/" + text[len(marker):]

        return text


def html_anchor(href, label):
        if not href:
                return ""

        return f'<a href="{escape(str(href), quote=True)}">{escape(str(label), quote=True)}</a>'


def website_plan_path(source_path):
        if source_path != ENRICHED_PLAN_PATH:
                return source_path

        try:
                import pandas as pd
        except ImportError as exc:
                raise RuntimeError(
                        "Publishing product links requires pandas. Install dependencies with "
                        "`pip install -r requirements.txt`."
                ) from exc

        df = pd.read_csv(source_path)

        for column in PRODUCT_COLUMNS:
                if column in df.columns:
                        df[column] = df[column].apply(product_url)

        for link_column, (href_column, label) in PRODUCT_LINK_COLUMNS.items():
                if link_column in df.columns and href_column in df.columns:
                        df[link_column] = df[href_column].apply(lambda href: html_anchor(href, label))

        PUBLISHED_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(PUBLISHED_PLAN_PATH, index=False)
        return PUBLISHED_PLAN_PATH


def upload_product_assets(client, bucket, prefix):
        if not PRODUCT_DIR.exists():
                return 0

        uploaded = 0

        for path in PRODUCT_DIR.rglob("*"):
                if not path.is_file():
                        continue

                relative = path.relative_to(PRODUCT_DIR).as_posix()
                key = f"{prefix}/latest/products/{relative}"
                upload_file(client, bucket, key, path, content_type_for_path(path))
                uploaded += 1

        return uploaded


def publish_observing_plan(plan_path=None):
        if not publish_enabled():
                print("[r2-publish] Publish disabled. Set SKYQ_ENABLE_R2_PUBLISH=1 to enable.", flush=True)
                return {
                        "enabled": False,
                        "published": False,
                }

        missing = missing_env()

        if missing:
                raise RuntimeError(f"R2 publish missing required environment variables: {', '.join(missing)}")

        source_path = Path(plan_path) if plan_path is not None else plan_source_path()

        if not source_path.exists():
                raise RuntimeError(f"Observing plan CSV does not exist: {source_path}")

        bucket = os.environ.get("R2_BUCKET", "skyq-submissions")
        prefix = os.environ.get("R2_PUBLISH_PREFIX", "published/")
        prefix = prefix.strip("/")

        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        latest_key = f"{prefix}/latest/observing_plan.csv"
        archive_key = f"{prefix}/archive/observing_plan_{stamp}.csv"
        manifest_key = f"{prefix}/latest/manifest.json"

        client = build_s3_client()
        website_csv_path = website_plan_path(source_path)
        product_assets_uploaded = upload_product_assets(client, bucket, prefix)

        upload_file(client, bucket, latest_key, website_csv_path, "text/csv; charset=utf-8")
        upload_file(client, bucket, archive_key, website_csv_path, "text/csv; charset=utf-8")

        manifest = {
                "published_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "source_path": str(source_path),
                "website_csv_path": str(website_csv_path),
                "bucket": bucket,
                "latest_key": latest_key,
                "archive_key": archive_key,
                "product_assets_uploaded": product_assets_uploaded,
                "size_bytes": website_csv_path.stat().st_size,
        }

        client.put_object(
                Bucket=bucket,
                Key=manifest_key,
                Body=json.dumps(manifest, indent=2).encode("utf-8"),
                ContentType="application/json; charset=utf-8",
                CacheControl="no-store",
        )

        print(f"[r2-publish] Published observing plan: {source_path}", flush=True)
        print(f"[r2-publish] Website CSV: {website_csv_path}", flush=True)
        print(f"[r2-publish] Product assets uploaded: {product_assets_uploaded}", flush=True)
        print(f"[r2-publish] Latest key: s3://{bucket}/{latest_key}", flush=True)
        print(f"[r2-publish] Archive key: s3://{bucket}/{archive_key}", flush=True)

        return {
                "enabled": True,
                "published": True,
                "bucket": bucket,
                "prefix": prefix,
                "source_path": str(source_path),
                "website_csv_path": str(website_csv_path),
                "latest_key": latest_key,
                "archive_key": archive_key,
                "manifest_key": manifest_key,
                "product_assets_uploaded": product_assets_uploaded,
                "size_bytes": website_csv_path.stat().st_size,
        }


if __name__ == "__main__":
        print(publish_observing_plan())
