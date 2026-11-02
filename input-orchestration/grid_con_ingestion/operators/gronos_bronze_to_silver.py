"""BronzeToSilver (GRONOS-API): verarbeitet alle GronosExports-Zeilen seit dem
letzten Lauf (Timestamp > MAX(BusinessTransactions.TimestampImportBronze)).

Logik in grid_con_ingestion/gronos/store.py (bronze_to_silver).
"""
from __future__ import annotations

from airflow.sdk import BaseOperator

from grid_con_ingestion.gronos.store import bronze_to_silver


class GronosBronzeToSilverOperator(BaseOperator):
    template_fields = ("db_path",)

    def __init__(self, *, db_path: str, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path

    def execute(self, context) -> dict:
        stats = bronze_to_silver(self.db_path)
        self.log.info("Silver geschrieben nach %s: %s", self.db_path, stats.as_dict())
        if stats.rows_rejected:
            self.log.warning("%d Bronze-Zeile(n) nicht verarbeitbar, siehe Warnungen", stats.rows_rejected)
        return stats.as_dict()
