import os
import sys
import subprocess
import site


def ensure_dependencies():
    tmp_packages_dir = "/tmp/airflow_packages"

    if not os.path.exists(tmp_packages_dir):
        os.makedirs(tmp_packages_dir, exist_ok=True)

    if tmp_packages_dir not in sys.path:
        site.addsitedir(tmp_packages_dir)

    required_packages = [
        ("polars", "polars"),
        ("fastexcel", "fastexcel"),
        ("pyarrow", "pyarrow")
    ]

    missing = []

    for import_name, pip_name in required_packages:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return

    lock_file = os.path.join(tmp_packages_dir, "pip.lock")

    if os.path.exists(lock_file):
        print(
            f"Auto-Installer: Installation läuft bereits im Hintergrund. "
            f"Fehlende Pakete: {', '.join(missing)}"
        )
        return

    print(
        f"Auto-Installer: Fehlende Pakete erkannt: {', '.join(missing)}. "
        "Starte Hintergrund-Installation..."
    )

    try:
        with open(lock_file, "w") as f:
            f.write("running")

        clean_env = os.environ.copy()
        clean_env["PIP_USER"] = "false"

        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target=" + tmp_packages_dir,
                "--no-cache-dir",
                *missing,
            ],
            env=clean_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        print(
            f"Auto-Installer: Installation gestartet für: "
            f"{', '.join(missing)}"
        )

    except Exception as e:
        print(f"Auto-Installer Fehler beim Starten von PIP: {e}")

        if os.path.exists(lock_file):
            os.remove(lock_file)


ensure_dependencies()