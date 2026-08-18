"""Tests der TCG- und GO-Strecken.

Beide Quellen sind in dieser Umgebung nicht erreichbar; getestet wird mit
nachgebildeten Nutzlasten im dokumentierten Format der Quellen. Das ist kein
Notbehelf, sondern Absicht: die Tests muessen auch dann laufen, wenn die
Quelle gerade nicht antwortet -- sonst prueft die CI bei jedem Quellausfall
nichts mehr.
"""

from __future__ import annotations

import pytest

from bi import warehouse
from bi.etl import go, load, spielformarchiv, tcg
from bi.etl.transform import zeilen_hash


@pytest.fixture
def conn():
    verbindung = warehouse.verbindung(":memory:")
    yield verbindung
    verbindung.close()


def _pokemon(slug: str, anzeigename: str) -> dict:
    return {
        "pokedex_id": 184, "slug": slug, "anzeigename": anzeigename,
        "spezies": slug.split("-")[0], "generation": 2, "typ1": "Water", "typ2": "Fairy",
        "typ_kombination": "Water / Fairy", "hp": 100, "attack": 50, "defense": 80,
        "sp_attack": 60, "sp_defense": 80, "speed": 50,
        "stufe50_hp": 175, "stufe50_attack": 70, "stufe50_defense": 100,
        "stufe50_sp_attack": 80, "stufe50_sp_defense": 100, "stufe50_speed": 70,
        "basiswert_summe": 420, "offensiv_profil": "Gemischt", "rolle": "Wall",
        "speed_klasse": "Langsam (60-79)", "resistenz_wert": 0.9,
        "row_hash": zeilen_hash({"slug": slug}),
    }


# --------------------------------------------------------------------------
# GO: Namensharmonisierung
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("quell_id", "slug", "schatten"), [
    ("azumarill", "azumarill", False),
    ("stunfisk_galarian", "stunfisk-galar", False),
    ("ninetales_alolan", "ninetales-alola", False),
    ("giratina_altered", "giratina-altered", False),
    ("swampert_shadow", "swampert", True),
    ("samurott_hisuian", "samurott-hisui", False),
])
def test_go_bezeichner_werden_aufgeloest(quell_id, slug, schatten) -> None:
    """pvpoke schreibt Formen anders als die PokeAPI -- regelbasiert geloest."""
    assert go.quell_id_zu_slug(quell_id) == (slug, schatten)


GO_RANGLISTE = [
    {"speciesId": "azumarill", "speciesName": "Azumarill", "score": 92.5},
    {"speciesId": "stunfisk_galarian", "speciesName": "Stunfisk (Galarian)", "score": 95.1},
    {"speciesId": "swampert_shadow", "speciesName": "Swampert (Shadow)", "score": 88.0},
    {"speciesId": "unbekanntes_wesen", "speciesName": "???", "score": 70.0},
]


def test_go_stand_wird_geladen_und_rangiert(conn) -> None:
    """Der Rang entsteht aus dem Score -- absteigend, als gekennzeichnete Ableitung."""
    load.lade_pokemon_dimension(conn, [
        _pokemon("azumarill", "Azumarill"),
        _pokemon("stunfisk-galar", "Galar-Flunschlik"),
        _pokemon("swampert", "Sumpex")], "2026-07-01")

    geladen, befunde = go.lade_stand(conn, "2026-08-18", "great", GO_RANGLISTE, 1)
    assert geladen == 4

    zeilen = conn.execute(
        "SELECT quell_id, rang, score, ist_schatten, slug FROM V_GO_Meta ORDER BY rang"
    ).fetchall()
    assert [z["quell_id"] for z in zeilen] == [
        "stunfisk_galarian", "azumarill", "swampert_shadow", "unbekanntes_wesen"]
    assert zeilen[0]["rang"] == 1 and zeilen[0]["score"] == 95.1
    assert zeilen[2]["ist_schatten"] == 1
    assert zeilen[2]["slug"] == "swampert"  # Schattenform auf das Grund-Pokemon
    # Der nicht aufloesbare Bezeichner ist geladen, aber unverknuepft -- Befund.
    assert zeilen[3]["slug"] is None
    assert any("ohne Entsprechung" in b.meldung for b in befunde)


