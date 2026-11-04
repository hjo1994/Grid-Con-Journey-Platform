"""GRONOS-API (RawToBronze, BronzeToSilver), Bewertungen (BronzeToGold) und
Schema-Umbau. Die API wird durch eine Attrappe ersetzt; Antworten im Format
der Pod-Tests vom 02.11.2026, Werte synthetisch."""
import json
import sqlite3
import urllib.parse
import uuid

import pytest

from grid_con_ingestion.evaluation_framework import FRAMEWORK, framework_rows
from grid_con_ingestion.gronos import GronosApiError, GronosClient, derive_customer, derive_request, fetch_delta
from grid_con_ingestion.migrations.evaluation import DEMO_USERS, setup_evaluation
from grid_con_ingestion.writer import (
    ensure_schema,
    next_input_timestamp,
    known_gronos_states,
    write_gold,
    write_gronos_bronze,
    write_gronos_silver,
    write_transaction,
)


def detail(oid="OBJ1", friendly="4902", company="1028399", updated="2026-07-24T06:33:36.356", **over):
    d = {
        "objectId": oid, "friendlyId": friendly, "companyId": company, "status": "4", "nextActor": "2",
        "dsoResponse": "0", "dsoContacted": "false", "projectName": "Test 20260724", "projectDescription": "",
        "projectPhase": "Z01", "createdAt": "2026-07-24T06:31:52.704", "updatedAt": updated,
        "expansionStageConnections": [
            {"objectId": "S1", "startDate": "2027-07-24T22:00:00.000", "expansionStageGroup": "Batterie",
             "connectionType": "1", "capacity": "150.00000000000000"},
            {"objectId": "S2", "startDate": "2026-12-01T00:00:00.000", "expansionStageGroup": "Batterie",
             "connectionType": "2", "capacity": "50"},
        ],
        "locations": [{"objectId": "L1", "displayName": None, "coordinate": {"latitude": "54.0593", "longitude": "12.3321"},
                       "address": {"street": "Am Moorweg", "streetNumber": "19", "postalCode": "18190", "municipality": "Sanitz"}}],
        "contacts": [{"objectId": "C1", "partyId": "1028410", "role": "1", "firstName": "Erika", "lastName": "Muster",
                      "email": "Erika.Muster@Example.invalid",
                      "companyInfo": {"partyId": company, "legalName": "ACME Gmbh", "vatNumber": "DE848715419"}}],
        "documents": [{"objectId": "D1", "documentFileName": "lageplan.pdf", "type": "3"}],
    }
    d.update(over)
    return d


class FakeApi:
    """Liste je Präfix, Detail je objectId; ``timeout_prefixes`` antworten mit 504."""

    def __init__(self, listing, details, timeout_prefixes=()):
        self.listing, self.details, self.timeout_prefixes = listing, details, set(timeout_prefixes)
        self.tokens = 0
        self.requests: list[dict] = []
        self.expire_next = False

    def __call__(self, method, url, headers, body):
        if url.endswith("/GenerateToken"):
            self.tokens += 1
            return 200, json.dumps({"access_token": f"t{self.tokens}"}).encode()
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.requests.append(params)
        if self.expire_next:
            self.expire_next = False
            return 401, b""
        if "id" in params:
            d = self.details.get(params["id"])
            return 200, json.dumps([d] if d else []).encode()
        prefix = params["companyId"].rstrip("*")
        if prefix in self.timeout_prefixes:
            return 504, b""
        hits = [r for r in self.listing if r["companyId"].startswith(prefix)]
        return 200, json.dumps(hits + hits).encode()   # jeder Antrag kommt doppelt


def client(api):
    return GronosClient("https://gronos.example.invalid", "id", "secret", transport=api)


# --------------------------------------------------------------------------- #
def test_derive_request_and_customer():
    r = derive_request(detail())
    assert r["GronosObjectID"] == "OBJ1" and r["id_gronos_new"] == 4902 and r["id_gronos_old"] == "Test 20260724"
    assert r["maxP"] == pytest.approx(200.0)
    assert r["CommissioningDate"] == "2026-12-01 00:00:00.000000"          # früheste Ausbaustufe
    assert r["GenerationTechnology"] == "Batterie"                         # eindeutige Werte
    assert r["SubstationLocation"] == "Am Moorweg 19, 18190 Sanitz"
    assert (r["Latitude"], r["Longitude"]) == (pytest.approx(54.0593), pytest.approx(12.3321))
    assert r["DsoContacted"] is False and r["RequestComment"] is None
    assert r["DocumentURL"] == "lageplan.pdf"
    c = derive_customer(detail())
    assert c == {"CompanyID": "1028399", "CustomerName": "ACME Gmbh", "CustomerContactPerson": "Erika Muster",
                 "CustomerContactPersonEmail": "erika.muster@example.invalid", "VatNumber": "DE848715419"}


