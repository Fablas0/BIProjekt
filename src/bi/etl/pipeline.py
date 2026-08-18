"""Orchestrierung der ETL-Laeufe.

Zwei Teilprozesse mit unterschiedlicher Ladefrequenz:

* :func:`stammdaten_laden` -- PokeAPI. Aendert sich nur bei einer neuen
  Spielgeneration oder einer Balance-Anpassung, laeuft also selten.
* :func:`attacken_ergaenzen`, :func:`items_ergaenzen`,
  :func:`faehigkeiten_ergaenzen` -- bedarfsgesteuertes Nachladen der
  Stammdaten aus den Hauptspielen. Champions nennt Attacken, Items und
  Faehigkeiten nur beim Namen; ihre Eigenschaften stehen in der PokeAPI.
* :func:`bi.etl.champions.laden` -- Pokemon Champions. Taeglich neue Daten;
  weil die Quelle nur rund zwei Wochen vorhaelt, sollte der Lauf regelmaessig
  erfolgen, damit keine Tage verloren gehen.

Beide sind wiederholbar: ein Abbruch hinterlaesst keinen inkonsistenten Zustand,
und ein erneuter Lauf fuehrt zum selben Ergebnis.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from . import extract, load
from .transform import (
    Befund,
    transformiere_attacke,
    transformiere_faehigkeit,
    transformiere_item,
    transformiere_pokemon,
)

Fortschritt = Callable[[float, str], None]


def _still(_anteil: float, _text: str) -> None:
    """Standard-Callback, wenn kein Fortschritt gemeldet werden soll."""


@dataclass
class LaufErgebnis:
    """Zusammenfassung eines ETL-Laufs fuer die Anzeige in der Oberflaeche."""

    lauf_id: int
    erfolgreich: bool
    gelesen: int = 0
    geladen: int = 0
    abgewiesen: int = 0
    meldung: str = ""
    details: list[str] = field(default_factory=list)
    historisierung: dict[str, int] = field(default_factory=dict)


def stammdaten_laden(conn: sqlite3.Connection, fortschritt: Fortschritt = _still,
                     stichtag: str | None = None) -> LaufErgebnis:
    """Laedt den Pokemon-Bestand aus der PokeAPI in ``Dim_Pokemon``.

    ``stichtag`` steuert den Beginn der fachlichen Gueltigkeit und ist vor allem
    fuer Tests der Historisierung nuetzlich.
    """
    lauf_id = load.lauf_beginnen(conn, "PokeAPI", "Vollstaendiger Stammdatenabzug")
    befunde: list[Befund] = []

    try:
        load.lade_quelle(conn, "pokeapi")

        with extract.sitzung() as s:
            abzug = extract.hole_pokemon_stammdaten(s, fortschritt)

            fortschritt(0.85, "Transformiere Stammdaten ...")
            saetze = []
            for nutzlast in abzug.pokemon:
                satz, befund = transformiere_pokemon(nutzlast, abzug.generation_je_spezies)
                if satz:
                    saetze.append(satz)
                elif befund:
                    befunde.append(befund)

            for slug in abzug.fehlversuche:
                befunde.append(Befund(
                    "Dim_Pokemon", slug, "Quellverfuegbarkeit",
                    "Ressource war nach mehreren Versuchen nicht abrufbar",
                    klasse="Mangel 2. Klasse", dimension="Vollstaendigkeit"))

            fortschritt(0.92, "Schreibe Dimension mit Historisierung ...")
            historisierung = load.lade_pokemon_dimension(conn, saetze, stichtag)

        load.befunde_protokollieren(conn, lauf_id, befunde)
        load.lauf_abschliessen(
            conn, lauf_id, "erfolgreich",
            gelesen=len(abzug.pokemon), geladen=len(saetze), abgewiesen=len(befunde),
            meldung=(f"{historisierung['neu']} neu, {historisierung['geaendert']} geaendert, "
                     f"{historisierung['unveraendert']} unveraendert"),
        )
        fortschritt(1.0, "Stammdaten geladen.")
        return LaufErgebnis(
            lauf_id=lauf_id, erfolgreich=True, gelesen=len(abzug.pokemon),
            geladen=len(saetze), abgewiesen=len(befunde),
            meldung=f"{len(saetze)} Pokemon verarbeitet.", historisierung=historisierung,
        )

    except Exception as fehler:  # noqa: BLE001 - Ladefehler wird protokolliert, nicht verschluckt
        load.befunde_protokollieren(conn, lauf_id, befunde)
        load.lauf_abschliessen(conn, lauf_id, "fehler", meldung=str(fehler))
        return LaufErgebnis(lauf_id=lauf_id, erfolgreich=False, meldung=str(fehler))


def _ergaenze_stammsaetze(conn: sqlite3.Connection, tabelle: str, ressource: str,
                          kompakte_namen: set[str], transformation,
                          lade, hole, fortschritt: Fortschritt = _still) -> int:
    """Gemeinsames Nachladeverfahren fuer Attacken, Items und Faehigkeiten.

    Alle drei folgen demselben Muster: Champions nennt nur den Anzeigenamen,
    die Eigenschaften stehen in den Hauptspielen. Geladen wird ausschliesslich,
    was in den Bewegungsdaten vorkommt und noch fehlt -- ein vollstaendiger
    Abzug waere ein Vielfaches an Aufrufen fuer Daten, die nie jemand ansieht.
    """
    vorhanden = {z["slug"] for z in conn.execute(f"SELECT slug FROM {tabelle}")}  # noqa: S608
    fehlend = kompakte_namen - vorhanden
    if not fehlend:
        return 0

    with extract.sitzung() as s:
        verzeichnis = extract.verzeichnis_kompakt(s, ressource)
        aufloesung = {k: verzeichnis[k] for k in fehlend if k in verzeichnis}
        if not aufloesung:
            return 0
        nutzlasten = hole(s, aufloesung.values(), fortschritt)

    lade(conn, [transformation(n) for n in nutzlasten])
    return len(nutzlasten)


def attacken_ergaenzen(conn: sqlite3.Connection, kompakte_namen: set[str],
                       fortschritt: Fortschritt = _still) -> int:
    """Laedt Attacken nach, die noch nicht in der Dimension stehen.

    Champions liefert nur den Anzeigenamen einer Attacke. Typ, Kategorie und
    Basisschaden -- die Grundlage jeder Matchup-Bewertung -- stammen aus der
    PokeAPI und werden hier bedarfsgesteuert nachgeladen.

    Rueckgabe: Anzahl neu geladener Attacken.
    """
    return _ergaenze_stammsaetze(
        conn, "Dim_Attacke", "move", kompakte_namen, transformiere_attacke,
        load.lade_attacken_dimension, extract.hole_attacken, fortschritt)


def items_ergaenzen(conn: sqlite3.Connection, kompakte_namen: set[str],
                    fortschritt: Fortschritt = _still) -> int:
    """Laedt Items nach, die noch nicht in der Dimension stehen.

    Champions liefert zum getragenen Item nur den Anzeigenamen. Wirkung und
    Kategorie -- und damit die Grundlage jeder Itemauswertung und des
    Schadensrechners -- stammen aus den Hauptspielen ueber die PokeAPI.
    """
    return _ergaenze_stammsaetze(
        conn, "Dim_Item", "item", kompakte_namen, transformiere_item,
        load.lade_item_dimension, extract.hole_items, fortschritt)


def faehigkeiten_ergaenzen(conn: sqlite3.Connection, kompakte_namen: set[str],
                           fortschritt: Fortschritt = _still) -> int:
    """Laedt Faehigkeiten nach, die noch nicht in der Dimension stehen."""
    return _ergaenze_stammsaetze(
        conn, "Dim_Faehigkeit", "ability", kompakte_namen, transformiere_faehigkeit,
        load.lade_faehigkeit_dimension, extract.hole_faehigkeiten, fortschritt)
