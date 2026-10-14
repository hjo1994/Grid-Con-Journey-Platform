import os
import sqlite3

from fastapi.testclient import TestClient

from app.main import get_app
from tests.conftest import CUSTOMER_A, CUSTOMER_B

BASE = "/api/v1/grid-connection-requests"


def tickets(resp):
    assert resp.status_code == 200, resp.text
    return [i["id_gronos_new"] for i in resp.json()["items"]]


def aggregate(client, query):
    resp = client.get(f"{BASE}/aggregate?{query}")
    assert resp.status_code == 200, resp.text
    return {i["key"]: (i["count"], i["sum_max_p"]) for i in resp.json()["items"]}


def test_healthz_is_independent_of_the_database(tmp_path):
    client = TestClient(get_app(tmp_path / "missing.db"))
    assert client.get("/api/healthz").json() == "OK"


def test_missing_database_returns_503(tmp_path):
    client = TestClient(get_app(tmp_path / "missing.db"))
    resp = client.get(BASE)
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "2"


def test_list_returns_newest_entry_per_ticket_with_silver_fields(client):
    body = client.get(BASE).json()
    assert body["total"] == 4
    assert body["data_as_of"] == "2026-10-02T08:00:00Z"
    first = body["items"][0]
    assert first == {
        "id": "r100-new",
        "id_gronos_new": 100,
        "id_gronos_old": "Projekt-0100",
        "customer_id": CUSTOMER_A,
        "business_transaction_id": None,
        "request_status": "Eingestellt",
        "generation_technology": "Photovoltaik",
        "max_p": 120.0,
        "substation_50hertz": "UW Nord",
        "substation_location": None,
        "switch_count": None,
        "document_url": None,
        "request_comment": None,
        "timestamp": "2026-10-02T08:00:00Z",
    }


def test_versions_all_returns_history(client):
    body = client.get(f"{BASE}?versions=all&sort=timestamp").json()
    assert body["total"] == 5
    assert [i["id"] for i in body["items"] if i["id_gronos_new"] == 100] == ["r100-old", "r100-new"]


def test_status_filter_applies_to_current_state_only(client):
    # ticket 100 was "Offen" once, but is "Eingestellt" now
    assert tickets(client.get(f"{BASE}?request_status=Offen")) == []
    assert tickets(client.get(f"{BASE}?versions=all&request_status=Offen")) == [100]
    multi = client.get(f"{BASE}?request_status=Eingestellt&request_status=Neuer Status")
    assert tickets(multi) == [100, 103]
    assert tickets(client.get(f"{BASE}?exclude_status=Eingestellt")) == [101, 102, 103]


def test_technology_filter_matches_single_values_in_multi_lists(client):
    assert tickets(client.get(f"{BASE}?generation_technology=Photovoltaik")) == [100, 101]
    # whole elements only: "Wind" matches neither "Wind Onshore" nor "Windkraft"
    assert tickets(client.get(f"{BASE}?generation_technology=Wind")) == []
    both = client.get(f"{BASE}?generation_technology=Batterie&generation_technology=Windkraft")
    assert tickets(both) == [101, 103]


def test_customer_and_substation_filters(client):
    assert tickets(client.get(f"{BASE}?customer_id={CUSTOMER_B}")) == [102, 103]
    assert tickets(client.get(f"{BASE}?substation_50hertz=UW Süd")) == [102]


def test_search_covers_ticket_project_and_customer_and_escapes_wildcards(client):
    assert tickets(client.get(f"{BASE}?q=102")) == [102]
    assert tickets(client.get(f"{BASE}?q=projekt-0101")) == [101]
    assert tickets(client.get(f"{BASE}?q=100%25")) == [100, 101]  # customer "Solar 100% GmbH"
    assert tickets(client.get(f"{BASE}?q=Wind_Park")) == [102, 103]
    assert tickets(client.get(f"{BASE}?q=d_P")) == [102, 103]
    assert tickets(client.get(f"{BASE}?q=dxP")) == []


def test_sort_by_status_uses_process_order_and_unknown_last(client):
    asc = tickets(client.get(f"{BASE}?sort=request_status"))
    # Standortanfrage (1) < Netzanschlussantrag (3) < Eingestellt (10) < unknown
    assert asc == [102, 101, 100, 103]
    assert tickets(client.get(f"{BASE}?sort=request_status&order=desc")) == [103, 100, 101, 102]


def test_sort_puts_nulls_last_in_both_directions(client):
    assert tickets(client.get(f"{BASE}?sort=max_p"))[-1] == 103
    assert tickets(client.get(f"{BASE}?sort=max_p&order=desc")) == [100, 101, 102, 103]


def test_pagination_keeps_total(client):
    body = client.get(f"{BASE}?limit=2&offset=1").json()
    assert [i["id_gronos_new"] for i in body["items"]] == [101, 102]
    assert body["total"] == 4 and body["limit"] == 2 and body["offset"] == 1


def test_invalid_params_rejected(client):
    assert client.get(f"{BASE}?sort=customer").status_code == 422
    assert client.get(f"{BASE}?limit=0").status_code == 422
    assert client.get(f"{BASE}?versions=some").status_code == 422
    assert client.get(f"{BASE}/abc").status_code == 422


def test_detail_returns_current_state_and_optional_customer(client):
    body = client.get(f"{BASE}/100").json()
    assert body["id"] == "r100-new" and body["request_status"] == "Eingestellt"
    assert "customer" not in body
    expanded = client.get(f"{BASE}/100?expand=customer").json()
    assert expanded["customer"] == {
        "id": CUSTOMER_A,
        "customer_name": "Solar 100% GmbH",
        "customer_contact_person": "Anna",
        "customer_contact_person_email": "a@example.invalid",
    }
    assert client.get(f"{BASE}/999").status_code == 404
    assert client.get(f"{BASE}/100?expand=owner").status_code == 422


