"""Input Orchestration DAG: wartet auf eine neue C4C/GRONOS-Lieferung,
legt sie as is in Bronce (C4CExports) ab und lädt daraus die
Netzanschlussanfragen nach Silver – beides in der zentralen SQLite-Datenbank
(data/db).

    wait_for_source  ──►  raw_to_bronce  ──►  bronce_to_silver

Single writer: max_active_runs=1, atomarer Datei-Tausch im Writer.
"""
from __future__ import annotations

import datetime
import os
import site
import sys

# Das Repo liegt als Ganzes im DAG-Ordner: Projektwurzel (grid_con_ingestion)
# importierbar machen und fehlende Pakete nachinstallieren, bevor die
# Operatoren polars importieren (siehe dependency_loader.py).
_DAG_DIR = os.path.dirname(os.path.abspath(__file__))
site.addsitedir(_DAG_DIR)

import dependency_loader  # noqa: E402,F401

from airflow import DAG  # noqa: E402

from grid_con_ingestion import config  # noqa: E402
from grid_con_ingestion.operators.bronce_to_silver import BronceToSilverOperator  # noqa: E402
from grid_con_ingestion.operators.raw_to_bronce import RawToBronceOperator  # noqa: E402
from grid_con_ingestion.operators.source_sensor import SourceSensor  # noqa: E402

SENSOR_TASK_ID = "wait_for_source"
BRONCE_TASK_ID = "raw_to_bronce"

with DAG(
    dag_id="grid_connection_requests_import",
    schedule="@hourly",
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,  # single writer – nie zwei Importläufe parallel
    tags=["grid-con", "input-orchestration"],
) as dag:
    source_kwargs = config.source_kwargs()

    wait_for_source = SourceSensor(
        task_id=SENSOR_TASK_ID,
        source_type=config.SOURCE_TYPE,
        source_kwargs=source_kwargs,
        poke_interval=60,
        timeout=60 * 60 * 6,
        mode="reschedule",  # gibt den Worker-Slot zwischen den Pokes frei
    )

    raw_to_bronce = RawToBronceOperator(
        task_id=BRONCE_TASK_ID,
        source_type=config.SOURCE_TYPE,
        source_kwargs=source_kwargs,
        sensor_task_id=SENSOR_TASK_ID,
        db_path=str(config.DB_PATH),
    )

    bronce_to_silver = BronceToSilverOperator(
        task_id="bronce_to_silver",
        bronce_task_id=BRONCE_TASK_ID,
        db_path=str(config.DB_PATH),
    )

    wait_for_source >> raw_to_bronce >> bronce_to_silver
