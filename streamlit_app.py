import io
import json
import csv
from typing import Dict, List, Optional

import streamlit as st

from lda_api import LDAClient, SIMPLE_CSV_FIELDS, _flatten_record, _simplified_row

x = 0
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
        client_name = st.text_area("Client Names (separated by new line / Enter)")
        client_name_list = [line.strip() for line in client_name.split("\n") if line.strip()]
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

    pause_seconds = st.slider("Pause between paginated requests (seconds), increase if you are rate-limited.", 0.0, 10.0, 1.0, 0.5)

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
        with st.spinner("Fetching filings from Senate API. This may take a while."):
            for name in client_name_list:
                client_name = name
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

                    if x == 1:
                        if results:
                            
                            results_placeholder.success(f"Returned {len(results)} filings for {name} (reported total: {count})")
                            st.write(f"Returned {len(results)} filings for {name} (reported total: {count})")
                            
                            json_bytes = json.dumps(payload, indent=2).encode("utf-8")
                            flattened_rows = [_flatten_record(r) for r in results]
                            simplified_rows = [_simplified_row(r) for r in results]
                            full_csv = build_csv(flattened_rows)
                            simplified_csv = build_csv(simplified_rows, SIMPLE_CSV_FIELDS)
                            
                            total_csv_string = total_csv.decode('utf-8')
                            main_buffer = io.StringIO(total_csv_string, newline='')
                            main_buffer.seek(0, io.SEEK_END)
                            writer = csv.writer(main_buffer)

                            simplified_csv_string = simplified_csv.decode('utf-8')
                            incoming_reader = csv.reader(io.StringIO(simplified_csv_string, newline=''))
                            next(incoming_reader, None)
                            writer.writerows(incoming_reader)

                            fields = ["Source", "Lobbyist Name", "Filing Link"]
                            writer.writerow(fields)
                            
                            for filing in payload.get("results", []):
                                for activity in filing.get("lobbying_activities", []):
                                    for lobbyist in activity.get("lobbyists", []):
                                        lobbyist_data = lobbyist.get("lobbyist", [])
                                        first_name = lobbyist_data.get("first_name") or ""
                                        last_name = lobbyist_data.get("last_name") or ""
                                        full_name = first_name + " " + last_name
                                        uuid = filing.get("filing_uuid")
                                        link = f"https://lda.senate.gov/filings/public/filing/{uuid}/print/"
                                        
                                        writer.writerow([name, full_name, link])
                                        
                            total_csv = main_buffer.getvalue().encode('utf-8')
                            main_buffer.close()
    
                        else:
                            results_placeholder.info(f"No filings matched the provided filters for {name}.")
                            st.write(f"No filings matched the provided filters for {name}.")
                            
                    if x == 0:              
                        if results:
                            
                            results_placeholder.success(f"Returned {len(results)} filings for {name} (reported total: {count})")
                            st.write(f"Returned {len(results)} filings for {name} (reported total: {count})")
                            
                            simplified_rows = [_simplified_row(r) for r in results]
                            simplified_csv = build_csv(simplified_rows, SIMPLE_CSV_FIELDS)
                            
                            simplified_csv_string = simplified_csv.decode('utf-8')
                            main_buffer = io.StringIO(simplified_csv_string, newline='')
                            main_buffer.seek(0, io.SEEK_END)
                            writer = csv.writer(main_buffer)
                            incoming_reader = csv.reader(io.StringIO(simplified_csv_string, newline=''))
                            next(incoming_reader, None)

                            fields = ["Source", "Lobbyist Name", "Filing Link"]
                            writer.writerow(fields)
                            
                            for filing in payload.get("results", []):
                                for activity in filing.get("lobbying_activities", []):
                                    for lobbyist in activity.get("lobbyists", []):
                                        lobbyist_data = lobbyist.get("lobbyist", [])
                                        first_name = lobbyist_data.get("first_name") or ""
                                        last_name = lobbyist_data.get("last_name") or ""
                                        full_name = first_name + " " + last_name
                                        uuid = filing.get("filing_uuid")
                                        link = f"https://lda.senate.gov/filings/public/filing/{uuid}/print/"
                                        writer.writerow([name, full_name, link])
                            
                            total_csv = main_buffer.getvalue().encode('utf-8')
                            main_buffer.close()
                            x = 1
                            
                        else:
                            results_placeholder.info(f"No filings matched the provided filters for {name}.")
                            st.write(f"No filings matched the provided filters for {name}.")

            with download_placeholder:
                    st.subheader("Download")
                    st.download_button(
                        "Download CSV",
                        data=total_csv,
                        file_name="filings_simple.csv",
                        mime="text/csv",
                    )
