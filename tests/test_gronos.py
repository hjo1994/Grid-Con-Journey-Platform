"""GRONOS API import: client (prefix split, dedupe), RawToBronze, BronzeToSilver.

All data is synthetic, no real requests or contacts.
"""
import json
import sqlite3

import pytest
import requests

from grid_con_ingestion.gronos.client import GronosApiError, GronosClient, parse_prefixes
from grid_con_ingestion.gronos.store import bronze_to_silver, current_states, raw_to_bronze
from grid_con_ingestion.gronos.transform import to_silver

BASE = "https://api.example.invalid"


def request_record(oid, updated="2026-07-24T06:33:36.356", company="1028399", **extra):
    rec = {
        "objectId": oid,
        "friendlyId": "4902",
        "companyId": company,
        "status": 4,
        "nextActor": 2,
        "dsoResponse": 0,
        "dsoContacted": False,
        "projectName": "Projekt-0001",
        "projectDescription": " ",
        "projectPhase": "Z01",
        "createdAt": "2026-07-24T06:31:52.704",
        "updatedAt": updated,
        "expansionStageConnections": [
            {"objectId": "S1", "startDate": "2027-01-01T00:00:00.000", "expansionStageGroup": "BESS",
             "connectionType": 1, "capacity": "150.00000000000000"},
            {"objectId": "S2", "startDate": "2026-07-24T22:00:00.000", "expansionStageGroup": "BESS",
             "connectionType": 2, "capacity": 20},
        ],
        "locations": [
            {"objectId": "L1", "coordinate": {"latitude": "54.0593", "longitude": "12.3321"},
             "displayName": "", "address": {"street": "Teststraße", "streetNumber": "1",
                                            "postalCode": "12345", "municipality": "Testort"}},
        ],
        "contacts": [
            {"objectId": "C0", "role": 2, "firstName": "Other", "lastName": "Person",
             "companyInfo": {"partyId": "999", "legalName": "Other GmbH"}},
            {"objectId": "C1", "role": 1, "firstName": "Erika", "lastName": "Muster",
             "email": "Erika.Muster@Example.invalid",
             "companyInfo": {"partyId": company, "legalName": "Unternehmen-1 GmbH", "vatNumber": "DE000000000"}},
        ],
        "documents": [{"objectId": "D1", "documentFileName": "lageplan.pdf", "type": "1"}],
    }
    rec.update(extra)
    return rec


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self.text = "" if body is None else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        return json.loads(self.text)


class FakeApi(requests.Session):
    """List by companyId prefix; prefixes shorter than ``min_len`` time out."""

    def __init__(self, data, min_len=4, details=None, missing=None):
        super().__init__()
        self.data, self.min_len, self.details = data, min_len, details or {}
        self.missing = missing or {}  # objectId -> companyId values answered without the record
        self.calls, self.tokens, self.expire_next = [], 0, False

    def post(self, url, **kw):
        self.tokens += 1
        return FakeResponse(200, {"access_token": f"t{self.tokens}"})

    def get(self, url, params=None, headers=None, **kw):
        self.calls.append(dict(params))
        if self.expire_next:
            self.expire_next = False
            return FakeResponse(401)
        company = params["companyId"]
        assert company.endswith("*")
        if "id" in params:
            if company in self.missing.get(params["id"], ()):
                return FakeResponse(200, [])
            rec = self.details.get(params["id"]) or next(r for r in self.data if r["objectId"] == params["id"])
            return FakeResponse(200, [rec])
        prefix = company[:-1]
        if len(prefix) < self.min_len:
            return FakeResponse(504)
        found = [r for r in self.data if r["companyId"].startswith(prefix)]
        return FakeResponse(200, found + found)  # the API returns every request twice


def client(api, **kw):
    return GronosClient(BASE, "id", "secret", session=api, **kw)


def rows(db, sql):
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# --------------------------------------------------------------------------- client
def test_parse_prefixes():
    assert parse_prefixes("1000-1002, 2000") == ["1000", "1001", "1002", "2000"]
    assert parse_prefixes("0998-1000") == ["0998", "0999", "1000"]
    with pytest.raises(ValueError):
        parse_prefixes("10*")


def test_list_splits_on_gateway_timeout_and_dedupes():
    api = FakeApi([request_record("A", company="1028399"), request_record("B", company="1025642")])
    result = client(api).list_all(["102"])                          # 3 digits time out, 4 work
    assert sorted(r["objectId"] for r in result.records) == ["A", "B"]
    assert result.duplicates == 2
    assert result.split_prefixes == ["102"]
    assert result.calls == 1 + 10


def test_list_fails_when_prefix_cannot_be_split():
    api = FakeApi([request_record("A")], min_len=8)
    with pytest.raises(GronosApiError):
        client(api, max_prefix_length=3).list_all(["1"])


def test_token_renewed_on_401():
    api = FakeApi([request_record("A")])
    c = client(api)
    c.list_all(["1028"])
    api.expire_next = True
    assert [r["objectId"] for r in c.list_all(["1028"]).records] == ["A"]
    assert api.tokens == 2


