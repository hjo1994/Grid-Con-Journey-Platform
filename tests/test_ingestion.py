import os
import sqlite3
import time
import uuid

import polars as pl
import pytest

from grid_con_ingestion.models import C4C_EXPORT_COLUMNS
from grid_con_ingestion.sources import MARKER_NAME, FileSource
from grid_con_ingestion.transforms.normalize import RAW_COLUMNS, transform
from grid_con_ingestion.writer import atomic_write, ensure_schema, load_customers, write_bronce, write_silver


def raw_row(**values) -> dict:
    row = {c: "#" for c in RAW_COLUMNS}
    row["overflow"] = None
    row.update(values)
    return row


def frame(*rows) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema={c: pl.String for c in RAW_COLUMNS})


@pytest.fixture
def sample() -> pl.DataFrame:
    return frame(
        raw_row(
            ticket="Projekt-0001", ticket_id="100", status="Offen",
            connection_point="Standort-0001",
            connection_solution="2 Schaltfelder Bestands-UW/SA",
            stakeholder="Unternehmen-1", contact_name="Person-1",
            contact_email="A@Example.invalid", connection_technology="Batterie | Biomasse",
            installed_capacity="1.530,00 MW | 20,00 MW", elo_link="Referenz-1",
        ),
        raw_row(
            ticket="Projekt-0002", ticket_id="101", status="Eingestellt",
            connection_solution="Nicht zugeordnet", connection_technology_raw="Battery",
            connection_technology=None, installed_capacity="300,00 MW,,,,",
            stakeholder="Unternehmen-1", contact_name="Person-1",
            contact_email="a@example.invalid",
        ),
        raw_row(ticket="Projekt-0003", ticket_id=None),                     # nur Ticketname
        raw_row(ticket="Projekt-0004", ticket_id=" zwp)", overflow="x"),    # defekt
    )


def test_placeholders_become_null(sample):
    req = transform(sample).requests.filter(pl.col("id_gronos_old") == "Projekt-0003").row(0, named=True)
    assert all(req[c] is None for c in req if c != "id_gronos_old")


def test_mapping_and_parsing(sample):
    requests = transform(sample).requests
    req = requests.filter(pl.col("id_gronos_new") == 100).row(0, named=True)
    assert req["maxP"] == pytest.approx(1550.0)
    assert req["SwitchCount"] == 2
    assert req["Substation50Hertz"] == "Standort-0001"
    assert req["DocumentURL"] == "Referenz-1"
    assert req["GenerationTechnology"] == "Batterie | Biomasse"

    req2 = requests.filter(pl.col("id_gronos_new") == 101).row(0, named=True)
    assert req2["maxP"] == 300.0
    assert req2["SwitchCount"] is None                 # "Nicht zugeordnet" → NULL
    assert req2["GenerationTechnology"] == "Battery"   # Fallback auf Rohspalte


def test_rejects_malformed_rows(sample):
    result = transform(sample)
    assert result.rejected["ticket"].to_list() == ["Projekt-0004"]
    assert "Projekt-0004" not in result.requests["id_gronos_old"].to_list()


def test_customers_deduplicated(sample):
    assert transform(sample).customers.height == 1     # E-Mail case-insensitiv


def export_frame(raw: pl.DataFrame) -> pl.DataFrame:
    """Rohzeilen mit den Originalheadern, wie sie im Export stehen."""
    return raw.rename(dict(zip(RAW_COLUMNS, C4C_EXPORT_COLUMNS)))


def load(sample, db, sha="sha-1", customers=True):
    if customers:
        with atomic_write(db) as conn:
            load_customers(conn, transform(sample).customers)
    bronce = write_bronce(export_frame(sample), "C4C_GRONOS_x.xlsx", sha, db)
    return bronce, write_silver(db, sha)