def test_list_splits_prefixes_on_timeout_and_deduplicates():
    listing = [{"objectId": "A", "companyId": "1025642", "updatedAt": "x"},
               {"objectId": "B", "companyId": "1028399", "updatedAt": "x"}]
    api = FakeApi(listing, {}, timeout_prefixes={"1"})
    found = client(api).list_requests(["1", "2"])
    assert set(found) == {"A", "B"}
    asked = [p["companyId"] for p in api.requests]
    assert asked[:2] == ["1*", "10*"] and "2*" in asked


def test_list_fails_when_prefix_cannot_be_split():
    api = FakeApi([], {}, timeout_prefixes={"1", "10", "100", "1000", "10000", "100000", "1000000"})
    with pytest.raises(GronosApiError):
        client(api).list_requests(["1"])


def test_token_refresh_on_401():
    api = FakeApi([{"objectId": "A", "companyId": "1", "updatedAt": "x"}], {})
    c = client(api)
    c.get({"companyId": "9*"})
    api.expire_next = True
    status, _ = c.get({"companyId": "1*"})
    assert status == 200 and api.tokens == 2


def test_raw_to_bronze_fetches_only_new_or_changed(tmp_path):
    db = tmp_path / "grid_con.db"
    d1, d2 = detail("OBJ1"), detail("OBJ2", friendly="4903", company="1025642")
    listing = [{k: d[k] for k in ("objectId", "companyId", "updatedAt")} for d in (d1, d2)]
    api = FakeApi(listing, {"OBJ1": d1, "OBJ2": d2})

    details, stats = fetch_delta(client(api), ["1"], known_gronos_states(db))
    assert (stats["listed"], stats["changed"]) == (2, 2)
    first = write_gronos_bronze(details, db)
    assert first.rows_inserted == 2

    # zweiter Lauf: nichts geändert → kein Detailabruf, nichts geschrieben
    details, stats = fetch_delta(client(api), ["1"], known_gronos_states(db))
    assert stats["changed"] == 0 and write_gronos_bronze(details, db).rows_inserted == 0

    # OBJ2 geändert
    d2b = detail("OBJ2", friendly="4903", company="1025642", updated="2026-08-01T10:00:00.000", status="5")
    api.listing[1]["updatedAt"] = d2b["updatedAt"]
    api.details["OBJ2"] = d2b
    details, stats = fetch_delta(client(api), ["1"], known_gronos_states(db))
    assert [d["objectId"] for d in details] == ["OBJ2"]
    write_gronos_bronze(details, db)

    con = sqlite3.connect(db)
    rows = con.execute("SELECT Timestamp, Content FROM GronosExports ORDER BY rowid").fetchall()
    assert len(rows) == 3 and rows[0][0] == rows[1][0] != rows[2][0]       # ein Timestamp je Abruf
    assert json.loads(rows[2][1])["status"] == "5"                          # Content as is


def test_bronze_to_silver_uses_previous_bronze_timestamp(tmp_path):
    db = tmp_path / "grid_con.db"
    write_gronos_bronze([detail("OBJ1"), detail("OBJ2", friendly="4903")], db)
    s1 = write_gronos_silver(db)
    assert (s1.bronze_rows, s1.requests_inserted, s1.customers_inserted) == (2, 2, 1)
    assert s1.previous_input_bronze_timestamp is None

    s_again = write_gronos_silver(db)
    assert s_again.bronze_rows == 0                                          # Wasserlinie

    # neuer Abruf: OBJ1 unverändert (nur erneut geholt), OBJ2 mit neuem Status
    write_gronos_bronze([detail("OBJ1"), detail("OBJ2", friendly="4903", status="7")], db)
    s2 = write_gronos_silver(db)
    assert (s2.bronze_rows, s2.requests_inserted, s2.requests_unchanged) == (2, 1, 1)
    assert s2.business_transactions_inserted == 2                            # je Bronze-Zeile eine BT
    assert s2.previous_input_bronze_timestamp is not None

    con = sqlite3.connect(db)
    hist = con.execute(
        "SELECT r.RequestStatus, bt.InputBronzeTimestamp, e.Timestamp, bt.Timestamp, r.timestamp "
        "FROM GridConnectionRequests r JOIN BusinessTransactions bt ON bt.ID = r.BusinessTransactionID "
        "JOIN GronosExports e ON e.ID = bt.GronosExportID WHERE r.GronosObjectID = 'OBJ2' ORDER BY r.rowid"
    ).fetchall()
    assert [h[0] for h in hist] == ["4", "7"]
    assert all(h[1] == h[2] and h[3] == h[4] for h in hist)                 # Input- vs. Transformationszeit
    assert con.execute("SELECT COUNT(*) FROM GridConnectionCustomers").fetchone()[0] == 1


