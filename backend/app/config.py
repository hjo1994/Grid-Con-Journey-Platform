"""Environment-based configuration and the request status catalogue."""
from __future__ import annotations

import os
from pathlib import Path

API_VERSION = "1.0.0"


def get_db_path() -> Path:
    # Mount point of the shared (interim) SQLite file – an infra decision,
    # hence overridable. Same variable name as in Input Orchestration.
    return Path(os.environ.get("GRID_CON_DB_PATH", "/data/db/grid_con.db"))


# BronzeToGold is triggered after every saved evaluation (best effort; without
# AIRFLOW_API_URL only its schedule applies). Airflow 2.10 (platform): REST API
# v1, Bearer token or basic auth. Airflow 3 (local): v2 with /auth/token.
AIRFLOW_GOLD_DAG_ID = os.environ.get("GRID_CON_GOLD_DAG_ID", "grid_con_bronze_to_gold")


def airflow_settings() -> dict:
    return {
        "url": os.environ.get("AIRFLOW_API_URL", "").rstrip("/"),
        "api_version": os.environ.get("AIRFLOW_API_VERSION", "v1").strip().lower(),
        "token": os.environ.get("AIRFLOW_API_TOKEN", ""),
        "username": os.environ.get("AIRFLOW_API_USERNAME", ""),
        "password": os.environ.get("AIRFLOW_API_PASSWORD", ""),
    }


# Process order and phases of RequestStatus. Not stored in the database, so it
# lives here. PENDING: business confirmation of the order (taken from the
# approved monitoring mockup). Statuses outside the process ("Offen",
# "Eingestellt") come last with phase None.
PROCESS_PHASES: list[tuple[str, list[str]]] = [
    ("Eingang", [
        "Standortanfrage eingegangen",
        "Standortcheck durchgeführt",
        "Netzanschlussantrag eingegangen",
    ]),
    ("Prüfung", [
        "Netztechnische Prüfung positiv (intern)",
        "Netztechnische Prüfung positiv (extern)",
    ]),
    ("Reservierung & Umsetzung", [
        "Reservierungsangebot angenommen",
        "AEV-Kick Off erfolgt",
        "Meilenstein 4 erreicht",
    ]),
]
OUTSIDE_PROCESS: list[str] = ["Offen", "Eingestellt"]


def status_catalogue() -> list[dict]:
    """Configured statuses in display order: name, order (1-based), phase, in_process."""
    entries = [
        {"name": name, "phase": phase, "in_process": True}
        for phase, names in PROCESS_PHASES
        for name in names
    ]
    entries += [{"name": name, "phase": None, "in_process": False} for name in OUTSIDE_PROCESS]
    return [{**entry, "order": i} for i, entry in enumerate(entries, start=1)]