# --------------------------------------------------------------------------- transform
def test_transform_maps_request_and_customer():
    rec = to_silver(json.dumps(request_record("A")))
    r, c = rec.request, rec.customer
    assert r["GronosObjectID"] == "A" and r["id_gronos_new"] == 4902 and r["id_gronos_old"] == "Projekt-0001"
    assert (r["RequestStatus"], r["NextActor"], r["DsoResponse"], r["DsoContacted"]) == ("4", "2", "0", False)
    assert r["RequestComment"] is None
    assert r["maxP"] == pytest.approx(170.0)
    assert r["CommissioningDate"] == "2026-07-24 22:00:00.000000"
    assert r["GenerationTechnology"] == "BESS"
    assert r["SubstationLocation"] == "Teststraße 1, 12345 Testort"
    assert (r["Latitude"], r["Longitude"]) == (pytest.approx(54.0593), pytest.approx(12.3321))
    assert r["DocumentURL"] == "lageplan.pdf"
    assert r["Substation50Hertz"] is None and r["SwitchCount"] is None
    assert c == {
        "CompanyID": "1028399", "CustomerName": "Unternehmen-1 GmbH", "CustomerContactPerson": "Erika Muster",
        "CustomerContactPersonEmail": "erika.muster@example.invalid", "VatNumber": "DE000000000",
    }


# --------------------------------------------------------------------------- pipeline
def test_raw_to_bronze_only_new_and_updated(tmp_path):
    db = tmp_path / "grid_con.db"
    data = [request_record("A"), request_record("B")]
    api = FakeApi(data)

    first = raw_to_bronze(client(api), db, ["1028"])
    assert (first.listed, first.new, first.rows_inserted) == (2, 2, 2)
    stored = rows(db, "SELECT Timestamp, Content FROM GronosExports")
    assert len({ts for ts, _ in stored}) == 1                        # one Timestamp per pull
    assert json.loads(stored[0][1])["objectId"] in {"A", "B"}       # raw JSON of one request

    second = raw_to_bronze(client(api), db, ["1028"])
    assert (second.new, second.updated, second.unchanged, second.rows_inserted) == (0, 0, 2, 0)
    assert not any("id" in c for c in api.calls[-1:])               # no detail call for unchanged

    data[1]["updatedAt"] = "2026-08-01T10:00:00.000"
    data.append(request_record("C"))
    third = raw_to_bronze(client(api), db, ["1028"])
    assert (third.new, third.updated, third.unchanged, third.rows_inserted) == (1, 1, 1, 2)
    assert current_states(db) == {
        "A": "2026-07-24T06:33:36.356", "B": "2026-08-01T10:00:00.000", "C": "2026-07-24T06:33:36.356",
    }


def test_bronze_to_silver_watermark_versions_and_timestamps(tmp_path):
    db = tmp_path / "grid_con.db"
    data = [request_record("A"), request_record("B", friendlyId="4903")]
    api = FakeApi(data)

    raw_to_bronze(client(api), db, ["1028"])
    first = bronze_to_silver(db)
    assert (first.watermark, first.bronze_rows, first.requests_inserted, first.customers_inserted) == (None, 2, 2, 1)
    assert bronze_to_silver(db).bronze_rows == 0                    # nothing newer than the watermark

    # B changes (status), A only gets a new updatedAt with the same mapped values
    data[0]["updatedAt"] = "2026-08-01T00:00:00.000"
    data[0]["createdAt"] = "changed, not mapped"
    data[1].update(updatedAt="2026-08-02T00:00:00.000", status=5)
    raw_to_bronze(client(api), db, ["1028"])
    second = bronze_to_silver(db)
    assert second.watermark is not None
    assert (second.bronze_rows, second.requests_inserted, second.requests_unchanged) == (2, 1, 1)
    assert second.business_transactions_inserted == 2

    history = rows(db, "SELECT GronosObjectID, RequestStatus FROM GridConnectionRequests ORDER BY rowid")
    assert history == [("A", "4"), ("B", "4"), ("B", "5")]

    bts = rows(
        db,
        "SELECT bt.TimestampImportBronze, e.Timestamp, bt.TimestampImportSilver, r.timestamp "
        "FROM BusinessTransactions bt JOIN GronosExports e ON e.ID = bt.GronosExportID "
        "LEFT JOIN GridConnectionRequests r ON r.BusinessTransactionID = bt.ID",
    )
    assert len(bts) == 4                                             # one BT per Bronze row
    for bronze_ts, export_ts, silver_ts, request_ts in bts:
        assert bronze_ts == export_ts
        assert silver_ts >= bronze_ts
        assert request_ts in (silver_ts, None)                      # None = unchanged, no Silver record

    customers = rows(db, "SELECT CompanyID, CustomerName FROM GridConnectionCustomers")
    assert customers == [("1028399", "Unternehmen-1 GmbH")]


