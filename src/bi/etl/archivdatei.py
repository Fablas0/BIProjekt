"""Gemeinsame Grundlage aller versionierten Archivdateien.

Das Archiv liegt als gzip-komprimiertes NDJSON im Repository. Damit das
funktioniert, muss eine Zusage gelten: **ein unveraenderter Inhalt darf keine
Aenderung an der Datei bewirken.** Sonst erzeugt jeder Betriebslauf einen
Commit ueber das gesamte Archiv, und die Historie wird unbrauchbar.

Die Zusage laesst sich nicht ueber die komprimierten Bytes einloesen: zlib
liefert je nach Fassung und Betriebssystem unterschiedliche Kompressate fuer
denselben Eingang. Verglichen wird deshalb immer die entpackte Nutzlast.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any


def lies_nutzlast(datei: Path) -> bytes | None:
    """Liest den entpackten Inhalt; ``None``, wenn die Datei fehlt oder defekt ist."""
    if not datei.exists():
        return None
    try:
        return gzip.decompress(datei.read_bytes())
    except (OSError, EOFError, gzip.BadGzipFile):
        # Eine abgebrochene Datei gilt als nicht vorhanden und wird kommentarlos
        # ueberschrieben -- die Datenbank ist die massgebliche Fassung.
        return None


def schreibe_wenn_geaendert(datei: Path, inhalt: bytes) -> bool:
    """Schreibt nur bei geaenderter Nutzlast. Rueckgabe: wurde geschrieben?"""
    if lies_nutzlast(datei) == inhalt:
        return False
    datei.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 haelt die Datei auch bei wiederholtem Lauf auf derselben Umgebung
    # bytegleich; der Zeitstempel gehoert nicht zum Inhalt.
    datei.write_bytes(gzip.compress(inhalt, compresslevel=9, mtime=0))
    return True


def als_ndjson(saetze: list[dict[str, Any]]) -> bytes:
    """Formt Saetze zu deterministischem NDJSON.

    Ein Satz je Zeile, Schluessel sortiert, ohne ueberfluessige Leerzeichen --
    damit derselbe Bestand immer dieselben Bytes ergibt.
    """
    return "".join(
        json.dumps(satz, separators=(",", ":"), sort_keys=True) + "\n"
        for satz in saetze
    ).encode("utf-8")


def aus_ndjson(rohdaten: bytes) -> list[dict[str, Any]]:
    """Liest NDJSON zurueck; Leerzeilen werden uebergangen."""
    return [json.loads(zeile) for zeile in rohdaten.decode("utf-8").splitlines() if zeile]
