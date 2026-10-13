"""Schreibt Bronce und Silver in die zentrale SQLite-Datei.

Wie im AI-Cockpit-Referenzprojekt ist Input Orchestration der einzige
Schreiber, das Backend liest nur. Damit das Backend nie einen halb
geschriebenen Stand sieht, läuft jeder Schreibvorgang über
:func:`atomic_write`:
  1. der aktuelle Stand wird per SQLite-Backup-API in eine Arbeitskopie gezogen,
  2. dort das Schema sichergestellt und geladen,
  3. die Arbeitskopie per atomarem ``os.replace`` aktiv geschaltet.

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
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# --------------------------------------------------------------------------- #
# Schema und atomares Schreiben
# --------------------------------------------------------------------------- #
def ensure_schema(db_path: str | Path) -> None:
    """Legt fehlende Tabellen an und ergänzt neue Spalten/Indizes in bestehenden.

    Neue Spalten sind nullable, bestehende Zeilen und IDs bleiben erhalten.
    """
    engine = create_engine(f"sqlite:///{db_path}")
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
def atomic_write(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Arbeitskopie → Schema → Transaktion → FK-Prüfung → atomarer Tausch."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_name(db_path.stem + ".new" + db_path.suffix)
    tmp_path.unlink(missing_ok=True)

    # 1. konsistenter Snapshot des aktiven Stands
    if db_path.exists():
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()

    # 2. Schema + Laden in der Arbeitskopie
    ensure_schema(tmp_path)
    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            yield conn
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Foreign-Key-Verletzungen: {violations[:5]}")
    except BaseException:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        raise
    conn.close()

    # 3. atomarer Tausch – Backend sieht nie einen halben Stand
    os.replace(tmp_path, db_path)


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
            "INSERT INTO BusinessTransactions (ID, C4CExportID) VALUES (?, ?)", (bt_id, row["C4CExportID"])
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