def test_bronce_keeps_export_as_is(sample, tmp_path):
    db = tmp_path / "db" / "grid_con.db"
    bronce, _ = load(sample, db)
    assert bronce.rows_inserted == 4

    con = sqlite3.connect(db)
    row = con.execute(
        'SELECT FileSha, FileName, Timestamp, "Ticket", "Official request date", "Zusatzfeld_33" '
        "FROM C4CExports WHERE \"Ticket\" = 'Projekt-0002'"
    ).fetchone()
    assert row[:2] == ("sha-1", "C4C_GRONOS_x.xlsx")
    assert row[2] is not None
    assert row[3:] == ("Projekt-0002", "Eingestellt", None)      # Status as is unter verschobenem Header
    # Platzhalter bleiben in Bronce erhalten (Anschlusslösung steht positionsbedingt unter "Spannungsebene")
    assert con.execute("SELECT COUNT(*) FROM C4CExports WHERE \"Spannungsebene\" = 'Nicht zugeordnet'").fetchone()[0] == 1

    again = write_bronce(export_frame(sample), "C4C_GRONOS_x.xlsx", "sha-1", db)
    assert again.already_loaded and again.rows_inserted == 0
    assert con.execute("SELECT COUNT(*) FROM C4CExports").fetchone()[0] == 4


def test_silver_versions_changed_requests(sample, tmp_path):
    db = tmp_path / "db" / "grid_con.db"
    _, first = load(sample, db, "sha-1")
    con = sqlite3.connect(db)
    first_rows = con.execute("SELECT ID, id_gronos_old, RequestStatus FROM GridConnectionRequests ORDER BY rowid").fetchall()

    # Projekt-0003 ohne Kunde → übersprungen, Projekt-0004 defekt → aussortiert
    assert (first.business_transactions_inserted, first.requests_inserted) == (2, 2)
    assert (first.customers_missing, first.rows_rejected) == (1, 1)
    assert [r[1] for r in first_rows] == ["Projekt-0001", "Projekt-0002"]
    assert write_silver(db, "sha-1").business_transactions_inserted == 0    # nichts Neues in Bronce

    # neue Lieferung: Projekt-0001 geändert, Projekt-0002 identisch, Projekt-0005 neu
    changed = pl.concat([
        sample.with_columns(
            pl.when(pl.col("ticket") == "Projekt-0001").then(pl.lit("Eingestellt")).otherwise(pl.col("status")).alias("status")
        ),
        frame(raw_row(ticket="Projekt-0005", ticket_id="102", stakeholder="Unternehmen-1",
                      contact_name="Person-1", contact_email="a@example.invalid")),
    ])
    _, second = load(changed, db, "sha-2", customers=False)
    assert (second.requests_inserted, second.requests_unchanged, second.customers_missing) == (2, 1, 1)
    assert second.business_transactions_inserted == 2

    con = sqlite3.connect(db)
    rows = con.execute("SELECT ID, id_gronos_old, RequestStatus FROM GridConnectionRequests ORDER BY rowid").fetchall()
    assert rows[:2] == first_rows                                       # alte Einträge unverändert
    assert [(r[1], r[2]) for r in rows[2:]] == [("Projekt-0001", "Eingestellt"), ("Projekt-0005", None)]
    assert len({r[0] for r in rows}) == 4                               # jeder Eintrag eigene UUID

    history = con.execute(
        "SELECT r.RequestStatus, e.FileSha FROM GridConnectionRequests r "
        "JOIN BusinessTransactions bt ON bt.ID = r.BusinessTransactionID "
        "JOIN C4CExports e ON e.ID = bt.C4CExportID WHERE r.id_gronos_new = 100 ORDER BY r.rowid"
    ).fetchall()
    assert history == [("Offen", "sha-1"), ("Eingestellt", "sha-2")]
    assert con.execute("SELECT COUNT(*) FROM BusinessTransactions").fetchone()[0] == 4
    assert con.execute(
        "SELECT COUNT(*) FROM GridConnectionRequests WHERE CustomerID IS NULL OR BusinessTransactionID IS NULL OR timestamp IS NULL"
    ).fetchone()[0] == 0
    assert not (db.parent / "grid_con.new.db").exists()   # Arbeitskopie aufgeräumt

    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"C4CExports", "BusinessTransactions", "GridConnectionRequests", "GridConnectionCustomers"}

    for table in tables:                                   # Primärschlüssel sind UUIDs
        for (pk,) in con.execute(f"SELECT ID FROM {table}"):
            assert str(uuid.UUID(pk)) == pk


