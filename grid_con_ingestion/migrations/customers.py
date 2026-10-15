"""Prototypische Migration: Kunden aus einem C4C-Export nach GridConnectionCustomers.

Kunden sind Stammdaten: BronceToSilver legt keine Kunden an, sondern prüft
nur, ob der referenzierte Kunde existiert. Diese Migration befüllt die
Tabelle aus einem Export (gleiche Normalisierung wie in Silver, Schlüssel
Name + Kontakt + E-Mail). Bereits vorhandene Kunden behalten ihre ID, ein
zweiter Lauf ändert nichts.

    python -m grid_con_ingestion.migrations.customers <export.xlsx> <grid_con.db>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from grid_con_ingestion.transforms.normalize import read_raw, transform
from grid_con_ingestion.writer import CustomerStats, atomic_write, load_customers


def migrate_customers(raw_path: str | Path, db_path: str | Path) -> CustomerStats:
    customers = transform(read_raw(Path(raw_path))).customers
    with atomic_write(db_path) as conn:
        return load_customers(conn, customers)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("db", type=Path)
    args = parser.parse_args()
    print(migrate_customers(args.export, args.db).as_dict())


if __name__ == "__main__":
    main()
