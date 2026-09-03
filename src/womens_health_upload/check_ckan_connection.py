"""Verify CKAN connectivity and publishing permission without making changes."""

from womens_health_upload.ckan_client import (
    CKANAPIError,
    CKANClient,
    CKANSettings,
)


def main() -> None:
    settings = CKANSettings.from_env()
    client = CKANClient(settings)

    print(f"Testing CKAN site: {settings.site_url}")
    print(f"Configured owner organisation: {settings.owner_org}")
    print("The API key will not be displayed.")

    status = client.action(
        "status_show",
        authenticated=False,
    )

    version = status.get("ckan_version", "unknown")
    site_title = status.get("site_title", "unknown")

    print(f"[OK] CKAN site responded: {site_title}")
    print(f"[OK] CKAN version: {version}")

    organisation = client.action(
        "organization_show",
        {"id": settings.owner_org},
    )

    print(
        "[OK] Organisation exists: "
        f"{organisation.get('title', settings.owner_org)}"
    )

    permitted_organisations = client.action(
        "organization_list_for_user",
        {"permission": "create_dataset"},
    )

    permitted_names = {
        organisation_record.get("name")
        for organisation_record in permitted_organisations
    }

    if settings.owner_org not in permitted_names:
        raise CKANAPIError(
            "The API key is valid. The user does not appear to have "
            f"create_dataset permission for '{settings.owner_org}'."
        )

    print(
        "[OK] API user has create_dataset permission for "
        f"{settings.owner_org}."
    )
    print("[OK] Read-only CKAN connection check completed.")
    print("No dataset or resource was created or modified.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, CKANAPIError) as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc