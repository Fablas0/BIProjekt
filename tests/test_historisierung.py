"""Tests der bi-temporalen Historisierung und der Idempotenz des Ladelaufs.

Diese Tests decken die zentrale Zusage des Datenmodells ab: Aenderungen an
Dimensionsattributen ueberschreiben nichts, sondern eroeffnen einen neuen
Gueltigkeitszeitraum -- und ein wiederholter Ladelauf erzeugt weder Dubletten
noch Datenverlust.
"""

from __future__ import annotations

import pytest

from bi import quality, warehouse
from bi.etl import load
from bi.etl.transform import UsageSatz, zeilen_hash


@pytest.fixture
def conn():
    """Leeres Data Warehouse im Arbeitsspeicher."""
    verbindung = warehouse.verbindung(":memory:")
    yield verbindung
    verbindung.close()


def _pokemon(slug: str = "incineroar", attack: int = 115, typ2: str | None = "Dark") -> dict:
    """Dimensionssatz mit passend berechnetem Aenderungs-Hash."""
    satz = {
        "pokedex_id": 727, "slug": slug, "anzeigename": slug.capitalize(),
        "spezies": slug, "generation": 7, "typ1": "Fire", "typ2": typ2,
        "typ_kombination": f"Fire / {typ2}" if typ2 else "Fire",
        "hp": 95, "attack": attack, "defense": 90, "sp_attack": 80,
        "sp_defense": 90, "speed": 60, "basiswert_summe": 435 + attack,
        "offensiv_profil": "Physisch", "rolle": "Bulky Offense",
        "speed_klasse": "Langsam (60-79)", "resistenz_wert": 2.0,
    }
    satz["row_hash"] = zeilen_hash((727, "Fire", typ2, 95, attack, 90, 80, 90, 60, 7))
    return satz


# --------------------------------------------------------------------------
# Historisierung
# --------------------------------------------------------------------------

def test_erstladung_legt_aktuellen_satz_an(conn) -> None:
    zaehler = load.lade_pokemon_dimension(conn, [_pokemon()], stichtag="2026-01-01")

    assert zaehler == {"neu": 1, "geaendert": 0, "unveraendert": 0}
    zeile = conn.execute("SELECT * FROM Dim_Pokemon").fetchone()
    assert zeile["ist_aktuell"] == 1
    assert zeile["gueltig_ab"] == "2026-01-01"
    assert zeile["gueltig_bis"] == warehouse.UNENDLICH


def test_unveraenderte_daten_erzeugen_keinen_neuen_satz(conn) -> None:
    """Ohne fachliche Aenderung darf kein zweiter Zeitraum entstehen."""
    load.lade_pokemon_dimension(conn, [_pokemon()], stichtag="2026-01-01")
    zaehler = load.lade_pokemon_dimension(conn, [_pokemon()], stichtag="2026-02-01")

    assert zaehler == {"neu": 0, "geaendert": 0, "unveraendert": 1}
    assert conn.execute("SELECT COUNT(*) FROM Dim_Pokemon").fetchone()[0] == 1


def test_aenderung_eroeffnet_neuen_zeitraum(conn) -> None:
    """Der alte Zustand bleibt erhalten und wird sauber abgegrenzt."""
    load.lade_pokemon_dimension(conn, [_pokemon(attack=115)], stichtag="2026-01-01")
    zaehler = load.lade_pokemon_dimension(conn, [_pokemon(attack=125)], stichtag="2026-06-01")

    assert zaehler["geaendert"] == 1
    saetze = conn.execute(
        "SELECT attack, gueltig_ab, gueltig_bis, ist_aktuell FROM Dim_Pokemon ORDER BY gueltig_ab"
    ).fetchall()

    assert len(saetze) == 2, "Der historische Zustand muss erhalten bleiben."

    alt, neu = saetze
    assert alt["attack"] == 115
    assert alt["ist_aktuell"] == 0
    assert alt["gueltig_bis"] == "2026-05-31", "Abgrenzung auf den Vortag der Aenderung."

    assert neu["attack"] == 125
    assert neu["ist_aktuell"] == 1
    assert neu["gueltig_ab"] == "2026-06-01"
    assert neu["gueltig_bis"] == warehouse.UNENDLICH


def test_zeitraeume_sind_lueckenlos_und_ueberschneidungsfrei(conn) -> None:
    """Die Gueltigkeitszeitraeume muessen direkt aneinander anschliessen."""
    load.lade_pokemon_dimension(conn, [_pokemon(attack=100)], stichtag="2026-01-01")
    load.lade_pokemon_dimension(conn, [_pokemon(attack=110)], stichtag="2026-03-01")
    load.lade_pokemon_dimension(conn, [_pokemon(attack=120)], stichtag="2026-05-01")

    saetze = conn.execute(
        "SELECT gueltig_ab, gueltig_bis FROM Dim_Pokemon ORDER BY gueltig_ab"
    ).fetchall()
    assert len(saetze) == 3

    assert saetze[0]["gueltig_bis"] == "2026-02-28"
    assert saetze[1]["gueltig_ab"] == "2026-03-01"
    assert saetze[1]["gueltig_bis"] == "2026-04-30"
    assert saetze[2]["gueltig_ab"] == "2026-05-01"

    # Genau ein Satz darf als aktuell markiert sein.
    assert conn.execute(
        "SELECT COUNT(*) FROM Dim_Pokemon WHERE ist_aktuell = 1").fetchone()[0] == 1


def test_historischer_stichtag_ist_abfragbar(conn) -> None:
    """Der Zweck der Historisierung: Auswertung zu einem vergangenen Stand."""
    load.lade_pokemon_dimension(conn, [_pokemon(attack=100)], stichtag="2026-01-01")
    load.lade_pokemon_dimension(conn, [_pokemon(attack=140)], stichtag="2026-06-01")

    stand = conn.execute(
        "SELECT attack FROM Dim_Pokemon WHERE slug = ? AND ? BETWEEN gueltig_ab AND gueltig_bis",
        ("incineroar", "2026-03-15"),
    ).fetchone()
    assert stand["attack"] == 100, "Zum Stichtag im Maerz galt noch der alte Wert."


def test_qualitaetsregeln_nach_historisierung(conn) -> None:
    """Die Konsistenzregeln muessen nach mehreren Aenderungen bestehen."""
    for monat, wert in (("2026-01-01", 100), ("2026-03-01", 110), ("2026-05-01", 120)):
        load.lade_pokemon_dimension(conn, [_pokemon(attack=wert)], stichtag=monat)

    eindeutig = quality.regel_dimension_eindeutig(conn)
    intervalle = quality.regel_historisierung_intervalle(conn)
    assert eindeutig.bestanden, eindeutig.befund
    assert intervalle.bestanden, intervalle.befund


# --------------------------------------------------------------------------
# Idempotenz der Faktenladung
# --------------------------------------------------------------------------

def _fakten_vorbereiten(conn) -> tuple[int, int, int]:
    """Legt die Dimensionen an, die fuer einen Faktensatz noetig sind."""
    load.lade_pokemon_dimension(conn, [_pokemon()], stichtag="2026-01-01")
    zeit = load.lade_zeit(conn, ["2026-05", "2026-06"])
    regulation_sk = load.lade_regulation(
        conn, "gen9vgc2026regi", "Reg I", "Bo1", "VGC 2026", "Gen 9", "VGC 2026 Reg I (Bo1)")
    skill_sk = load.lade_skill(conn, 1760, "Top-Spieler", 4)
    load.lade_hilfsdimensionen(conn, {"choiceband"}, {"blaze"}, {"fire"})
    return zeit["2026-06"], regulation_sk, skill_sk


def _usage_satz(usage: float) -> UsageSatz:
    return UsageSatz(
        slug="incineroar", usage_rate=usage, raw_count=1000,
        gxe_top=88.0, gxe_p75=78.0, gxe_p50=61.0, rang=1,
        attacken=[], items=[("choiceband", 60.0, 1)],
        faehigkeiten=[("blaze", 100.0, 1)], tera_typen=[("fire", 70.0, 1)], partner=[],
    )


def test_wiederholter_faktenlauf_erzeugt_keine_dubletten(conn) -> None:
    """Derselbe Monat zweimal geladen ergibt genau einen Faktensatz."""
    zeit_sk, regulation_sk, skill_sk = _fakten_vorbereiten(conn)
    lauf = load.lauf_beginnen(conn, "Test", "idempotenz")

    load.lade_fakten(conn, [_usage_satz(40.0)], zeit_sk, regulation_sk, skill_sk, 5000, lauf)
    load.lade_fakten(conn, [_usage_satz(45.0)], zeit_sk, regulation_sk, skill_sk, 5000, lauf)

    zeilen = conn.execute("SELECT usage_rate FROM Fact_Usage").fetchall()
    assert len(zeilen) == 1, "Der fachliche Schluessel muss die Dublette verhindern."
    assert zeilen[0]["usage_rate"] == 45.0, "Der erneute Lauf aktualisiert die Kennzahl."


def test_neuer_monat_loescht_vorhandene_historie_nicht(conn) -> None:
    """Nicht-Volatilitaet: bereits geladene Monate bleiben unberuehrt.

    Die urspruengliche Umsetzung leerte die Faktentabelle vor jedem Lauf. Damit
    waere jede Zeitreihe und jede Trendkennzahl unmoeglich.
    """
    zeit = load.lade_zeit(conn, ["2026-05", "2026-06"])
    load.lade_pokemon_dimension(conn, [_pokemon()], stichtag="2026-01-01")
    regulation_sk = load.lade_regulation(
        conn, "gen9vgc2026regi", "Reg I", "Bo1", "VGC 2026", "Gen 9", "VGC 2026 Reg I (Bo1)")
    skill_sk = load.lade_skill(conn, 1760, "Top-Spieler", 4)
    load.lade_hilfsdimensionen(conn, {"choiceband"}, {"blaze"}, {"fire"})
    lauf = load.lauf_beginnen(conn, "Test", "zeitreihe")

    load.lade_fakten(conn, [_usage_satz(40.0)], zeit["2026-05"], regulation_sk, skill_sk,
                     5000, lauf)
    load.lade_fakten(conn, [_usage_satz(50.0)], zeit["2026-06"], regulation_sk, skill_sk,
                     6000, lauf)

    monate = conn.execute("""
        SELECT z.monat_iso, f.usage_rate FROM Fact_Usage f
        JOIN Dim_Zeit z ON z.zeit_sk = f.zeit_sk ORDER BY z.monat_iso
    """).fetchall()

    assert len(monate) == 2
    assert monate[0]["monat_iso"] == "2026-05"
    assert monate[0]["usage_rate"] == 40.0
    assert monate[1]["usage_rate"] == 50.0


def test_fakt_ohne_dimensionssatz_wird_abgewiesen(conn) -> None:
    """Referenzielle Integritaet: ohne Dimensionssatz kein Fakt."""
    zeit_sk, regulation_sk, skill_sk = _fakten_vorbereiten(conn)
    lauf = load.lauf_beginnen(conn, "Test", "integritaet")

    unbekannt = _usage_satz(10.0)
    unbekannt.slug = "gibtesnicht"
    anzahl, befunde = load.lade_fakten(
        conn, [unbekannt], zeit_sk, regulation_sk, skill_sk, 5000, lauf)

    assert anzahl == 0
    assert any(b.dimension == "Referenzielle Integritaet" for b in befunde)


def test_etl_protokoll_wird_gefuehrt(conn) -> None:
    """Jeder Lauf muss mit Kennzahlen und Laufzeit protokolliert werden."""
    lauf = load.lauf_beginnen(conn, "Test", "protokoll")
    load.lauf_abschliessen(conn, lauf, "erfolgreich", gelesen=100, geladen=95, abgewiesen=5,
                           meldung="Testlauf")

    zeile = conn.execute("SELECT * FROM ETL_Lauf WHERE lauf_id = ?", (lauf,)).fetchone()
    assert zeile["status"] == "erfolgreich"
    assert zeile["zeilen_gelesen"] == 100
    assert zeile["zeilen_geladen"] == 95
    assert zeile["zeilen_abgewiesen"] == 5
    assert zeile["dauer_sekunden"] is not None
    assert zeile["beendet_am"] is not None
