"""ETL-Strecke fuer das Sammelkartenspiel (Quelle: Limitless-Turnierdaten).

Warum diese Quelle
------------------
Das Sammelkartenspiel kennt keine Ranked-Ladder mit veroeffentlichter Nutzung;
seine Meta zeigt sich in Turnieren. Limitless fuehrt die Standings der
offiziellen und der grossen Online-Turniere -- und zu jedem Spieler das
**Land**. Genau das traegt die Laenderhypothese: ob verschiedene Maerkte
verschieden spielen, laesst sich nur mit einer Quelle pruefen, die den Ort
mitliefert. Champions liefert ihn nicht, pvpoke auch nicht.

Die Meta-Einheit ist hier das **Deck**, nicht das einzelne Pokemon: gespielt
wird ein Archetyp ("Charizard ex", "Lost Box"), dessen Liste um ein oder zwei
Leit-Pokemon gebaut ist. Das Datenmodell folgt der Quelle -- ``Dim_TCG_Deck``
mit dem Leit-Pokemon als Bruecke zur konformen Pokemon-Dimension, wo die
Aufloesung gelingt.

Zugang
------
Die API verlangt einen kostenlosen Schluessel (``VGC_BI_TCG_SCHLUESSEL``).
Fehlt er, wird die Strecke uebersprungen und als Befund ausgewiesen -- eine
Zusatzquelle darf den Gesamtlauf nicht scheitern lassen, ihr Fehlen darf aber
auch nicht unbemerkt bleiben.

Kennzahlen sind **kardinal**: gezaehlt werden Spieler je Deck und Land. Summen
und Anteile sind zulaessig -- im Gegensatz zur ordinalen Champions-Strecke.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

import requests

from ..config import TCG_API_BASIS, TCG_API_SCHLUESSEL, TCG_MIN_TEILNEHMER
from . import load
from .extract import sitzung
from .mapping import loese_auf
from .transform import Befund, zeitdimension


def _kopfzeilen() -> dict[str, str]:
    return {"X-Access-Key": TCG_API_SCHLUESSEL}


def hole_turniere(s: requests.Session, limit: int = 20) -> list[dict[str, Any]]:
    """Die juengsten abgeschlossenen Turniere des Standardformats."""
    antwort = s.get(f"{TCG_API_BASIS}/tournaments",
                    params={"game": "PTCG", "format": "standard", "limit": limit},
                    headers=_kopfzeilen(), timeout=30)
    antwort.raise_for_status()
    return antwort.json()


def hole_standings(s: requests.Session, turnier_id: str) -> list[dict[str, Any]]:
    """Die Standings eines Turniers: Platzierung, Land, Deck je Spieler."""
    antwort = s.get(f"{TCG_API_BASIS}/tournaments/{turnier_id}/standings",
                    headers=_kopfzeilen(), timeout=30)
    antwort.raise_for_status()
    return antwort.json()


def archiviere(conn: sqlite3.Connection, turnier: dict[str, Any],
               standings: list[dict[str, Any]], lauf_id: int) -> None:
    conn.execute(
        """INSERT INTO Archiv_TCG (stand_iso, turnier_id, nutzlast, archiviert_am, lauf_id)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(turnier_id) DO NOTHING""",
        ((turnier.get("date") or "")[:10], str(turnier["id"]),
         json.dumps({"turnier": turnier, "standings": standings},
                    separators=(",", ":")),
         datetime.now().isoformat(timespec="seconds"), lauf_id))
    conn.commit()


def archivierte_turniere(conn: sqlite3.Connection) -> set[str]:
    return {z[0] for z in conn.execute("SELECT turnier_id FROM Archiv_TCG")}


def lies_aus_archiv(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [json.loads(z["nutzlast"]) for z in
            conn.execute("SELECT nutzlast FROM Archiv_TCG ORDER BY stand_iso")]


def deck_schluessel(name: str) -> str:
    """Normalisiert einen Archetypnamen zum Dimensionsschluessel."""
    return "".join(c for c in name.lower() if c.isalnum() or c == " ").strip().replace(" ", "-")


def lade_turnier(conn: sqlite3.Connection, nutzlast: dict[str, Any],
                 lauf_id: int, bekannte_slugs: set[str]) -> tuple[int, list[Befund]]:
    """Ueberfuehrt ein archiviertes Turnier in den Fakt.

    Granularitaet: Deck x Land x Turniertag. Mehrere Turniere am selben Tag
    werden aufaddiert -- die Kennzahl ist eine Zaehlung, das ist zulaessig.
    """
    befunde: list[Befund] = []
    turnier = nutzlast.get("turnier") or {}
    standings = nutzlast.get("standings") or []
    datum = (turnier.get("date") or "")[:10]
    if not datum or not standings:
        return 0, befunde

    quelle_sk = load.lade_quelle(conn, "tcg_limitless")
    zeitsatz = zeitdimension(datum)
    conn.execute(
        """INSERT INTO Dim_Zeit (zeit_sk, datum_iso, jahr, quartal, monat, tag,
               monat_iso, monat_name, quartal_label, tag_label, wochentag)
           VALUES (:zeit_sk, :datum_iso, :jahr, :quartal, :monat, :tag, :monat_iso,
               :monat_name, :quartal_label, :tag_label, :wochentag)
           ON CONFLICT(datum_iso) DO NOTHING""",
        zeitsatz)
    zeit_sk = zeitsatz["zeit_sk"]

    # Zaehlung je Deck und Land; die besten acht gesondert.
    zaehlung: dict[tuple[str, str], dict[str, Any]] = {}
    ohne_deck = 0
    for eintrag in standings:
        deck = eintrag.get("deck") or {}
        name = deck.get("name")
        land = (eintrag.get("country") or "").upper()
        if not name or not land:
            ohne_deck += 1
            continue
        schluessel = (deck_schluessel(name), land)
        satz = zaehlung.setdefault(schluessel, {
            "name": name, "icons": deck.get("icons") or [], "spieler": 0, "top8": 0})
        satz["spieler"] += 1
        platzierung = eintrag.get("placing")
        if isinstance(platzierung, int) and platzierung <= 8:
            satz["top8"] += 1

    zeilen = []
    for (deck_key, land), satz in zaehlung.items():
        # Leit-Pokemon: das erste Symbol des Decks, gegen die Pokemon-Dimension
        # aufgeloest. Gelingt die Aufloesung nicht, bleibt die Bruecke leer --
        # das Deck selbst ist davon unberuehrt.
        leit_slug = None
        if satz["icons"] and bekannte_slugs:
            leit_slug = loese_auf(str(satz["icons"][0]).replace("-", " "), bekannte_slugs)
        conn.execute(
            """INSERT INTO Dim_TCG_Deck (schluessel, anzeigename, leit_slug)
               VALUES (?, ?, ?)
               ON CONFLICT(schluessel) DO UPDATE SET
                   leit_slug = COALESCE(Dim_TCG_Deck.leit_slug, excluded.leit_slug)""",
            (deck_key, satz["name"], leit_slug))
        deck_sk = int(conn.execute(
            "SELECT deck_sk FROM Dim_TCG_Deck WHERE schluessel = ?",
            (deck_key,)).fetchone()[0])
        markt_sk = load.lade_markt(conn, land)
        zeilen.append((deck_sk, markt_sk, zeit_sk, quelle_sk,
                       satz["spieler"], satz["top8"], lauf_id))

    conn.executemany(
        """INSERT INTO Fact_TCG_Meta
               (deck_sk, markt_sk, zeit_sk, quelle_sk, spieler, top8, etl_lauf_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(deck_sk, markt_sk, zeit_sk) DO UPDATE SET
               spieler = Fact_TCG_Meta.spieler + excluded.spieler,
               top8 = Fact_TCG_Meta.top8 + excluded.top8,
               etl_lauf_id = excluded.etl_lauf_id""",
        zeilen)
    conn.commit()

    if ohne_deck:
        befunde.append(Befund(
            "Fact_TCG_Meta", str(turnier.get("id", "?")), "Pflichtfelder Deck und Land",
            f"{ohne_deck} von {len(standings)} Standing-Zeilen ohne Deck- oder "
            "Landesangabe -- nicht zaehlbar.",
            klasse="Mangel 1. Klasse", dimension="Vollstaendigkeit"))
    return len(zeilen), befunde


def laden(conn: sqlite3.Connection, aus_archiv: bool = False,
          max_turniere: int = 20) -> dict[str, Any]:
    """Vollstaendiger TCG-Ladelauf. Ohne API-Schluessel: Befund statt Fehler.

    Wiederholte Laeufe sind idempotent: der Fakt wird je Turnier aufaddiert,
    aber ein bereits archiviertes Turnier wird nicht erneut geladen -- die
    Archivtabelle ist zugleich das Gedaechtnis der Strecke. Beim Neuaufbau
    (``aus_archiv``) werden die Fakten zuvor geleert, sonst zaehlte jedes
    Turnier doppelt.
    """
    lauf_id = load.lauf_beginnen(conn, "TCG",
                                 "Archiv-Neuverarbeitung" if aus_archiv else
                                 f"max. {max_turniere} Turniere")
    try:
        bekannte_slugs = {z[0] for z in conn.execute(
            "SELECT slug FROM Dim_Pokemon WHERE ist_aktuell = 1")}
        befunde: list[Befund] = []

        if not aus_archiv:
            if not TCG_API_SCHLUESSEL:
                befund = Befund(
                    "Archiv_TCG", "Limitless", "Zugangsschluessel",
                    "Kein API-Schluessel gesetzt (VGC_BI_TCG_SCHLUESSEL) -- die "
                    "TCG-Strecke wurde uebersprungen. Ein kostenloser Schluessel "
                    "ist unter play.limitlesstcg.com erhaeltlich.",
                    klasse="Mangel 2. Klasse", dimension="Vollstaendigkeit",
                    verworfen=False)
                load.befunde_protokollieren(conn, lauf_id, [befund])
                load.lauf_abschliessen(conn, lauf_id, "erfolgreich",
                                       meldung="Uebersprungen: kein API-Schluessel.")
                return {"erfolgreich": True, "lauf_id": lauf_id, "geladen": 0,
                        "uebersprungen": True}

            bereits = archivierte_turniere(conn)
            with sitzung() as s:
                for turnier in hole_turniere(s, max_turniere):
                    if str(turnier.get("id")) in bereits:
                        continue
                    if int(turnier.get("players") or 0) < TCG_MIN_TEILNEHMER:
                        continue
                    standings = hole_standings(s, str(turnier["id"]))
                    archiviere(conn, turnier, standings, lauf_id)
        else:
            # Neuverarbeitung: die Zaehlfakten entstehen aus dem Archiv neu.
            conn.execute("DELETE FROM Fact_TCG_Meta")
            conn.commit()

        geladen = 0
        turniere = lies_aus_archiv(conn)
        if not aus_archiv:
            # Auch im Tageslauf alles neu zaehlen, damit die Summen stimmen.
            conn.execute("DELETE FROM Fact_TCG_Meta")
            conn.commit()
        for nutzlast in turniere:
            anzahl, neue = lade_turnier(conn, nutzlast, lauf_id, bekannte_slugs)
            geladen += anzahl
            befunde.extend(neue)

        load.befunde_protokollieren(conn, lauf_id, befunde)
        load.lauf_abschliessen(conn, lauf_id, "erfolgreich",
                               gelesen=len(turniere), geladen=geladen,
                               meldung=f"{len(turniere)} Turniere verarbeitet")
        return {"erfolgreich": True, "lauf_id": lauf_id, "geladen": geladen,
                "turniere": len(turniere)}
    except Exception as fehler:  # noqa: BLE001 -- protokolliert, nicht verschluckt
        load.lauf_abschliessen(conn, lauf_id, "fehler", meldung=str(fehler))
        return {"erfolgreich": False, "lauf_id": lauf_id, "meldung": str(fehler)}
