"""Datenqualitaetspruefung als Qualitaetstor.

Fuehrt alle Regeln aus und beendet sich mit einem Fehlercode, wenn der
Qualitaetsindex einen Mindestwert unterschreitet. Damit laesst sich verhindern,
dass ein Data Warehouse in unzureichender Qualitaet weiterverwendet oder
veroeffentlicht wird.

Aufruf:
    python -m scripts.qualitaet_pruefen --mindestindex 90
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bi import quality, warehouse  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueft die Qualitaet des Data Warehouse.")
    parser.add_argument("--mindestindex", type=float, default=90.0,
                        help="Erforderlicher Qualitaetsindex in Prozent (Standard: 90)")
    parser.add_argument("--db", help="Abweichender Pfad zur Datenbankdatei")
    argumente = parser.parse_args(argv)

    conn = warehouse.verbindung(argumente.db)
    ergebnisse = quality.pruefe_alles(conn)
    index = quality.qualitaetsindex(ergebnisse)

    breite = max(len(e.regel) for e in ergebnisse) + 2
    print("Datenqualitaetsbericht")
    print("=" * (breite + 60))
    for e in ergebnisse:
        marke = "OK  " if e.bestanden else "FEHL"
        print(f"{marke}  {e.regel:<{breite}} {e.befund}")
    print("=" * (breite + 60))

    bestanden = sum(1 for e in ergebnisse if e.bestanden)
    print(f"Qualitaetsindex: {index} % ({bestanden} von {len(ergebnisse)} Regeln bestanden)")

    if index < argumente.mindestindex:
        print(f"\nFEHLER: Der Qualitaetsindex liegt unter dem geforderten Mindestwert von "
              f"{argumente.mindestindex} %.", file=sys.stderr)
        return 1

    print("Die Qualitaetsanforderungen sind erfuellt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