def test_silver_skips_rows_without_known_customer(sample, tmp_path):
    db = tmp_path / "db" / "grid_con.db"
    _, stats = load(sample, db, customers=False)
    con = sqlite3.connect(db)
    assert stats.customers_missing == 3                  # Unternehmen-1 (2×) und Projekt-0003 ohne Kunde
    assert con.execute("SELECT COUNT(*) FROM GridConnectionCustomers").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM GridConnectionRequests").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM BusinessTransactions").fetchone()[0] == 0


def test_customer_migration_is_idempotent(sample, tmp_path):
    db = tmp_path / "db" / "grid_con.db"
    customers = transform(sample).customers
    with atomic_write(db) as conn:
        first = load_customers(conn, customers)
    with atomic_write(db) as conn:
        second = load_customers(conn, customers)
    assert (first.customers_inserted, second.customers_inserted, second.customers_existing) == (1, 0, 1)


def test_schema_upgrade_keeps_existing_rows(tmp_path):
    db = tmp_path / "grid_con.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE GridConnectionRequests (ID INTEGER PRIMARY KEY, id_gronos_old VARCHAR)")
    con.execute("INSERT INTO GridConnectionRequests VALUES (7, 'Projekt-0007')")
    con.commit()
    con.close()

    ensure_schema(db)
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(GridConnectionRequests)")}
    assert {"BusinessTransactionID", "timestamp"} <= cols
    assert con.execute("SELECT ID, id_gronos_old FROM GridConnectionRequests").fetchall() == [(7, "Projekt-0007")]


def test_file_source_marker_lifecycle(tmp_path):
    src = FileSource(str(tmp_path), filename_glob="C4C_GRONOS_*.xlsx", settle_seconds=0)
    assert src.poll() is None

    f = tmp_path / "C4C_GRONOS_x.xlsx"
    f.write_bytes(b"x")
    ref = src.poll()
    assert ref == str(f)

    src.acknowledge(ref)
    assert (tmp_path / MARKER_NAME).exists()
    assert src.poll() is None                         # unverändert → kein neuer Import
    assert f.exists()                                 # Quelldatei bleibt liegen

    later = time.time() + 5
    os.utime(f, (later, later))                       # Datei geändert
    assert src.poll() == str(f)



def test_silver_keeps_rows_with_duplicate_ticket_id(sample, tmp_path):
    db = tmp_path / "db" / "grid_con.db"
    load(sample, db, "sha-1")

    # Projekt-0002 bekommt die Ticket ID von Projekt-0001 → zwei Zeilen mit 100
    dup = sample.with_columns(
        pl.when(pl.col("ticket") == "Projekt-0002").then(pl.lit("100")).otherwise(pl.col("ticket_id")).alias("ticket_id")
    )
    _, second = load(dup, db, "sha-2", customers=False)
    assert (second.requests_inserted, second.requests_unchanged) == (1, 1)

    con = sqlite3.connect(db)
    assert con.execute(
        "SELECT id_gronos_old FROM GridConnectionRequests WHERE id_gronos_new = 100 ORDER BY rowid"
    ).fetchall() == [("Projekt-0001",), ("Projekt-0002",)]

    _, third = load(dup, db, "sha-3", customers=False)            # gleiche Daten erneut
    assert (third.requests_inserted, third.requests_unchanged) == (0, 2)
