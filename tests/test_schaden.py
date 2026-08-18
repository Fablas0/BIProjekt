"""Tests des Schadensrechners.

Die Grundformel ist gegen von Hand gerechnete Werte geprueft -- die Rechnung
steht jeweils im Test, damit sie nachvollziehbar bleibt und nicht zirkulaer
gegen den eigenen Code prueft. Die Multiplikatoren sind einzeln getestet, weil
das Spiel zwischen ihnen abrundet und ihre Reihenfolge damit ergebniswirksam
ist.
"""

from __future__ import annotations

from bi.analytics.schaden import (
    Angriff,
    Kaempfer,
    berechne,
    treffer_bis_ko,
)


def _kaempfer(**abweichungen) -> Kaempfer:
    """Neutraler Kaempfer: alle Kampfwerte 100, einfacher Typ."""
    werte = {
        "name": "Testmon", "typ1": "Normal", "typ2": None,
        "hp": 175, "attack": 100, "defense": 100,
        "sp_attack": 100, "sp_defense": 100,
    }
    werte.update(abweichungen)
    return Kaempfer(**werte)


def _angriff(**abweichungen) -> Angriff:
    werte = {"name": "Testschlag", "typ": "Fighting", "kategorie": "physical",
             "staerke": 100}
    werte.update(abweichungen)
    return Angriff(**werte)


# --------------------------------------------------------------------------
# Grundformel
# --------------------------------------------------------------------------

def test_grundformel_gegen_handrechnung() -> None:
    """Stufe 50, Staerke 100, Angriff 100 gegen Verteidigung 100, neutral.

    grund = floor(floor(floor(2*50/5 + 2) * 100 * 100 / 100) / 50) + 2
          = floor(floor(22 * 100) / 50) + 2 = floor(2200/50) + 2 = 46
    Kein STAB (Normal-Pokemon, Kampf-Attacke), Effektivitaet 1:
    min = floor(46 * 85 / 100) = 39,  max = 46.
    """
    spanne = berechne(_kaempfer(), _kaempfer(typ1="Grass"), _angriff())
    assert (spanne.minimum, spanne.maximum) == (39, 46)


def test_stab_wirkt_mit_anderthalb() -> None:
    """Gleicher Typ: max 46 * 1.5 = 69; min 39 * 1.5 = 58.5 -> 58.

    Die Spiele runden bei exakt 0,5 **ab** (pokeRound) -- deshalb 58, nicht 59.
    """
    spanne = berechne(_kaempfer(typ1="Fighting"), _kaempfer(typ1="Grass"), _angriff())
    assert (spanne.minimum, spanne.maximum) == (58, 69)


def test_typeneffektivitaet_verdoppelt_und_halbiert() -> None:
    neutral = berechne(_kaempfer(), _kaempfer(typ1="Grass"), _angriff())
    sehr_effektiv = berechne(_kaempfer(), _kaempfer(typ1="Normal"), _angriff())
    resistiert = berechne(_kaempfer(), _kaempfer(typ1="Bug"), _angriff())
    assert sehr_effektiv.maximum == neutral.maximum * 2
    assert resistiert.maximum == neutral.maximum // 2
    assert sehr_effektiv.effektivitaet == 2.0
    assert resistiert.effektivitaet == 0.5


def test_immunitaet_ergibt_null() -> None:
    spanne = berechne(_kaempfer(), _kaempfer(typ1="Ghost"), _angriff())
    assert (spanne.minimum, spanne.maximum) == (0, 0)
    assert spanne.urteil == "Wirkt nicht."


def test_doppeltyp_multipliziert_beide_seiten() -> None:
    """Kampf gegen Eis/Gestein: 2 * 2 = 4."""
    spanne = berechne(_kaempfer(), _kaempfer(typ1="Ice", typ2="Rock"), _angriff())
    assert spanne.effektivitaet == 4.0


def test_spezialangriff_nutzt_die_spezialwerte() -> None:
    physisch = berechne(_kaempfer(attack=150), _kaempfer(typ1="Grass"), _angriff())
    speziell = berechne(_kaempfer(sp_attack=150), _kaempfer(typ1="Grass"),
                        _angriff(kategorie="special"))
    assert physisch.maximum == speziell.maximum


def test_mindestschaden_ist_eins() -> None:
    """Auch der schwaechste Angriff hinterlaesst einen Punkt."""
    spanne = berechne(_kaempfer(attack=10), _kaempfer(typ1="Steel", defense=250),
                      _angriff(staerke=10, typ="Bug"))
    assert spanne.minimum >= 1


# --------------------------------------------------------------------------
# Situationsfaktoren
# --------------------------------------------------------------------------

def test_flaechenattacke_gegen_mehrere_ziele() -> None:
    """0,75 auf den Grundschaden: 46 -> 34 (34.5 rundet halb ab),
    min floor(34 * 0.85) = 28."""
    spanne = berechne(_kaempfer(), _kaempfer(typ1="Grass"), _angriff(mehrfachziel=True))
    assert (spanne.minimum, spanne.maximum) == (28, 34)


