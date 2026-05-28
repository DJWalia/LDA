import io
import json
from typing import Dict, List, Optional

import streamlit as st

from lda_api import LDAClient, SIMPLE_CSV_FIELDS, _flatten_record, _simplified_row


st.set_page_config(page_title="LDA Filings Explorer", layout="wide")
st.title("Lobbying Disclosure Filings Explorer")


def build_csv(rows: List[Dict], fieldnames: Optional[List[str]] = None) -> bytes:
    """Return CSV bytes for download."""
    import csv

    buffer = io.StringIO()
    resolved_fieldnames = (
        fieldnames if fieldnames is not None else sorted({key for row in rows for key in row})
    )
    writer = csv.DictWriter(buffer, fieldnames=resolved_fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def fetch_filings(
    token: str,
    *,
    client_name: Optional[str] = None,
    client_id: Optional[int] = None,
    lobbyist_name: Optional[str] = None,
    lobbyist_id: Optional[int] = None,
    pause_seconds: float = 0.25,
) -> Dict:
    """Call the API and return the filings payload."""
    client = LDAClient(token=token, timeout=90)
    return client.list_all_filings(
        client_name=client_name,
        client_id=client_id,
        lobbyist_name=lobbyist_name,
        lobbyist_id=lobbyist_id,
        pause_seconds=pause_seconds,
    )


def get_secret_token() -> Optional[str]:
    token = None
    try:
        token = st.secrets["api_token"]
    except KeyError:
        pass
    return token


with st.sidebar:
    st.header("Configuration")
    api_token = get_secret_token()
    if api_token:
        st.caption("Using API token from `.streamlit/secrets.toml`.")
    else:
        st.error("Add `api_token = \"...\"` to `.streamlit/secrets.toml` to authenticate.")

    query_mode = st.radio("Search Mode", ("Client", "Lobbyist"))

    client_name = client_id = lobbyist_name = lobbyist_id = None

    if query_mode == "Client":
        client_name = st.text_input("Client Name")
        client_id_input = st.text_input("Client ID", placeholder="Numeric ID")
        if client_id_input.strip():
            try:
                client_id = int(client_id_input)
            except ValueError:
                st.warning("Client ID must be numeric.")
    else:
        lobbyist_name = st.text_input("Lobbyist Name")
        lobbyist_id_input = st.text_input("Lobbyist ID", placeholder="Numeric ID")
        if lobbyist_id_input.strip():
            try:
                lobbyist_id = int(lobbyist_id_input)
            except ValueError:
                st.warning("Lobbyist ID must be numeric.")

    pause_seconds = st.slider("Pause between paginated requests (seconds)", 0.0, 1.0, 0.3, 0.05)

    fetch_button = st.button("Fetch Filings", type="primary")


results_placeholder = st.empty()
download_placeholder = st.container()


def validate_inputs() -> Optional[str]:
    if not api_token:
        return "API token is required."
    if query_mode == "Client":
        if not client_name and client_id is None:
            return "Provide a client name or ID."
    else:
        if not lobbyist_name and lobbyist_id is None:
            return "Provide a lobbyist name or ID."
    return None


if fetch_button:
    error = validate_inputs()
    if error:
        st.error(error)
    else:
        with st.spinner("Fetching filings from Senate API..."):
            try:
                payload = fetch_filings(
                    api_token,
                    client_name=client_name or None,
                    client_id=client_id,
                    lobbyist_name=lobbyist_name or None,
                    lobbyist_id=lobbyist_id,
                    pause_seconds=pause_seconds,
                )
            except Exception as exc:
                st.error(f"Request failed: {exc}")
            else:
                results = payload.get("results", [])
                count = payload.get("count", len(results))

                results_placeholder.success(f"Returned {len(results)} filings (reported total: {count}).")

                if results:
                    sample = results[:20]
                    st.subheader("Preview (first 20 filings)")
                    st.dataframe(
                        [
                            {
                                "filing_uuid": row.get("filing_uuid"),
                                "filing_year": row.get("filing_year"),
                                "filing_period": row.get("filing_period_display") or row.get("filing_period"),
                                "registrant": (row.get("registrant") or {}).get("name"),
                                "client": (row.get("client") or {}).get("name"),
                                "income": row.get("income"),
                                "expenses": row.get("expenses"),
                            }
                            for row in sample
                        ]
                    )

                    # Build download artifacts
                    json_bytes = json.dumps(payload, indent=2).encode("utf-8")
                    flattened_rows = [_flatten_record(r) for r in results]
                    simplified_rows = [_simplified_row(r) for r in results]
                    full_csv = build_csv(flattened_rows)
                    simplified_csv = build_csv(simplified_rows, SIMPLE_CSV_FIELDS)

                    with download_placeholder:
                        st.subheader("Downloads")
                        st.download_button(
                            "Download JSON payload",
                            data=json_bytes,
                            file_name="filings.json",
                            mime="application/json",
                        )
                        st.download_button(
                            "Download full CSV (flattened)",
                            data=full_csv,
                            file_name="filings_full.csv",
                            mime="text/csv",
                        )
                        st.download_button(
                            "Download simplified CSV",
                            data=simplified_csv,
                            file_name="filings_simple.csv",
                            mime="text/csv",
                        )
                else:
                    results_placeholder.info("No filings matched the provided filters.")
