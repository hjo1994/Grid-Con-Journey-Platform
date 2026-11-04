"""BronzeToGold: UserEvaluationInputs → BusinessTransactions, RequestEvaluationChecks
(writer.write_gold).

Ausgelöst vom Backend, sobald eine Prüfer:in eine Bewertung speichert
(Airflow REST API), optional zusätzlich per Zeitplan. Neue Eingaben sind alle
mit ``Timestamp`` nach dem höchsten InputBronzeTimestamp der bisherigen
Gold-BusinessTransactions. Jede Eingabe bekommt eine BusinessTransaction,
einen RequestEvaluationChecks-Eintrag nur, wenn sie sich vom letzten Gold-Stand
unterscheidet (Delta, ``writer.input_unchanged``); mehrere Auslösungen kurz hintereinander
verarbeiten jede Eingabe genau einmal.
"""
from __future__ import annotations

from pathlib import Path

from airflow.sdk import BaseOperator

from grid_con_ingestion.writer import GoldStats, write_gold


def bronze_to_gold(db_path: str | Path) -> GoldStats:
    return write_gold(db_path)


class BronzeToGoldOperator(BaseOperator):
    template_fields = ("db_path",)

    def __init__(self, *, db_path: str, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path

    def execute(self, context) -> dict:
        stats = bronze_to_gold(self.db_path)
        self.log.info("Gold geschrieben nach %s: %s", self.db_path, stats.as_dict())
        if stats.rows_unchanged:
            self.log.info("%d Eingabe(n) unverändert gegenüber Gold, kein neuer Eintrag", stats.rows_unchanged)
        if stats.rows_rejected:
            self.log.warning("%d Eingabe(n) passen nicht zum Framework und wurden übersprungen", stats.rows_rejected)
        return stats.as_dict()
