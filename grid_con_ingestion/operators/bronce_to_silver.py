"""Bronce-to-Silver: verarbeitet die neuen Zeilen der Bronce-Tabelle C4CExports.

Upsert gegen GridConnectionRequests: Zeilen ohne passenden Kunden in
GridConnectionCustomers und Zeilen mit identischen Werten zum neuesten
Eintrag des Tickets werden übersprungen. Alle anderen bekommen zuerst einen
Eintrag in BusinessTransactions und dann einen komplett neuen Eintrag in
GridConnectionRequests mit neuer UUID (writer.write_silver).
"""
from __future__ import annotations

from pathlib import Path

from airflow.models.baseoperator import BaseOperator

from grid_con_ingestion.operators.raw_to_bronce import XCOM_KEY_FILE_SHA
from grid_con_ingestion.writer import LoadStats, write_silver


def bronce_to_silver(db_path: str | Path, file_sha: str) -> LoadStats:
    """Airflow-unabhängiger Kern (auch für Tests und manuelle Läufe)."""
    return write_silver(db_path, file_sha)


class BronceToSilverOperator(BaseOperator):
    template_fields = ("db_path",)

    def __init__(self, *, bronce_task_id: str, db_path: str, **kwargs):
        super().__init__(**kwargs)
        self.bronce_task_id = bronce_task_id
        self.db_path = db_path

    def execute(self, context) -> dict:
        sha = context["ti"].xcom_pull(task_ids=self.bronce_task_id, key=XCOM_KEY_FILE_SHA)
        if not sha:
            raise RuntimeError(
                f"Kein FileSha in XCom von Task {self.bronce_task_id!r} – RawToBronce muss zuerst laufen"
            )

        stats = bronce_to_silver(self.db_path, sha)
        self.log.info("Silver geschrieben nach %s: %s", self.db_path, stats.as_dict())
        if stats.customers_missing:
            self.log.warning("%d Zeile(n) ohne passenden Kunden übersprungen", stats.customers_missing)
        return stats.as_dict()
