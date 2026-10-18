"""Bronce → Silver Transformation für den C4C/GRONOS-Export (Polars).

Der Export hat verschobene Spaltenüberschriften (z. B. steht der Ticket-Status
unter "Official request date"). Darum wird **positionsbasiert** gemappt: die
Rohdaten werden mit korrigierten Spaltennamen (``RAW_COLUMNS``) versehen und
erst danach auf das Zielmodell abgebildet.

Ergebnis von :func:`transform` ist ein :class:`SilverResult` mit
  * ``customers`` – Spalten wie Tabelle GridConnectionCustomers (ohne ID)
  * ``requests``  – Spalten wie GridConnectionRequests (ohne ID / CustomerID)
                    plus Join-Schlüssel auf den Kunden
  * ``rejected``  – strukturell fehlerhafte Rohzeilen (werden nicht geladen)

Enthält der Eingang die Spalte ``C4CExportID`` (Zeilen aus der Bronce-Tabelle),
wird sie an ``requests`` durchgereicht.
"""
from __future__ import annotations
import sys
sys.path.insert(0, '/tmp/airflow_packages')

import os
print("DEBUG", os.getuid(), sys.executable, sys.version, sys.path[:3], os.listdir("/tmp/airflow_packages"))

import logging
from dataclasses import dataclass
from pathlib import Path

try:
    import polars as pl
except ImportError as e:
    import os
    raise ImportError(
        f"DEBUG uid={os.getuid()} exe={sys.executable} path={sys.path[:4]} "
        f"tmp={os.listdir('/tmp/airflow_packages') if os.path.isdir('/tmp/airflow_packages') else 'FEHLT'}"
    ) from e

log = logging.getLogger(__name__)

# Werte, die im Quellsystem "nicht befüllt" bedeuten → NULL
NULL_TOKENS: frozenset[str] = frozenset({"", "#", "Nicht zugeordnet"})

# Korrigierte Spaltennamen in Quellreihenfolge (Position = Spaltenindex).
# Abgeleitet aus dem Inhalt der Spalten, nicht aus den (verschobenen) Headern.
RAW_COLUMNS: list[str] = [
    "ticket",                      # 0  Projekt-xxxx
    "ticket_id",                   # 1  numerische Ticket-ID
    "status",                      # 2  Ticket-Status
    "official_request_date",       # 3
    "complete_request_date",       # 4
    "next_actor",                  # 5  Kunde / Netzbetreiber / ...
    "statement_issued_date",       # 6
    "statement_expiry_date",       # 7
    "connection_technology_raw",   # 8  gemischt DE/EN, Freitext
    "elo_link",                    # 9  Dokumentreferenz
    "connection_point",            # 10 Anschlusspunkt (Standort/UW)
    "connection_solution",         # 11 Schaltfeld / Stich / Doppelstich
    "voltage_level",               # 12 380 kV / 110 kV
    "grid_info_case_number",       # 13 Vorgangsnummer Netzauskunft
    "commissioning_date",          # 14
    "stakeholder",                 # 15 Kunde (Unternehmen)
    "account_id",                  # 16
    "account_address",             # 17
    "s4_business_partner",         # 18
    "s4_customer_id",              # 19
    "gpdb_id",                     # 20
    "contact_id",                  # 21
    "contact_name",                # 22
    "contact_email",               # 23
    "phone",                       # 24
    "mobile",                      # 25
    "plant_location_address",      # 26
    "vnb",                         # 27
    "description",                 # 28
    "connection_technology",       # 29 normierte Technologie(n), " | "-getrennt
    "connection_technology_code",  # 30
    "installed_capacity",          # 31 "1.530,00 MW" bzw. "20,00 MW | 100,00 MW"
    "overflow",                    # 32 nur bei fehlerhaften Zeilen befüllt
]

CUSTOMER_COLUMNS = ["CustomerName", "CustomerContactPerson", "CustomerContactPersonEmail"]
REQUEST_COLUMNS = [
    "RequestStatus",
    "SubstationLocation",
    "GenerationTechnology",
    "Substation50Hertz",
    "maxP",
    "SwitchCount",
    "DocumentURL",
    "id_gronos_old",
    "id_gronos_new",
    "RequestComment",
]


@dataclass(frozen=True)
class SilverResult:
    customers: pl.DataFrame
    requests: pl.DataFrame
    rejected: pl.DataFrame