def test_wetter_verstaerkt_und_schwaecht() -> None:
    wasser = _angriff(typ="Water", kategorie="special", staerke=100)
    neutral = berechne(_kaempfer(), _kaempfer(typ1="Normal"), wasser)
    regen = berechne(_kaempfer(), _kaempfer(typ1="Normal"),
                     _angriff(typ="Water", kategorie="special", staerke=100, wetter="Regen"))
    sonne = berechne(_kaempfer(), _kaempfer(typ1="Normal"),
                     _angriff(typ="Water", kategorie="special", staerke=100, wetter="Sonne"))
    assert regen.maximum > neutral.maximum > sonne.maximum


def test_brand_halbiert_nur_physisch() -> None:
    physisch = berechne(_kaempfer(), _kaempfer(typ1="Grass"), _angriff(brand=True))
    ohne = berechne(_kaempfer(), _kaempfer(typ1="Grass"), _angriff())
    speziell = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                        _angriff(kategorie="special", brand=True))
    speziell_ohne = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                             _angriff(kategorie="special"))
    assert physisch.maximum == 23  # 46 * 0.5
    assert physisch.maximum < ohne.maximum
    assert speziell.maximum == speziell_ohne.maximum


def test_schirm_daempft_aber_nicht_bei_kritischem_treffer() -> None:
    mit_schirm = berechne(_kaempfer(), _kaempfer(typ1="Grass"), _angriff(schirm=True))
    kritisch = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                        _angriff(schirm=True, kritisch=True))
    ohne = berechne(_kaempfer(), _kaempfer(typ1="Grass"), _angriff())
    assert mit_schirm.maximum < ohne.maximum
    assert kritisch.maximum > ohne.maximum  # 1,5 fuer kritisch, Schirm entfaellt


# --------------------------------------------------------------------------
# Items und Faehigkeiten
# --------------------------------------------------------------------------

def test_leben_orb_wirkt_auf_beide_kategorien() -> None:
    """1,3 auf den Endschaden: max 46 -> 60 (59.8 halbrundet auf)."""
    orb = berechne(_kaempfer(item_slug="lifeorb"), _kaempfer(typ1="Grass"), _angriff())
    assert orb.maximum == 60
    orb_speziell = berechne(_kaempfer(item_slug="lifeorb"), _kaempfer(typ1="Grass"),
                            _angriff(kategorie="special"))
    assert orb_speziell.maximum == 60


def test_wahlband_wirkt_nur_physisch() -> None:
    physisch = berechne(_kaempfer(item_slug="choiceband"), _kaempfer(typ1="Grass"), _angriff())
    speziell = berechne(_kaempfer(item_slug="choiceband"), _kaempfer(typ1="Grass"),
                        _angriff(kategorie="special"))
    assert physisch.maximum == 69   # 46 * 1.5
    assert speziell.maximum == 46   # unveraendert


def test_expertengurt_nur_bei_sehr_effektiv() -> None:
    neutral = berechne(_kaempfer(item_slug="expertbelt"), _kaempfer(typ1="Grass"), _angriff())
    effektiv = berechne(_kaempfer(item_slug="expertbelt"), _kaempfer(typ1="Normal"), _angriff())
    ohne = berechne(_kaempfer(), _kaempfer(typ1="Normal"), _angriff())
    assert neutral.maximum == 46
    assert effektiv.maximum > ohne.maximum


def test_faehigkeit_immunitaet_und_abschwaechung() -> None:
    feuer = _angriff(typ="Fire", kategorie="special")
    feuerfaenger = berechne(_kaempfer(), _kaempfer(faehigkeit_slug="flashfire"), feuer)
    assert feuerfaenger.maximum == 0
    speckschicht = berechne(_kaempfer(), _kaempfer(faehigkeit_slug="thickfat"), feuer)
    ohne = berechne(_kaempfer(), _kaempfer(), feuer)
    assert speckschicht.maximum < ohne.maximum
    schwebe = berechne(_kaempfer(), _kaempfer(faehigkeit_slug="levitate"),
                       _angriff(typ="Ground"))
    assert schwebe.maximum == 0


# --------------------------------------------------------------------------
# Urteil
# --------------------------------------------------------------------------

def test_ko_urteile() -> None:
    sicher = berechne(_kaempfer(attack=400), _kaempfer(typ1="Normal", hp=100), _angriff())
    assert sicher.sicherer_ko
    assert "Sicherer K.o." in sicher.urteil

    knapp = berechne(_kaempfer(), _kaempfer(typ1="Grass", hp=42), _angriff())
    assert not knapp.sicherer_ko and knapp.moeglicher_ko
    assert "hohem Wurf" in knapp.urteil

    chip = berechne(_kaempfer(attack=30), _kaempfer(typ1="Grass", hp=200), _angriff())
    assert "Chip" in chip.urteil


def test_treffer_bis_ko() -> None:
    spanne = berechne(_kaempfer(), _kaempfer(typ1="Grass", hp=100), _angriff())
    # max 46: ceil(100/46) = 3; min 39: ceil(100/39) = 3.
    assert treffer_bis_ko(spanne) == (3, 3)
    keiner = berechne(_kaempfer(), _kaempfer(typ1="Ghost"), _angriff())
    assert treffer_bis_ko(keiner) == (0, 0)


def test_prozentangaben() -> None:
    spanne = berechne(_kaempfer(), _kaempfer(typ1="Grass", hp=100), _angriff())
    assert spanne.minimum_prozent == 39.0
    assert spanne.maximum_prozent == 46.0
