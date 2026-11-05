"""Bewertung: Framework, Nutzer:innen, BronzeToGold (Versionen, Delta, Wasserlinie)."""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from grid_con_ingestion.evaluation_framework import FRAMEWORK, framework_rows, seed_framework
from grid_con_ingestion.gronos.store import bronze_to_silver, write_bronze
from grid_con_ingestion.migrations.evaluation import DEMO_USERS, setup_evaluation
from grid_con_ingestion.writer import (
    FrameworkNotSeeded,
    ensure_schema,
    next_input_timestamp,
    write_gold,
    write_transaction,
)
from tests.test_gronos import request_record


def seed(db):
    """Framework, Demo-Nutzer:innen und ein Antrag in Silver."""
    write_bronze(db, [request_record("OBJ1")])
    bronze_to_silver(db)
    setup_evaluation(db, DEMO_USERS)
    con = sqlite3.connect(db)
    users = dict(con.execute("SELECT Role, ID FROM Users"))
    request_id = con.execute("SELECT ID FROM GridConnectionRequests").fetchone()[0]
    return users, request_id


def add_input(db, request_id, user_id, check, verdict, score=None, comment=None):
    with write_transaction(db) as conn:
        conn.execute(
            "INSERT INTO UserEvaluationInputs (ID, GridConnectionRequestID, EvaluationCheckID, UserID, "
            "EvaluationVerdict, EvaluationScore, Comment, Timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), request_id, check, user_id, verdict, score, comment, next_input_timestamp(conn)),
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
    write_bronze(db, [request_record("OBJ1", updated="2026-08-01T00:00:00.000", status=9)])
    bronze_to_silver(db)
    con = sqlite3.connect(db)
    new_state = con.execute("SELECT ID FROM GridConnectionRequests ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    assert new_state != first_state
    add_input(db, new_state, users["finanzen"], "C3-01", "not_fulfilled", 0)
    write_gold(db)
    assert [r[0] for r in con.execute("SELECT Version FROM RequestEvaluationChecks ORDER BY rowid")] == [1, 2]


def test_users_are_upserted_by_email_and_roles_validated(tmp_path):
    db = tmp_path / "grid_con.db"
    first = setup_evaluation(db, [{"email": "A@Example.invalid", "name": "A", "role": "finanzen"}])
    assert (first["users_inserted"], first["users_updated"]) == (1, 0)
    again = setup_evaluation(db, [{"email": "a@example.invalid", "name": "A", "role": "netzplanung"}])
    assert (again["users_inserted"], again["users_updated"]) == (0, 1)
    assert sqlite3.connect(db).execute("SELECT Email, Role FROM Users").fetchall() == [("a@example.invalid", "netzplanung")]
    with pytest.raises(ValueError):
        setup_evaluation(db, [{"email": "b@example.invalid", "name": "B", "role": "admin"}])


def test_schema_upgrade_renames_business_transaction_timestamps(tmp_path):
    """Bestehende DB mit TimestampImportBronze/-Silver: Spalten werden umbenannt, Werte bleiben."""
    db = tmp_path / "grid_con.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE GronosExports (ID VARCHAR(36) PRIMARY KEY, Timestamp DATETIME NOT NULL, Content TEXT NOT NULL);
        CREATE TABLE BusinessTransactions (ID VARCHAR(36) PRIMARY KEY, C4CExportID VARCHAR(36),
            GronosExportID VARCHAR(36) UNIQUE REFERENCES GronosExports (ID),
            TimestampImportBronze DATETIME, TimestampImportSilver DATETIME);
        INSERT INTO GronosExports VALUES ('e1', '2026-11-01 10:00:00.000000', '{}');
        INSERT INTO BusinessTransactions VALUES ('bt1', NULL, 'e1', '2026-11-01 10:00:00.000000', '2026-11-01 10:05:00.000000');
    """)
    con.close()
    ensure_schema(db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT ID, GronosExportID, InputBronzeTimestamp, Timestamp, UserEvaluationInputID "
                       "FROM BusinessTransactions").fetchall() == [
        ("bt1", "e1", "2026-11-01 10:00:00.000000", "2026-11-01 10:05:00.000000", None)]
    assert {"Users", "UserEvaluationInputs", "RequestEvaluationChecks", "EvaluationChecks"} <= {
        r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_seeding_dag_writes_framework_only(tmp_path):
    """grid_con_seed_config: legt Tabellen an, schreibt das Framework idempotent, keine Nutzer:innen."""
    db = tmp_path / "grid_con.db"
    assert seed_framework(db) == {"criteria": 5, "sub_criteria": 10, "checks": 39}
    assert seed_framework(db) == {"criteria": 5, "sub_criteria": 10, "checks": 39}
    con = sqlite3.connect(db)
    counts = [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("EvaluationCriteria", "EvaluationSubCriteria", "EvaluationChecks", "Users")]
    assert counts == [5, 10, 39, 0]


def test_bronze_to_gold_needs_seeded_framework_and_leaves_config_alone(tmp_path):
    db = tmp_path / "grid_con.db"
    ensure_schema(db)
    with pytest.raises(FrameworkNotSeeded, match="grid_con_seed_config"):
        write_gold(db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM EvaluationChecks").fetchone()[0] == 0   # nichts angelegt
    assert con.execute("SELECT COUNT(*) FROM BusinessTransactions").fetchone()[0] == 0

    seed_framework(db)
    con.execute("UPDATE EvaluationChecks SET Points = 7 WHERE ID = 'B3-04'")          # Config manuell geändert
    con.commit()
    assert write_gold(db).inputs == 0
    assert con.execute("SELECT Points FROM EvaluationChecks WHERE ID = 'B3-04'").fetchone()[0] == 7
