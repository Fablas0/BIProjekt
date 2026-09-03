"""Tests der Spielstaende: Durchspielen, Nuzlocke-Regeln, Kartensammlung.

Die Nuzlocke-Regeln sind Zusagen an den Spieler und liegen an der
Datenschicht, nicht an der Oberflaeche -- genau deshalb sind sie hier
pruefbar: ein gewoehnlicher Durchgang laesst zu, was ein Nuzlocke verweigert.
"""

from __future__ import annotations

import pytest

from bi import nutzerdaten, sammlung, spielstand, warehouse


@pytest.fixture
def conn(tmp_path):
    verbindung = warehouse.verbindung(str(tmp_path / "dwh.db"))
    nutzerdaten.anhaengen(verbindung, tmp_path / "nutzer.db")
    yield verbindung
    verbindung.close()


@pytest.fixture
def nutzer(conn):
    return nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")


# --------------------------------------------------------------------------
# Laeufe
# --------------------------------------------------------------------------

def test_lauf_anlegen_prueft_edition_und_art(conn, nutzer) -> None:
    with pytest.raises(ValueError, match="Edition"):
        spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Test", "Pokemon Snap")
    with pytest.raises(ValueError, match="Art"):
        spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Test", "Platin", "hardcore")
    lauf_id = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Erster Lauf", "Platin")
    with pytest.raises(ValueError, match="existiert bereits"):
        spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Erster Lauf", "Perl")

    laeufe = spielstand.laeufe_lesen(conn, nutzer.nutzer_id)
    assert [lauf["lauf_id"] for lauf in laeufe] == [lauf_id]
    assert laeufe[0]["regeln"] == []
    assert laeufe[0]["art"] == "normal"


def test_nuzlocke_lauf_traegt_seine_regeln(conn, nutzer) -> None:
    spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Nuz", "Smaragd", "nuzlocke")
    lauf = spielstand.laeufe_lesen(conn, nutzer.nutzer_id, art="nuzlocke")[0]
    assert set(lauf["regeln"]) == set(spielstand.NUZLOCKE_REGELN)
    assert spielstand.laeufe_lesen(conn, nutzer.nutzer_id, art="normal") == []


def test_lauf_fortschreiben_und_loeschen(conn, nutzer) -> None:
    lauf_id = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Lauf", "Gold")
    spielstand.lauf_aktualisieren(conn, nutzer.nutzer_id, lauf_id, orden=8, status="abgeschlossen")
    lauf = spielstand.laeufe_lesen(conn, nutzer.nutzer_id)[0]
    assert (lauf["orden"], lauf["status"]) == (8, "abgeschlossen")
    with pytest.raises(ValueError, match="Orden"):
        spielstand.lauf_aktualisieren(conn, nutzer.nutzer_id, lauf_id, orden=17)

    spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 29", "sentret")
    spielstand.lauf_loeschen(conn, nutzer.nutzer_id, lauf_id)
    assert spielstand.laeufe_lesen(conn, nutzer.nutzer_id) == []
    assert conn.execute("SELECT COUNT(*) FROM nutzer.Spielstand_Begegnung").fetchone()[0] == 0


def test_fremder_lauf_ist_unerreichbar(conn, nutzer) -> None:
    anderer = nutzerdaten.anlegen(conn, "gast", "sicheres-passwort")
    lauf_id = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Lauf", "Gold")
    with pytest.raises(ValueError, match="nicht gefunden"):
        spielstand.begegnung_speichern(conn, anderer.nutzer_id, lauf_id, "Route 29", "sentret")
    spielstand.lauf_loeschen(conn, anderer.nutzer_id, lauf_id)
    assert len(spielstand.laeufe_lesen(conn, nutzer.nutzer_id)) == 1


# --------------------------------------------------------------------------
# Nuzlocke-Regeln
# --------------------------------------------------------------------------

