"""Publish configured datasets and processed CSV resources to CKAN."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from womens_health_upload.ckan_client import (
    CKANAPIError,
    CKANClient,
    CKANNotFoundError,
    CKANSettings,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATASET_CONFIG_PATH = (
    PROJECT_ROOT / "config" / "dataset_config.csv"
)
RESOURCE_CONFIG_PATH = (
    PROJECT_ROOT / "config" / "resource_config.csv"
)
PROCESSED_DATA_ROOT = (
    PROJECT_ROOT / "data" / "processed"
).resolve()

CKAN_NAME_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$"
)


def load_config_rows(path: Path) -> list[dict[str, str]]:
    """Read and clean a CSV configuration table."""

    if not path.is_file():
        raise FileNotFoundError(
            f"Configuration file does not exist: {path}"
        )

    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as config_file:
            reader = csv.DictReader(config_file)

            if not reader.fieldnames:
                raise ValueError(
                    f"Configuration file has no header: {path}"
                )

            rows: list[dict[str, str]] = []

            for line_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"{path.name}, line {line_number}, contains "
                        "more values than its header. Check that text "
                        "containing commas is enclosed in double quotes."
                    )

                cleaned = {
                    str(key).strip(): (
                        "" if value is None else str(value).strip()
                    )
                    for key, value in row.items()
                }

                if any(cleaned.values()):
                    rows.append(cleaned)

    except csv.Error as exc:
        raise ValueError(
            f"Could not parse {path}: {exc}"
        ) from exc

    if not rows:
        raise ValueError(
            f"Configuration file contains no data rows: {path}"
        )

    return rows


def require_columns(
    rows: list[dict[str, str]],
    required: set[str],
    config_name: str,
) -> None:
    """Confirm that a configuration table has required columns."""

    available = set(rows[0])
    missing = sorted(required - available)

    if missing:
        raise ValueError(
            f"{config_name} is missing required column(s): "
            + ", ".join(missing)
        )


def select_dataset(
    dataset_id: str,
    rows: list[dict[str, str]],
) -> dict[str, str]:
    """Return exactly one configured dataset."""

    matches = [
        row
        for row in rows
        if row.get("dataset_id") == dataset_id
    ]

    if not matches:
        raise ValueError(
            f"Dataset ID is not present in dataset_config.csv: "
            f"{dataset_id}"
        )

    if len(matches) > 1:
        raise ValueError(
            f"dataset_config.csv contains duplicate rows for: "
            f"{dataset_id}"
        )

    return matches[0]


def select_resources(
    dataset_id: str,
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Return and validate resources belonging to a dataset."""

    resources = [
        row
        for row in rows
        if row.get("dataset_id") == dataset_id
    ]

    if not resources:
        raise ValueError(
            f"No resources are configured for dataset: {dataset_id}"
        )

    resource_ids = [
        row.get("resource_id", "")
        for row in resources
    ]
    resource_names = [
        row.get("resource_name", "")
        for row in resources
    ]

    if any(not value for value in resource_ids):
        raise ValueError(
            "Every resource row must have a resource_id."
        )

    if any(not value for value in resource_names):
        raise ValueError(
            "Every resource row must have a resource_name."
        )

    if len(resource_ids) != len(set(resource_ids)):
        raise ValueError(
            f"Duplicate resource_id values exist for {dataset_id}."
        )

    if len(resource_names) != len(set(resource_names)):
        raise ValueError(
            f"Duplicate resource_name values exist for {dataset_id}."
        )

    return resources


def validate_dataset_config(
    dataset: dict[str, str],
    settings: CKANSettings,
) -> None:
    """Validate important dataset publishing settings."""

    slug = dataset.get("output_slug", "")
    owner_org = dataset.get("owner_org", "")

    if not CKAN_NAME_PATTERN.fullmatch(slug):
        raise ValueError(
            "output_slug must contain 2–100 lowercase letters, "
            f"numbers or hyphens. Received: {slug!r}"
        )

    if owner_org != settings.owner_org:
        raise ValueError(
            "The dataset owner_org does not match CKAN_OWNER_ORG. "
            f"Config: {owner_org!r}; .env: "
            f"{settings.owner_org!r}"
        )

    for field in ("title", "notes", "topic_name"):
        if not dataset.get(field, "").strip():
            raise ValueError(
                f"Dataset field cannot be empty: {field}"
            )


