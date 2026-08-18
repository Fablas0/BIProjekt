"""Tests der Trendanalysen -- mit synthetischem Warehouse bekannter Wahrheit.

Angelegt werden drei Tage mit gezielten Bewegungen: ein Typ steigt auf, ein
Pokemon steigt neu in die Spitzengruppe ein, ein Item verliert Traeger. Die
Auswertungen muessen genau diese Bewegungen ausweisen -- nicht mehr, nicht
weniger.
"""

from __future__ import annotations

import pytest

from bi import warehouse
from bi.analytics import trends
from bi.etl import load
from bi.etl.transform import zeilen_hash

TAGE = ["2026-08-01", "2026-08-02", "2026-08-03"]


def _pokemon(nummer: int, typ: str) -> dict:
    return {
        "pokedex_id": 100 + nummer, "slug": f"mon-{nummer:02d}",
        "anzeigename": f"Mon {nummer:02d}", "spezies": f"mon-{nummer:02d}",
        "generation": 9, "typ1": typ, "typ2": None, "typ_kombination": typ,
        "hp": 80, "attack": 100, "defense": 80, "sp_attack": 90,
        "sp_defense": 80, "speed": 90,
        "stufe50_hp": 160, "stufe50_attack": 120, "stufe50_defense": 100,
        "stufe50_sp_attack": 110, "stufe50_sp_defense": 100, "stufe50_speed": 110,
        "basiswert_summe": 520, "offensiv_profil": "Physisch", "rolle": "Sweeper",
        "speed_klasse": "Mittel (80-99)", "resistenz_wert": 1.0,
        "row_hash": zeilen_hash({"slug": f"mon-{nummer:02d}"}),
    }


@pytest.fixture
def conn(tmp_path):
    """Zwoelf Pokemon, drei Tage, eingebaute Bewegungen.

    * Mon 00-05 sind Wasser, Mon 06-11 Feuer.
    * An Tag 3 verdraengt Mon 11 (Feuer) das Wasser-Pokemon Mon 05 aus den
      besten 10 -- Feuer steigt, Wasser faellt, und Mon 11 ist Neuzugang.
    * Mon 00 traegt an allen Tagen dasselbe Item; Mon 01 wechselt an Tag 3.
    """
    verbindung = warehouse.verbindung(str(tmp_path / "dwh.db"))
    quelle_sk = load.lade_quelle(verbindung, "champions")
    formate = load.lade_alle_kampfformate(verbindung)
    zeit = load.lade_zeit(verbindung, TAGE)
    saison_sk = load.lade_saison(verbindung, "T1", "Test", quelle_sk, TAGE)
    load.lade_pokemon_dimension(
        verbindung,
        [_pokemon(i, "Water" if i < 6 else "Fire") for i in range(12)], TAGE[0])
    pokemon = {z["slug"]: z["pokemon_sk"] for z in
               verbindung.execute("SELECT slug, pokemon_sk FROM Dim_Pokemon")}

    for tag_index, tag in enumerate(TAGE):
        # Grundreihenfolge: Mon 00 auf Rang 1 usw. An Tag 3 tauschen 05 und 11.
        reihenfolge = list(range(12))
        if tag_index == 2:
            reihenfolge[5], reihenfolge[11] = reihenfolge[11], reihenfolge[5]
        for rang, nummer in enumerate(reihenfolge, start=1):
            slug = f"mon-{nummer:02d}"
            verbindung.execute(
                """INSERT INTO Fact_Champions_Usage
                   (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, quelle_sk,
                    rang, rang_perzentil, erfasste_pokemon, etl_lauf_id)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 12, 0)""",
                (pokemon[slug], zeit[tag], saison_sk, formate["Doubles"],
                 quelle_sk, rang))

        item_fuer_mon01 = "Leftovers" if tag_index < 2 else "Focus Sash"
        for slug, item in (("mon-00", "Focus Sash"), ("mon-01", item_fuer_mon01)):
            verbindung.execute(
                """INSERT INTO Fact_Champions_Merkmal
                   (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, kategorie,
                    rang, bezeichnung, anteil)
                   VALUES (?, ?, ?, ?, 'held_item', 1, ?, 60.0)""",
                (pokemon[slug], zeit[tag], saison_sk, formate["Doubles"], item))
    verbindung.commit()
    yield verbindung
    verbindung.close()


def test_typenstaerke_zaehlt_vertreter_je_tag(conn) -> None:
    verlauf = trends.typenstaerke_verlauf(conn, n=10)
    tag1 = verlauf.loc[verlauf["datum_iso"] == TAGE[0]].set_index("typ")["vertreter"]
    tag3 = verlauf.loc[verlauf["datum_iso"] == TAGE[2]].set_index("typ")["vertreter"]
    assert tag1["Water"] == 6 and tag1["Fire"] == 4
    assert tag3["Water"] == 5 and tag3["Fire"] == 5


def test_typen_bewegung_weist_auf_und_absteiger_aus(conn) -> None:
    bewegung = trends.typen_bewegung(conn, n=10).set_index("typ")
    assert bewegung.loc["Fire", "veraenderung"] == 1
    assert bewegung.loc["Water", "veraenderung"] == -1


def test_neuzugang_wird_erkannt(conn) -> None:
    """Mon 11 steht erst ab Tag 3 in den besten 10 -- und nur Mon 11."""
    neu = trends.neuzugaenge(conn, n=10)
    assert neu["anzeigename"].tolist() == ["Mon 11"]
    assert neu.iloc[0]["erster_tag_oben"] == TAGE[2]
    assert bool(neu.iloc[0]["noch_oben"])


def test_etablierte_pokemon_sind_keine_neuzugaenge(conn) -> None:
    """Wer am ersten Tag schon oben stand, darf nicht als neu gelten."""
    neu = trends.neuzugaenge(conn, n=10)
    assert "Mon 00" not in neu["anzeigename"].tolist()


def test_item_nutzung_am_juengsten_tag(conn) -> None:
    aktuell = trends.item_nutzung(conn).set_index("bezeichnung")
    # An Tag 3 tragen beide Pokemon den Fokusgurt.
    assert aktuell.loc["Focus Sash", "traeger"] == 2
    assert "Leftovers" not in aktuell.index


def test_item_verlauf_zeigt_den_wechsel(conn) -> None:
    verlauf = trends.item_nutzung_verlauf(conn)
    leftovers = verlauf.loc[verlauf["bezeichnung"] == "Leftovers"]
    assert leftovers["datum_iso"].tolist() == TAGE[:2]  # ab Tag 3 verschwunden


def test_spitzenreiter_ist_die_verweildauer(conn) -> None:
    dauer = trends.spitzenreiter(conn, n=10)
    erste = dauer.iloc[0]
    assert erste["tage_in_top"] == 3
    assert erste["bestaendigkeit"] == "Dauerhaft"
    # Der Neuzugang steht mit einem Tag am Ende.
    assert dauer.loc[dauer["anzeigename"] == "Mon 11", "tage_in_top"].iloc[0] == 1


def test_leere_datenbank_liefert_leere_rahmen(tmp_path) -> None:
    leer = warehouse.verbindung(str(tmp_path / "leer.db"))
    assert trends.typenstaerke_verlauf(leer).empty
    assert trends.typen_bewegung(leer).empty
    assert trends.neuzugaenge(leer).empty
    assert trends.item_nutzung(leer).empty
    leer.close()
