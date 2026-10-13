"""Austauschbare Datenquellen für den Sensor.

Sensor und Raw-to-Bronce-Operator sprechen nur gegen das Interface
:class:`DataSource`. Für den Umstieg von Datei auf API wird lediglich
:class:`ApiSource` implementiert und ``GRID_CON_SOURCE_TYPE=api`` gesetzt –
DAG, Operatoren und Transformation bleiben unverändert.

Lebenszyklus einer Lieferung:
    poll()        → Referenz (str) auf eine neue Lieferung oder None
    fetch(ref)    → lokaler Pfad der Rohdatei (bei API: Download nach staging)
    acknowledge() → Lieferung als verarbeitet markieren
"""
from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from pathlib import Path

MARKER_NAME = ".grid_con_import.last_processed"


class DataSource(ABC):
    @abstractmethod
    def poll(self) -> str | None: ...

    @abstractmethod
    def fetch(self, ref: str) -> Path: ...

    @abstractmethod
    def acknowledge(self, ref: str) -> None: ...


class FileSource(DataSource):
    """Neueste Datei im Quellordner, die sich seit dem letzten Import geändert hat.

    Wie im AI-Cockpit-Referenzprojekt bleibt die Quelldatei liegen; der
    zuletzt verarbeitete Stand wird über die mtime einer Marker-Datei im
    Quellordner erkannt. Zusätzlich muss die Dateigröße über ein kurzes
    Intervall stabil sein (Schutz vor halb kopierten Dateien).
    """

    def __init__(self, source_dir: str, filename_glob: str = "*.xlsx", settle_seconds: float = 2.0):
        self.source_dir = Path(source_dir)
        self.filename_glob = filename_glob
        self.settle_seconds = settle_seconds

    @property
    def marker(self) -> Path:
        return self.source_dir / MARKER_NAME

    def poll(self) -> str | None:
        if not self.source_dir.is_dir():
            return None
        candidates = [
            p
            for p in self.source_dir.glob(self.filename_glob)
            if p.is_file() and not p.name.startswith((".", "~$"))
        ]
        if not candidates:
            return None

        source_file = max(candidates, key=lambda p: p.stat().st_mtime)
        last_processed = self.marker.stat().st_mtime if self.marker.exists() else 0.0
        if source_file.stat().st_mtime <= last_processed:
            return None

        size_before = source_file.stat().st_size
        time.sleep(self.settle_seconds)
        if not source_file.exists() or source_file.stat().st_size != size_before:
            return None
        return str(source_file)

    def fetch(self, ref: str) -> Path:
        path = Path(ref)
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    def acknowledge(self, ref: str) -> None:
        mtime = Path(ref).stat().st_mtime
        self.marker.touch()
        os.utime(self.marker, (mtime, mtime))


class ApiSource(DataSource):
    """Platzhalter für die spätere API-Anbindung (z. B. C4C OData).

    Erwartetes Verhalten:
      * poll(): prüft per API, ob seit dem letzten Abruf neue/geänderte
        Tickets vorliegen, und gibt z. B. einen Delta-Token als Referenz zurück.
      * fetch(): lädt die Daten und schreibt sie im Format des Dateiexports
        nach ``staging_dir`` – so bleibt die Transformation unverändert.
      * acknowledge(): speichert den Delta-Token (z. B. Airflow Variable).
    """

    def __init__(self, base_url: str, conn_id: str, staging_dir: str):
        self.base_url = base_url
        self.conn_id = conn_id
        self.staging_dir = Path(staging_dir)

    def poll(self) -> str | None:
        raise NotImplementedError("ApiSource ist noch nicht implementiert.")

    def fetch(self, ref: str) -> Path:
        raise NotImplementedError("ApiSource ist noch nicht implementiert.")

    def acknowledge(self, ref: str) -> None:
        raise NotImplementedError("ApiSource ist noch nicht implementiert.")


SOURCES: dict[str, type[DataSource]] = {"file": FileSource, "api": ApiSource}


def build_source(source_type: str, **kwargs) -> DataSource:
    try:
        return SOURCES[source_type](**kwargs)
    except KeyError as exc:
        raise ValueError(f"Unbekannter Quelltyp '{source_type}'. Erlaubt: {list(SOURCES)}") from exc
