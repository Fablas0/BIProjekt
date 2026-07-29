"""Kopfloser ETL-Lauf.

Baut das Data Warehouse ohne Benutzeroberflaeche auf und ist damit die Grundlage
der Operationalisierung: derselbe Aufruf laeuft in der Continuous Integration,
als zeitgesteuerter Auftrag und lokal.

Aufruf::

    python -m scripts.etl_lauf                  # Stammdaten und Bewegungsdaten
    python -m scripts.etl_lauf --nur-champions  # nur die taegliche Strecke
    python -m scripts.etl_lauf --aus-archiv     # ohne Quellzugriff neu verarbeiten

Der taegliche Lauf ist wichtig: die Quelle haelt nur rund zwei Wochen vor, danach
sind Tage endgueltig verloren. Der Rueckgabewert ist 0 bei Erfolg und 1 bei einem
Fehler, sodass ein uebergeordneter Auftragsplaner den Ausgang auswerten kann.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bi import warehouse  # noqa: E402
from bi.config import ARCHIV_VERZEICHNIS  # noqa: E402
from bi.etl import champions, pipeline, stammarchiv  # noqa: E402

# Ein Ausfall des Quellsystems ist kein Codefehler. Der eigene Exit-Code
# erlaubt es dem aufrufenden Workflow, beides zu unterscheiden: 1 bedeutet
# "etwas stimmt am Programm nicht", 75 bedeutet "die Quelle war nicht erreichbar"
# (in Anlehnung an EX_TEMPFAIL aus sysexits.h).
EXIT_QUELLE = 75


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Baut das VGC Data Warehouse aus Pokemon Champions auf.")
    parser.add_argument("--nur-champions", action="store_true",
                        help="Stammdaten ueberspringen (setzt eine befuellte Dimension voraus)")
    parser.add_argument("--nur-stammdaten", action="store_true",
                        help="Nur die PokeAPI-Stammdaten laden")
    parser.add_argument("--aus-archiv", action="store_true",
                        help="Champions-Daten allein aus dem Archiv neu verarbeiten")
    parser.add_argument("--max-tage", type=int,
                        help="Nur die juengsten N Tage der Quelle abrufen")
    parser.add_argument("--archiv", type=Path, default=ARCHIV_VERZEICHNIS,
                        help=f"Verzeichnis des Rohdatenarchivs (Standard: {ARCHIV_VERZEICHNIS})")
    parser.add_argument("--ohne-archiv", action="store_true",
                        help="Das Archiv auf der Platte nicht einlesen")
    parser.add_argument("--db", help="Abweichender Pfad zur Datenbankdatei")
    argumente = parser.parse_args(argv)

    def melde(anteil: float, text: str) -> None:
        print(f"[{anteil * 100:5.1f}%] {text}", flush=True)

    conn = warehouse.verbindung(argumente.db)

    # Zuerst das auf der Platte gesicherte Archiv einlesen. Auf einem frischen
    # Runner ist die Datenbank leer; ohne diesen Schritt begaenne jeder Lauf bei
    # null und die Zeitreihe koennte die Vorhaltezeit der Quelle nie ueberschreiten.
    if not argumente.ohne_archiv:
        # Stammdaten zuerst: ohne sie laesst sich kein Champions-Name aufloesen.
        stammarchiv.importiere_stammdaten(conn, argumente.archiv)
        eingelesen = champions.importiere_archiv(conn, argumente.archiv)
        if eingelesen["saetze"]:
            print(f"== Archiv eingelesen: {eingelesen['saetze']} Rohdatensaetze aus "
                  f"{eingelesen['dateien']} Dateien ==", flush=True)

    if not argumente.nur_champions:
        print("== Schritt 1: Stammdaten (PokeAPI) ==", flush=True)
        ergebnis = pipeline.stammdaten_laden(conn, melde)
        if not ergebnis.erfolgreich:
            print(f"FEHLER: {ergebnis.meldung}", file=sys.stderr)
            return EXIT_QUELLE
        h = ergebnis.historisierung
        print(f"   {ergebnis.geladen} Pokemon verarbeitet "
              f"(neu {h.get('neu', 0)}, geaendert {h.get('geaendert', 0)}, "
              f"unveraendert {h.get('unveraendert', 0)}).")

    if argumente.nur_stammdaten:
        print(f"\nDatenbank: {argumente.db or warehouse.DWH_PFAD}")
        return 0

    print("\n== Schritt 2: Bewegungsdaten (Pokemon Champions) ==", flush=True)
    champ = champions.laden(conn, max_tage=argumente.max_tage,
                            aus_archiv=argumente.aus_archiv, fortschritt=melde)
    if not champ.get("erfolgreich"):
        print(f"FEHLER: {champ.get('meldung')}", file=sys.stderr)
        return EXIT_QUELLE

    print(f"   {champ['meldung']}")
    print(f"   {champ.get('neu_archiviert', 0)} Rohdatensaetze neu archiviert.")

    umfang = warehouse.archiv_umfang(conn)
    if umfang.get("tage"):
        print(f"   Archiv: {umfang['tage']} Tage "
              f"({umfang['erster_tag']} bis {umfang['letzter_tag']}), "
              f"{umfang['saetze']} Rohdatensaetze.")

    print(f"\nDatenbank: {argumente.db or warehouse.DWH_PFAD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
