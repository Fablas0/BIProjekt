"""Kopflose Pruefung des Hypothesenkatalogs.

Gibt den vollstaendigen Bericht auf der Kommandozeile aus -- dieselbe Rechnung,
die auch die Oberflaeche zeigt, nur ohne sie. Damit ist der Katalog Teil der
Operationalisierung: er laeuft im taeglichen Ladelauf mit und haelt fest, wie
sich die Befunde mit wachsender Zeitreihe entwickeln.

Aufruf::

    python -m scripts.hypothesen_pruefen                 # vollstaendiger Bericht
    python -m scripts.hypothesen_pruefen --kurz          # nur die Ergebnistabelle
    python -m scripts.hypothesen_pruefen --alpha 0.01    # strengeres Niveau
    python -m scripts.hypothesen_pruefen --json          # maschinenlesbar

Der Rueckgabewert ist 0, solange der Katalog gerechnet werden konnte, und 2,
wenn keine einzige Hypothese pruefbar war -- dann fehlt die Datenbasis, und das
soll ein Auftragsplaner erkennen koennen. Ein *beibehaltenes* H0 ist dagegen
kein Fehler, sondern ein Ergebnis: der Rueckgabewert haengt ausdruecklich nicht
davon ab, wie die Pruefungen ausgehen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bi import warehouse  # noqa: E402
from bi.analytics import hypothesen  # noqa: E402
from bi.config import ALPHA  # noqa: E402

# Rueckgabewert, wenn die Datenbasis fuer keine einzige Hypothese reicht.
EXIT_KEINE_DATEN = 2


def _kopf(text: str) -> str:
    return f"\n{text}\n{'=' * len(text)}"


def bericht(ergebnis: hypothesen.Katalogergebnis, ausfuehrlich: bool) -> str:
    """Formatiert den Katalog als Textbericht."""
    zeilen: list[str] = [
        _kopf("Hypothesenpruefung"),
        f"Signifikanzniveau: {ergebnis.alpha:.2f}, familienweise korrigiert nach "
        f"Holm-Bonferroni ueber {ergebnis.geprueft} pruefbare Hypothesen.",
    ]

    for bereich, eintraege in ergebnis.nach_bereich().items():
        zeilen.append(_kopf(bereich))
        for e in eintraege:
            h = e.hypothese
            zeilen.append(f"\n[{h.schluessel}] {h.titel}")
            zeilen.append(f"  H0: {h.nullhypothese}")
            zeilen.append(f"  H1: {h.alternativhypothese}")
            if not e.pruefbar:
                zeilen.append(f"  Ergebnis: nicht pruefbar -- {e.hinweis}")
                continue
            p = e.pruefgroesse
            zeilen.append(
                f"  {p.verfahren}: {p.statistik_name} = {p.statistik}"
                + (f", df = {p.freiheitsgrade}" if p.freiheitsgrade is not None else "")
                + f", n = {p.n}")
            zeilen.append(
                f"  p = {p.p_wert:.6f} gegen die Holm-Schranke {e.schranke:.6f}"
                f"  ->  {e.status}")
            zeilen.append(f"  Effektstaerke: {p.effekt_name} = {p.effekt} "
                          f"({p.effekt_deutung})")
            zeilen.append(f"  Befund: {e.befund}")
            if ausfuehrlich:
                zeilen.append(f"  Warum diese Frage: {h.begruendung}")
                zeilen.append(f"  Verfahren: {h.verfahren}")
                zeilen.append(f"  Datenbasis: {h.datenbasis}")
                if h.einschraenkung:
                    zeilen.append(f"  Einschraenkung: {h.einschraenkung}")

    zeilen.append(_kopf("Zusammenfassung"))
    zeilen.append(f"  {ergebnis.geprueft} von {len(ergebnis.ergebnisse)} Hypothesen geprueft")
    zeilen.append(f"  {ergebnis.verworfen} mal H0 verworfen")
    zeilen.append(f"  {ergebnis.geprueft - ergebnis.verworfen} mal H0 beibehalten")
    if ergebnis.nicht_pruefbar:
        zeilen.append(f"  {ergebnis.nicht_pruefbar} nicht pruefbar (Datenbasis fehlt)")
    return "\n".join(zeilen)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prueft den Hypothesenkatalog auf dem geladenen Data Warehouse.")
    parser.add_argument("--alpha", type=float, default=ALPHA,
                        help=f"Signifikanzniveau (Standard: {ALPHA})")
    parser.add_argument("--kurz", action="store_true",
                        help="Nur die Ergebnistabelle ausgeben")
    parser.add_argument("--json", action="store_true", dest="als_json",
                        help="Ergebnis maschinenlesbar ausgeben")
    parser.add_argument("--db", help="Abweichender Pfad zur Datenbankdatei")
    argumente = parser.parse_args(argv)

    conn = warehouse.verbindung(argumente.db)
    ergebnis = hypothesen.pruefe_alle(conn, alpha=argumente.alpha)

    if argumente.als_json:
        print(json.dumps({
            "alpha": ergebnis.alpha,
            "geprueft": ergebnis.geprueft,
            "verworfen": ergebnis.verworfen,
            "nicht_pruefbar": ergebnis.nicht_pruefbar,
            "hypothesen": [
                {
                    "schluessel": e.hypothese.schluessel,
                    "titel": e.hypothese.titel,
                    "bereich": e.hypothese.bereich,
                    "status": e.status,
                    "p_wert": e.pruefgroesse.p_wert if e.pruefbar else None,
                    "schranke": e.schranke if e.pruefbar else None,
                    "effekt": e.pruefgroesse.effekt if e.pruefbar else None,
                    "effekt_name": e.pruefgroesse.effekt_name if e.pruefbar else None,
                    "hinweis": e.hinweis,
                }
                for e in ergebnis.ergebnisse
            ],
        }, indent=2, ensure_ascii=True))
    elif argumente.kurz:
        print(ergebnis.als_tabelle().to_string(index=False))
    else:
        print(bericht(ergebnis, ausfuehrlich=True))

    if ergebnis.geprueft == 0:
        print("\nKeine einzige Hypothese war pruefbar -- ist das Warehouse geladen?",
              file=sys.stderr)
        return EXIT_KEINE_DATEN
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
