"""Auswahl der auszuwertenden Saison.

Bis hierher filterte jede Abfrage der Analyseschicht fest auf ``ist_aktuell = 1``
-- also auf die jeweils juengste Saison. Das ist im Normalfall richtig, hat aber
eine unangenehme Folge: sobald Pokemon Champions eine neue Saison eroeffnet,
verliert die vorige ihr Kennzeichen, und die gesamte archivierte Historie
verschwindet aus der Oberflaeche. Sie liegt weiterhin in Datenbank und Archiv,
ist aber nicht mehr erreichbar -- ausgerechnet die Daten also, deren Sicherung
der eigentliche Zweck des Archivs ist.

Die Auswahl wird auf den **Surrogatschluessel** aufgeloest und als Zahl in die
Abfragen eingesetzt. Das hat zwei Gruende:

* Der Schluessel stammt aus der eigenen Dimensionstabelle und ist eine
  ganze Zahl. Eine Einschleusung ist damit ausgeschlossen -- was bei einer
  Zeichenkette aus der Oberflaeche zu pruefen waere.
* Die Stellung der Platzhalter in den bestehenden Abfragen bleibt unberuehrt.
  Ein zusaetzlicher Parameter haette in ueber zwanzig Abfragen die Reihenfolge
  verschoben, und jede Verwechslung waere ein stiller Fehler gewesen.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

# Das Praedikat, das jede Abfrage der Analyseschicht traegt, samt optionalem
# Tabellenalias. ``saison_aktuell`` ist in den Sichten eine echte Spalte; in den
# Abfragen auf die Dimensionstabellen dient derselbe Name als Platzhalter.
#
# Das ist Absicht: wird die Ersetzung einmal vergessen, bricht SQLite mit
# "no such column" ab. Ein stiller Fehler, der schlicht die falsche Saison
# auswertet, waere sehr viel teurer.
_PRAEDIKAT = re.compile(r"(\w+\.)?saison_aktuell = 1")


@dataclass(frozen=True)
class Saison:
    """Eine Saison der Quelle samt abgedecktem Zeitraum."""

    schluessel: str
    bezeichnung: str
    ist_aktuell: bool
    beginn: str | None
    ende: str | None
    tage: int

    @property
    def anzeige(self) -> str:
        """Beschriftung fuer die Auswahl in der Oberflaeche."""
        zusatz = " (laufend)" if self.ist_aktuell else ""
        return f"{self.schluessel}{zusatz} · {self.tage} Tage"


def verfuegbare(conn: sqlite3.Connection) -> list[Saison]:
    """Alle Saisons, fuer die Fakten vorliegen -- die laufende zuerst."""
    zeilen = conn.execute("""
        SELECT s.schluessel, s.bezeichnung, s.ist_aktuell, s.beginn, s.ende,
               COUNT(DISTINCT f.zeit_sk) AS tage
        FROM Dim_Saison s
        JOIN Fact_Champions_Usage f ON f.saison_sk = s.saison_sk
        GROUP BY s.saison_sk
        ORDER BY s.ist_aktuell DESC, s.beginn DESC
    """).fetchall()
    return [
        Saison(z["schluessel"], z["bezeichnung"], bool(z["ist_aktuell"]),
               z["beginn"], z["ende"], int(z["tage"]))
        for z in zeilen
    ]


def schluessel_aufloesen(conn: sqlite3.Connection, schluessel: str | None) -> int | None:
    """Loest einen Saisonschluessel in seinen Surrogatschluessel auf.

    ``None`` bedeutet "die laufende Saison". Ist der uebergebene Schluessel
    unbekannt, wird ebenfalls auf die laufende zurueckgefallen -- eine veraltete
    Auswahl in der Sitzung darf die Anwendung nicht lahmlegen.
    """
    if schluessel:
        zeile = conn.execute(
            "SELECT saison_sk FROM Dim_Saison WHERE schluessel = ?",
            (schluessel,)).fetchone()
        if zeile:
            return int(zeile[0])

    zeile = conn.execute(
        "SELECT saison_sk FROM Dim_Saison WHERE ist_aktuell = 1 LIMIT 1").fetchone()
    return int(zeile[0]) if zeile else None


def anwenden(sql: str, conn: sqlite3.Connection) -> str:
    """Setzt die gewaehlte Saison in eine Abfrage ein.

    Ersetzt ``saison_aktuell = 1`` durch ``saison_sk = <Zahl>``. Ein
    vorangestellter Tabellenalias bleibt erhalten, weil er nicht Teil des
    Musters ist: aus ``u.saison_aktuell = 1`` wird ``u.saison_sk = 3``.

    Der Weg ueber eine Textersetzung ist bewusst gewaehlt. Ein zusaetzlicher
    Abfrageparameter haette in ueber zwanzig Abfragen die Stellung der
    Platzhalter verschoben -- jede Verwechslung waere ein stiller Fehler
    gewesen, der falsche Zahlen liefert statt abzubrechen. Eingesetzt wird
    ausschliesslich ein aus der eigenen Dimensionstabelle gelesener
    Surrogatschluessel, also eine ganze Zahl; eine Einschleusung ist damit
    ausgeschlossen.

    Welche Saison gilt, traegt die Verbindung selbst -- siehe
    :class:`bi.warehouse.Verbindung`. Ohne gesetzte Wahl bleibt es bei der
    laufenden Saison, also beim bisherigen Verhalten.

    Liegt keine Saison vor -- ein leeres Warehouse --, entsteht ein Praedikat,
    das nichts liefert, statt versehentlich alles.
    """
    sk = schluessel_aufloesen(conn, getattr(conn, "saison_wahl", None))

    def _ersetze(treffer: re.Match) -> str:
        if sk is None:
            # Ohne Saison faellt auch der Alias weg -- "u.1 = 0" waere kein SQL.
            return "1 = 0"
        return f"{treffer.group(1) or ''}saison_sk = {int(sk)}"

    return _PRAEDIKAT.sub(_ersetze, sql)
