"""GRONOS-API -> Bronze -> Silver, als zwei DAGs.

    gronos_raw_to_bronze      (Schedule, Standard alle 30 min)
        raw_to_bronze  -->  trigger_bronze_to_silver
                                   | loest aus und wartet auf das Ende
                                   v
    gronos_bronze_to_silver   (kein eigener Schedule)
        bronze_to_silver

* raw_to_bronze: listet alle Anfragen (companyId-Praefixe), holt nur neue
  objectIds und solche mit neuerem updatedAt als in Bronze und haengt sie
  as is (JSON) mit Timestamp an GronosExports an.
* bronze_to_silver: verarbeitet alle GronosExports mit Timestamp nach dem
  letzten Lauf (MAX(BusinessTransactions.InputBronzeTimestamp)), wandelt
  sie um und haengt sie an GridConnectionRequests an.

Ein abgeschlossener RawToBronze-Lauf loest BronzeToSilver aus, auch wenn er
nichts Neues gefunden hat (dann verarbeitet BronzeToSilver nichts). Durch
wait_for_completion + max_active_runs=1 ueberschneiden sich die Laeufe nicht;
writer.write_transaction (BEGIN IMMEDIATE) serialisiert zusaetzlich manuelle Laeufe.
"""
from __future__ import annotations

import datetime
import os
import site
import sys

# Wie im Excel-DAG: Projektwurzel importierbar machen und fehlende Pakete
# (polars, fastexcel) nachinstallieren, bevor die Operatoren sie importieren.
_DAG_DIR = os.path.dirname(os.path.abspath(__file__))
site.addsitedir(_DAG_DIR)
sys.path.insert(0, '/data/dags/grid_con_ingestion/operators')
sys.path.insert(0, '/data/dags/grid_con_ingestion/transforms')

import dependency_loader  # noqa: E402,F401

from airflow import DAG  # noqa: E402
from airflow.operators.trigger_dagrun import TriggerDagRunOperator  # noqa: E402

from grid_con_ingestion import config  # noqa: E402
from grid_con_ingestion.operators.gronos_bronze_to_silver import GronosBronzeToSilverOperator  # noqa: E402
from grid_con_ingestion.operators.gronos_raw_to_bronze import GronosRawToBronzeOperator  # noqa: E402

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
        detail_mode=config.GRONOS_DETAIL_MODE,
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
    schedule=None,  # wird von gronos_raw_to_bronze ausgeloest
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=TAGS,
):
    GronosBronzeToSilverOperator(task_id="bronze_to_silver", db_path=str(config.DB_PATH))