def test_nuzlocke_erlaubt_je_ort_nur_die_erste_begegnung(conn, nutzer) -> None:
    lauf_id = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Nuz", "Platin", "nuzlocke")
    spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 201", "starly",
                                   spitzname="Pieps")
    with pytest.raises(ValueError, match="erste zaehlt"):
        spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 201", "bidoof",
                                       spitzname="Bibo")
    # Eine entkommene Begegnung belegt den Ort ebenfalls.
    spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 202", "shinx",
                                   status="entkommen")
    with pytest.raises(ValueError, match="erste zaehlt"):
        spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 202", "shinx",
                                       spitzname="Blitz")


def test_gewoehnlicher_durchgang_kennt_die_regel_nicht(conn, nutzer) -> None:
    lauf_id = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Normal", "Platin")
    spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 201", "starly")
    spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 201", "bidoof")
    assert len(spielstand.begegnungen_lesen(conn, nutzer.nutzer_id, lauf_id)) == 2


def test_nuzlocke_verlangt_spitznamen_beim_fang(conn, nutzer) -> None:
    lauf_id = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Nuz", "Platin", "nuzlocke")
    with pytest.raises(ValueError, match="Spitznamen"):
        spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 201", "starly")
    # Nicht gefangen: kein Spitzname noetig.
    spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 201", "starly",
                                   status="besiegt")


def test_gefallenes_pokemon_kehrt_im_nuzlocke_nicht_zurueck(conn, nutzer) -> None:
    lauf_id = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Nuz", "Platin", "nuzlocke")
    b = spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 201", "starly",
                                       spitzname="Pieps")
    spielstand.begegnung_status_setzen(conn, nutzer.nutzer_id, b, "tot")
    with pytest.raises(ValueError, match="kehrt nicht zurueck"):
        spielstand.begegnung_status_setzen(conn, nutzer.nutzer_id, b, "team")

    normal = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Normal", "Platin")
    b2 = spielstand.begegnung_speichern(conn, nutzer.nutzer_id, normal, "Route 201", "starly")
    spielstand.begegnung_status_setzen(conn, nutzer.nutzer_id, b2, "tot")
    spielstand.begegnung_status_setzen(conn, nutzer.nutzer_id, b2, "team")  # erlaubt


def test_team_hat_hoechstens_sechs_plaetze(conn, nutzer) -> None:
    lauf_id = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Normal", "Platin")
    for i in range(6):
        spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, f"Route {i}", "bidoof")
    with pytest.raises(ValueError, match="voll"):
        spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 7", "bidoof")
    box = spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, "Route 7", "bidoof",
                                         status="box")
    with pytest.raises(ValueError, match="voll"):
        spielstand.begegnung_status_setzen(conn, nutzer.nutzer_id, box, "team")


# --------------------------------------------------------------------------
# Auswertung
# --------------------------------------------------------------------------

def test_bilanz_zaehlt_je_status(conn, nutzer) -> None:
    lauf_id = spielstand.lauf_anlegen(conn, nutzer.nutzer_id, "Normal", "Platin")
    for ort, status in (("A", "team"), ("B", "team"), ("C", "box"), ("D", "tot"),
                        ("E", "entkommen"), ("A", "besiegt")):
        spielstand.begegnung_speichern(conn, nutzer.nutzer_id, lauf_id, ort, "bidoof",
                                       status=status)
    bilanz = spielstand.bilanz(spielstand.begegnungen_lesen(conn, nutzer.nutzer_id, lauf_id))
    assert bilanz == {"begegnungen": 6, "gefangen": 4, "team": 2, "box": 1,
                      "gefallen": 1, "verpasst": 2, "orte": 5}


