"""Bronze and Silver load for the GRONOS API (SQLite, via writer.atomic_write).

RawToBronze (:func:`raw_to_bronze`)
  1. list all requests (company-id prefixes, unique by objectId),
  2. keep an objectId if it is new, or if its ``updatedAt`` is newer than
     the newest state already in Bronze
     (``MAX(json_extract(Content, '$.updatedAt'))`` per objectId),
  3. fetch the detail of each remaining objectId,
  4. append one ``GronosExports`` row per detail: ``Content`` = JSON of the
     request as is, ``Timestamp`` = time of the pull (one value per pull).
  All rows of a pull are written in one transaction. A list error fails the
  run before anything is written; a failing detail is skipped (logged, not in
  Bronze, so the next run tries it again) unless 5 fail in a row.

BronzeToSilver (:func:`bronze_to_silver`)
  1. watermark = ``MAX(BusinessTransactions.InputBronzeTimestamp)``,
  2. read every ``GronosExports`` row with ``Timestamp`` > watermark
     (everything on the first run), oldest first,
  3. parse ``Content`` (gronos/transform.py), upsert the customer by
     ``CompanyID``,
  4. write one ``BusinessTransactions`` row per Bronze row
     (``GronosExportID``, ``InputBronzeTimestamp`` = Bronze ``Timestamp``,
     ``Timestamp`` = now) – also for unchanged or invalid rows,
     so the watermark moves on,
  5. append a new ``GridConnectionRequests`` record (new UUID, ``timestamp``
     = ``Timestamp``) unless its values equal the newest record
     with the same ``GronosObjectID`` (same change check as the Excel import;
     ``SourceUpdatedAt`` alone does not count as a change).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from grid_con_ingestion.gronos.client import GronosApiError, GronosClient
from grid_con_ingestion.gronos.transform import (
    CUSTOMER_VALUE_COLUMNS,
    REQUEST_VALUE_COLUMNS,
    InvalidContent,
    to_silver,
)
from grid_con_ingestion.writer import _new_id, _utcnow, atomic_write

# Child of "airflow.task": the lines land in the Airflow task log in every
# executor/logging setup; outside Airflow it is a normal logger.
log = logging.getLogger("airflow.task.gronos.store")


@dataclass
class BronzeStats:
    listed: int = 0
    list_calls: int = 0
    duplicates: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    from_list: int = 0
    detail_failed: int = 0
    rows_inserted: int = 0
    timestamp: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SilverStats:
    bronze_rows: int = 0
    business_transactions_inserted: int = 0
    requests_inserted: int = 0
    requests_unchanged: int = 0
    customers_inserted: int = 0
    customers_updated: int = 0
    rows_rejected: int = 0
    watermark: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Bronze
# --------------------------------------------------------------------------- #
CURRENT_STATE_SQL = (
    "SELECT json_extract(Content, '$.objectId') AS oid, MAX(json_extract(Content, '$.updatedAt')) "
    "FROM GronosExports GROUP BY oid"
)


def current_states(db_path: str | Path) -> dict[str, str | None]:
    """objectId -> newest ``updatedAt`` in Bronze (read-only, empty if no DB yet)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'GronosExports'"
        ).fetchone()
        if not exists:
            return {}
        return {oid: updated for oid, updated in conn.execute(CURRENT_STATE_SQL) if oid}
    finally:
        conn.close()


def is_newer(updated_at: str | None, known: str | None) -> bool:
    """API ``updatedAt`` strings share one ISO format, so text order = time order."""
    if updated_at is None:
        return False
    return known is None or updated_at > known


def select_changed(listing: Iterable[dict], known: dict[str, str | None], stats: BronzeStats) -> list[dict]:
    changed = []
    for rec in listing:
        oid = rec["objectId"]
        if oid not in known:
            stats.new += 1
            changed.append(rec)
        elif is_newer(rec.get("updatedAt"), known[oid]):
            stats.updated += 1
            changed.append(rec)
        else:
            stats.unchanged += 1
    return changed


