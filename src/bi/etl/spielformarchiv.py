"""Versionierte Dateiablage der TCG- und GO-Rohdaten.

Gleiches Prinzip wie beim Champions-Archiv (:mod:`bi.etl.champions`): die
Datenbanktabellen ``Archiv_TCG`` und ``Archiv_GO`` ueberleben zwar jedes
Zuruecksetzen des Warehouse, aber keinen frischen Rechner. Deshalb werden sie
zusaetzlich als gzip-NDJSON-Dateien exportiert und mitversioniert:

```
archiv/go/2026-08-18_great.ndjson.gz          ein Ranglistenstand je Datei
archiv/tcg/0000123.ndjson.gz                  ein Turnier je Datei
```

Der Determinismus-Vertrag (:mod:`bi.etl.archivdatei`) gilt unveraendert:
geschrieben wird nur bei geaenderter Nutzlast, verglichen ueber den entpackten
Inhalt.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from . import archivdatei

GO_UNTERVERZEICHNIS = "go"
TCG_UNTERVERZEICHNIS = "tcg"


def exportiere(conn: sqlite3.Connection, ziel: Path) -> dict[str, int]:
    """Schreibt beide Archive als Dateien. Rueckgabe: Zaehler."""
    zaehler = {"dateien": 0, "geschrieben": 0}

    go_ordner = ziel / GO_UNTERVERZEICHNIS
    for zeile in conn.execute(
            "SELECT stand_iso, liga, nutzlast FROM Archiv_GO ORDER BY stand_iso, liga"):
        go_ordner.mkdir(parents=True, exist_ok=True)
        datei = go_ordner / f"{zeile['stand_iso']}_{zeile['liga']}.ndjson.gz"
        inhalt = archivdatei.als_ndjson(json.loads(zeile["nutzlast"]))
        zaehler["dateien"] += 1
        if archivdatei.schreibe_wenn_geaendert(datei, inhalt):
            zaehler["geschrieben"] += 1

    tcg_ordner = ziel / TCG_UNTERVERZEICHNIS
    for zeile in conn.execute(
            "SELECT turnier_id, nutzlast FROM Archiv_TCG ORDER BY turnier_id"):
        tcg_ordner.mkdir(parents=True, exist_ok=True)
        datei = tcg_ordner / f"{zeile['turnier_id']}.ndjson.gz"
        zaehler["dateien"] += 1
        if archivdatei.schreibe_wenn_geaendert(
                datei, archivdatei.als_ndjson([json.loads(zeile["nutzlast"])])):
            zaehler["geschrieben"] += 1

    return zaehler


def importiere(conn: sqlite3.Connection, quelle: Path, lauf_id: int = 0) -> dict[str, int]:
    """Liest die Dateiablage zurueck in die Archivtabellen."""
    zaehler = {"go": 0, "tcg": 0}
    jetzt = datetime.now().isoformat(timespec="seconds")

    for datei in sorted((quelle / GO_UNTERVERZEICHNIS).glob("*.ndjson.gz")
                        if (quelle / GO_UNTERVERZEICHNIS).is_dir() else []):
        stand, _, liga = datei.stem.removesuffix(".ndjson").partition("_")
        saetze = archivdatei.aus_ndjson(archivdatei.lies_nutzlast(datei) or b"")
        if not saetze:
            continue
        conn.execute(
            """INSERT INTO Archiv_GO (stand_iso, liga, nutzlast, archiviert_am, lauf_id)
               VALUES (?, ?, ?, ?, ?) ON CONFLICT(stand_iso, liga) DO NOTHING""",
            (stand, liga, json.dumps(saetze, separators=(",", ":")), jetzt, lauf_id))
        zaehler["go"] += 1

    for datei in sorted((quelle / TCG_UNTERVERZEICHNIS).glob("*.ndjson.gz")
                        if (quelle / TCG_UNTERVERZEICHNIS).is_dir() else []):
        saetze = archivdatei.aus_ndjson(archivdatei.lies_nutzlast(datei) or b"")
        if not saetze:
            continue
        nutzlast = saetze[0]
        turnier_id = str((nutzlast.get("turnier") or {}).get("id") or
                         datei.stem.removesuffix(".ndjson"))
        stand = ((nutzlast.get("turnier") or {}).get("date") or "")[:10]
        conn.execute(
            """INSERT INTO Archiv_TCG (stand_iso, turnier_id, nutzlast,
                   archiviert_am, lauf_id)
               VALUES (?, ?, ?, ?, ?) ON CONFLICT(turnier_id) DO NOTHING""",
            (stand, turnier_id, json.dumps(nutzlast, separators=(",", ":")),
             jetzt, lauf_id))
        zaehler["tcg"] += 1

    conn.commit()
    return zaehler