# --------------------------------------------------------------------------- #
# Lesen
# --------------------------------------------------------------------------- #
def read_export(path: str | Path) -> pl.DataFrame:
    """Liest eine Rohdatei as is: Originalheader, alle Werte als Text."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        df = pl.read_excel(path, infer_schema_length=0)
    elif suffix == ".csv":
        df = pl.read_csv(path, infer_schema_length=0)
    else:
        raise ValueError(f"Nicht unterstütztes Dateiformat: {path.name}")

    if df.width != len(RAW_COLUMNS):
        raise ValueError(
            f"{path.name}: {df.width} Spalten gefunden, erwartet {len(RAW_COLUMNS)}. "
            "Exportformat hat sich geändert – Mapping in transform.RAW_COLUMNS prüfen."
        )
    return df


def to_raw(export: pl.DataFrame, id_column: str | None = None) -> pl.DataFrame:
    """Versieht die Exportspalten positionsbasiert mit den korrigierten Namen.

    ``id_column`` (z. B. ``C4CExportID``) wird unverändert mitgeführt.
    """
    data_columns = [c for c in export.columns if c != id_column]
    return export.rename(dict(zip(data_columns, RAW_COLUMNS)))


def read_raw(path: str | Path) -> pl.DataFrame:
    """Liest eine Rohdatei komplett als Text (keine implizite Typinferenz)."""
    return to_raw(read_export(path))


# --------------------------------------------------------------------------- #
# Bausteine
# --------------------------------------------------------------------------- #
def normalize_nulls(df: pl.DataFrame, tokens: frozenset[str] = NULL_TOKENS) -> pl.DataFrame:
    """Trimmt alle Textspalten und ersetzt Platzhalter / Leerwerte durch NULL."""
    exprs = []
    for name, dtype in df.schema.items():
        if dtype == pl.String:
            trimmed = pl.col(name).str.strip_chars()
            exprs.append(
                pl.when(trimmed.is_in(list(tokens))).then(None).otherwise(trimmed).alias(name)
            )
    return df.with_columns(exprs)


def parse_capacity_mw(col: str) -> pl.Expr:
    """'1.530,00 MW | 20,00 MW' → 1550.0 (Summe in MW). Leer → NULL."""
    parts = (
        pl.col(col)
        .str.split("|")
        .list.eval(
            pl.element()
            .str.replace_all(r"(?i)mw", "")
            .str.replace_all(r"[,\s]+$", "")      # z. B. "300,00 MW,,,,"
            .str.strip_chars()
            .str.replace_all(r"\.", "")           # Tausenderpunkt
            .str.replace(",", ".")                # Dezimalkomma
            .cast(pl.Float64, strict=False)
        )
    )
    return (
        pl.when(parts.list.drop_nulls().list.len() > 0)
        .then(parts.list.sum())
        .otherwise(None)
    )


def parse_switch_count(col: str) -> pl.Expr:
    """Anzahl Schaltfelder aus der Anschlusslösung.

    '2 Schaltfelder Bestands-UW/SA' → 2, 'Schaltfeld Bestands-UW/SA' → 1,
    alles andere (Stich, Doppelstich, leer) → NULL.
    """
    leading = pl.col(col).str.extract(r"^\s*(\d+)\s+Schaltfeld", 1).cast(pl.Int64, strict=False)
    return (
        pl.when(leading.is_not_null())
        .then(leading)
        .when(pl.col(col).str.contains(r"(?i)schaltfeld"))
        .then(pl.lit(1, dtype=pl.Int64))
        .otherwise(None)
    )


def split_valid_rows(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Trennt strukturell fehlerhafte Zeilen ab (z. B. durch Kommas verschobene Felder)."""
    ticket_id_int = pl.col("ticket_id").cast(pl.Int64, strict=False)
    is_bad = (
        pl.col("overflow").is_not_null()
        | (pl.col("ticket_id").is_not_null() & ticket_id_int.is_null())
        | pl.col("ticket").is_null()
    )
    bad = df.filter(is_bad)
    if bad.height:
        log.warning(
            "%d fehlerhafte Rohzeile(n) aussortiert: %s", bad.height, bad["ticket"].to_list()
        )
    return df.filter(~is_bad), bad


# --------------------------------------------------------------------------- #
# Hauptfunktion
# --------------------------------------------------------------------------- #
def transform(raw: pl.DataFrame) -> SilverResult:
    """Wendet NULL-Handling, Validierung und Mapping auf das Zielmodell an."""
    df = normalize_nulls(raw)
    df, rejected = split_valid_rows(df)

    passthrough = [c for c in ("C4CExportID",) if c in df.columns]
    silver = df.select(
        *passthrough,
        # --- Kunde
        pl.col("stakeholder").alias("CustomerName"),
        pl.col("contact_name").alias("CustomerContactPerson"),
        pl.col("contact_email").str.to_lowercase().alias("CustomerContactPersonEmail"),
        # --- Anfrage
        pl.col("status").alias("RequestStatus"),
        pl.col("plant_location_address").alias("SubstationLocation"),
        pl.coalesce("connection_technology", "connection_technology_raw").alias(
            "GenerationTechnology"
        ),
        pl.col("connection_point").alias("Substation50Hertz"),
        parse_capacity_mw("installed_capacity").alias("maxP"),
        parse_switch_count("connection_solution").alias("SwitchCount"),
        pl.col("elo_link").alias("DocumentURL"),
        pl.col("ticket").alias("id_gronos_old"),
        pl.col("ticket_id").cast(pl.Int64, strict=False).alias("id_gronos_new"),
        pl.col("description").alias("RequestComment"),
    )

    has_customer = pl.any_horizontal(pl.col(CUSTOMER_COLUMNS).is_not_null())
    customers = silver.filter(has_customer).select(CUSTOMER_COLUMNS).unique(maintain_order=True)

    # Jede Anfrage behält die Kundenattribute als Join-Schlüssel für den Load.
    # Keine Deduplizierung: jede gültige Zeile geht nach Silver; ob sie neu ist,
    # entscheidet der Writer per Vergleich mit dem Bestand.
    requests = silver.select(passthrough + REQUEST_COLUMNS + CUSTOMER_COLUMNS)

    return SilverResult(customers=customers, requests=requests, rejected=rejected)