def write_bronze(db_path: str | Path, details: list[dict]) -> tuple[int, str | None]:
    """Appends one GronosExports row per detail; returns (rows, Timestamp)."""
    if not details:
        return 0, None
    with atomic_write(db_path) as conn:
        pulled_at = _utcnow()
        conn.executemany(
            "INSERT INTO GronosExports (ID, Timestamp, Content) VALUES (?, ?, ?)",
            (
                (_new_id(), pulled_at, json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
                for rec in details
            ),
        )
    return len(details), pulled_at


MAX_CONSECUTIVE_DETAIL_FAILURES = 5
DETAIL_MODES = ("always", "auto", "never")


def needs_detail(rec: dict, mode: str) -> bool:
    """always: detail call per request (dev: the list has no contacts/stages).
    auto: only if the list record lacks ``contacts`` (ACC: the list is complete).
    never: store the list record."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    return "contacts" not in rec


def raw_to_bronze(
    client: GronosClient, db_path: str | Path, prefixes: list[str], detail_mode: str = "always"
) -> BronzeStats:
    if detail_mode not in DETAIL_MODES:
        raise ValueError(f"Unknown GRONOS_DETAIL_MODE {detail_mode!r}, expected one of {DETAIL_MODES}")
    stats = BronzeStats()
    log.info("RawToBronze: %d prefixes (%s ... %s), DB %s", len(prefixes), prefixes[0] if prefixes else "-",
             prefixes[-1] if prefixes else "-", db_path)
    listing = client.list_all(prefixes)
    stats.listed, stats.list_calls, stats.duplicates = len(listing.records), listing.calls, listing.duplicates
    if listing.split_prefixes:
        log.info("Split prefixes (gateway timeout): %s", listing.split_prefixes)

    known = current_states(db_path)
    log.info("Bronze already holds %d objectIds", len(known))
    changed = select_changed(listing.records, known, stats)
    to_fetch = [rec for rec in changed if needs_detail(rec, detail_mode)]
    details = [rec for rec in changed if not needs_detail(rec, detail_mode)]
    stats.from_list = len(details)
    log.info(
        "List done: %d requests (%d calls) - %d new, %d updated, %d unchanged; "
        "detail mode %s: %d taken from the list, fetching %d details",
        stats.listed, stats.list_calls, stats.new, stats.updated, stats.unchanged,
        detail_mode, len(details), len(to_fetch),
    )

    detail_start = time.monotonic()
    consecutive_failures = 0
    for i, rec in enumerate(to_fetch, start=1):
        started = time.monotonic()
        try:
            detail = client.detail(rec["objectId"], rec.get("companyId"))
        except GronosApiError as exc:
            # One bad request must not cost the whole run. It is not in Bronze,
            # so the next run tries it again. Many failures in a row point to a
            # general problem (auth, gateway) -> fail the task.
            stats.detail_failed += 1
            consecutive_failures += 1
            log.warning("Detail %d/%d skipped, retried next run: %s", i, len(to_fetch), exc)
            if consecutive_failures >= MAX_CONSECUTIVE_DETAIL_FAILURES:
                raise GronosApiError(
                    f"{consecutive_failures} detail calls in a row failed, aborting (last: {exc})"
                ) from exc
            continue
        consecutive_failures = 0
        elapsed = time.monotonic() - detail_start
        remaining = elapsed / i * (len(to_fetch) - i)
        log.info(
            "Detail %d/%d objectId %s: %.1f s (elapsed %.0f s, approx. %.0f min left)",
            i, len(to_fetch), rec["objectId"], time.monotonic() - started, elapsed, remaining / 60,
        )
        # Same state as in Bronze already (e.g. list was newer than detail)? skip
        if rec["objectId"] in known and not is_newer(detail.get("updatedAt"), known[rec["objectId"]]):
            stats.unchanged += 1
            continue
        details.append(detail)

    if stats.detail_failed:
        log.warning("%d of %d detail calls failed and were skipped", stats.detail_failed, len(to_fetch))
    log.info("Writing %d rows to GronosExports ...", len(details))
    stats.rows_inserted, stats.timestamp = write_bronze(db_path, details)
    return stats


# --------------------------------------------------------------------------- #
# Silver
# --------------------------------------------------------------------------- #
def _watermark(conn: sqlite3.Connection) -> str | None:
    return conn.execute(
        "SELECT MAX(InputBronzeTimestamp) FROM BusinessTransactions WHERE GronosExportID IS NOT NULL"
    ).fetchone()[0]


def _new_bronze_rows(conn: sqlite3.Connection, watermark: str | None) -> list[tuple[str, str, str]]:
    return conn.execute(
        "SELECT ID, Timestamp, Content FROM GronosExports "
        "WHERE ? IS NULL OR Timestamp > ? ORDER BY Timestamp, rowid",
        (watermark, watermark),
    ).fetchall()


def _upsert_customer(conn: sqlite3.Connection, customer: dict, stats: SilverStats) -> str:
    cols = CUSTOMER_VALUE_COLUMNS[1:]
    row = conn.execute(
        f"SELECT ID, {', '.join(cols)} FROM GridConnectionCustomers WHERE CompanyID = ?",
        (customer["CompanyID"],),
    ).fetchone()
    if row is None:
        customer_id = _new_id()
        conn.execute(
            f"INSERT INTO GridConnectionCustomers (ID, {', '.join(CUSTOMER_VALUE_COLUMNS)}) "
            f"VALUES (?, {', '.join('?' for _ in CUSTOMER_VALUE_COLUMNS)})",
            (customer_id, *(customer[c] for c in CUSTOMER_VALUE_COLUMNS)),
        )
        stats.customers_inserted += 1
        return customer_id

    customer_id, *current = row
    # keep known values if a newer request leaves them empty
    new = [customer[c] if customer[c] is not None else old for c, old in zip(cols, current)]
    if new != list(current):
        conn.execute(
            f"UPDATE GridConnectionCustomers SET {', '.join(f'{c} = ?' for c in cols)} WHERE ID = ?",
            (*new, customer_id),
        )
        stats.customers_updated += 1
    return customer_id


def _latest_values(conn: sqlite3.Connection, object_id: str, cols: list[str]) -> tuple | None:
    return conn.execute(
        f"SELECT {', '.join(cols)} FROM GridConnectionRequests "
        "WHERE GronosObjectID = ? ORDER BY rowid DESC LIMIT 1",
        (object_id,),
    ).fetchone()


# A new updatedAt alone (change in a field Silver does not show, e.g. a phone
# number) does not create a new Silver record.
NOT_COMPARED = frozenset({"SourceUpdatedAt"})


def bronze_to_silver(db_path: str | Path) -> SilverStats:
    stats = SilverStats()
    value_cols = ["CustomerID", *REQUEST_VALUE_COLUMNS]
    compare_cols = [c for c in value_cols if c not in NOT_COMPARED]
    insert_cols = ["ID", "BusinessTransactionID", *value_cols, "timestamp"]
    insert_sql = (
        f"INSERT INTO GridConnectionRequests ({', '.join(insert_cols)}) "
        f"VALUES ({', '.join('?' for _ in insert_cols)})"
    )

    with atomic_write(db_path) as conn:
        stats.watermark = _watermark(conn)
        rows = _new_bronze_rows(conn, stats.watermark)
        stats.bronze_rows = len(rows)
        imported_at = _utcnow()

        for export_id, bronze_ts, content in rows:
            bt_id = _new_id()
            conn.execute(
                "INSERT INTO BusinessTransactions "
                "(ID, GronosExportID, InputBronzeTimestamp, Timestamp) VALUES (?, ?, ?, ?)",
                (bt_id, export_id, bronze_ts, imported_at),
            )
            stats.business_transactions_inserted += 1

            try:
                record = to_silver(content)
            except InvalidContent as exc:
                stats.rows_rejected += 1
                log.warning("GronosExports %s cannot be processed (%s) - kept in Bronze only", export_id, exc)
                continue

            customer_id = _upsert_customer(conn, record.customer, stats) if record.customer else None
            values = (customer_id, *(_db(record.request[c]) for c in REQUEST_VALUE_COLUMNS))
            compared = tuple(v for c, v in zip(value_cols, values) if c not in NOT_COMPARED)
            if _latest_values(conn, record.request["GronosObjectID"], compare_cols) == compared:
                stats.requests_unchanged += 1
                continue
            conn.execute(insert_sql, (_new_id(), bt_id, *values, imported_at))
            stats.requests_inserted += 1
    return stats


def _db(value):
    """Python value as SQLite returns it (bool -> 0/1), for the change check."""
    return int(value) if isinstance(value, bool) else value
