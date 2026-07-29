"""Tests des Transformationsschritts.

Geprueft werden die vier Teilschritte Filterung, Harmonisierung, Aggregation und
Anreicherung -- jeweils mit synthetischen Daten, damit die Tests ohne Zugriff auf
die Quellsysteme laufen.
"""

from __future__ import annotations

import pytest

from bi.etl.mapping import loese_auf, normalisiere
from bi.etl.transform import (
    offensiv_profil,
    pruefe_gewichtssummen,
    rolle,
    speed_klasse,
    taktik_klasse,
    transformiere_pokemon,
    transformiere_usage_dump,
    zeilen_hash,
    zeitdimension,
)

BEKANNTE_SLUGS = {
    "incineroar", "landorus-incarnate", "urshifu-single-strike", "urshifu-rapid-strike",
    "ogerpon-cornerstone-mask", "ogerpon-hearthflame-mask", "iron-hands", "ho-oh",
    "indeedee-male", "indeedee-female", "calyrex-ice",
}


def _pokeapi_nutzlast(**abweichungen) -> dict:
    """Minimale, gueltige PokeAPI-Nutzlast fuer Tests."""
    basis = {
        "id": 727,
        "name": "incineroar",
        "species": {"name": "incineroar"},
        "types": [{"type": {"name": "fire"}}, {"type": {"name": "dark"}}],
        "stats": [
            {"stat": {"name": "hp"}, "base_stat": 95},
            {"stat": {"name": "attack"}, "base_stat": 115},
            {"stat": {"name": "defense"}, "base_stat": 90},
            {"stat": {"name": "special-attack"}, "base_stat": 80},
            {"stat": {"name": "special-defense"}, "base_stat": 90},
            {"stat": {"name": "speed"}, "base_stat": 60},
        ],
    }
    basis.update(abweichungen)
    return basis


# --------------------------------------------------------------------------
# Harmonisierung
# --------------------------------------------------------------------------

def test_normalisierung_von_sonderzeichen() -> None:
    assert normalisiere("Iron Hands") == "iron-hands"
    assert normalisiere("Ho-Oh") == "ho-oh"
    assert normalisiere("Farfetch'd") == "farfetchd"
    assert normalisiere("Mr. Mime") == "mr-mime"


def test_explizite_zuordnung_wird_bevorzugt() -> None:
    """Formen ohne Suffix muessen auf die richtige PokeAPI-Form zeigen."""
    assert loese_auf("Landorus", BEKANNTE_SLUGS) == "landorus-incarnate"
    assert loese_auf("Urshifu", BEKANNTE_SLUGS) == "urshifu-single-strike"
    assert loese_auf("Indeedee-F", BEKANNTE_SLUGS) == "indeedee-female"


def test_ogerpon_formen_bleiben_getrennt() -> None:
    """Die Maskenformen duerfen nicht auf dieselbe Entitaet zusammenfallen.

    Genau dieser Fehler entstuende bei einem Rueckfall auf den Namensteil vor dem
    ersten Bindestrich -- die drei Formen unterscheiden sich in Typ und Rolle.
    """
    ergebnisse = {
        loese_auf(name, BEKANNTE_SLUGS)
        for name in ("Ogerpon-Cornerstone", "Ogerpon-Hearthflame")
    }
    assert len(ergebnisse) == 2
    assert None not in ergebnisse


def test_unbekannter_bezeichner_wird_nicht_geraten() -> None:
    """Ohne eindeutige Zuordnung ist ``None`` das richtige Ergebnis."""
    assert loese_auf("Voelligunbekannt", BEKANNTE_SLUGS) is None
    # Kein stiller Rueckfall auf den Basisnamen:
    assert loese_auf("Ogerpon-Erfunden", BEKANNTE_SLUGS) is None


def test_direkte_treffer_ohne_zuordnungstabelle() -> None:
    assert loese_auf("Iron Hands", BEKANNTE_SLUGS) == "iron-hands"
    assert loese_auf("Incineroar", BEKANNTE_SLUGS) == "incineroar"


# --------------------------------------------------------------------------
# Filterung
# --------------------------------------------------------------------------

def test_gueltige_nutzlast_wird_uebernommen() -> None:
    satz, befund = transformiere_pokemon(_pokeapi_nutzlast(), {"incineroar": 7})
    assert befund is None
    assert satz["slug"] == "incineroar"
    assert satz["typ1"] == "Fire"
    assert satz["typ2"] == "Dark"
    assert satz["generation"] == 7
    assert satz["basiswert_summe"] == 530


