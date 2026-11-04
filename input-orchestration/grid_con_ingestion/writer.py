"""Schreibt Bronze, Silver und Gold in die zentrale SQLite-Datei.

Jeder Schreibvorgang läuft über :func:`write_transaction`: Schema
sicherstellen, eine SQLite-Transaktion (``BEGIN IMMEDIATE``), FK-Prüfung,
COMMIT. Neben Input Orchestration schreibt nur noch das Backend, und zwar
ausschließlich in die Bronze-Tabelle ``UserEvaluationInputs``.

GRONOS-API (:mod:`grid_con_ingestion.gronos`, :func:`write_gronos_bronze`,
:func:`write_gronos_silver`) und Bewertungen (:func:`write_gold`) siehe
unten; die C4C-Excel-Funktionen bleiben als Legacy-Pfad erhalten.

Legacy C4C – Bronce (:func:`write_bronce`)
  Der Export wird as is in ``C4CExports`` angehängt, je Lieferung mit
  FileSha, FileName und Timestamp. Eine Lieferung mit bereits geladenem
  FileSha wird übersprungen.

Legacy C4C – Silver (:func:`write_silver`)
  Upsert gegen ``GridConnectionRequests`` für die Bronce-Zeilen einer
  Lieferung. Übersprungen werden
    * Zeilen ohne passenden Kunden in ``GridConnectionCustomers``
      (Stammdaten, siehe migrations/customers.py; hier werden nie Kunden
      angelegt) und
    * Zeilen, deren Werte identisch zum neuesten Eintrag desselben Tickets
      (Ticketname + Ticket ID) sind.
  Alle anderen (neues Ticket oder mindestens ein geänderter Wert) bekommen
  zuerst einen Eintrag in ``BusinessTransactions`` und dann einen komplett
  neuen Eintrag in ``GridConnectionRequests`` mit neuer UUID. Bestehende
  Einträge werden nie geändert; je Ticket entsteht so eine Historie, der
  neueste Eintrag ist der aktuelle Stand.

Primärschlüssel aller Tabellen sind UUIDs (uuid4, als Text), vergeben hier
im Writer.

Schlüssel
  * Kunde:   (CustomerName, CustomerContactPerson, CustomerContactPersonEmail), NULL-sicher
  * Ticket: (id_gronos_old, id_gronos_new), NULL-sicher. Doppelte Ticket IDs
    bei verschiedenen Ticketnamen sind damit verschiedene Tickets.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import polars as pl
from sqlalchemy import create_engine, inspect

from grid_con_ingestion.models import C4C_EXPORT_COLUMNS, Base
from grid_con_ingestion.transforms.normalize import CUSTOMER_COLUMNS, REQUEST_COLUMNS, to_raw, transform

log = logging.getLogger(__name__)


@dataclass
class BronceStats:
    rows_inserted: int = 0
    already_loaded: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class LoadStats:
    business_transactions_inserted: int = 0
    requests_inserted: int = 0
    requests_unchanged: int = 0
    customers_missing: int = 0
    rows_rejected: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class CustomerStats:
    customers_inserted: int = 0
    customers_existing: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# --------------------------------------------------------------------------- #
# Schema und transaktionales Schreiben
# --------------------------------------------------------------------------- #
# Leere Tabellen eines früheren Entwurfs (INTEGER-IDs, Singular-Namen). Sie
# werden beim ersten Lauf entfernt; enthalten sie Zeilen, bricht der Lauf ab.
_LEGACY_EMPTY_TABLES = ("RequestDocument", "EvaluationCheck", "EvaluationCriterion", "EvaluationSubCriterion")

SQLITE_TIMEOUT_SECONDS = 30.0


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Verbindung für Schreiber: Autocommit-Modus, Transaktionen explizit."""
    conn = sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT_SECONDS, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout = {int(SQLITE_TIMEOUT_SECONDS * 1000)}")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, dict]:
    return {r[1]: {"type": r[2], "notnull": bool(r[3])} for r in conn.execute(f"PRAGMA table_info({_quote(table)})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _drop_legacy_tables(conn: sqlite3.Connection) -> None:
    tables = _tables(conn)
    candidates = [t for t in _LEGACY_EMPTY_TABLES if t in tables]
    # RequestEvaluationChecks des alten Entwurfs: INTEGER-ID, ohne Version
    if "RequestEvaluationChecks" in tables and "Version" not in _columns(conn, "RequestEvaluationChecks"):
        candidates.insert(0, "RequestEvaluationChecks")
    for table in candidates:
        if conn.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]:
            raise RuntimeError(f"Alte Tabelle {table} enthält Daten – bitte manuell migrieren")
        conn.execute(f"DROP TABLE {_quote(table)}")
        log.info("Leere Alt-Tabelle %s entfernt", table)


def _rebuild_business_transactions(conn: sqlite3.Connection) -> None:
    """BusinessTransactions aus der C4C-Zeit (C4CExportID NOT NULL) auf das
    neue Schema umbauen: Quell-FKs nullable, Timestamps nachgetragen
    (Timestamp = Silver-Ladezeit, InputBronzeTimestamp = Bronze-Ladezeit).
    Vorgehen nach https://sqlite.org/lang_altertable.html (neue Tabelle,
    kopieren, alte löschen, umbenennen); IDs und Verweise bleiben erhalten."""
    if "BusinessTransactions" not in _tables(conn):
        return
    cols = _columns(conn, "BusinessTransactions")
    if not cols.get("C4CExportID", {}).get("notnull"):
        return
    log.info("BusinessTransactions: Umbau auf das neue Schema (%s Zeilen)",
             conn.execute("SELECT COUNT(*) FROM BusinessTransactions").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""
            CREATE TABLE "BusinessTransactions_new" (
                "ID" VARCHAR(36) NOT NULL PRIMARY KEY,
                "C4CExportID" VARCHAR(36) UNIQUE REFERENCES "C4CExports" ("ID"),
                "GronosExportID" VARCHAR(36) UNIQUE REFERENCES "GronosExports" ("ID"),
                "UserEvaluationInputID" VARCHAR(36) UNIQUE REFERENCES "UserEvaluationInputs" ("ID"),
                "Timestamp" DATETIME,
                "InputBronzeTimestamp" DATETIME
            )""")
        conn.execute("""
            INSERT INTO BusinessTransactions_new (ID, C4CExportID, Timestamp, InputBronzeTimestamp)
            SELECT bt.ID, bt.C4CExportID,
                   (SELECT r.timestamp FROM GridConnectionRequests r WHERE r.BusinessTransactionID = bt.ID),
                   (SELECT e.Timestamp FROM C4CExports e WHERE e.ID = bt.C4CExportID)
            FROM BusinessTransactions bt""")
        conn.execute("DROP TABLE BusinessTransactions")
        conn.execute("ALTER TABLE BusinessTransactions_new RENAME TO BusinessTransactions")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Foreign-Key-Verletzungen nach Umbau: {violations[:5]}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def ensure_schema(db_path: str | Path) -> None:
    """Legt fehlende Tabellen an und ergänzt neue Spalten/Indizes in bestehenden.

    Neue Spalten sind nullable, bestehende Zeilen und IDs bleiben erhalten.
    Einmalige Umbauten (leere Alt-Tabellen, BusinessTransactions) laufen davor.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        _drop_legacy_tables(conn)
        _rebuild_business_transactions(conn)
    finally:
        conn.close()

    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"timeout": SQLITE_TIMEOUT_SECONDS}
    )
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            insp = inspect(conn)
            for table in Base.metadata.sorted_tables:
                existing = {c["name"] for c in insp.get_columns(table.name)}
                for column in table.columns:
                    if column.name not in existing:
                        col_type = column.type.compile(dialect=engine.dialect)
                        refs = "".join(
                            f" REFERENCES {_quote(fk.column.table.name)} ({_quote(fk.column.name)})"
                            for fk in column.foreign_keys
                        )
                        conn.exec_driver_sql(
                            f"ALTER TABLE {_quote(table.name)} ADD COLUMN {_quote(column.name)} {col_type}{refs}"
                        )
                for index in table.indexes:
                    index.create(conn, checkfirst=True)
    finally:
        engine.dispose()


