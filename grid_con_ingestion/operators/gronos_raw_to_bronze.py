"""RawToBronze (GRONOS-API): holt neue und geänderte Anfragen nach GronosExports.

Logik in grid_con_ingestion/gronos/store.py (raw_to_bronze).
"""
from __future__ import annotations

from airflow.models.baseoperator import BaseOperator

from grid_con_ingestion import config
from grid_con_ingestion.gronos.client import parse_prefixes
from grid_con_ingestion.gronos.store import raw_to_bronze


class GronosRawToBronzeOperator(BaseOperator):
    template_fields = ("db_path", "prefixes")

    def __init__(self, *, db_path: str, prefixes: str, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path
        self.prefixes = prefixes

    def execute(self, context) -> dict:
        stats = raw_to_bronze(config.gronos_client(), self.db_path, parse_prefixes(self.prefixes))
        self.log.info(
            "%d requests listed (%d calls, %d duplicates): %d new, %d updated, %d unchanged",
            stats.listed, stats.list_calls, stats.duplicates, stats.new, stats.updated, stats.unchanged,
        )
        self.log.info("%d rows written to GronosExports (Timestamp %s)", stats.rows_inserted, stats.timestamp)
        return stats.as_dict()
