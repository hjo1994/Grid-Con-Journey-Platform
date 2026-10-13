"""Raw-to-Bronce: liest die vom Sensor gemeldete Lieferung as is mit Polars
und hängt sie mit Metadaten (FileSha, FileName, Timestamp) an die
Bronce-Tabelle C4CExports an (writer.py, atomarer Tausch).

Eine Lieferung mit bereits geladenem Inhalt (gleicher FileSha) wird nicht
erneut geschrieben. Quittiert wird erst nach erfolgreichem Schreiben –
schlägt der Import fehl, erkennt der Sensor die Lieferung im nächsten Lauf
erneut. Der FileSha geht per XCom an BronceToSilver.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from airflow.sdk import BaseOperator

from grid_con_ingestion.operators.source_sensor import XCOM_KEY_SOURCE_REF
from grid_con_ingestion.sources import build_source
from grid_con_ingestion.transforms.normalize import read_export
from grid_con_ingestion.writer import BronceStats, write_bronce

XCOM_KEY_FILE_SHA = "file_sha"


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def raw_to_bronce(raw_path: str | Path, db_path: str | Path) -> tuple[str, BronceStats]:
    """Airflow-unabhängiger Kern (auch für Tests und manuelle Läufe)."""
    raw_path = Path(raw_path)
    sha = file_sha256(raw_path)
    return sha, write_bronce(read_export(raw_path), raw_path.name, sha, db_path)


class RawToBronceOperator(BaseOperator):
    template_fields = ("db_path",)

    def __init__(
        self,
        *,
        source_type: str,
        source_kwargs: dict,
        sensor_task_id: str,
        db_path: str,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.source_type = source_type
        self.source_kwargs = source_kwargs
        self.sensor_task_id = sensor_task_id
        self.db_path = db_path

    def execute(self, context) -> dict:
        ref = context["ti"].xcom_pull(task_ids=self.sensor_task_id, key=XCOM_KEY_SOURCE_REF)
        if not ref:
            raise RuntimeError(
                f"Keine Quellreferenz in XCom von Task {self.sensor_task_id!r} – der Sensor muss zuerst laufen"
            )

        source = build_source(self.source_type, **self.source_kwargs)
        raw_path = source.fetch(ref)
        self.log.info("Lese %s", raw_path)

        sha, stats = raw_to_bronce(raw_path, self.db_path)
        if stats.already_loaded:
            self.log.info("Inhalt bereits in Bronce (FileSha %s) – nichts geschrieben", sha)
        else:
            self.log.info("%d Zeilen nach C4CExports geschrieben (FileSha %s)", stats.rows_inserted, sha)

        source.acknowledge(ref)
        context["ti"].xcom_push(key=XCOM_KEY_FILE_SHA, value=sha)
        return {"file_sha": sha, **stats.as_dict()}
