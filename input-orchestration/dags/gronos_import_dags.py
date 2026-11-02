"""GRONOS-API → Bronze → Silver, als zwei DAGs.

    gronos_raw_to_bronze      (Schedule, Standard alle 30 min)
        raw_to_bronze  ──►  trigger_bronze_to_silver
                                   │ löst aus und wartet auf das Ende
                                   ▼
    gronos_bronze_to_silver   (kein eigener Schedule)
        bronze_to_silver

* raw_to_bronze: listet alle Anfragen (companyId-Präfixe), holt nur neue
  objectIds und solche mit neuerem updatedAt als in Bronze und hängt sie
  as is (JSON) mit Timestamp an GronosExports an.
* bronze_to_silver: verarbeitet alle GronosExports mit Timestamp nach dem
  letzten Lauf (MAX(BusinessTransactions.TimestampImportBronze)), wandelt
  sie um und hängt sie an GridConnectionRequests an.

Ein abgeschlossener RawToBronze-Lauf löst BronzeToSilver aus, auch wenn er
nichts Neues gefunden hat (dann verarbeitet BronzeToSilver nichts). Durch
wait_for_completion + max_active_runs=1 überschneiden sich die Läufe nicht;
writer.atomic_write sperrt die Datenbank zusätzlich für manuelle Läufe.
"""
from __future__ import annotations

import datetime

from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.sdk import DAG

from grid_con_ingestion import config
from grid_con_ingestion.operators.gronos_bronze_to_silver import GronosBronzeToSilverOperator
from grid_con_ingestion.operators.gronos_raw_to_bronze import GronosRawToBronzeOperator

RAW_TO_BRONZE_DAG_ID = "gronos_raw_to_bronze"
BRONZE_TO_SILVER_DAG_ID = "gronos_bronze_to_silver"
TAGS = ["grid-con", "input-orchestration", "gronos-api"]

with DAG(
    dag_id=RAW_TO_BRONZE_DAG_ID,
    schedule=config.GRONOS_RAW_TO_BRONZE_SCHEDULE,
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=TAGS,
):
    raw_to_bronze = GronosRawToBronzeOperator(
        task_id="raw_to_bronze",
        db_path=str(config.DB_PATH),
        prefixes=config.GRONOS_COMPANY_ID_PREFIXES,
        retries=1,
        retry_delay=datetime.timedelta(minutes=5),
    )

    trigger_bronze_to_silver = TriggerDagRunOperator(
        task_id="trigger_bronze_to_silver",
        trigger_dag_id=BRONZE_TO_SILVER_DAG_ID,
        wait_for_completion=True,
        poke_interval=30,
        allowed_states=["success"],
        failed_states=["failed"],
    )

    raw_to_bronze >> trigger_bronze_to_silver

with DAG(
    dag_id=BRONZE_TO_SILVER_DAG_ID,
    schedule=None,  # wird von gronos_raw_to_bronze ausgelöst
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=TAGS,
):
    GronosBronzeToSilverOperator(task_id="bronze_to_silver", db_path=str(config.DB_PATH))
