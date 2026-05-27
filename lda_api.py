"""
Helper utilities for interacting with the U.S. Senate Lobbying Disclosure API.

The module supports:
* Searching clients or lobbyists by name.
* Retrieving filings filtered by client or lobbyist.
* Downloading the printable disclosure document for a filing UUID.
* Saving complete result sets to JSON or CSV for downstream analysis.

Example:
    from lda_api import LDAClient

    client = LDAClient(token="your_api_token_here")
    matches = client.search_clients("Acme")
    filings = client.list_filings(client_id=matches["results"][0]["id"])
    client.download_filing_document(filings["results"][0]["filing_uuid"], "first_filing.html")
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import time
from typing import Any, Dict, Iterable, List, Optional

import requests
from requests import Response
from requests.exceptions import HTTPError, Timeout


BASE_API_URL = "https://lda.senate.gov/api/v1"
FILINGS_PRINT_URL = "https://lda.senate.gov/filings/public/filing/{uuid}/print/"
SIMPLE_CSV_FIELDS = [
    "registrant_name",
    "registrant_address",
    "registrant_contact",
    "registrant_phone",
    "senate_id",
    "client_name",
    "filing_information",
    "income",
    "expenses",
    "expenses_method",
    "dt_posted",
    "description",
    "government_entities",
    "filing_uuid",
    "filing_document_url",
]


class LDAClient:
    """Simple REST API wrapper for the Senate Lobbying Disclosure endpoints."""

    def __init__(self, token: str, base_url: str = BASE_API_URL, timeout: float = 60.0) -> None:
        if not token:
            raise ValueError("API token is required.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Token {token}", "Accept": "application/json"})

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Issue a GET request and return JSON data."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempts = 0
        while True:
            attempts += 1
            try:
                response: Response = self._session.get(url, params=params, timeout=self.timeout)
                break
            except Timeout as exc:
                if attempts >= 2:
                    raise RuntimeError(
                        f"Request to {url} timed out after {self.timeout} seconds."
                    ) from exc
                time.sleep(1)
        try:
            response.raise_for_status()
        except HTTPError as exc:
            detail = response.text
            raise RuntimeError(f"Request failed: {response.status_code} {detail}") from exc
        return response.json()

    def search_clients(self, name: str, page: int = 1, page_size: int = 25) -> Dict[str, Any]:
        """Search client records by reported client name."""
        params = {"client_name": name, "page": page, "page_size": page_size}
        return self._request("clients/", params=params)

    def search_lobbyists(self, name: str, page: int = 1, page_size: int = 25) -> Dict[str, Any]:
        """Search lobbyist records by lobbyist name."""
        params = {"lobbyist_name": name, "page": page, "page_size": page_size}
        return self._request("lobbyists/", params=params)

    def list_filings(
        self,
        *,
        client_id: Optional[int] = None,
        client_name: Optional[str] = None,
        lobbyist_id: Optional[int] = None,
        lobbyist_name: Optional[str] = None,
        page: int = 1,
        page_size: int = 25,
        additional_filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve filings filtered by client or lobbyist.

        At least one filtering parameter must be supplied when requesting `page > 1`
        to comply with the API pagination rules.
        """
        filters: Dict[str, Any] = {
            "page": page,
            "page_size": page_size,
        }

        if client_id is not None:
            filters["client_id"] = client_id
        if client_name:
            filters["client_name"] = client_name
        if lobbyist_id is not None:
            filters["lobbyist_id"] = lobbyist_id
        if lobbyist_name:
            filters["lobbyist_name"] = lobbyist_name
        if additional_filters:
            filters.update(additional_filters)

        has_filter = any(
            key in filters
            for key in ("client_id", "client_name", "lobbyist_id", "lobbyist_name")
        )

        if page > 1 and not has_filter:
            raise ValueError("The API requires at least one filter when requesting page > 1.")

        return self._request("filings/", params=filters)

    def list_all_filings(
        self,
        *,
        client_id: Optional[int] = None,
        client_name: Optional[str] = None,
        lobbyist_id: Optional[int] = None,
        lobbyist_name: Optional[str] = None,
        page_size: int = 25,
        additional_filters: Optional[Dict[str, Any]] = None,
        pause_seconds: float = 0.0,
        max_pages: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve every page of filings for the provided filters.

        Parameters mirror `list_filings` with added controls for pacing requests.
        """
        all_results = []
        first_response: Optional[Dict[str, Any]] = None
        page = 1

        while True:
            response = self.list_filings(
                client_id=client_id,
                client_name=client_name,
                lobbyist_id=lobbyist_id,
                lobbyist_name=lobbyist_name,
                page=page,
                page_size=page_size,
                additional_filters=additional_filters,
            )

            if first_response is None:
                first_response = response

            all_results.extend(response.get("results", []))

            next_page_exists = bool(response.get("next"))
            if max_pages is not None and page >= max_pages:
                next_page_exists = False

            if not next_page_exists:
                merged = dict(first_response)
                merged["results"] = all_results
                merged["fetched_pages"] = page
                return merged

            page += 1
            if pause_seconds > 0:
                time.sleep(pause_seconds)

    def download_filing_document(self, filing_uuid: str, destination: str | pathlib.Path) -> pathlib.Path:
        """
        Download the printable disclosure document for the provided filing UUID.
        The API serves HTML; saving with .html preserves formatting. If you prefer PDF,
        open the URL in a browser and print to PDF.
        """
        url = FILINGS_PRINT_URL.format(uuid=filing_uuid)
        path = pathlib.Path(destination)
        response = self._session.get(url, timeout=self.timeout)
        try:
            response.raise_for_status()
        except HTTPError as exc:
            raise RuntimeError(f"Failed to download filing {filing_uuid}: {response.status_code}") from exc
        path.write_bytes(response.content)
        return path


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search and download Lobbying Disclosure filings.")
    parser.add_argument("--token", required=True, help="API token issued by OPR.")
    parser.add_argument("--client-name", help="Client name filter.")
    parser.add_argument("--client-id", type=int, help="Client ID filter.")
    parser.add_argument("--lobbyist-name", help="Lobbyist name filter.")
    parser.add_argument("--lobbyist-id", type=int, help="Lobbyist ID filter.")
    parser.add_argument("--page", type=int, default=1, help="Pagination page (default: 1).")
    parser.add_argument("--page-size", type=int, default=25, help="Results per page (default: 25).")
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-request timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--download-first",
        metavar="PATH",
        help="Download the first filing in the result set to PATH.",
    )
    parser.add_argument(
        "--all-pages",
        action="store_true",
        help="Fetch all pages of filings that match the filters.",
    )
    parser.add_argument(
        "--output-json",
        metavar="FILE",
        help="Write the filings JSON payload to FILE.",
    )
    parser.add_argument(
        "--output-csv",
        metavar="FILE",
        help="Write a flattened CSV summary of the filings to FILE.",
    )
    parser.add_argument(
        "--output-simple-csv",
        metavar="FILE",
        help="Write a simplified CSV with curated columns.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.25,
        help="Seconds to pause between paginated requests when fetching all pages (default: 0.25).",
    )
    return parser


def _flatten_record(record: Dict[str, Any], prefix: str = "", sep: str = ".") -> Dict[str, Any]:
    """Flatten nested dictionaries into a single dictionary with dotted keys."""
    items: Dict[str, Any] = {}
    for key, value in record.items():
        new_key = f"{prefix}{sep}{key}" if prefix else str(key)
        if isinstance(value, dict):
            items.update(_flatten_record(value, new_key, sep))
        elif isinstance(value, list):
            # Lists can include dicts; JSON encode to keep structure intact.
            items[new_key] = json.dumps(value, ensure_ascii=False)
        else:
            items[new_key] = value
    return items


def _write_csv(
    path: pathlib.Path,
    rows: Iterable[Dict[str, Any]],
    *,
    fieldnames: Optional[Iterable[str]] = None,
) -> None:
    """Write flattened rows to CSV with headers determined from the data."""
    flattened_rows = [dict(row) for row in rows]
    resolved_fields = (
        list(fieldnames)
        if fieldnames is not None
        else sorted({key for row in flattened_rows for key in row})
    )
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=resolved_fields)
        writer.writeheader()
        for row in flattened_rows:
            writer.writerow(row)


def _unique(values: Iterable[Any]) -> List[Any]:
    seen = set()
    ordered: List[Any] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _format_address(parts: Iterable[Any]) -> str:
    return ", ".join(str(part).strip() for part in parts if part and str(part).strip())


def _format_person_name(data: Dict[str, Any]) -> str:
    parts = [
        data.get("prefix_display") or data.get("prefix"),
        data.get("first_name"),
        data.get("middle_name"),
        data.get("last_name"),
        data.get("suffix_display") or data.get("suffix"),
    ]
    return " ".join(str(part).strip() for part in parts if part and str(part).strip())


def _simplified_row(record: Dict[str, Any]) -> Dict[str, Any]:
    registrant = record.get("registrant") or {}
    client = record.get("client") or {}

    addr_line_1 = record.get("registrant_address_1") or registrant.get("address_1")
    addr_line_2 = record.get("registrant_address_2") or registrant.get("address_2")
    city = record.get("registrant_city") or registrant.get("city")
    state = record.get("registrant_state") or registrant.get("state_display") or registrant.get("state")
    postal = record.get("registrant_zip") or registrant.get("zip")
    country = record.get("registrant_country") or registrant.get("country_display") or registrant.get("country")

    registrant_address = _format_address(
        [addr_line_1, addr_line_2, city, state, postal, country]
    )

    client_location = _format_address(
        [
            client.get("state_display") or client.get("state"),
            client.get("country_display") or client.get("country"),
        ]
    )

    client_ppb_location = _format_address(
        [
            client.get("ppb_state_display") or client.get("ppb_state"),
            client.get("ppb_country_display") or client.get("ppb_country"),
        ]
    )

    government_entities = _unique(
        entity.get("name")
        for activity in record.get("lobbying_activities", [])
        for entity in activity.get("government_entities", [])
    )

    activity_descriptions = _unique(
        _normalize_text(activity.get("description"))
        for activity in record.get("lobbying_activities", [])
    )

    registrant_id = registrant.get("id")
    client_legacy_id = client.get("client_id") or client.get("id")
    senate_id = None
    if registrant_id and client_legacy_id:
        senate_id = f"{registrant_id}-{client_legacy_id}"

    return {
        "registrant_name": registrant.get("name"),
        "registrant_address": registrant_address,
        "registrant_contact": registrant.get("contact_name"),
        "registrant_phone": registrant.get("contact_telephone"),
        "senate_id": senate_id,
        "client_name": client.get("name"),
        "filing_information": " | ".join(
            part
            for part in [
                str(record.get("filing_year")),
                record.get("filing_period_display") or record.get("filing_period"),
                record.get("filing_type_display") or record.get("filing_type"),
            ]
            if part
        ),
        "income": record.get("income"),
        "expenses": record.get("expenses"),
        "expenses_method": record.get("expenses_method_display") or record.get("expenses_method"),
        "dt_posted": record.get("dt_posted"),
        "description": "; ".join(activity_descriptions),
        "government_entities": "; ".join(government_entities),
        "filing_uuid": record.get("filing_uuid"),
        "filing_document_url": record.get("filing_document_url"),
    }


def main() -> None:
    parser = _build_cli()
    args = parser.parse_args()

    client = LDAClient(token=args.token, timeout=args.timeout)

    if args.client_name and not args.client_id:
        client_results = client.search_clients(args.client_name, page=1)
        print(f"Found {client_results.get('count', 0)} client match(es). Showing first page.")
        for entry in client_results.get("results", []):
            name = entry.get("client_name") or entry.get("name") or "<unknown>"
            legacy_id = entry.get("client_id") or ""
            legacy_suffix = f" (Legacy client_id: {legacy_id})" if legacy_id else ""
            print(f"Client ID {entry.get('id', '?')}: {name}{legacy_suffix}")

    if args.lobbyist_name and not args.lobbyist_id:
        lobbyist_results = client.search_lobbyists(args.lobbyist_name, page=1)
        print(f"Found {lobbyist_results.get('count', 0)} lobbyist match(es). Showing first page.")
        for entry in lobbyist_results.get("results", []):
            registrant = entry.get("registrant") or {}
            registrant_name = registrant.get("name") or registrant.get("registrant_name") or "Unknown Registrant"
            lobbyist_name = entry.get("lobbyist_name") or entry.get("name") or "<unknown>"
            print(f"Lobbyist ID {entry.get('id', '?')}: {lobbyist_name} (Registrant: {registrant_name})")

    fetch_all = (
        args.all_pages
        or bool(args.output_json)
        or bool(args.output_csv)
        or bool(args.output_simple_csv)
    )

    if fetch_all:
        filings = client.list_all_filings(
            client_id=args.client_id,
            client_name=args.client_name,
            lobbyist_id=args.lobbyist_id,
            lobbyist_name=args.lobbyist_name,
            page_size=args.page_size,
            pause_seconds=max(args.pause, 0.0),
        )
    else:
        filings = client.list_filings(
            client_id=args.client_id,
            client_name=args.client_name,
            lobbyist_id=args.lobbyist_id,
            lobbyist_name=args.lobbyist_name,
            page=args.page,
            page_size=args.page_size,
        )

    results = filings.get("results", [])
    print(f"\nFilings count: {filings.get('count', 0)}")

    display_slice = results if not fetch_all else results[: args.page_size]
    for entry in display_slice:
        registrant = entry.get("registrant") or {}
        registrant_name = registrant.get("name") or registrant.get("registrant_name") or "Unknown Registrant"
        print(
            f"Filing UUID: {entry.get('filing_uuid')}, "
            f"Type: {entry.get('filing_type')}, "
            f"Registrant: {registrant_name} "
            f"({entry.get('filing_year')})"
        )

    if fetch_all and len(results) > len(display_slice):
        remaining = len(results) - len(display_slice)
        print(f"...and {remaining} more filings (use --output-json/--output-csv to save everything).")

    if args.output_json:
        output_path = pathlib.Path(args.output_json)
        output_path.write_text(json.dumps(filings, indent=2))
        print(f"\nWrote {len(results)} filings to {output_path.resolve()}")

    if args.output_csv:
        csv_path = pathlib.Path(args.output_csv)
        flattened = (_flatten_record(entry) for entry in results)
        _write_csv(csv_path, flattened)
        print(f"Wrote CSV summary with {len(results)} rows to {csv_path.resolve()}")

    if args.output_simple_csv:
        simple_path = pathlib.Path(args.output_simple_csv)
        simplified_rows = (_simplified_row(entry) for entry in results)
        _write_csv(simple_path, simplified_rows, fieldnames=SIMPLE_CSV_FIELDS)
        print(f"Wrote simplified CSV with {len(results)} rows to {simple_path.resolve()}")

    if args.download_first and filings.get("results"):
        first_uuid = filings["results"][0].get("filing_uuid")
        if not first_uuid:
            raise RuntimeError("First filing lacks a filing_uuid; cannot download.")
        path = client.download_filing_document(first_uuid, args.download_first)
        print(f"\nDownloaded first filing document to {path.resolve()}")


if __name__ == "__main__":
    main()