def validate_processed_csv(local_path: str) -> Path:
    """Resolve and minimally validate a processed CSV resource."""

    path = (PROJECT_ROOT / local_path).resolve()

    try:
        path.relative_to(PROCESSED_DATA_ROOT)
    except ValueError as exc:
        raise ValueError(
            "Resource uploads must come from data/processed. "
            f"Received: {path}"
        ) from exc

    if path.suffix.lower() != ".csv":
        raise ValueError(
            f"Only processed CSV files are currently allowed: {path}"
        )

    if not path.is_file():
        raise FileNotFoundError(
            f"Processed resource does not exist: {path}"
        )

    if path.stat().st_size == 0:
        raise ValueError(
            f"Processed resource is empty: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.reader(csv_file)
        header = next(reader, None)
        first_data_row = next(reader, None)

    if not header or not all(column.strip() for column in header):
        raise ValueError(
            f"CSV has an invalid or incomplete header: {path}"
        )

    if first_data_row is None:
        raise ValueError(
            f"CSV contains a header but no data rows: {path}"
        )

    return path


def get_topic_tag(
    client: CKANClient,
    topic_name: str,
) -> dict[str, str]:
    """Find a topic in CKAN's controlled Topics vocabulary."""

    vocabularies = client.action("vocabulary_list")

    topics_vocabulary = next(
        (
            vocabulary
            for vocabulary in vocabularies
            if str(vocabulary.get("name", "")).lower()
            == "topics"
        ),
        None,
    )

    if topics_vocabulary is None:
        raise CKANAPIError(
            "CKAN does not contain a vocabulary named 'Topics'."
        )

    vocabulary_id = topics_vocabulary["id"]

    tags = client.action(
        "tag_list",
        {
            "vocabulary_id": vocabulary_id,
            "all_fields": True,
        },
    )

    matching_tag = next(
        (
            tag
            for tag in tags
            if str(tag.get("name", "")).casefold()
            == topic_name.casefold()
        ),
        None,
    )

    if matching_tag is None:
        available_topics = sorted(
            str(tag.get("name", ""))
            for tag in tags
            if tag.get("name")
        )

        raise CKANAPIError(
            f"Topic {topic_name!r} is not present in CKAN's "
            "'Topics' vocabulary. Available topics: "
            + ", ".join(available_topics)
        )

    return {
        "name": str(matching_tag["name"]),
        "vocabulary_id": str(vocabulary_id),
    }


def get_ogl_license_id(
    client: CKANClient,
) -> str | None:
    """Use CKAN's Open Government Licence when available."""

    licences = client.action(
        "license_list",
        authenticated=False,
    )

    licence_ids = {
        str(licence.get("id", ""))
        for licence in licences
    }

    for candidate in (
        "uk-ogl",
        "uk-ogl-3.0",
        "ogl-3.0",
    ):
        if candidate in licence_ids:
            return candidate

    return None


def find_existing_dataset(
    client: CKANClient,
    slug: str,
) -> dict[str, Any] | None:
    """Return an existing dataset or None when it does not exist."""

    try:
        result = client.action(
            "package_show",
            {"id": slug},
        )
    except CKANNotFoundError:
        return None

    if not isinstance(result, dict):
        raise CKANAPIError(
            "package_show returned an unexpected result."
        )

    return result


def build_dataset_payload(
    dataset: dict[str, str],
    client: CKANClient,
) -> dict[str, Any]:
    """Construct the CKAN dataset metadata payload."""

    payload: dict[str, Any] = {
        "name": dataset["output_slug"],
        "title": dataset["title"],
        "notes": dataset["notes"],
        "owner_org": dataset["owner_org"],
        "tags": [
            get_topic_tag(
                client,
                dataset["topic_name"],
            )
        ],
    }

    source_url = dataset.get("source_url", "").strip()
    if source_url:
        payload["url"] = source_url

    licence_id = get_ogl_license_id(client)
    if licence_id:
        payload["license_id"] = licence_id

    return payload


def find_existing_resource(
    package: dict[str, Any] | None,
    resource_name: str,
) -> dict[str, Any] | None:
    """Match a managed CKAN resource by its exact name."""

    if package is None:
        return None

    matches = [
        resource
        for resource in package.get("resources", [])
        if resource.get("name") == resource_name
    ]

    if len(matches) > 1:
        raise CKANAPIError(
            "More than one existing CKAN resource has the name "
            f"{resource_name!r}. Resolve the duplicate manually."
        )

    return matches[0] if matches else None


def require_upload_approval(
    dataset: dict[str, str],
    resources: list[dict[str, str]],
) -> None:
    """Require explicit upload decisions before a live write."""

    if dataset.get("upload_decision", "").lower() != "upload":
        raise ValueError(
            "Live publication is blocked because the dataset's "
            "upload_decision is not 'upload'."
        )

    blocked_resources = [
        resource["resource_id"]
        for resource in resources
        if resource.get(
            "upload_decision",
            "",
        ).lower() != "upload"
    ]

    if blocked_resources:
        raise ValueError(
            "Live publication is blocked for resource(s): "
            + ", ".join(blocked_resources)
            + ". Set their upload_decision to 'upload' only "
            "after reviewing the dry run."
        )


def print_dry_run(
    dataset_action: str,
    dataset_payload: dict[str, Any],
    existing_package: dict[str, Any] | None,
    resources: list[dict[str, str]],
) -> None:
    """Display the intended actions without changing CKAN."""

    print("[DRY RUN] No CKAN data will be created or modified.")
    print(f"[DRY RUN] Dataset action: {dataset_action}")
    print("[DRY RUN] Dataset payload:")
    print(json.dumps(dataset_payload, indent=2))

    for resource in resources:
        path = validate_processed_csv(
            resource["local_path"]
        )
        existing = find_existing_resource(
            existing_package,
            resource["resource_name"],
        )

        resource_action = (
            "resource_patch"
            if existing is not None
            else "resource_create"
        )

        print(
            f"[DRY RUN] Resource action: {resource_action}"
        )
        print(
            f"[DRY RUN] Resource name: "
            f"{resource['resource_name']}"
        )
        print(f"[DRY RUN] Local file: {path}")
        print(
            f"[DRY RUN] File size: "
            f"{path.stat().st_size:,} bytes"
        )

    print(
        "[DRY RUN] Review the metadata and decisions above. "
        "Do not use --apply until they are correct."
    )


def publish_resources(
    client: CKANClient,
    package: dict[str, Any],
    resources: list[dict[str, str]],
) -> None:
    """Create or update configured CKAN file resources."""

    package_id = str(package["id"])

    for resource in resources:
        path = validate_processed_csv(
            resource["local_path"]
        )

        existing = find_existing_resource(
            package,
            resource["resource_name"],
        )

        resource_payload: dict[str, Any] = {
            "name": resource["resource_name"],
            "description": resource.get(
                "description",
                "",
            ),
            "format": resource.get(
                "format",
                "CSV",
            ).upper(),
        }

        if existing is None:
            action_name = "resource_create"
            resource_payload["package_id"] = package_id
        else:
            action_name = "resource_patch"
            resource_payload["id"] = existing["id"]

        print(
            f"[APPLY] {action_name}: "
            f"{resource['resource_name']}"
        )

        uploaded = client.upload_resource(
            action_name,
            resource_payload,
            path,
        )

        print(
            f"[OK] Uploaded resource: "
            f"{uploaded.get('name', resource['resource_name'])}"
        )


def run(dataset_id: str, *, apply: bool) -> None:
    """Prepare a dry run or publish one configured dataset."""

    settings = CKANSettings.from_env()
    client = CKANClient(settings)

    dataset_rows = load_config_rows(
        DATASET_CONFIG_PATH
    )
    resource_rows = load_config_rows(
        RESOURCE_CONFIG_PATH
    )

    require_columns(
        dataset_rows,
        {
            "dataset_id",
            "source_url",
            "output_slug",
            "title",
            "notes",
            "topic_name",
            "owner_org",
            "upload_decision",
        },
        DATASET_CONFIG_PATH.name,
    )

    require_columns(
        resource_rows,
        {
            "resource_id",
            "dataset_id",
            "resource_name",
            "description",
            "format",
            "local_path",
            "upload_decision",
        },
        RESOURCE_CONFIG_PATH.name,
    )

    dataset = select_dataset(
        dataset_id,
        dataset_rows,
    )
    resources = select_resources(
        dataset_id,
        resource_rows,
    )

    validate_dataset_config(dataset, settings)

    for resource in resources:
        validate_processed_csv(
            resource["local_path"]
        )

    dataset_payload = build_dataset_payload(
        dataset,
        client,
    )

    slug = dataset["output_slug"]
    existing_package = find_existing_dataset(
        client,
        slug,
    )

    if existing_package is None:
        dataset_action = "package_create"
    else:
        dataset_action = "package_patch"
        dataset_payload["id"] = existing_package["id"]

    if not apply:
        print_dry_run(
            dataset_action,
            dataset_payload,
            existing_package,
            resources,
        )
        return

    require_upload_approval(dataset, resources)

    print(
        f"[APPLY] {dataset_action}: {slug}"
    )
    package = client.action(
        dataset_action,
        dataset_payload,
    )

    if not isinstance(package, dict):
        raise CKANAPIError(
            f"{dataset_action} returned an unexpected result."
        )

    print(
        f"[OK] Dataset metadata saved: "
        f"{package.get('title', slug)}"
    )

    publish_resources(
        client,
        package,
        resources,
    )

    final_package = client.action(
        "package_show",
        {"id": slug},
    )

    resource_count = len(
        final_package.get("resources", [])
    )

    print(
        f"[OK] CKAN reports {resource_count} resource(s)."
    )
    print(
        f"[OK] Public dataset URL: "
        f"{settings.site_url}/dataset/{slug}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or publish a configured women's health "
            "dataset to CKAN."
        )
    )
    parser.add_argument(
        "dataset_id",
        help="The dataset_id from config/dataset_config.csv.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Perform CKAN writes. Without this option, the "
            "publisher only produces a dry run."
        ),
    )

    arguments = parser.parse_args()

    run(
        arguments.dataset_id,
        apply=arguments.apply,
    )


if __name__ == "__main__":
    try:
        main()
    except (
        CKANAPIError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc