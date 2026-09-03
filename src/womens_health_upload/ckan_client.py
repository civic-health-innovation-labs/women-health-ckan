"""Secure client for the CKAN Action API."""

from __future__ import annotations

import mimetypes
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


class CKANAPIError(RuntimeError):
    """Raised when CKAN or the network returns an unsuccessful response."""


class CKANNotFoundError(CKANAPIError):
    """Raised when a requested CKAN object does not exist."""


@dataclass(frozen=True)
class CKANSettings:
    """Connection settings loaded from the local .env file."""

    site_url: str
    api_key: str
    owner_org: str

    @classmethod
    def from_env(cls) -> CKANSettings:
        """Load and validate CKAN settings from .env."""

        load_dotenv()

        site_url = os.getenv("CKAN_SITE_URL", "").strip().rstrip("/")
        api_key = os.getenv("CKAN_API_KEY", "").strip()
        owner_org = os.getenv("CKAN_OWNER_ORG", "").strip()

        missing = [
            name
            for name, value in (
                ("CKAN_SITE_URL", site_url),
                ("CKAN_API_KEY", api_key),
                ("CKAN_OWNER_ORG", owner_org),
            )
            if not value
        ]

        if missing:
            raise ValueError(
                "Missing required environment variable(s): "
                + ", ".join(missing)
            )

        if not site_url.startswith("https://"):
            raise ValueError(
                "CKAN_SITE_URL must use HTTPS. "
                f"Received: {site_url!r}"
            )

        if api_key == "your_api_key_here":
            raise ValueError(
                "CKAN_API_KEY still contains the placeholder value."
            )

        if owner_org == "your_owner_org_slug":
            raise ValueError(
                "CKAN_OWNER_ORG still contains the placeholder value."
            )

        return cls(
            site_url=site_url,
            api_key=api_key,
            owner_org=owner_org,
        )


class CKANClient:
    """Client for JSON CKAN actions and multipart resource uploads."""

    def __init__(
        self,
        settings: CKANSettings,
        *,
        connect_timeout: int = 10,
        response_timeout: int = 120,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.timeout = (connect_timeout, response_timeout)
        self.session = session or requests.Session()

    def action(
        self,
        action_name: str,
        data: Mapping[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> Any:
        """Call a CKAN Action API endpoint using a JSON request."""

        url = self._action_url(action_name)

        headers = {
            "Accept": "application/json",
        }

        if authenticated:
            headers["Authorization"] = self.settings.api_key

        try:
            response = self.session.post(
                url,
                headers=headers,
                json=dict(data or {}),
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise CKANAPIError(
                f"Network error while calling {action_name}: {exc}"
            ) from exc

        return self._parse_response(action_name, response)

    def upload_resource(
        self,
        action_name: str,
        resource_data: Mapping[str, Any],
        file_path: str | Path,
    ) -> dict[str, Any]:
        """
        Upload a local file using resource_create or resource_patch.

        CKAN file uploads require multipart/form-data rather than JSON.
        """

        if action_name not in {"resource_create", "resource_patch"}:
            raise ValueError(
                "File uploads are restricted to resource_create "
                "and resource_patch."
            )

        path = Path(file_path).expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(
                f"Resource file does not exist: {path}"
            )

        mime_type = (
            mimetypes.guess_type(path.name)[0]
            or "application/octet-stream"
        )

        form_data = {
            key: str(value)
            for key, value in resource_data.items()
            if value is not None and str(value).strip() != ""
        }

        headers = {
            "Authorization": self.settings.api_key,
            "Accept": "application/json",
        }

        url = self._action_url(action_name)

        try:
            with path.open("rb") as upload_handle:
                response = self.session.post(
                    url,
                    headers=headers,
                    data=form_data,
                    files={
                        "upload": (
                            path.name,
                            upload_handle,
                            mime_type,
                        )
                    },
                    timeout=self.timeout,
                    allow_redirects=False,
                )
        except requests.RequestException as exc:
            raise CKANAPIError(
                f"Network error while uploading {path.name}: {exc}"
            ) from exc

        result = self._parse_response(action_name, response)

        if not isinstance(result, dict):
            raise CKANAPIError(
                f"{action_name} returned an unexpected result."
            )

        return result

    def _action_url(self, action_name: str) -> str:
        """Construct a CKAN Action API URL."""

        if not action_name or not action_name.replace("_", "").isalnum():
            raise ValueError(
                f"Invalid CKAN action name: {action_name!r}"
            )

        return (
            f"{self.settings.site_url}/api/3/action/{action_name}"
        )

    @staticmethod
    def _parse_response(
        action_name: str,
        response: requests.Response,
    ) -> Any:
        """Validate and extract a CKAN API response."""

        if 300 <= response.status_code < 400:
            location = response.headers.get("Location", "unknown")
            raise CKANAPIError(
                f"CKAN unexpectedly redirected {action_name} to "
                f"{location}. The API key was not forwarded."
            )

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise CKANAPIError(
                f"{action_name} returned HTTP "
                f"{response.status_code} with a non-JSON response."
            ) from exc

        error = response_payload.get("error", {})

        if isinstance(error, dict):
            error_type = str(error.get("__type", ""))
            error_message = (
                error.get("message")
                or error.get("__type")
                or response.reason
                or "Unknown CKAN error"
            )
        else:
            error_type = str(error)
            error_message = str(error) or response.reason

        if (
            response.status_code == 404
            or "not found" in error_type.lower()
        ):
            raise CKANNotFoundError(
                f"CKAN object was not found during {action_name}."
            )

        if (
            not response.ok
            or response_payload.get("success") is not True
        ):
            raise CKANAPIError(
                f"{action_name} failed with HTTP "
                f"{response.status_code}: {error_message}"
            )

        return response_payload["result"]