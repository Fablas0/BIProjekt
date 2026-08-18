"""Exportiert das Rohdatenarchiv in versionierbare Dateien.

Die Quelle haelt nur rund zwei Wochen vor. Damit die Zeitreihe darueber
hinauswaechst, muessen die Rohdaten an einem Ort liegen, der Laeufe ueberdauert.
Im Betrieb ist das das Repository selbst: der taegliche Workflow ruft dieses
Skript auf und schreibt das Ergebnis zurueck.

Gesichert werden ausschliesslich die **Rohdaten**, nicht die Datenbank. Das Data
Warehouse ist daraus jederzeit neu ableitbar, die Rohnutzlast dagegen nicht
wiederbeschaffbar.

Aufruf::

    python -m scripts.archiv_export
    python -m scripts.archiv_export --ziel archiv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bi import warehouse  # noqa: E402
from bi.config import ARCHIV_VERZEICHNIS  # noqa: E402
from bi.etl import champions, spielformarchiv, stammarchiv  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Schreibt das Rohdatenarchiv als gzip-NDJSON auf die Platte.")
    parser.add_argument("--ziel", type=Path, default=ARCHIV_VERZEICHNIS,
                        help=f"Zielverzeichnis (Standard: {ARCHIV_VERZEICHNIS})")
    parser.add_argument("--db", help="Abweichender Pfad zur Datenbankdatei")
    argumente = parser.parse_args(argv)

    conn = warehouse.verbindung(argumente.db)
    umfang = warehouse.archiv_umfang(conn)

    if not umfang.get("saetze"):
        print("Das Archiv in der Datenbank ist leer -- nichts zu exportieren.")
        return 0

    zaehler = champions.exportiere_archiv(conn, argumente.ziel)
    print(f"{zaehler['saetze']} Rohdatensaetze in {zaehler['dateien']} Dateien "
          f"unter {argumente.ziel}.")
    print(f"Davon neu geschrieben: {zaehler['geschrieben']} "
          f"({zaehler['dateien'] - zaehler['geschrieben']} unveraendert).")

    # Ohne die Stammdaten laesst sich aus den Rohdaten kein Warehouse aufbauen:
    # Champions liefert nur Namen und Raenge, alles Weitere stammt aus der
    # PokeAPI. Gzip-komprimiert sind es 0,12 MB.
    stamm = stammarchiv.exportiere_stammdaten(conn, argumente.ziel)
    print(f"Stammdaten: {stamm['saetze']} Saetze in {stamm['tabellen']} Tabellen, "
          f"{stamm['geschrieben']} neu geschrieben.")

    spielformen = spielformarchiv.exportiere(conn, argumente.ziel)
    if spielformen["dateien"]:
        print(f"Spielformen (TCG/GO): {spielformen['dateien']} Dateien, "
              f"{spielformen['geschrieben']} neu geschrieben.")
    print(f"Abgedeckter Zeitraum: {umfang['erster_tag']} bis {umfang['letzter_tag']} "
          f"({umfang['tage']} Tage).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