def test_satz_ohne_typ_wird_abgewiesen() -> None:
    satz, befund = transformiere_pokemon(_pokeapi_nutzlast(types=[]), {})
    assert satz is None
    assert befund is not None
    assert befund.klasse == "Mangel 1. Klasse"
    assert befund.dimension == "Vollstaendigkeit"


def test_satz_mit_fehlenden_basiswerten_wird_abgewiesen() -> None:
    unvollstaendig = _pokeapi_nutzlast()
    unvollstaendig["stats"] = unvollstaendig["stats"][:3]
    satz, befund = transformiere_pokemon(unvollstaendig, {})
    assert satz is None
    assert "speed" in befund.meldung


# --------------------------------------------------------------------------
# Anreicherung
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("attack", "sp_attack", "erwartet"),
    [(150, 60, "Physisch"), (60, 150, "Speziell"), (100, 105, "Gemischt"), (0, 0, "Kein Angriff")],
)
def test_offensivprofil(attack: int, sp_attack: int, erwartet: str) -> None:
    assert offensiv_profil(attack, sp_attack) == erwartet


@pytest.mark.parametrize(
    ("speed", "erwartet"),
    [(135, "Sehr schnell (120+)"), (100, "Schnell (100-119)"), (85, "Mittel (80-99)"),
     (60, "Langsam (60-79)"), (30, "Sehr langsam (<60)")],
)
def test_speed_klasse(speed: int, erwartet: str) -> None:
    assert speed_klasse(speed) == erwartet


def test_rollenableitung() -> None:
    # Schnell und stark
    assert rolle(70, 130, 70, 60, 70, 120) == "Schneller Sweeper"
    # Langsam und stark -- der klassische Bizarroraum-Nutzniesser
    assert rolle(130, 140, 100, 50, 80, 50) == "Bizarroraum-Angreifer"
    # Defensiv
    assert rolle(120, 60, 120, 60, 120, 40) == "Defensive Wand"


def test_taktik_klasse_aus_namensliste() -> None:
    assert taktik_klasse("trickroom", "status", 0, "user") == "Bizarroraum"
    assert taktik_klasse("followme", "status", 2, "user") == "Umleitung"
    assert taktik_klasse("swordsdance", "status", 0, "user") == "Setup"


def test_taktik_klasse_aus_strukturmerkmalen() -> None:
    """Nicht namentlich hinterlegte Attacken werden ueber ihre Merkmale erkannt."""
    assert taktik_klasse("aquajet", "physical", 1, "selected-pokemon") == "Prioritaet"
    assert taktik_klasse("dazzlinggleam", "special", 0, "all-opponents") == "Flaechenschaden"
    assert taktik_klasse("flamethrower", "special", 0, "selected-pokemon") == "Offensiv"


def test_zeilen_hash_reagiert_auf_aenderungen() -> None:
    """Der Hash muss sich genau dann aendern, wenn sich ein Attribut aendert."""
    a = zeilen_hash((727, "Fire", "Dark", 95, 115, 90, 80, 90, 60))
    b = zeilen_hash((727, "Fire", "Dark", 95, 115, 90, 80, 90, 60))
    c = zeilen_hash((727, "Fire", "Dark", 95, 120, 90, 80, 90, 60))
    assert a == b
    assert a != c


def test_zeitdimension_konsolidierungspfad() -> None:
    satz = zeitdimension("2026-06")
    assert satz["jahr"] == 2026
    assert satz["monat"] == 6
    assert satz["quartal"] == 2
    assert satz["quartal_label"] == "Q2 2026"
    assert satz["zeit_sk"] == 202606


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def _smogon_eintrag(usage: float = 0.5, gewicht: float = 100.0) -> dict:
    """Erzeugt einen Smogon-Eintrag mit stimmigen Gewichtssummen."""
    return {
        "usage": usage,
        "Raw count": 1000,
        "Viability Ceiling": [500, 88, 78, 61],
        "Abilities": {"blaze": gewicht},
        "Items": {"choiceband": gewicht * 0.6, "lifeorb": gewicht * 0.4},
        "Moves": {"flareblitz": gewicht, "closecombat": gewicht,
                  "uturn": gewicht, "protect": gewicht},
        "Tera Types": {"fire": gewicht * 0.7, "grass": gewicht * 0.3},
        "Teammates": {"Landorus": gewicht * 3, "Iron Hands": gewicht * 2},
    }


