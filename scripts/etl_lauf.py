"""Kopfloser ETL-Lauf.

Baut das Data Warehouse ohne Benutzeroberflaeche auf und ist damit die Grundlage
der Operationalisierung: derselbe Aufruf laeuft in der Continuous Integration,
als zeitgesteuerter Auftrag und lokal.

Aufruf:
    python -m scripts.etl_lauf --format gen9vgc2026regi --elo 1760 --monate 6

Ohne Angabe eines Formats wird das aktuellste verfuegbare VGC-Format verwendet.
Der Rueckgabewert ist 0 bei Erfolg und 1 bei einem Fehler, sodass ein
uebergeordneter Auftragsplaner den Ausgang auswerten kann.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bi import warehouse  # noqa: E402
from bi.config import STANDARD_ELO, STANDARD_MONATE  # noqa: E402
from bi.etl import extract, pipeline  # noqa: E402


def _neuestes_format(elo: int) -> str:
    """Ermittelt das aktuellste VGC-Format mit der gewuenschten Skill-Stufe.

    Bevorzugt wird das Format ohne Bo3-Zusatz, weil es die breitere Datenbasis hat.
    """
    with extract.sitzung() as s:
        for monat in extract.verfuegbare_monate(s, grenze=4):
            kandidaten = [code for code, cutoff in extract.verfuegbare_formate(s, monat)
                          if cutoff == elo and not code.endswith("bo3")]
            if kandidaten:
                return sorted(kandidaten)[-1]
    raise SystemExit(f"Kein VGC-Format mit ELO-Grenze {elo} im Smogon-Archiv gefunden.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baut das VGC Data Warehouse auf.")
    parser.add_argument("--format", dest="format_code",
                        help="Smogon-Formatkennung, z.B. gen9vgc2026regi")
    parser.add_argument("--elo", type=int, default=STANDARD_ELO,
                        help=f"ELO-Grenzwert der Auswertung (Standard: {STANDARD_ELO})")
    parser.add_argument("--monate", type=int, default=STANDARD_MONATE,
                        help=f"Anzahl Monate der Zeitreihe (Standard: {STANDARD_MONATE})")
    parser.add_argument("--db", help="Abweichender Pfad zur Datenbankdatei")
    parser.add_argument("--nur-bewegungsdaten", action="store_true",
                        help="Stammdaten ueberspringen (setzt eine befuellte Dimension voraus)")
    argumente = parser.parse_args(argv)

    def melde(anteil: float, text: str) -> None:
        print(f"[{anteil * 100:5.1f}%] {text}", flush=True)

    conn = warehouse.verbindung(argumente.db)

    if not argumente.nur_bewegungsdaten:
        print("== Schritt 1: Stammdaten (PokeAPI) ==", flush=True)
        ergebnis = pipeline.stammdaten_laden(conn, melde)
        if not ergebnis.erfolgreich:
            print(f"FEHLER: {ergebnis.meldung}", file=sys.stderr)
            return 1
        h = ergebnis.historisierung
        print(f"   {ergebnis.geladen} Pokemon verarbeitet "
              f"(neu {h.get('neu', 0)}, geaendert {h.get('geaendert', 0)}, "
              f"unveraendert {h.get('unveraendert', 0)}).")

    format_code = argumente.format_code or _neuestes_format(argumente.elo)
    print(f"\n== Schritt 2: Bewegungsdaten (Smogon) -- {format_code}, ELO {argumente.elo} ==",
          flush=True)

    ergebnis = pipeline.bewegungsdaten_laden(
        conn, format_code, argumente.elo, argumente.monate, melde)
    if not ergebnis.erfolgreich:
        print(f"FEHLER: {ergebnis.meldung}", file=sys.stderr)
        return 1

    print(f"   {ergebnis.meldung}")
    for zeile in ergebnis.details:
        print(f"   - {zeile}")
    print(f"\nGelesen {ergebnis.gelesen}, geladen {ergebnis.geladen}, "
          f"abgewiesen {ergebnis.abgewiesen}.")
    print(f"Datenbank: {warehouse.DWH_PFAD if not argumente.db else argumente.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