def test_go_laden_ist_idempotent(conn) -> None:
    load.lade_pokemon_dimension(conn, [_pokemon("azumarill", "Azumarill")], "2026-07-01")
    go.lade_stand(conn, "2026-08-18", "great", GO_RANGLISTE, 1)
    go.lade_stand(conn, "2026-08-18", "great", GO_RANGLISTE, 2)
    assert conn.execute("SELECT COUNT(*) FROM Fact_GO_Meta").fetchone()[0] == 4


def test_go_ligen_trennen_die_meta(conn) -> None:
    go.lade_stand(conn, "2026-08-18", "great", GO_RANGLISTE, 1)
    go.lade_stand(conn, "2026-08-18", "master", list(reversed(GO_RANGLISTE)), 1)
    ligen = conn.execute(
        "SELECT liga, COUNT(*) AS n FROM V_GO_Meta GROUP BY liga ORDER BY liga"
    ).fetchall()
    assert [(z["liga"], z["n"]) for z in ligen] == [("great", 4), ("master", 4)]


# --------------------------------------------------------------------------
# TCG: Turnierdaten
# --------------------------------------------------------------------------

def _turnier(turnier_id: str = "T1", datum: str = "2026-08-10") -> dict:
    return {
        "turnier": {"id": turnier_id, "date": f"{datum}T10:00:00Z",
                    "name": "Testturnier", "players": 128},
        "standings": [
            {"placing": 1, "country": "DE", "deck": {"name": "Charizard ex",
                                                     "icons": ["charizard"]}},
            {"placing": 2, "country": "DE", "deck": {"name": "Charizard ex",
                                                     "icons": ["charizard"]}},
            {"placing": 3, "country": "JP", "deck": {"name": "Lost Box",
                                                     "icons": ["comfey"]}},
            {"placing": 9, "country": "US", "deck": {"name": "Charizard ex",
                                                     "icons": ["charizard"]}},
            {"placing": 10, "country": "JP", "deck": {"name": "Lost Box",
                                                      "icons": ["comfey"]}},
            {"placing": 11, "country": "DE", "deck": None},  # unvollstaendig
        ],
    }


def test_tcg_turnier_wird_je_land_gezaehlt(conn) -> None:
    geladen, befunde = tcg.lade_turnier(conn, _turnier(), 1, set())
    assert geladen == 3  # (Charizard, DE), (Lost Box, JP), (Charizard, US)

    zeilen = conn.execute("""
        SELECT deck_name, iso2, region, spieler, top8 FROM V_TCG_Meta
        ORDER BY deck_name, iso2
    """).fetchall()
    nach_schluessel = {(z["deck_name"], z["iso2"]): z for z in zeilen}
    assert nach_schluessel[("Charizard ex", "DE")]["spieler"] == 2
    assert nach_schluessel[("Charizard ex", "DE")]["top8"] == 2
    assert nach_schluessel[("Charizard ex", "US")]["top8"] == 0
    assert nach_schluessel[("Charizard ex", "DE")]["region"] == "Europa"
    assert nach_schluessel[("Lost Box", "JP")]["region"] == "Asien-Pazifik"
    # Die unvollstaendige Zeile ist ein Befund erster Klasse, kein Absturz.
    assert any("ohne Deck- oder Landesangabe" in b.meldung for b in befunde)


def test_tcg_leitpokemon_verknuepft_die_spielformen(conn) -> None:
    """Das erste Deck-Symbol wird gegen die Pokemon-Dimension aufgeloest."""
    load.lade_pokemon_dimension(conn, [_pokemon("charizard", "Glurak")], "2026-07-01")
    tcg.lade_turnier(conn, _turnier(), 1, {"charizard"})
    zeile = conn.execute(
        "SELECT leit_slug FROM Dim_TCG_Deck WHERE anzeigename = 'Charizard ex'"
    ).fetchone()
    assert zeile["leit_slug"] == "charizard"


def test_tcg_ohne_schluessel_wird_uebersprungen_mit_befund(conn, monkeypatch) -> None:
    """Eine Zusatzquelle darf den Lauf nicht scheitern lassen -- aber ihr
    Fehlen muss im Protokoll stehen."""
    monkeypatch.setattr(tcg, "TCG_API_SCHLUESSEL", "")
    ergebnis = tcg.laden(conn)
    assert ergebnis["erfolgreich"]
    assert ergebnis.get("uebersprungen")
    befund = conn.execute("SELECT meldung FROM DQ_Befund").fetchone()
    assert "VGC_BI_TCG_SCHLUESSEL" in befund["meldung"]


