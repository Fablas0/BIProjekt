"""Orchestrierung der ETL-Laeufe.

Zwei getrennte Prozesse mit unterschiedlicher Ladefrequenz:

* :func:`stammdaten_laden` -- PokeAPI. Aendert sich nur bei einer neuen
  Spielgeneration oder einer Balance-Anpassung, laeuft also selten.
* :func:`bewegungsdaten_laden` -- Smogon. Monatlich neue Daten, laeuft regelmaessig.

Beide sind wiederholbar: ein Abbruch hinterlaesst keinen inkonsistenten Zustand,
und ein erneuter Lauf fuehrt zum selben Ergebnis.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from ..config import SKILL_STUFEN, STANDARD_MONATE
from . import extract, load
from .transform import (
    Befund,
    transformiere_attacke,
    transformiere_pokemon,
    transformiere_usage_dump,
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


# --------------------------------------------------------------------------
# Prozess 1: Stammdaten
# --------------------------------------------------------------------------

def stammdaten_laden(conn: sqlite3.Connection, fortschritt: Fortschritt = _still,
                     stichtag: str | None = None) -> LaufErgebnis:
    """Laedt den Pokemon-Bestand aus der PokeAPI in ``Dim_Pokemon``.

    ``stichtag`` steuert den Beginn der fachlichen Gueltigkeit und ist vor allem
    fuer Tests der Historisierung nuetzlich.
    """
    lauf_id = load.lauf_beginnen(conn, "PokeAPI", "Vollstaendiger Stammdatenabzug")
    befunde: list[Befund] = []

    try:
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


# --------------------------------------------------------------------------
# Prozess 2: Bewegungsdaten
# --------------------------------------------------------------------------

def bewegungsdaten_laden(conn: sqlite3.Connection, format_code: str, elo_cutoff: int,
                         anzahl_monate: int = STANDARD_MONATE,
                         fortschritt: Fortschritt = _still) -> LaufErgebnis:
    """Laedt die Smogon-Nutzungsstatistik fuer mehrere Monate.

    Der Mehrmonatsbezug ist die Voraussetzung fuer jede Trendauswertung -- eine
    Momentaufnahme allein laesst keine Aussage ueber die Entwicklung des Metagames zu.
    """
    parameter = f"{format_code} / ELO {elo_cutoff} / {anzahl_monate} Monate"
    lauf_id = load.lauf_beginnen(conn, "Smogon", parameter)
    alle_befunde: list[Befund] = []
    details: list[str] = []
    gelesen = geladen = 0

    try:
        with extract.sitzung() as s:
            fortschritt(0.02, "Suche verfuegbare Monate ...")
            ziele = extract.finde_ziele(s, format_code, elo_cutoff, anzahl_monate)
            if not ziele:
                raise ValueError(
                    f"Fuer '{format_code}' mit ELO-Grenze {elo_cutoff} liegen keine "
                    "Auswertungen im Smogon-Archiv vor."
                )

            erstes = ziele[0]
            regulation_sk = load.lade_regulation(
                conn, erstes.format_code, erstes.regulation, erstes.spielmodus,
                erstes.saison, erstes.generation, erstes.anzeige,
            )
            bezeichnung, stufe = SKILL_STUFEN.get(elo_cutoff, (f"ELO {elo_cutoff}", 0))
            skill_sk = load.lade_skill(conn, elo_cutoff, bezeichnung, stufe)
            zeit_karte = load.lade_zeit(conn, [z.monat_iso for z in ziele])

            bekannte_slugs = {
                zeile["slug"] for zeile in
                conn.execute("SELECT slug FROM Dim_Pokemon WHERE ist_aktuell = 1")
            }
            if not bekannte_slugs:
                raise ValueError(
                    "Die Pokemon-Dimension ist leer. Bitte zuerst die Stammdaten laden."
                )

            # Erster Durchlauf: laden und transformieren, um den benoetigten
            # Umfang der Attacken-, Item- und Faehigkeitsdimensionen zu kennen.
            transformiert = []
            for i, ziel in enumerate(ziele):
                anteil = 0.05 + 0.45 * (i / len(ziele))
                fortschritt(anteil, f"Lade Smogon-Daten {ziel.monat_iso} ...")
                dump = extract.hole_usage_dump(s, ziel)
                if dump is None:
                    alle_befunde.append(Befund(
                        "Fact_Usage", ziel.monat_iso, "Quellverfuegbarkeit",
                        f"Datei {ziel.url} war nicht abrufbar -- Monat fehlt in der Zeitreihe",
                        klasse="Mangel 2. Klasse", dimension="Vollstaendigkeit"))
                    continue

                saetze, befunde, partien = transformiere_usage_dump(dump, bekannte_slugs)
                alle_befunde.extend(befunde)
                gelesen += len(dump.get("data") or {})
                transformiert.append((ziel, saetze, partien))
                load.staging_smogon(conn, lauf_id, ziel.format_code, ziel.elo_cutoff,
                                    ziel.monat_iso, dump)

            if not transformiert:
                raise ValueError("Kein einziger Monat konnte geladen werden.")

            # Dimensionen aus den beobachteten Auspraegungen aufbauen.
            fortschritt(0.55, "Baue Auspraegungs-Dimensionen ...")
            attacken_slugs: set[str] = set()
            items: set[str] = set()
            faehigkeiten: set[str] = set()
            tera_typen: set[str] = set()
            for _, saetze, _ in transformiert:
                for satz in saetze:
                    attacken_slugs.update(slug for slug, _, _ in satz.attacken)
                    items.update(slug for slug, _, _ in satz.items)
                    faehigkeiten.update(slug for slug, _, _ in satz.faehigkeiten)
                    tera_typen.update(slug for slug, _, _ in satz.tera_typen)

            # Lesbare Bezeichnungen fuer Items und Faehigkeiten aus den
            # Ressourcenverzeichnissen der PokeAPI (zwei Sammelabfragen).
            anzeigenamen = _kompaktnamen_aufloesen(s, ("item", "ability"))
            load.lade_hilfsdimensionen(conn, items, faehigkeiten, tera_typen, anzeigenamen)

            fortschritt(0.62, "Lade Attacken-Stammdaten ...")
            bereits_bekannt = {
                zeile["slug"] for zeile in conn.execute("SELECT slug FROM Dim_Attacke")
            }
            fehlende = attacken_slugs - bereits_bekannt
            if fehlende:
                # Die PokeAPI erwartet Bindestriche, die Smogon-Slugs haben keine.
                # Es wird daher ueber eine Nachschlagetabelle aufgeloest.
                aufloesung = _attacken_slug_aufloesung(s, fehlende)
                nutzlasten = extract.hole_attacken(
                    s, aufloesung.values(),
                    lambda a, t: fortschritt(0.62 + 0.18 * a, t),
                )
                load.lade_attacken_dimension(conn, [transformiere_attacke(n) for n in nutzlasten])

            # Zweiter Durchlauf: Fakten schreiben.
            for i, (ziel, saetze, partien) in enumerate(transformiert):
                anteil = 0.82 + 0.16 * (i / len(transformiert))
                fortschritt(anteil, f"Schreibe Fakten {ziel.monat_iso} ...")
                anzahl, befunde = load.lade_fakten(
                    conn, saetze, zeit_karte[ziel.monat_iso], regulation_sk, skill_sk,
                    partien, lauf_id,
                )
                alle_befunde.extend(befunde)
                geladen += anzahl
                details.append(
                    f"{ziel.monat_iso}: {anzahl} Pokemon, "
                    f"{format(partien, ',').replace(',', '.')} Partien"
                )

        load.befunde_protokollieren(conn, lauf_id, alle_befunde)
        load.staging_bereinigen(conn)
        verworfen = sum(1 for b in alle_befunde if b.verworfen)
        load.lauf_abschliessen(
            conn, lauf_id, "erfolgreich", gelesen=gelesen, geladen=geladen,
            abgewiesen=verworfen,
            meldung=f"{len(transformiert)} Monate geladen ({erstes.anzeige}).",
        )
        fortschritt(1.0, "Bewegungsdaten geladen.")
        return LaufErgebnis(
            lauf_id=lauf_id, erfolgreich=True, gelesen=gelesen, geladen=geladen,
            abgewiesen=verworfen,
            meldung=f"{len(transformiert)} Monate fuer {erstes.anzeige} geladen.",
            details=details,
        )

    except Exception as fehler:  # noqa: BLE001 - Ladefehler wird protokolliert, nicht verschluckt
        load.befunde_protokollieren(conn, lauf_id, alle_befunde)
        load.lauf_abschliessen(conn, lauf_id, "fehler", gelesen=gelesen, geladen=geladen,
                               meldung=str(fehler))
        return LaufErgebnis(lauf_id=lauf_id, erfolgreich=False, gelesen=gelesen,
                            geladen=geladen, meldung=str(fehler))


def _kompaktnamen_aufloesen(s, ressourcen: tuple[str, ...]) -> dict[str, str]:
    """Bildet bindestrichlose Smogon-Bezeichner auf die PokeAPI-Slugs ab.

    Smogon schreibt ``closecombat``, die PokeAPI ``close-combat``. Die Wortgrenze
    ist aus dem Smogon-Namen nicht rekonstruierbar, daher wird je Ressourcenart
    einmalig das Verzeichnis geladen und darueber abgeglichen.
    """
    zuordnung: dict[str, str] = {}
    for ressource in ressourcen:
        antwort = s.get(f"{extract.POKEAPI_BASIS}/{ressource}?limit=3000", timeout=60)
        if antwort.status_code != 200:
            continue
        for eintrag in antwort.json().get("results", []):
            zuordnung.setdefault(eintrag["name"].replace("-", ""), eintrag["name"])
    return zuordnung


def _attacken_slug_aufloesung(s, slugs: set[str]) -> dict[str, str]:
    """Ordnet den benoetigten Attacken-Slugs ihre PokeAPI-Schreibweise zu."""
    verzeichnis = _kompaktnamen_aufloesen(s, ("move",))
    return {slug: verzeichnis[slug] for slug in slugs if slug in verzeichnis}
