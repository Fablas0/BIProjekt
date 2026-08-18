"""Versionierter Auszug der Stammdatendimensionen.

Die Rohdaten von Pokemon Champions liegen im Archiv, aber allein daraus laesst
sich kein Data Warehouse aufbauen: Champions liefert nur Namen und Raenge. Typ,
Basiswerte, Generation und die Eigenschaften von Attacken, Items und
Faehigkeiten stammen aus der PokeAPI.

Ohne diesen Auszug muesste jeder Kaltstart 1351 Pokemon einzeln bei der PokeAPI
abrufen -- rund 40 Sekunden, abhaengig von einem fremden Dienst, der genau dann
ausfallen kann, wenn jemand die Anwendung ansieht. Gzip-komprimiert sind es
0,12 MB; das gehoert ins Repository.

Anders als beim Rohdatenarchiv wird hier **tabellengetreu** gesichert, samt
Gueltigkeitszeitraeumen und Surrogatschluesseln. Der Auszug ist eine
Wiederherstellung, keine Neuladung: die bi-temporale Historie von
``Dim_Pokemon`` bliebe sonst nicht erhalten.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import archivdatei

# Genau die Dimensionen, die aus der PokeAPI stammen und daher nicht aus dem
# Champions-Archiv ableitbar sind.
STAMMTABELLEN = ("Dim_Pokemon", "Dim_Attacke", "Dim_Item", "Dim_Faehigkeit")

UNTERVERZEICHNIS = "stammdaten"


def _datei(ziel: Path, tabelle: str) -> Path:
    return ziel / UNTERVERZEICHNIS / f"{tabelle}.ndjson.gz"


def exportiere_stammdaten(conn: sqlite3.Connection, ziel: Path) -> dict[str, int]:
    """Schreibt die Stammdatendimensionen als versionierbare Dateien."""
    zaehler = {"tabellen": 0, "saetze": 0, "geschrieben": 0}

    for tabelle in STAMMTABELLEN:
        # Nach Surrogatschluessel sortiert, damit die Reihenfolge unabhaengig
        # von der Abfrageplanung stabil bleibt.
        schluessel = f"{tabelle.replace('Dim_', '').lower()}_sk"
        saetze = [dict(z) for z in conn.execute(
            f"SELECT * FROM {tabelle} ORDER BY {schluessel}")]  # noqa: S608
        if not saetze:
            continue

        zaehler["tabellen"] += 1
        zaehler["saetze"] += len(saetze)
        if archivdatei.schreibe_wenn_geaendert(
                _datei(ziel, tabelle), archivdatei.als_ndjson(saetze)):
            zaehler["geschrieben"] += 1

    return zaehler


def importiere_stammdaten(conn: sqlite3.Connection, quelle: Path) -> dict[str, int]:
    """Stellt die Stammdatendimensionen aus dem Auszug wieder her.

    Bereits befuellte Tabellen bleiben unangetastet: der laufende Betrieb haelt
    ueber die PokeAPI den aktuelleren Stand, der Auszug ist nur die Grundlage
    fuer einen Kaltstart.
    """
    zaehler = {"tabellen": 0, "saetze": 0}

    for tabelle in STAMMTABELLEN:
        vorhanden = conn.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0]  # noqa: S608
        if vorhanden:
            continue

        rohdaten = archivdatei.lies_nutzlast(_datei(quelle, tabelle))
        if rohdaten is None:
            continue

        saetze = archivdatei.aus_ndjson(rohdaten)
        if not saetze:
            continue

        spalten = list(saetze[0])
        conn.executemany(
            f"INSERT OR IGNORE INTO {tabelle} ({','.join(spalten)}) "  # noqa: S608
            f"VALUES ({','.join('?' * len(spalten))})",
            [tuple(satz.get(spalte) for spalte in spalten) for satz in saetze],
        )
        zaehler["tabellen"] += 1
        zaehler["saetze"] += len(saetze)

    conn.commit()
    return zaehler