def seed(db):
    """Framework, Demo-Nutzer:innen und ein Antrag in Silver."""
    write_gronos_bronze([detail("OBJ1")], db)
    write_gronos_silver(db)
    setup_evaluation(db, DEMO_USERS)
    con = sqlite3.connect(db)
    users = dict(con.execute("SELECT Role, ID FROM Users"))
    request_id = con.execute("SELECT ID FROM GridConnectionRequests").fetchone()[0]
    return users, request_id


def add_input(db, request_id, user_id, check, verdict, score=None, comment=None, ts=None):
    with write_transaction(db) as conn:
        ts = ts or next_input_timestamp(conn)
        conn.execute(
            "INSERT INTO UserEvaluationInputs (ID, GridConnectionRequestID, EvaluationCheckID, UserID, "
            "EvaluationVerdict, EvaluationScore, Comment, Timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), request_id, check, user_id, verdict, score, comment, ts),
        )


def test_framework_matches_excel_rules():
    criteria, subs, checks = framework_rows()
    assert sum(c[2] for c in criteria) == pytest.approx(1.0)
    groups = {s[3]: s[5] for s in subs}
    assert groups == {"F1": 0, "A1": 2, "A2": 1, "B1+B2": 1, "B3": 2, "C1+C2": 2, "C3": 1, "D1": 2}
    by_code = {c[0]: c for c in checks}
    assert by_code["A1-06"][3:5] == ("points", 2) and by_code["A1-01"][3] == "minimum"
    assert by_code["D1-01"][5] == 1                                         # D1-01: 1 oder 2 Punkte
    assert len({c[0] for c in checks}) == len(checks) == sum(len(s.checks) for c in FRAMEWORK for s in c.sub_criteria)


def test_bronze_to_gold_versions_per_user_and_check(tmp_path):
    db = tmp_path / "grid_con.db"
    users, request_id = seed(db)
    np_, re_ = users["netzplanung"], users["flaechen_recht"]

    add_input(db, request_id, np_, "B3-04", "fulfilled", 2)
    add_input(db, request_id, re_, "B3-04", "not_fulfilled", 0, "Wegerechte fehlen")
    g1 = write_gold(db)
    assert (g1.inputs, g1.checks_inserted, g1.previous_input_bronze_timestamp) == (2, 2, None)
    assert write_gold(db).inputs == 0                                        # nichts doppelt

    add_input(db, request_id, np_, "B3-04", "not_fulfilled", 0, "Trasse gesetzt, Wegerechte offen")
    add_input(db, request_id, np_, "B3-03", "fulfilled", 5)                  # mehr als 1 Punkt
    g2 = write_gold(db)
    assert (g2.inputs, g2.checks_inserted, g2.rows_rejected) == (2, 1, 1)

    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT u.Role, c.Version, c.EvaluationVerdict, c.EvaluationComment, c.Timestamp = i.Timestamp, "
        "bt.InputBronzeTimestamp = i.Timestamp, bt.Timestamp >= i.Timestamp "
        "FROM RequestEvaluationChecks c JOIN Users u ON u.ID = c.UserID "
        "JOIN BusinessTransactions bt ON bt.ID = c.BusinessTransactionID "
        "JOIN UserEvaluationInputs i ON i.ID = bt.UserEvaluationInputID ORDER BY c.rowid"
    ).fetchall()
    assert rows == [
        ("netzplanung", 1, "fulfilled", None, 1, 1, 1),
        ("flaechen_recht", 1, "not_fulfilled", "Wegerechte fehlen", 1, 1, 1),
        ("netzplanung", 2, "not_fulfilled", "Trasse gesetzt, Wegerechte offen", 1, 1, 1),
    ]


