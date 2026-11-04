"""BronzeToSilver (GRONOS-API): GronosExports → BusinessTransactions,
GridConnectionCustomers, GridConnectionRequests (writer.write_gronos_silver).

Ausgelöst durch das Asset-Event von RawToBronze. Welche Bronze-Zeilen neu
sind, ergibt sich aus dem höchsten InputBronzeTimestamp der bisherigen
BusinessTransactions; ein zweiter Lauf ohne neue Bronze-Zeilen ändert nichts.
"""
from __future__ import annotations

from pathlib import Path

from airflow.sdk import BaseOperator

from grid_con_ingestion.writer import GronosSilverStats, write_gronos_silver


def gronos_bronze_to_silver(db_path: str | Path) -> GronosSilverStats:
    return write_gronos_silver(db_path)


class GronosBronzeToSilverOperator(BaseOperator):
    template_fields = ("db_path",)

    def __init__(self, *, db_path: str, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path

    def execute(self, context) -> dict:
        stats = gronos_bronze_to_silver(self.db_path)
        self.log.info("Silver geschrieben nach %s: %s", self.db_path, stats.as_dict())
        if stats.rows_rejected:
            self.log.warning("%d Bronze-Zeile(n) nicht verarbeitbar", stats.rows_rejected)
        return stats.as_dict()