def test_aggregate_by_status(client):
    result = aggregate(client, "group_by=request_status")
    assert result == {
        "Eingestellt": (1, 120.0),
        "Netzanschlussantrag eingegangen": (1, 50.0),
        "Standortanfrage eingegangen": (1, 30.0),
        "Neuer Status": (1, 0.0),
    }
    assert aggregate(client, "group_by=request_status&versions=all")["Offen"] == (1, 100.0)


def test_aggregate_technology_with_split_and_filters(client):
    assert aggregate(client, "group_by=generation_technology")["Batterie | Photovoltaik"] == (1, 50.0)
    split = aggregate(client, "group_by=generation_technology&split_multi=true&exclude_status=Eingestellt")
    assert split == {
        "Batterie": (1, 25.0),
        "Photovoltaik": (1, 25.0),
        "Wind Onshore": (1, 30.0),
        "Windkraft": (1, 0.0),
    }
    body = client.get(f"{BASE}/aggregate?group_by=generation_technology&split_multi=true").json()
    assert body["total"] == 4 and body["split_multi"] is True


def test_aggregate_by_customer_and_validation(client):
    assert aggregate(client, "group_by=customer_id") == {CUSTOMER_A: (2, 170.0), CUSTOMER_B: (2, 30.0)}
    assert client.get(f"{BASE}/aggregate").status_code == 422
    assert client.get(f"{BASE}/aggregate?group_by=request_status&split_multi=true").status_code == 422


def test_customers_list_search_and_detail(client):
    body = client.get("/api/v1/grid-connection-customers").json()
    assert body["total"] == 2
    assert [c["customer_name"] for c in body["items"]] == ["Solar 100% GmbH", "Wind_Park AG"]
    found = client.get("/api/v1/grid-connection-customers?q=ben").json()
    assert [c["id"] for c in found["items"]] == [CUSTOMER_B]
    assert client.get(f"/api/v1/grid-connection-customers/{CUSTOMER_A}").json()["customer_contact_person"] == "Anna"
    assert client.get("/api/v1/grid-connection-customers/unknown").status_code == 404


def test_customer_requests_use_list_semantics(client):
    url = f"/api/v1/grid-connection-customers/{CUSTOMER_A}/grid-connection-requests"
    assert tickets(client.get(url)) == [100, 101]
    assert tickets(client.get(f"{url}?versions=all"))  == [100, 100, 101]
    assert tickets(client.get(f"{url}?exclude_status=Eingestellt")) == [101]
    assert client.get("/api/v1/grid-connection-customers/unknown/grid-connection-requests").status_code == 404


def test_request_statuses_in_process_order_plus_unknown(client):
    statuses = client.get("/api/v1/request-statuses").json()
    assert [s["order"] for s in statuses[:10]] == list(range(1, 11))
    assert statuses[0] == {"name": "Standortanfrage eingegangen", "order": 1, "phase": "Eingang",
                           "in_process": True, "configured": True}
    assert [s["name"] for s in statuses[8:10]] == ["Offen", "Eingestellt"]
    assert all(not s["in_process"] and s["phase"] is None for s in statuses[8:10])
    assert statuses[10:] == [{"name": "Neuer Status", "order": None, "phase": None,
                              "in_process": False, "configured": False}]


def test_meta(client):
    assert client.get("/api/v1/meta").json() == {"api_version": "1.0.0", "data_as_of": "2026-10-02T08:00:00Z"}


def test_openapi_lists_all_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) >= {
        "/api/v1/grid-connection-requests",
        "/api/v1/grid-connection-requests/aggregate",
        "/api/v1/grid-connection-requests/{id_gronos_new}",
        "/api/v1/grid-connection-customers",
        "/api/v1/grid-connection-customers/{customer_id}",
        "/api/v1/grid-connection-customers/{customer_id}/grid-connection-requests",
        "/api/v1/request-statuses",
        "/api/v1/meta",
    }


def test_database_is_opened_read_only(client, db_path):
    client.get(BASE)
    engine = client.app.state.engine
    with engine.connect() as conn:
        raw = conn.connection.dbapi_connection
        try:
            raw.execute("DELETE FROM GridConnectionRequests")
        except sqlite3.OperationalError as exc:
            assert "readonly" in str(exc)
        else:
            raise AssertionError("write succeeded on a read-only connection")


def test_every_request_sees_a_replaced_file(client, db_path, tmp_path):
    # Input Orchestration swaps the file with an atomic rename; no pooled handle
    # may keep reading the old inode.
    assert client.get(BASE).json()["total"] == 4
    new = tmp_path / "new.db"
    with sqlite3.connect(db_path) as src, sqlite3.connect(new) as dst:
        src.backup(dst)
    with sqlite3.connect(new) as conn:
        conn.execute("DELETE FROM GridConnectionRequests WHERE id_gronos_new = 103")
    os.replace(new, db_path)
    assert client.get(BASE).json()["total"] == 3



def test_session_can_be_used_from_another_thread(db_path):
    # FastAPI opens the session in the dependency and runs the sync endpoint in
    # a different threadpool thread; parallel requests made that fail with 500.
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import text

    from app.db import make_engine, open_session

    session = open_session(make_engine(db_path))
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            count = pool.submit(
                lambda: session.execute(text("SELECT count(*) FROM GridConnectionRequests")).scalar()
            ).result()
        assert count == 5
    finally:
        session.close()