def test_bronze_to_silver_skips_identical_state_but_moves_watermark(tmp_path):
    db = tmp_path / "grid_con.db"
    api = FakeApi([request_record("A")])
    raw_to_bronze(client(api), db, ["1028"])
    bronze_to_silver(db)

    # same state stored again (e.g. manual re-import) -> BT yes, new Silver record no
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO GronosExports (ID, Timestamp, Content) VALUES ('x', '2999-01-01 00:00:00.000000', ?)",
        (json.dumps(request_record("A")),),
    )
    con.execute(
        "INSERT INTO GronosExports (ID, Timestamp, Content) VALUES ('y', '2999-01-01 00:00:00.000000', 'kein json')"
    )
    con.commit()
    con.close()

    stats = bronze_to_silver(db)
    assert (stats.bronze_rows, stats.requests_unchanged, stats.rows_rejected) == (2, 1, 1)
    assert stats.business_transactions_inserted == 2
    assert bronze_to_silver(db).bronze_rows == 0
    assert rows(db, "SELECT COUNT(*) FROM GridConnectionRequests") == [(1,)]


def test_detail_retries_with_short_prefix_and_skips_missing(tmp_path):
    db = tmp_path / "grid_con.db"
    data = [request_record("A"), request_record("B"), request_record("C")]
    api = FakeApi(data, missing={"B": {"1028399*"}, "C": {"1028399*", "1028*"}})

    stats = raw_to_bronze(client(api), db, ["1028"])
    assert (stats.new, stats.detail_failed, stats.rows_inserted) == (3, 1, 2)
    assert {"id": "B", "companyId": "1028*"} in api.calls             # retried with the short prefix
    assert sorted(current_states(db)) == ["A", "B"]                   # C not in Bronze ...

    api.missing = {}
    again = raw_to_bronze(client(api), db, ["1028"])
    assert (again.new, again.unchanged, again.rows_inserted) == (1, 2, 1)  # ... so the next run gets it


def test_detail_failures_in_a_row_abort(tmp_path):
    data = [request_record(f"R{i}") for i in range(6)]
    api = FakeApi(data, missing={r["objectId"]: {"1028399*", "1028*"} for r in data})
    with pytest.raises(GronosApiError, match="in a row"):
        raw_to_bronze(client(api), tmp_path / "grid_con.db", ["1028"])


def test_detail_mode_auto_uses_complete_list_records(tmp_path):
    db = tmp_path / "grid_con.db"
    full = request_record("A")                                        # list record with contacts (ACC)
    bare = {k: v for k, v in request_record("B").items() if k not in ("contacts", "expansionStageConnections")}
    api = FakeApi([full, bare], details={"B": request_record("B")})

    stats = raw_to_bronze(client(api), db, ["1028"], detail_mode="auto")
    assert (stats.from_list, stats.rows_inserted) == (1, 2)
    assert [c["id"] for c in api.calls if "id" in c] == ["B"]          # detail only for the bare record
    stored = {json.loads(c)["objectId"]: json.loads(c) for (c,) in rows(db, "SELECT Content FROM GronosExports")}
    assert "contacts" in stored["A"] and "contacts" in stored["B"]


def test_detail_mode_rejects_unknown_value(tmp_path):
    with pytest.raises(ValueError):
        raw_to_bronze(client(FakeApi([])), tmp_path / "grid_con.db", ["1028"], detail_mode="sometimes")


def test_transform_acc_shape():
    """ACC: all values as strings, no expansionStageGroup / displayName / contact names."""
    rec = request_record("A", status="22", nextActor="2", dsoContacted="false", friendlyId="22554")
    rec["expansionStageConnections"] = [
        {"objectId": "S1", "connectionType": "7", "startDate": "2026-05-29T22:00:00.000", "capacity": "50.0"},
        {"objectId": "S2", "connectionType": "12", "startDate": "2026-05-29T22:00:00.000", "capacity": "50.0"},
        {"objectId": "S3", "connectionType": "7", "startDate": "2026-06-01T22:00:00.000", "capacity": "1.0"},
    ]
    rec["locations"] = [{"objectId": "L1", "note": "", "coordinate": {"latitude": "", "longitude": ""},
                         "address": {"street": "", "streetNumber": "", "postalCode": "", "municipality": "",
                                     "countryCode": "DE"}}]
    rec["contacts"] = [{"objectId": "C1", "role": "1", "partyId": "8000000000",
                        "companyInfo": {"partyId": "1028399", "legalName": "Unternehmen-2 AG", "vatNumber": ""}}]
    del rec["documents"]
    r, c = (lambda s: (s.request, s.customer))(to_silver(json.dumps(rec)))
    assert (r["RequestStatus"], r["NextActor"], r["DsoContacted"], r["id_gronos_new"]) == ("22", "2", False, 22554)
    assert r["GenerationTechnology"] == "7 | 12"                       # connectionType fallback, unique
    assert r["maxP"] == pytest.approx(101.0)
    assert r["CommissioningDate"] == "2026-05-29 22:00:00.000000"
    assert (r["SubstationLocation"], r["Latitude"], r["DocumentURL"]) == (None, None, None)
    assert c == {"CompanyID": "1028399", "CustomerName": "Unternehmen-2 AG", "CustomerContactPerson": None,
                 "CustomerContactPersonEmail": None, "VatNumber": None}