def test_anteile_werden_auf_bezugsgewicht_normiert() -> None:
    """Ein Anteil von 100 Prozent bedeutet: kommt in jedem Set vor."""
    dump = {"info": {"number of battles": 5000}, "data": {"Incineroar": _smogon_eintrag()}}
    saetze, befunde, partien = transformiere_usage_dump(dump, BEKANNTE_SLUGS)

    assert partien == 5000
    assert len(saetze) == 1
    satz = saetze[0]

    assert satz.usage_rate == pytest.approx(50.0)
    # Alle vier Attacken haben das volle Bezugsgewicht -> je 100 Prozent.
    assert dict((s, a) for s, a, _ in satz.attacken)["flareblitz"] == pytest.approx(100.0)
    # Items summieren sich auf 100 Prozent.
    assert sum(a for _, a, _ in satz.items) == pytest.approx(100.0)
    # Partner werden ebenfalls auf das Bezugsgewicht bezogen.
    assert dict((s, a) for s, a, _ in satz.partner)["landorus-incarnate"] == pytest.approx(300.0)
    assert not [b for b in befunde if b.verworfen]


def test_rangvergabe_nach_nutzung() -> None:
    dump = {"info": {}, "data": {
        "Incineroar": _smogon_eintrag(usage=0.30),
        "Calyrex-Ice": _smogon_eintrag(usage=0.50),
        "Iron Hands": _smogon_eintrag(usage=0.10),
    }}
    saetze, _, _ = transformiere_usage_dump(dump, BEKANNTE_SLUGS)
    raenge = {s.slug: s.rang for s in saetze}
    assert raenge["calyrex-ice"] == 1
    assert raenge["incineroar"] == 2
    assert raenge["iron-hands"] == 3


def test_nicht_zuordenbarer_bezeichner_erzeugt_befund() -> None:
    dump = {"info": {}, "data": {"Voelligunbekannt": _smogon_eintrag()}}
    saetze, befunde, _ = transformiere_usage_dump(dump, BEKANNTE_SLUGS)
    assert saetze == []
    assert any(b.dimension == "Referenzielle Integritaet" and b.verworfen for b in befunde)


def test_unplausibler_nutzungsanteil_wird_verworfen() -> None:
    eintrag = _smogon_eintrag(usage=1.5)  # ergaebe 150 Prozent
    dump = {"info": {}, "data": {"Incineroar": eintrag}}
    saetze, befunde, _ = transformiere_usage_dump(dump, BEKANNTE_SLUGS)
    assert saetze == []
    assert any(b.dimension == "Wertebereich" for b in befunde)


def test_gewichtspruefung_erkennt_abweichung() -> None:
    """Eine zu kleine Attackensumme muss als Auffaelligkeit erkannt werden."""
    eintrag = _smogon_eintrag()
    eintrag["Moves"] = {"flareblitz": 100.0}   # nur 1x statt 4x das Bezugsgewicht
    abweichungen = pruefe_gewichtssummen(eintrag, 100.0)
    assert "Moves" in abweichungen
    assert abweichungen["Moves"] == pytest.approx(0.75)


def test_gewichtspruefung_bei_stimmigen_daten_leer() -> None:
    assert pruefe_gewichtssummen(_smogon_eintrag(), 100.0) == {}


def test_gewichtsauffaelligkeit_wird_verdichtet() -> None:
    """Auffaelligkeiten erscheinen als ein Befund je Merkmal, nicht je Satz."""
    daten = {}
    for i in range(20):
        eintrag = _smogon_eintrag()
        eintrag["Moves"] = {"flareblitz": 100.0}
        daten[f"Incineroar{i}" if i else "Incineroar"] = eintrag

    dump = {"info": {}, "data": daten}
    _, befunde, _ = transformiere_usage_dump(dump, BEKANNTE_SLUGS)

    plausibilitaet = [b for b in befunde if b.dimension == "Plausibilitaet"]
    assert len(plausibilitaet) == 1, "Es darf nur ein verdichteter Befund je Merkmal entstehen."
    assert not plausibilitaet[0].verworfen
