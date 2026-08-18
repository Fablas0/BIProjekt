"""ETL-Strecke fuer die PvP-Meta von Pokemon GO (Quelle: pvpoke).

Warum diese Quelle
------------------
Pokemon GO veroeffentlicht selbst keine Nutzungsdaten. pvpoke berechnet aus dem
Spielstand (Werte, Attacken, Typen) eine simulationsgestuetzte Rangliste je
Liga und ist die Referenz, an der sich die GO-PvP-Szene ausrichtet. Bezogen
wird der Datenbestand aus dem oeffentlichen GitHub-Repository des Projekts --
dieselben Dateien, die auch die Website ausliefert, aber ueber eine stabile,
zwischenspeicherfreundliche Adresse.

Zwei Eigenheiten praegen die Umsetzung:

**Die Quelle hat keine Historie.** pvpoke ueberschreibt seine Ranglisten bei
jeder Balance-Anpassung. Was gestern galt, ist nicht mehr abrufbar -- dieselbe
Lage wie bei Champions, nur ohne die 14 Tage Gnadenfrist. Jeder Abzug wird
deshalb nach ``Archiv_GO`` gesichert; erst dadurch entsteht eine Zeitreihe.

**Die Kennzahl ist kardinal.** Die Quelle bewertet jedes Pokemon mit einer
Punktzahl von 0 bis 100. Anders als beim Champions-Rang sind hier Differenzen
und Mittelwerte zulaessig; der Rang wird zusaetzlich abgeleitet und ist als
Ableitung gekennzeichnet. Das Messniveau steht an der Quelle
(``Dim_Quelle.messniveau_nutzung``), die Auswertung fragt es dort ab.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any

import requests

from ..config import GO_LIGEN, GO_RANKING_URL, HTTP_TIMEOUT
from . import load
from .extract import sitzung
from .transform import Befund, zeitdimension

# Formzusaetze der Quelle -> Schreibweise der PokeAPI. pvpoke schreibt
# 'stunfisk_galarian', die PokeAPI 'stunfisk-galar'.
_FORM_ZUORDNUNG = {
    "galarian": "galar", "alolan": "alola", "hisuian": "hisui", "paldean": "paldea",
    "altered": "altered", "origin": "origin", "incarnate": "incarnate",
    "therian": "therian", "standard": "standard", "shadow": None,  # eigenes Kennzeichen
}


def quell_id_zu_slug(quell_id: str) -> tuple[str, bool]:
    """Bildet einen pvpoke-Bezeichner auf den PokeAPI-Slug ab.

    Rueckgabe: (Slug, ist_schatten). Schatten-Formen sind eine GO-eigene
    Mechanik ohne Entsprechung in der Hauptreihe; sie werden auf das
    Grund-Pokemon abgebildet und eigens gekennzeichnet.
    """
    teile = quell_id.lower().split("_")
    ist_schatten = "shadow" in teile
    teile = [t for t in teile if t != "shadow"]
    umgeschrieben = [_FORM_ZUORDNUNG.get(t, t) for t in teile]
    return "-".join(t for t in umgeschrieben if t), ist_schatten


def hole_rangliste(s: requests.Session, liga: str) -> list[dict[str, Any]]:
    """Laedt die Rangliste einer Liga."""
    antwort = s.get(GO_RANKING_URL.format(wp=GO_LIGEN[liga]), timeout=HTTP_TIMEOUT)
    antwort.raise_for_status()
    return antwort.json()


def archiviere(conn: sqlite3.Connection, stand: str, liga: str,
               nutzlast: list[dict[str, Any]], lauf_id: int) -> None:
    """Sichert den Rohabzug -- die Quelle selbst vergisst bei jeder Anpassung."""
    conn.execute(
        """INSERT INTO Archiv_GO (stand_iso, liga, nutzlast, archiviert_am, lauf_id)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(stand_iso, liga) DO NOTHING""",
        (stand, liga, json.dumps(nutzlast, separators=(",", ":")),
         datetime.now().isoformat(timespec="seconds"), lauf_id))
    conn.commit()


def lies_aus_archiv(conn: sqlite3.Connection) -> list[tuple[str, str, list[dict]]]:
    """Alle archivierten Staende: (Stand, Liga, Nutzlast)."""
    return [(z["stand_iso"], z["liga"], json.loads(z["nutzlast"]))
            for z in conn.execute(
                "SELECT stand_iso, liga, nutzlast FROM Archiv_GO ORDER BY stand_iso")]


def lade_stand(conn: sqlite3.Connection, stand: str, liga: str,
               nutzlast: list[dict[str, Any]], lauf_id: int) -> tuple[int, list[Befund]]:
    """Ueberfuehrt eine Rangliste in den Fakt."""
    befunde: list[Befund] = []
    quelle_sk = load.lade_quelle(conn, "go_pvpoke")
    liga_sk = load.lade_liga(conn, liga)
    zeit_sk = zeitdimension(stand)["zeit_sk"]
    conn.execute(
        """INSERT INTO Dim_Zeit (zeit_sk, datum_iso, jahr, quartal, monat, tag,
               monat_iso, monat_name, quartal_label, tag_label, wochentag)
           VALUES (:zeit_sk, :datum_iso, :jahr, :quartal, :monat, :tag, :monat_iso,
               :monat_name, :quartal_label, :tag_label, :wochentag)
           ON CONFLICT(datum_iso) DO NOTHING""",
        zeitdimension(stand))

    pokemon_karte = {
        z["slug"]: z["pokemon_sk"] for z in
        conn.execute("SELECT slug, pokemon_sk FROM Dim_Pokemon WHERE ist_aktuell = 1")
    }

    # Nach Score absteigend rangieren -- der Rang ist eine Ableitung.
    sortiert = sorted(
        (satz for satz in nutzlast if satz.get("speciesId") and satz.get("score") is not None),
        key=lambda satz: -float(satz["score"]))

    zeilen = []
    nicht_aufloesbar = 0
    for rang, satz in enumerate(sortiert, start=1):
        slug, ist_schatten = quell_id_zu_slug(satz["speciesId"])
        pokemon_sk = pokemon_karte.get(slug)
        if pokemon_sk is None:
            nicht_aufloesbar += 1
        zeilen.append((pokemon_sk, satz["speciesId"], liga_sk, zeit_sk, quelle_sk,
                       round(float(satz["score"]), 2), rang, int(ist_schatten), lauf_id))

    conn.executemany(
        """INSERT INTO Fact_GO_Meta
               (pokemon_sk, quell_id, liga_sk, zeit_sk, quelle_sk, score, rang,
                ist_schatten, etl_lauf_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(quell_id, liga_sk, zeit_sk) DO UPDATE SET
               pokemon_sk = excluded.pokemon_sk, score = excluded.score,
               rang = excluded.rang, ist_schatten = excluded.ist_schatten,
               etl_lauf_id = excluded.etl_lauf_id""",
        zeilen)
    conn.commit()

    if nicht_aufloesbar:
        befunde.append(Befund(
            "Fact_GO_Meta", liga, "Namensharmonisierung",
            f"{nicht_aufloesbar} von {len(zeilen)} GO-Bezeichnern ohne Entsprechung "
            "in der Pokemon-Dimension. Die Saetze sind geladen; nur die "
            "spieluebergreifende Verknuepfung fehlt ihnen.",
            klasse="Mangel 2. Klasse", dimension="Referenzielle Integritaet",
            verworfen=False))
    return len(zeilen), befunde


def laden(conn: sqlite3.Connection, aus_archiv: bool = False) -> dict[str, Any]:
    """Vollstaendiger GO-Ladelauf: Abzug, Archivierung, Fakten.

    ``aus_archiv`` verarbeitet nur bereits gesicherte Staende neu -- fuer den
    Kaltstart ohne Netzzugriff.
    """
    lauf_id = load.lauf_beginnen(conn, "GO",
                                 "Archiv-Neuverarbeitung" if aus_archiv else "Tagesabzug")
    try:
        heute = date.today().isoformat()
        geladen = 0
        befunde: list[Befund] = []

        if not aus_archiv:
            with sitzung() as s:
                for liga in GO_LIGEN:
                    nutzlast = hole_rangliste(s, liga)
                    archiviere(conn, heute, liga, nutzlast, lauf_id)

        staende = lies_aus_archiv(conn)
        if not staende:
            raise ValueError("Es liegen weder neue noch archivierte GO-Daten vor.")

        for stand, liga, nutzlast in staende:
            anzahl, neue_befunde = lade_stand(conn, stand, liga, nutzlast, lauf_id)
            geladen += anzahl
            befunde.extend(neue_befunde)

        load.befunde_protokollieren(conn, lauf_id, befunde)
        load.lauf_abschliessen(conn, lauf_id, "erfolgreich",
                               gelesen=len(staende), geladen=geladen,
                               meldung=f"{len(staende)} Ranglistenstaende")
        return {"erfolgreich": True, "lauf_id": lauf_id, "geladen": geladen,
                "staende": len(staende)}
    except Exception as fehler:  # noqa: BLE001 -- protokolliert, nicht verschluckt
        load.lauf_abschliessen(conn, lauf_id, "fehler", meldung=str(fehler))
        return {"erfolgreich": False, "lauf_id": lauf_id, "meldung": str(fehler)}
