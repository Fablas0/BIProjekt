"""Aufbau des Data Warehouse aus dem mitversionierten Archiv.

Ohne diesen Schritt haette die Anwendung in der Cloud keine Daten. Das
Datenverzeichnis ist bewusst nicht versioniert, und Streamlit Community Cloud
setzt bei jedem Deployment einen frischen Behaelter auf -- auch beim taeglichen
Archiv-Commit. Die Datenbank waere dort jeden Tag wieder leer.

Der Ausweg ergibt sich aus dem Groessenverhaeltnis:

===================  ==========  ==========  =================================
Bestand              je Tag      je Jahr     wiederbeschaffbar?
===================  ==========  ==========  =================================
Rohdatenarchiv          0,3 MB      110 MB   **nein** -- Quelle vergisst nach 14 Tagen
Data Warehouse          6,0 MB      2,2 GB   ja -- in Sekunden aus dem Archiv
===================  ==========  ==========  =================================

Gesichert wird deshalb das Kleine und Unersetzliche, aufgebaut wird das Grosse
und Ableitbare -- bei jedem Start neu. Das ist zugleich die Kernidee einer
Staging-Schicht: Rohdaten sind die Wahrheit, das Warehouse ist eine Ableitung.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from . import warehouse
from .config import ARCHIV_VERZEICHNIS
from .etl import champions, stammarchiv

Fortschritt = Callable[[float, str], None]


def _still(_anteil: float, _text: str) -> None:
    """Standard-Callback, wenn kein Fortschritt gemeldet werden soll."""


def _aufbaubetrieb(conn: sqlite3.Connection) -> None:
    """Stellt die Datenbank auf Durchsatz statt auf Absturzsicherheit um.

    Waehrend des Aufbaus ist Haltbarkeit belanglos: die Datei entsteht ohnehin
    aus dem Archiv neu, wenn etwas schiefgeht. Gemessen verkuerzt das den
    Aufbau um rund ein Drittel.
    """
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA cache_size = -64000")


def _regelbetrieb(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA synchronous = NORMAL")


def ist_aufbau_moeglich(archiv: Path | None = None) -> bool:
    """Prueft, ob Tagesstaende zum Aufbauen bereitliegen.

    Gesucht wird nach ``<Saison>/<Kampfformat>/<Tag>.ndjson.gz`` -- also nach
    Bewegungsdaten. Ein Stammdatenauszug allein ergibt kein Warehouse.
    """
    verzeichnis = archiv or ARCHIV_VERZEICHNIS
    return verzeichnis.is_dir() and any(verzeichnis.glob("*/*/*.ndjson.gz"))


def sicherstellen(conn: sqlite3.Connection, archiv: Path | None = None,
                  fortschritt: Fortschritt = _still) -> dict[str, object]:
    """Baut das Warehouse aus dem Archiv auf, falls es leer ist.

    Ist bereits ein befuelltes Warehouse vorhanden, geschieht nichts -- der
    Aufruf ist damit gefahrlos wiederholbar und kann bei jedem Start erfolgen.
    """
    if warehouse.ist_befuellt(conn):
        return {"aufgebaut": False, "grund": "Warehouse bereits befuellt."}

    verzeichnis = archiv or ARCHIV_VERZEICHNIS
    if not ist_aufbau_moeglich(verzeichnis):
        return {"aufgebaut": False,
                "grund": f"Kein Archiv unter {verzeichnis} gefunden."}

    _aufbaubetrieb(conn)
    try:
        fortschritt(0.05, "Lade Stammdaten aus dem Archiv ...")
        stamm = stammarchiv.importiere_stammdaten(conn, verzeichnis)

        fortschritt(0.25, "Lese das Rohdatenarchiv ein ...")
        roh = champions.importiere_archiv(conn, verzeichnis)

        fortschritt(0.45, "Baue die Faktentabellen auf ...")
        ergebnis = champions.laden(
            conn, aus_archiv=True,
            fortschritt=lambda anteil, text: fortschritt(0.45 + anteil * 0.5, text))
    finally:
        _regelbetrieb(conn)

    fortschritt(1.0, "Data Warehouse bereit.")
    umfang = warehouse.archiv_umfang(conn)
    return {
        "aufgebaut": True,
        "stammdaten": stamm["saetze"],
        "rohdaten": roh["saetze"],
        "tage": umfang.get("tage", 0),
        "erster_tag": umfang.get("erster_tag"),
        "letzter_tag": umfang.get("letzter_tag"),
        "meldung": ergebnis.get("meldung", ""),
        "erfolgreich": bool(ergebnis.get("erfolgreich")),
    }