def test_tcg_neuverarbeitung_zaehlt_nicht_doppelt(conn) -> None:
    """Der Fakt addiert je Turnier -- die Neuverarbeitung muss vorher leeren."""
    tcg.archiviere(conn, _turnier()["turnier"], _turnier()["standings"], 1)
    tcg.laden(conn, aus_archiv=True)
    tcg.laden(conn, aus_archiv=True)
    spieler = conn.execute(
        "SELECT spieler FROM V_TCG_Meta WHERE deck_name = 'Charizard ex' AND iso2 = 'DE'"
    ).fetchone()[0]
    assert spieler == 2


# --------------------------------------------------------------------------
# Dateiarchiv
# --------------------------------------------------------------------------

def test_spielformarchiv_ueberlebt_als_datei(conn, tmp_path) -> None:
    """Export -> frische Datenbank -> Import -> identischer Bestand."""
    go.archiviere(conn, "2026-08-18", "great", GO_RANGLISTE, 1)
    tcg.archiviere(conn, _turnier()["turnier"], _turnier()["standings"], 1)

    zaehler = spielformarchiv.exportiere(conn, tmp_path)
    assert zaehler["geschrieben"] == 2

    frisch = warehouse.verbindung(":memory:")
    eingelesen = spielformarchiv.importiere(frisch, tmp_path)
    assert eingelesen == {"go": 1, "tcg": 1}
    assert frisch.execute("SELECT COUNT(*) FROM Archiv_GO").fetchone()[0] == 1
    assert frisch.execute(
        "SELECT turnier_id FROM Archiv_TCG").fetchone()[0] == "T1"
    frisch.close()


def test_spielformarchiv_export_ist_deterministisch(conn, tmp_path) -> None:
    go.archiviere(conn, "2026-08-18", "great", GO_RANGLISTE, 1)
    spielformarchiv.exportiere(conn, tmp_path)
    zweiter = spielformarchiv.exportiere(conn, tmp_path)
    assert zweiter["geschrieben"] == 0  # unveraendert -> kein Neuschreiben


# --------------------------------------------------------------------------
# Anschluss an den Hypothesenkatalog
# --------------------------------------------------------------------------

def test_go_ligenhypothese_rechnet_auf_fixturedaten(conn) -> None:
    """H12 muss auf geladenen GO-Daten rechnen -- mit bekannter Wahrheit."""
    from bi.analytics import hypothesen

    rangliste_a = [{"speciesId": f"mon_{i}", "score": 50 + i} for i in range(25)]
    # Meisterliga: gleiche Reihenfolge, leicht gestoert -- starker Zusammenhang.
    rangliste_b = [{"speciesId": f"mon_{i}", "score": 50 + i + (3 if i % 5 == 0 else 0)}
                   for i in range(25)]
    go.lade_stand(conn, "2026-08-18", "great", rangliste_a, 1)
    go.lade_stand(conn, "2026-08-18", "master", rangliste_b, 1)

    ergebnis = hypothesen._pruefe_go_ligen(conn)
    assert ergebnis.effekt > 0.9
    assert ergebnis.n == 25


def test_laenderhypothese_rechnet_auf_fixturedaten(conn) -> None:
    """H11 mit eingebautem Regionsunterschied: Europa spielt Deck A, Asien Deck B."""
    from bi.analytics import hypothesen

    standings = []
    for i in range(60):
        standings.append({"placing": i + 1, "country": "DE",
                          "deck": {"name": "Deck A" if i < 50 else "Deck B",
                                   "icons": []}})
    for i in range(60):
        standings.append({"placing": i + 1, "country": "JP",
                          "deck": {"name": "Deck B" if i < 50 else "Deck A",
                                   "icons": []}})
    tcg.lade_turnier(conn, {"turnier": {"id": "T9", "date": "2026-08-10"},
                            "standings": standings}, 1, set())

    ergebnis = hypothesen._pruefe_laender(conn)
    assert ergebnis.p_wert < 0.001
    assert ergebnis.effekt > 0.5  # Cramers V: deutlicher Unterschied
