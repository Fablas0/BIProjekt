"""Zentrale Konfiguration der BI-Loesung.

Alle Pfade, Endpunkte und fachlichen Schwellwerte sind hier gebuendelt, damit
Umgebungswechsel (lokal / Streamlit Cloud / CI) ohne Codeaenderung moeglich sind.
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------
# Ablage
# --------------------------------------------------------------------------
PROJEKT_WURZEL = Path(__file__).resolve().parents[2]
DATEN_VERZEICHNIS = Path(os.getenv("VGC_BI_DATA_DIR", PROJEKT_WURZEL / "data"))
DWH_PFAD = Path(os.getenv("VGC_BI_DB", DATEN_VERZEICHNIS / "vgc_dwh.db"))

# --------------------------------------------------------------------------
# Quellsysteme
# --------------------------------------------------------------------------
POKEAPI_BASIS = "https://pokeapi.co/api/v2"
CHAMPIONS_BASIS = "https://championsbattledata.com"

# PokeAPI ist unauthentifiziert und fair-use; 12 Threads bleiben deutlich unter
# der inoffiziellen Grenze und halten den Erstimport unter zwei Minuten.
HTTP_THREADS = int(os.getenv("VGC_BI_THREADS", "12"))
HTTP_TIMEOUT = 60
HTTP_WIEDERHOLUNGEN = 3

# Nur Generation 9 ist fuer das aktuelle VGC-Format relevant.
GENERATIONEN = list(range(1, 10))

# --------------------------------------------------------------------------
# Fachliche Parameter
# --------------------------------------------------------------------------
# Kampfformate von Pokemon Champions und die Zahl der im Team-Preview zu
# waehlenden Pokemon.
KAMPFFORMATE = ("Doubles", "Singles")
MITNAHME = {"Doubles": 4, "Singles": 3}
STANDARD_KAMPFFORMAT = "Doubles"

# Bis zu diesem Rang gilt ein Pokemon als Meta-relevant.
META_RANGGRENZE = 50

# Anteil, ab dem eine Attacke oder ein Item als Teil des Standard-Sets gilt.
SET_SCHWELLE = 20.0

# Vorhaltezeit der Quelle in Tagen. Alles darueber hinaus existiert nur noch im
# eigenen Archiv.
QUELLE_VORHALTUNG_TAGE = 14

ALLE_TYPEN = [
    "Normal", "Fire", "Water", "Electric", "Grass", "Ice",
    "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug",
    "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy",
]

TYP_FARBEN = {
    "Normal": "#A8A77A", "Fire": "#EE8130", "Water": "#6390F0", "Electric": "#F7D02C",
    "Grass": "#7AC74C", "Ice": "#96D9D6", "Fighting": "#C22E28", "Poison": "#A33EA1",
    "Ground": "#E2BF65", "Flying": "#A98FF3", "Psychic": "#F95587", "Bug": "#A6B91A",
    "Rock": "#B6A136", "Ghost": "#735797", "Dragon": "#6F35FC", "Dark": "#705746",
    "Steel": "#B7B7CE", "Fairy": "#D685AD",
}

TYP_DEUTSCH = {
    "Normal": "Normal", "Fire": "Feuer", "Water": "Wasser", "Electric": "Elektro",
    "Grass": "Pflanze", "Ice": "Eis", "Fighting": "Kampf", "Poison": "Gift",
    "Ground": "Boden", "Flying": "Flug", "Psychic": "Psycho", "Bug": "Kaefer",
    "Rock": "Gestein", "Ghost": "Geist", "Dragon": "Drache", "Dark": "Unlicht",
    "Steel": "Stahl", "Fairy": "Fee",
}

SPRITE_BASIS = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork"
)


def sprite_url(pokedex_id: int) -> str:
    """Liefert die URL des offiziellen Artworks zu einer Pokedex-Nummer."""
    return f"{SPRITE_BASIS}/{pokedex_id}.png"


def datenverzeichnis_anlegen() -> None:
    """Stellt sicher, dass das Datenverzeichnis existiert."""
    DATEN_VERZEICHNIS.mkdir(parents=True, exist_ok=True)