@contextmanager
def write_transaction(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Schema sicherstellen → ``BEGIN IMMEDIATE`` → laden → FK-Prüfung → COMMIT.

    Schreibt direkt in die aktive Datei. Seit das Backend die Eingaben der
    Prüfer:innen in ``UserEvaluationInputs`` schreibt, gibt es zwei Schreiber;
    der frühere Datei-Tausch (Arbeitskopie + ``os.replace``) hätte deren
    Eingaben zwischen Snapshot und Tausch verloren. SQLite serialisiert die
    Schreiber über die Dateisperre (``busy_timeout``), Leser sehen dank der
    Transaktion nie einen halben Stand.
    """
    db_path = Path(db_path)
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"Foreign-Key-Verletzungen: {violations[:5]}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


# Alter Name, von Migrationen und Tests verwendet.
atomic_write = write_transaction


# --------------------------------------------------------------------------- #
# Kunden
# --------------------------------------------------------------------------- #
def _customer_key(row: dict) -> tuple:
    return tuple(row[c] for c in CUSTOMER_COLUMNS)


def _existing_customers(conn: sqlite3.Connection) -> dict[tuple, str]:
    return {
        tuple(r[1:]): r[0]
        for r in conn.execute(
            "SELECT ID, CustomerName, CustomerContactPerson, CustomerContactPersonEmail "
            "FROM GridConnectionCustomers"
        )
    }


def load_customers(conn: sqlite3.Connection, customers: pl.DataFrame) -> CustomerStats:
    """Legt fehlende Kunden an; vorhandene behalten ihre ID."""
    stats = CustomerStats()
    existing = _existing_customers(conn)
    for row in customers.iter_rows(named=True):
        key = _customer_key(row)
        if key in existing:
            stats.customers_existing += 1
            continue
        existing[key] = _insert_customer(conn, key)
        stats.customers_inserted += 1
    return stats


def _insert_customer(conn: sqlite3.Connection, key: tuple) -> str:
    customer_id = _new_id()
    conn.execute(
        "INSERT INTO GridConnectionCustomers "
        "(ID, CustomerName, CustomerContactPerson, CustomerContactPersonEmail) VALUES (?, ?, ?, ?)",
        (customer_id, *key),
    )
    return customer_id


# --------------------------------------------------------------------------- #
# Bronce
# --------------------------------------------------------------------------- #
def write_bronce(export: pl.DataFrame, file_name: str, file_sha: str, db_path: str | Path) -> BronceStats:
    """Hängt den Export as is an C4CExports an (positionsbasiert, alle Werte Text)."""
    if export.width != len(C4C_EXPORT_COLUMNS):
        raise ValueError(f"{export.width} Spalten, erwartet {len(C4C_EXPORT_COLUMNS)}")

    stats = BronceStats()
    with atomic_write(db_path) as conn:
        if conn.execute("SELECT 1 FROM C4CExports WHERE FileSha = ? LIMIT 1", (file_sha,)).fetchone():
            stats.already_loaded = True
            return stats

        cols = ["ID", "FileSha", "FileName", "Timestamp", *C4C_EXPORT_COLUMNS]
        sql = (
            f"INSERT INTO C4CExports ({', '.join(_quote(c) for c in cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})"
        )
        loaded_at = _utcnow()
        conn.executemany(sql, ((_new_id(), file_sha, file_name, loaded_at, *row) for row in export.iter_rows()))
        stats.rows_inserted = export.height
    return stats


# --------------------------------------------------------------------------- #
# Silver
# --------------------------------------------------------------------------- #
def _read_unprocessed_bronce(conn: sqlite3.Connection, file_sha: str | None) -> pl.DataFrame:
    """Bronce-Zeilen ohne BusinessTransactions, optional nur einer Lieferung."""
    cols = ", ".join(f"e.{_quote(c)}" for c in C4C_EXPORT_COLUMNS)
    sql = (
        f"SELECT e.ID, {cols} FROM C4CExports e "
        "LEFT JOIN BusinessTransactions bt ON bt.C4CExportID = e.ID "
        "WHERE bt.ID IS NULL"
    )
    params: tuple = ()
    if file_sha is not None:
        sql += " AND e.FileSha = ?"
        params = (file_sha,)
    sql += " ORDER BY e.rowid"  # Reihenfolge wie im Export (IDs sind UUIDs)

    schema = {"C4CExportID": pl.String, **{c: pl.String for c in C4C_EXPORT_COLUMNS}}
    return pl.DataFrame(conn.execute(sql, params).fetchall(), schema=schema, orient="row")


def _latest_request(conn: sqlite3.Connection, row: dict, cols: list[str]) -> tuple | None:
    """Werte ``cols`` des neuesten Eintrags desselben Tickets (oder None)."""
    return conn.execute(
        f"SELECT {', '.join(cols)} FROM GridConnectionRequests "
        "WHERE id_gronos_old IS ? AND id_gronos_new IS ? ORDER BY rowid DESC LIMIT 1",
        (row["id_gronos_old"], row["id_gronos_new"]),
    ).fetchone()


def _load_requests(conn: sqlite3.Connection, requests: pl.DataFrame, stats: LoadStats) -> None:
    customer_ids = _existing_customers(conn)
    value_cols = ["CustomerID", *REQUEST_COLUMNS]
    cols = ["ID", "BusinessTransactionID", *value_cols, "timestamp"]
    insert_sql = (
        f"INSERT INTO GridConnectionRequests ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    )
    loaded_at = _utcnow()

    for row in requests.iter_rows(named=True):
        key = _customer_key(row)
        customer_id = customer_ids.get(key)
        if customer_id is None:
            stats.customers_missing += 1
            log.warning(
                "Kunde %s zu Anfrage %s nicht in GridConnectionCustomers – Zeile übersprungen",
                key, row["id_gronos_old"],
            )
            continue

        values = (customer_id, *(row[c] for c in REQUEST_COLUMNS))
        if _latest_request(conn, row, value_cols) == values:
            stats.requests_unchanged += 1
            continue

        bt_id = _new_id()
        conn.execute(
            "INSERT INTO BusinessTransactions (ID, C4CExportID, Timestamp, InputBronzeTimestamp) "
            "VALUES (?, ?, ?, (SELECT Timestamp FROM C4CExports WHERE ID = ?))",
            (bt_id, row["C4CExportID"], loaded_at, row["C4CExportID"]),
        )
        stats.business_transactions_inserted += 1

        conn.execute(insert_sql, [_new_id(), bt_id, *values, loaded_at])
        stats.requests_inserted += 1


def write_silver(db_path: str | Path, file_sha: str) -> LoadStats:
    """Verarbeitet die noch offenen Bronce-Zeilen einer Lieferung nach Silver.

    Pro Lauf genau eine Lieferung (``file_sha``), damit Tickets in der
    Reihenfolge der Lieferungen versioniert werden. Strukturell fehlerhafte,
    übersprungene und unveränderte Zeilen bekommen keinen Eintrag in
    BusinessTransactions; fehlerhafte und Zeilen ohne Kunden erscheinen als
    Warnung im Log.
    """
    stats = LoadStats()
    with atomic_write(db_path) as conn:
        bronce = _read_unprocessed_bronce(conn, file_sha)
        if bronce.height == 0:
            return stats
        result = transform(to_raw(bronce, id_column="C4CExportID"))
        stats.rows_rejected = result.rejected.height
        _load_requests(conn, result.requests, stats)
    return stats


# --------------------------------------------------------------------------- #
# GRONOS-API – Bronze
# --------------------------------------------------------------------------- #
@dataclass
class GronosBronzeStats:
    rows_inserted: int = 0
    timestamp: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def known_gronos_states(db_path: str | Path) -> dict[str, str]:
    """objectId → neuestes ``updatedAt`` in Bronze (Basis für das Delta)."""
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        return {
            oid: updated
            for oid, updated in conn.execute(
                "SELECT json_extract(Content, '$.objectId') AS oid, MAX(json_extract(Content, '$.updatedAt')) "
                "FROM GronosExports GROUP BY oid"
            )
            if oid is not None
        }
    finally:
        conn.close()


def write_gronos_bronze(details: list[dict], db_path: str | Path) -> GronosBronzeStats:
    """Hängt die Detail-Antworten as is an GronosExports an – ein gemeinsamer
    Timestamp je Abruf, alles in einer Transaktion."""
    stats = GronosBronzeStats()
    if not details:
        return stats
    with write_transaction(db_path) as conn:
        stats.timestamp = _utcnow()
        conn.executemany(
            "INSERT INTO GronosExports (ID, Timestamp, Content) VALUES (?, ?, ?)",
            ((_new_id(), stats.timestamp, json.dumps(d, ensure_ascii=False)) for d in details),
        )
        stats.rows_inserted = len(details)
    return stats


# --------------------------------------------------------------------------- #
# GRONOS-API – Silver
# --------------------------------------------------------------------------- #
@dataclass
class GronosSilverStats:
    bronze_rows: int = 0
    business_transactions_inserted: int = 0
    requests_inserted: int = 0
    requests_unchanged: int = 0
    customers_inserted: int = 0
    customers_updated: int = 0
    rows_rejected: int = 0
    previous_input_bronze_timestamp: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _watermark(conn: sqlite3.Connection, source_column: str) -> str | None:
    return conn.execute(
        f"SELECT MAX(InputBronzeTimestamp) FROM BusinessTransactions WHERE {source_column} IS NOT NULL"
    ).fetchone()[0]


_CUSTOMER_VALUE_COLUMNS = ["CustomerName", "CustomerContactPerson", "CustomerContactPersonEmail", "VatNumber"]


def _upsert_gronos_customer(conn: sqlite3.Connection, customer: dict, stats: GronosSilverStats) -> str | None:
    """Kunde über CompanyID anlegen bzw. Stammdaten aktualisieren (nicht versioniert)."""
    if customer["CompanyID"] is None:
        return None
    row = conn.execute(
        f"SELECT ID, {', '.join(_CUSTOMER_VALUE_COLUMNS)} FROM GridConnectionCustomers WHERE CompanyID = ?",
        (customer["CompanyID"],),
    ).fetchone()
    values = tuple(customer[c] for c in _CUSTOMER_VALUE_COLUMNS)
    if row is None:
        customer_id = _new_id()
        conn.execute(
            "INSERT INTO GridConnectionCustomers (ID, CompanyID, CustomerName, CustomerContactPerson, "
            "CustomerContactPersonEmail, VatNumber) VALUES (?, ?, ?, ?, ?, ?)",
            (customer_id, customer["CompanyID"], *values),
        )
        stats.customers_inserted += 1
        return customer_id
    if tuple(row[1:]) != values:
        conn.execute(
            f"UPDATE GridConnectionCustomers SET {', '.join(f'{c} = ?' for c in _CUSTOMER_VALUE_COLUMNS)} WHERE ID = ?",
            (*values, row[0]),
        )
        stats.customers_updated += 1
    return row[0]


def _comparable(value):
    # SQLite liefert Booleans als 0/1 zurück
    return int(value) if isinstance(value, bool) else value


def write_gronos_silver(db_path: str | Path) -> GronosSilverStats:
    """BronzeToSilver für GRONOS: alle Bronze-Zeilen mit ``Timestamp`` nach dem
    InputBronzeTimestamp des vorherigen Laufs, in Abrufreihenfolge.

    Je verarbeiteter Bronze-Zeile eine BusinessTransaction (Timestamp =
    Zeitpunkt dieses Laufs, InputBronzeTimestamp = Timestamp der Bronze-Zeile).
    Ein neuer Eintrag in GridConnectionRequests entsteht nur, wenn sich die
    abgeleiteten Werte gegenüber dem neuesten Eintrag derselben
    ``GronosObjectID`` geändert haben (Änderungsprüfung wie im C4C-Pfad).
    """
    from grid_con_ingestion.gronos import REQUEST_VALUE_COLUMNS, derive_customer, derive_request

    stats = GronosSilverStats()
    with write_transaction(db_path) as conn:
        last = _watermark(conn, "GronosExportID")
        stats.previous_input_bronze_timestamp = last
        rows = conn.execute(
            "SELECT ID, Timestamp, Content FROM GronosExports WHERE (? IS NULL OR Timestamp > ?) "
            "ORDER BY Timestamp, rowid",
            (last, last),
        ).fetchall()
        stats.bronze_rows = len(rows)
        now = _utcnow()
        value_cols = ["CustomerID", *REQUEST_VALUE_COLUMNS]
        insert_sql = (
            f"INSERT INTO GridConnectionRequests (ID, BusinessTransactionID, {', '.join(value_cols)}, timestamp) "
            f"VALUES ({', '.join('?' for _ in range(len(value_cols) + 3))})"
        )
        for export_id, bronze_ts, content in rows:
            try:
                payload = json.loads(content)
                request = derive_request(payload)
            except (ValueError, TypeError, AttributeError) as exc:
                stats.rows_rejected += 1
                log.warning("GronosExports %s nicht lesbar (%s) – übersprungen", export_id, exc)
                continue
            if request["GronosObjectID"] is None:
                stats.rows_rejected += 1
                log.warning("GronosExports %s ohne objectId – übersprungen", export_id)
                continue

            bt_id = _new_id()
            conn.execute(
                "INSERT INTO BusinessTransactions (ID, GronosExportID, Timestamp, InputBronzeTimestamp) "
                "VALUES (?, ?, ?, ?)",
                (bt_id, export_id, now, bronze_ts),
            )
            stats.business_transactions_inserted += 1

            customer_id = _upsert_gronos_customer(conn, derive_customer(payload), stats)
            values = (customer_id, *(request[c] for c in REQUEST_VALUE_COLUMNS))
            latest = conn.execute(
                f"SELECT {', '.join(value_cols)} FROM GridConnectionRequests WHERE GronosObjectID = ? "
                "ORDER BY timestamp DESC, rowid DESC LIMIT 1",
                (request["GronosObjectID"],),
            ).fetchone()
            if latest is not None and tuple(latest) == tuple(_comparable(v) for v in values):
                stats.requests_unchanged += 1
                continue
            conn.execute(insert_sql, (_new_id(), bt_id, *values, now))
            stats.requests_inserted += 1
    return stats


# --------------------------------------------------------------------------- #
# Bewertungen – Gold
# --------------------------------------------------------------------------- #
@dataclass
class GoldStats:
    inputs: int = 0
    business_transactions_inserted: int = 0
    checks_inserted: int = 0
    rows_rejected: int = 0
    previous_input_bronze_timestamp: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def next_input_timestamp(conn: sqlite3.Connection) -> str:
    """Timestamp für neue UserEvaluationInputs: jetzt, aber streng größer als
    jeder vorhandene. Innerhalb einer Schreibtransaktion aufrufen; so kann
    keine Eingabe hinter der Wasserlinie von BronzeToGold landen. Gegenstück
    im Backend: app/evaluation.py."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last = conn.execute("SELECT MAX(Timestamp) FROM UserEvaluationInputs").fetchone()[0]
    if last is not None:
        floor = datetime.fromisoformat(last) + timedelta(microseconds=1)
        now = max(now, floor)
    return now.isoformat(sep=" ", timespec="microseconds")


def _valid_input(conn: sqlite3.Connection, check_id: str, verdict: str, score) -> str | None:
    """Fehlertext, falls die Eingabe nicht zum Framework passt (sonst None)."""
    from grid_con_ingestion.models import VERDICTS

    if verdict not in VERDICTS:
        return f"unbekannter Verdict {verdict!r}"
    check = conn.execute("SELECT CheckType, Points FROM EvaluationChecks WHERE ID = ?", (check_id,)).fetchone()
    if check is None:
        return f"unbekannter Check {check_id!r}"
    if score is not None and not (0 <= score <= check[1]):
        return f"Punkte {score} außerhalb 0…{check[1]}"
    return None


def write_gold(db_path: str | Path) -> GoldStats:
    """BronzeToGold: alle UserEvaluationInputs mit ``Timestamp`` nach dem
    InputBronzeTimestamp des vorherigen Laufs → RequestEvaluationChecks.

    Je Eingabe eine BusinessTransaction und ein Gold-Eintrag mit fortlaufender
    ``Version`` je Antrag (``id_gronos_new``), Nutzer:in und Check. Das
    Framework wird vorher abgeglichen (idempotent), damit die Config-Tabellen
    immer zum Code passen.
    """
    from grid_con_ingestion.evaluation_framework import sync_framework

    stats = GoldStats()
    with write_transaction(db_path) as conn:
        sync_framework(conn)
        last = _watermark(conn, "UserEvaluationInputID")
        stats.previous_input_bronze_timestamp = last
        rows = conn.execute(
            "SELECT i.ID, i.GridConnectionRequestID, i.EvaluationCheckID, i.UserID, i.EvaluationVerdict, "
            "i.EvaluationScore, i.Comment, i.Timestamp, r.id_gronos_new "
            "FROM UserEvaluationInputs i JOIN GridConnectionRequests r ON r.ID = i.GridConnectionRequestID "
            "WHERE (? IS NULL OR i.Timestamp > ?) ORDER BY i.Timestamp, i.rowid",
            (last, last),
        ).fetchall()
        stats.inputs = len(rows)
        now = _utcnow()
        for input_id, request_id, check_id, user_id, verdict, score, comment, ts, ticket in rows:
            problem = _valid_input(conn, check_id, verdict, score)
            if problem:
                stats.rows_rejected += 1
                log.warning("UserEvaluationInputs %s übersprungen: %s", input_id, problem)
                continue
            version = conn.execute(
                "SELECT COALESCE(MAX(c.Version), 0) + 1 FROM RequestEvaluationChecks c "
                "JOIN GridConnectionRequests r ON r.ID = c.GridConnectionRequestID "
                "WHERE c.UserID = ? AND c.EvaluationCheckID = ? AND "
                "(r.id_gronos_new = ? OR (? IS NULL AND r.ID = ?))",
                (user_id, check_id, ticket, ticket, request_id),
            ).fetchone()[0]
            bt_id = _new_id()
            conn.execute(
                "INSERT INTO BusinessTransactions (ID, UserEvaluationInputID, Timestamp, InputBronzeTimestamp) "
                "VALUES (?, ?, ?, ?)",
                (bt_id, input_id, now, ts),
            )
            conn.execute(
                "INSERT INTO RequestEvaluationChecks (ID, GridConnectionRequestID, UserID, EvaluationCheckID, "
                "BusinessTransactionID, EvaluationVerdict, EvaluationScore, EvaluationComment, Version, Timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_new_id(), request_id, user_id, check_id, bt_id, verdict, score, comment, version, ts),
            )
            stats.business_transactions_inserted += 1
            stats.checks_inserted += 1
    return stats


# --------------------------------------------------------------------------- #
# Nutzer:innen
# --------------------------------------------------------------------------- #
def upsert_users(conn: sqlite3.Connection, users: list[dict]) -> dict[str, int]:
    """Legt Nutzer:innen über die E-Mail an bzw. aktualisiert Name und Rolle."""
    from grid_con_ingestion.models import ROLES

    inserted = updated = 0
    for u in users:
        email = u["email"].strip().lower()
        if u["role"] not in ROLES:
            raise ValueError(f"Unbekannte Rolle {u['role']!r}, erlaubt: {list(ROLES)}")
        row = conn.execute("SELECT ID, Name, Role FROM Users WHERE Email = ?", (email,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO Users (ID, Email, Name, Role) VALUES (?, ?, ?, ?)",
                (_new_id(), email, u.get("name"), u["role"]),
            )
            inserted += 1
        elif (row[1], row[2]) != (u.get("name"), u["role"]):
            conn.execute("UPDATE Users SET Name = ?, Role = ? WHERE ID = ?", (u.get("name"), u["role"], row[0]))
            updated += 1
    return {"users_inserted": inserted, "users_updated": updated}
