"""Installiert fehlende Python-Pakete zur Laufzeit nach /tmp/airflow_packages.

Das Airflow-Image der Plattform bringt polars, fastexcel und pyarrow nicht
mit; ein eigenes Image ist nicht vorgesehen. Beim Parsen des DAGs wird
geprüft, ob die Pakete importierbar sind. Fehlende werden im Hintergrund per
pip installiert (Lock-Datei verhindert parallele Installationen); bis dahin
schlagen Tasks fehl und laufen beim nächsten Retry/Lauf durch.
"""
import os
import site
import subprocess
import sys

TMP_PACKAGES_DIR = "/tmp/airflow_packages"

# (Import-Name, pip-Name)
REQUIRED_PACKAGES = [
    ("polars", "polars"),
    ("fastexcel", "fastexcel"),
    ("pyarrow", "pyarrow"),
]


def ensure_dependencies() -> None:
    os.makedirs(TMP_PACKAGES_DIR, exist_ok=True)
    if TMP_PACKAGES_DIR not in sys.path:
        site.addsitedir(TMP_PACKAGES_DIR)

    missing = []
    for import_name, pip_name in REQUIRED_PACKAGES:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)
    if not missing:
        return

    lock_file = os.path.join(TMP_PACKAGES_DIR, "pip.lock")
    if os.path.exists(lock_file):
        print(f"Auto-Installer: Installation läuft bereits. Fehlende Pakete: {', '.join(missing)}")
        return

    print(f"Auto-Installer: Fehlende Pakete erkannt: {', '.join(missing)}. Starte Hintergrund-Installation...")
    try:
        with open(lock_file, "w") as f:
            f.write("running")
        env = os.environ.copy()
        env["PIP_USER"] = "false"
        # Lock-Datei erst nach Ende von pip entfernen, damit kein zweiter Lauf startet.
        cmd = (
            f"{sys.executable} -m pip install --target={TMP_PACKAGES_DIR} --no-cache-dir "
            + " ".join(missing)
            + f"; rm -f {lock_file}"
        )
        subprocess.Popen(cmd, shell=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Auto-Installer: Installation gestartet für: {', '.join(missing)}")
    except Exception as e:  # noqa: BLE001 – DAG-Parsing darf hier nicht abbrechen
        print(f"Auto-Installer Fehler beim Starten von pip: {e}")
        if os.path.exists(lock_file):
            os.remove(lock_file)


ensure_dependencies()