def test_team_schwaechen_aus_der_typenlehre() -> None:
    """Zwei Wasser-Pokemon: Elektro trifft beide, niemand faengt es ab."""
    team = [{"typ1": "Water", "typ2": None}, {"typ1": "Water", "typ2": "Ground"}]
    schwaechen = {s["typ"]: s for s in spielstand.team_schwaechen(team)}
    assert schwaechen["Electric"]["schwach"] == 1     # Wasser/Boden ist immun
    assert schwaechen["Electric"]["widerstand"] == 1
    assert schwaechen["Grass"]["schwach"] == 2        # Pflanze trifft beide doppelt
    assert schwaechen["Grass"]["widerstand"] == 0
    assert schwaechen["Fire"]["widerstand"] == 2
    # Die Sortierung stellt die groesste Luecke nach vorn.
    assert spielstand.team_schwaechen(team)[0]["typ"] == "Grass"


# --------------------------------------------------------------------------
# Kartensammlung
# --------------------------------------------------------------------------

def test_karten_anlegen_lesen_loeschen(conn, nutzer) -> None:
    with pytest.raises(ValueError, match="Satz"):
        sammlung.karte_speichern(conn, nutzer.nutzer_id, {"name": "Glurak-ex"})
    with pytest.raises(ValueError, match="Seltenheit"):
        sammlung.karte_speichern(conn, nutzer.nutzer_id,
                                 {"satz": "OBF", "name": "Glurak-ex", "seltenheit": "Legendary"})
    karte_id = sammlung.karte_speichern(conn, nutzer.nutzer_id, {
        "satz": "Obsidianflammen", "nummer": "125/197", "name": "Glurak-ex",
        "slug": "charizard", "anzahl": 2, "seltenheit": "Double Rare"})
    karten = sammlung.karten_lesen(conn, nutzer.nutzer_id)
    assert karten[0]["anzahl"] == 2
    assert karten[0]["meta_decks"] is None  # keine Turnierdaten geladen

    assert sammlung.bilanz(karten) == {"karten": 1, "exemplare": 2, "saetze": 1, "im_meta": 0}
    sammlung.karte_loeschen(conn, nutzer.nutzer_id, karte_id)
    assert sammlung.karten_lesen(conn, nutzer.nutzer_id) == []


def test_karte_findet_ihr_meta_deck(conn, nutzer) -> None:
    """Die Bruecke Karte -> Pokemon -> Leit-Pokemon eines Turnierdecks."""
    from bi.etl import load, tcg
    from bi.etl.transform import zeilen_hash

    load.lade_pokemon_dimension(conn, [{
        "pokedex_id": 6, "slug": "charizard", "anzeigename": "Charizard",
        "spezies": "charizard", "generation": 1, "typ1": "Fire", "typ2": "Flying",
        "typ_kombination": "Fire / Flying", "hp": 78, "attack": 84, "defense": 78,
        "sp_attack": 109, "sp_defense": 85, "speed": 100,
        "stufe50_hp": 153, "stufe50_attack": 104, "stufe50_defense": 98,
        "stufe50_sp_attack": 129, "stufe50_sp_defense": 105, "stufe50_speed": 120,
        "basiswert_summe": 534, "offensiv_profil": "Speziell", "rolle": "Sweeper",
        "speed_klasse": "Schnell (100-119)", "resistenz_wert": 0.0,
        "row_hash": zeilen_hash({"slug": "charizard"}),
    }], "2026-07-01")
    tcg.lade_turnier(conn, {
        "turnier": {"id": "T1", "date": "2026-08-10"},
        "standings": [{"placing": 1, "country": "DE",
                       "deck": {"name": "Charizard ex", "icons": ["charizard"]}}],
    }, 1, {"charizard"})

    sammlung.karte_speichern(conn, nutzer.nutzer_id,
                             {"satz": "OBF", "name": "Glurak-ex", "slug": "charizard"})
    karte = sammlung.karten_lesen(conn, nutzer.nutzer_id)[0]
    assert karte["meta_decks"] == "Charizard ex"
    assert sammlung.bilanz([karte])["im_meta"] == 1