def test_bronze_to_gold_stores_only_changed_checks(tmp_path):
    """Delta in BronzeToGold: jede Eingabe bekommt eine BusinessTransaction,
    einen Gold-Eintrag nur, wenn sich Wert oder Kommentar ändern."""
    db = tmp_path / "grid_con.db"
    users, request_id = seed(db)
    np_ = users["netzplanung"]

    add_input(db, request_id, np_, "B3-04", "fulfilled", 2)
    add_input(db, request_id, np_, "B3-04", "fulfilled", 2)                  # gleicher Wert, im selben Lauf
    g1 = write_gold(db)
    assert (g1.inputs, g1.business_transactions_inserted, g1.checks_inserted, g1.rows_unchanged) == (2, 2, 1, 1)

    add_input(db, request_id, np_, "B3-04", "fulfilled", 2.0)                # unverändert
    add_input(db, request_id, np_, "B3-04", "fulfilled", 2, "Trasse liegt vor")  # neuer Kommentar → Eintrag
    add_input(db, request_id, np_, "B3-04", "fulfilled", 2, "Trasse liegt vor")  # derselbe Kommentar → keiner
    add_input(db, request_id, np_, "B3-04", "not_fulfilled", 0)              # geänderter Wert
    add_input(db, request_id, np_, "B3-03", "fulfilled", 5)                  # verworfen, BT trotzdem
    g2 = write_gold(db)
    assert (g2.inputs, g2.business_transactions_inserted, g2.checks_inserted, g2.rows_unchanged, g2.rows_rejected) \
        == (5, 5, 2, 2, 1)
    assert write_gold(db).inputs == 0                                        # Wasserlinie ist vorgerückt

    con = sqlite3.connect(db)
    assert con.execute("SELECT Version, EvaluationVerdict, EvaluationComment FROM RequestEvaluationChecks "
                       "ORDER BY Version").fetchall() == [
        (1, "fulfilled", None), (2, "fulfilled", "Trasse liegt vor"), (3, "not_fulfilled", None)]
    assert con.execute("SELECT COUNT(*) FROM BusinessTransactions WHERE UserEvaluationInputID IS NOT NULL").fetchone() == (7,)
    assert con.execute("SELECT COUNT(*) FROM UserEvaluationInputs").fetchone() == (7,)  # Bronze bleibt vollständig


def test_gold_versions_survive_new_silver_state(tmp_path):
    db = tmp_path / "grid_con.db"
    users, first_state = seed(db)
    add_input(db, first_state, users["finanzen"], "C3-01", "fulfilled", 1)
    write_gold(db)
    # neuer Silver-Stand desselben Antrags
    write_gronos_bronze([detail("OBJ1", status="9")], db)
    write_gronos_silver(db)
    con = sqlite3.connect(db)
    new_state = con.execute("SELECT ID FROM GridConnectionRequests ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    assert new_state != first_state
    add_input(db, new_state, users["finanzen"], "C3-01", "not_fulfilled", 0)
    write_gold(db)
    assert [r[0] for r in con.execute("SELECT Version FROM RequestEvaluationChecks ORDER BY rowid")] == [1, 2]


def test_schema_upgrade_from_c4c_database(tmp_path):
    """Bestehende DB aus der C4C-Zeit: BT NOT NULL-Spalte, alte leere Bewertungstabellen."""
    db = tmp_path / "grid_con.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE C4CExports (ID VARCHAR(36) PRIMARY KEY, FileSha VARCHAR, FileName VARCHAR, Timestamp DATETIME);
        CREATE TABLE BusinessTransactions (ID VARCHAR(36) NOT NULL PRIMARY KEY,
            C4CExportID VARCHAR(36) NOT NULL UNIQUE REFERENCES C4CExports (ID));
        CREATE TABLE GridConnectionRequests (ID VARCHAR(36) PRIMARY KEY,
            BusinessTransactionID VARCHAR(36) REFERENCES BusinessTransactions (ID), timestamp DATETIME);
        CREATE TABLE EvaluationCriterion (ID INTEGER PRIMARY KEY);
        CREATE TABLE RequestEvaluationChecks (ID INTEGER PRIMARY KEY, GridConnectionRequestID INTEGER);
        INSERT INTO C4CExports VALUES ('e1', 'sha', 'f.xlsx', '2026-10-13 14:17:06');
        INSERT INTO BusinessTransactions VALUES ('bt1', 'e1');
        INSERT INTO GridConnectionRequests VALUES ('r1', 'bt1', '2026-10-13 14:23:11');
    """)
    con.commit()
    con.close()

    ensure_schema(db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT ID, C4CExportID, Timestamp, InputBronzeTimestamp FROM BusinessTransactions").fetchall() == [
        ("bt1", "e1", "2026-10-13 14:23:11", "2026-10-13 14:17:06")
    ]
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "EvaluationCriterion" not in tables and {"EvaluationCriteria", "UserEvaluationInputs"} <= tables
    assert "Version" in {r[1] for r in con.execute("PRAGMA table_info(RequestEvaluationChecks)")}
    con.execute("PRAGMA foreign_keys = ON")
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    # neue BT ohne C4C-Quelle ist jetzt erlaubt
    con.execute("INSERT INTO BusinessTransactions (ID) VALUES ('bt2')")
