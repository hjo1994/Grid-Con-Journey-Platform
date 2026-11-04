"""RawToBronze (GRONOS-API): Liste → Delta gegen Bronze → Details → GronosExports.

Ersetzt für die API den Datei-Pfad aus SourceSensor + RawToBronceOperator.
Schreibt nur, wenn alle Detail-Abrufe gelungen sind (eine Transaktion, ein
Timestamp je Lauf). Ohne neue oder geänderte Anträge wird der Task
übersprungen, dann entsteht auch kein Asset-Event und BronzeToSilver läuft
nicht an.
"""
from __future__ import annotations

from pathlib import Path

from airflow.exceptions import AirflowSkipException
from airflow.sdk import BaseOperator

from grid_con_ingestion import config
from grid_con_ingestion.gronos import GronosClient, fetch_delta
from grid_con_ingestion.writer import known_gronos_states, write_gronos_bronze


def gronos_raw_to_bronze(client: GronosClient, prefixes: list[str], db_path: str | Path) -> dict:
    """Airflow-unabhängiger Kern (auch für Tests und manuelle Läufe)."""
    details, fetch_stats = fetch_delta(client, prefixes, known_gronos_states(db_path))
    return {**fetch_stats, **write_gronos_bronze(details, db_path).as_dict()}


def _credentials(conn_id: str) -> tuple[str, str, str]:
    try:
        from airflow.sdk.bases.hook import BaseHook

        conn = BaseHook.get_connection(conn_id)
        base_url = conn.host if (conn.host or "").startswith("http") else f"https://{conn.host}"
        return base_url, conn.login, conn.password
    except Exception:  # Connection nicht angelegt → Env-Variablen
        if not (config.GRONOS_BASE_URL and config.GRONOS_CLIENT_ID and config.GRONOS_CLIENT_SECRET):
            raise RuntimeError(
                f"Weder Airflow Connection {conn_id!r} noch GRONOS_BASE_URL/GRONOS_CLIENT_ID/"
                "GRONOS_CLIENT_SECRET gesetzt"
            )
        return config.GRONOS_BASE_URL, config.GRONOS_CLIENT_ID, config.GRONOS_CLIENT_SECRET


class GronosRawToBronzeOperator(BaseOperator):
    template_fields = ("db_path",)

    def __init__(self, *, db_path: str, conn_id: str, prefixes: list[str], **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path
        self.conn_id = conn_id
        self.prefixes = prefixes

    def execute(self, context) -> dict:
        base_url, client_id, secret = _credentials(self.conn_id)
        stats = gronos_raw_to_bronze(GronosClient(base_url, client_id, secret), self.prefixes, self.db_path)
        self.log.info("GRONOS-Abruf: %s", stats)
        if not stats["rows_inserted"]:
            raise AirflowSkipException("Keine neuen oder geänderten Anträge")
        return stats
