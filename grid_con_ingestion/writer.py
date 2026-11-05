"""Schreibt Bronce und Silver in die zentrale SQLite-Datei.

Zwei Schreiber: Input Orchestration (Bronze, Silver, Gold, Config) und das
Backend (nur ``UserEvaluationInputs``, die Eingaben der Prüfer:innen). Jeder
Schreibvorgang läuft deshalb direkt auf der aktiven Datei in einer
Transaktion (:func:`write_transaction`, ``BEGIN IMMEDIATE`` +
``busy_timeout``). Der frühere Datei-Tausch (Arbeitskopie + ``os.replace``)
hätte Eingaben aus dem Backend zwischen Snapshot und Tausch verloren. Leser
sehen dank der Transaktion nie einen halben Stand.

Bronce (:func:`write_bronce`)
  Der Export wird as is in ``C4CExports`` angehängt, je Lieferung mit
  FileSha, FileName und Timestamp. Eine Lieferung mit bereits geladenem
  FileSha wird übersprungen.

Silver (:func:`write_silver`)
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
    # feste Länge (immer mit Mikrosekunden), damit Textvergleiche = Zeitvergleiche sind
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# --------------------------------------------------------------------------- #
# Schema und transaktionales Schreiben
# --------------------------------------------------------------------------- #
SQLITE_TIMEOUT_SECONDS = 30.0

# Umbenannte Spalten (alt → neu), werden in bestehenden Datenbanken nachgezogen.
_RENAMED_COLUMNS = {
    "BusinessTransactions": {"TimestampImportBronze": "InputBronzeTimestamp", "TimestampImportSilver": "Timestamp"},
}


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Verbindung für Schreiber: Autocommit-Modus, Transaktionen explizit."""
    conn = sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT_SECONDS, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout = {int(SQLITE_TIMEOUT_SECONDS * 1000)}")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({_quote(table)})")}


def _rename_columns(conn: sqlite3.Connection) -> None:
    for table, renames in _RENAMED_COLUMNS.items():
        existing = _columns(conn, table)
        for old, new in renames.items():
            if old in existing and new not in existing:
                conn.execute(f"ALTER TABLE {_quote(table)} RENAME COLUMN {_quote(old)} TO {_quote(new)}")
                log.info("%s: Spalte %s in %s umbenannt", table, old, new)


def ensure_schema(db_path: str | Path) -> None:
    """Legt fehlende Tabellen an und ergänzt neue Spalten/Indizes in bestehenden.

    Neue Spalten sind nullable, bestehende Zeilen und IDs bleiben erhalten;
    umbenannte Spalten werden vorher umbenannt.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        _rename_columns(conn)
    finally:
        conn.close()

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": SQLITE_TIMEOUT_SECONDS})
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

    Schreibt direkt in die aktive Datei. SQLite serialisiert die Schreiber
    (DAGs und Backend) über die Dateisperre, ``busy_timeout`` lässt den
    zweiten warten. Bei einem Fehler wird alles zurückgerollt.
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


# Bisheriger Name, von GRONOS-Store, Migrationen und Tests verwendet.
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


def _watermark(conn: sqlite3.Connection, source_column: str) -> str | None:
    """InputBronzeTimestamp des letzten verarbeiteten Bronze-Eintrags einer Quelle."""
    return conn.execute(
        f"SELECT MAX(InputBronzeTimestamp) FROM BusinessTransactions WHERE {_quote(source_column)} IS NOT NULL"
    ).fetchone()[0]


# --------------------------------------------------------------------------- #
# Bewertungen – Gold
# --------------------------------------------------------------------------- #
@dataclass
class GoldStats:
    inputs: int = 0
    business_transactions_inserted: int = 0
    checks_inserted: int = 0
    rows_unchanged: int = 0
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


def input_unchanged(latest: tuple, verdict: str, score, comment: str | None) -> bool:
    """Delta-Regel: eine Eingabe ist unverändert, wenn Verdict und Punkte dem
    letzten Gold-Eintrag ``(verdict, score, comment)`` derselben Nutzer:in und
    desselben Checks entsprechen und sie keinen neuen Kommentar trägt (keiner
    oder derselbe). Ein neuer Kommentar zu gleichem Wert wird gespeichert.
    Gegenstück im Backend: app/evaluation.py ``unchanged``."""
    last_verdict, last_score, last_comment = latest
    return (
        verdict == last_verdict
        and (None if score is None else float(score)) == (None if last_score is None else float(last_score))
        and (not comment or comment == last_comment)
    )


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


class FrameworkNotSeeded(RuntimeError):
    """BronzeToGold ohne Framework in den Config-Tabellen."""


def write_gold(db_path: str | Path) -> GoldStats:
    """BronzeToGold: alle UserEvaluationInputs mit ``Timestamp`` nach dem
    InputBronzeTimestamp des vorherigen Laufs → RequestEvaluationChecks.

    Jede Eingabe bekommt eine BusinessTransaction (auch verworfene und
    unveränderte, so rückt die Wasserlinie immer vor). Ein Gold-Eintrag mit fortlaufender
    ``Version`` je Antrag (``id_gronos_new``), Nutzer:in und Check entsteht nur,
    wenn sich die Eingabe vom letzten Gold-Eintrag unterscheidet (Delta, siehe
    ``input_unchanged``); eine BusinessTransaction ohne Gold-Eintrag heißt
    "verarbeitet, unverändert". Die Config-Tabellen des Frameworks füllt der
    Seeding-DAG ``grid_con_seed_config``; BronzeToGold liest sie nur und
    bricht ab, solange sie leer sind (sonst würde jede Eingabe verworfen).
    """
    from grid_con_ingestion.evaluation_framework import framework_seeded

    stats = GoldStats()
    with write_transaction(db_path) as conn:
        if not framework_seeded(conn):
            raise FrameworkNotSeeded(
                "Evaluation framework is empty (EvaluationChecks). Run the seeding DAG grid_con_seed_config first."
            )
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
            bt_id = _new_id()
            conn.execute(
                "INSERT INTO BusinessTransactions (ID, UserEvaluationInputID, Timestamp, InputBronzeTimestamp) "
                "VALUES (?, ?, ?, ?)",
                (bt_id, input_id, now, ts),
            )
            stats.business_transactions_inserted += 1
            problem = _valid_input(conn, check_id, verdict, score)
            if problem:
                stats.rows_rejected += 1
                log.warning("UserEvaluationInputs %s übersprungen: %s", input_id, problem)
                continue
            latest = conn.execute(
                "SELECT c.Version, c.EvaluationVerdict, c.EvaluationScore, c.EvaluationComment "
                "FROM RequestEvaluationChecks c "
                "JOIN GridConnectionRequests r ON r.ID = c.GridConnectionRequestID "
                "WHERE c.UserID = ? AND c.EvaluationCheckID = ? AND "
                "(r.id_gronos_new = ? OR (? IS NULL AND r.ID = ?)) ORDER BY c.Version DESC LIMIT 1",
                (user_id, check_id, ticket, ticket, request_id),
            ).fetchone()
            if latest is not None and input_unchanged(latest[1:], verdict, score, comment):
                stats.rows_unchanged += 1
                continue
            version = (latest[0] if latest else 0) + 1
            conn.execute(
                "INSERT INTO RequestEvaluationChecks (ID, GridConnectionRequestID, UserID, EvaluationCheckID, "
                "BusinessTransactionID, EvaluationVerdict, EvaluationScore, EvaluationComment, Version, Timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_new_id(), request_id, user_id, check_id, bt_id, verdict, score, comment, version, ts),
            )
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
