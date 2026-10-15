"""Sensor: wartet auf eine neue Lieferung der konfigurierten Quelle.

Heute eine Datei im Quellordner (FileSource: neueste passende Datei, die sich
seit dem letzten erfolgreichen Import geändert hat und fertig geschrieben
ist), später eine API (ApiSource) – umschaltbar über GRID_CON_SOURCE_TYPE,
ohne den DAG anzufassen.
"""
from __future__ import annotations

from airflow.sensors.base import BaseSensorOperator

from grid_con_ingestion.sources import build_source

XCOM_KEY_SOURCE_REF = "source_ref"


class SourceSensor(BaseSensorOperator):
    """Pusht die Referenz der gefundenen Lieferung nach XCom (Key ``source_ref``)."""

    template_fields = ("source_kwargs",)

    def __init__(self, *, source_type: str, source_kwargs: dict, **kwargs):
        super().__init__(**kwargs)
        self.source_type = source_type
        self.source_kwargs = source_kwargs

    def poke(self, context) -> bool:
        ref = build_source(self.source_type, **self.source_kwargs).poll()
        if ref is None:
            self.log.info("Keine neue Lieferung (%s, %s)", self.source_type, self.source_kwargs)
            return False
        context["ti"].xcom_push(key=XCOM_KEY_SOURCE_REF, value=ref)
        self.log.info("Neue Lieferung erkannt: %s", ref)
        return True
