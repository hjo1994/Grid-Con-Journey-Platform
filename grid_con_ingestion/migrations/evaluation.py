"""Einmalig bzw. bei Änderungen: Bewertungs-Framework und Nutzer:innen anlegen.

Das Framework (EvaluationCriteria, EvaluationSubCriteria, EvaluationChecks)
kommt aus ``evaluation_framework.py``; im Cluster schreibt es der Seeding-DAG
``grid_con_seed_config``, dieses Skript ist die lokale Alternative. Nutzer:innen kommen aus einer CSV-Datei mit den Spalten
``email,name,role`` (Rollen siehe ``models.ROLES``) oder – nur für lokale
Demos – mit ``--demo`` aus drei Beispiel-Prüfer:innen (eine je Fachrolle).
Beides ist idempotent; bestehende Nutzer:innen werden über die E-Mail
gefunden und behalten ihre ID.

    python -m grid_con_ingestion.migrations.evaluation <grid_con.db> [--users users.csv] [--demo]
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from grid_con_ingestion.evaluation_framework import sync_framework
from grid_con_ingestion.writer import upsert_users, write_transaction

DEMO_USERS = [
    {"email": "netzplanung@example.invalid", "name": "J. Hoffmann", "role": "netzplanung"},
    {"email": "flaechen-recht@example.invalid", "name": "A. Becker", "role": "flaechen_recht"},
    {"email": "finanzen@example.invalid", "name": "M. Krüger", "role": "finanzen"},
    {"email": "lesend@example.invalid", "name": "L. Weber", "role": "viewer"},
]


def setup_evaluation(db_path: str | Path, users: list[dict] | None = None) -> dict:
    with write_transaction(db_path) as conn:
        result = sync_framework(conn)
        if users:
            result.update(upsert_users(conn, users))
    return result


def read_users(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [{k.strip().lower(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--users", type=Path, help="CSV mit email,name,role")
    parser.add_argument("--demo", action="store_true", help="Beispiel-Prüfer:innen anlegen (nur lokal)")
    args = parser.parse_args()
    users = (read_users(args.users) if args.users else []) + (DEMO_USERS if args.demo else [])
    print(setup_evaluation(args.db, users))


if __name__ == "__main__":
    main()
