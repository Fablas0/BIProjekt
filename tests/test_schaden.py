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


def test_statusstufen_wirken_auf_die_kampfwerte() -> None:
    """+2 Angriff verdoppelt den Angriffswert: grund = floor(4400/50)+2 = 90.

    -1 Verteidigung entspricht x1,5 auf den Angriffserfolg ueber den Nenner:
    Verteidigung floor(100 * 2/3) = 66.
    """
    plus_zwei = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                         _angriff(stufe_angriff=2))
    assert (plus_zwei.minimum, plus_zwei.maximum) == (76, 90)

    gesenkt = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                       _angriff(stufe_verteidigung=-1))
    # floor(floor(22 * 100 * 100 / 66) / 50) + 2 = floor(3333/50) + 2 = 68.
    assert gesenkt.maximum == 68


def test_kritischer_treffer_ignoriert_schuetzende_stufen() -> None:
    """Krit ignoriert Bonusstufen der Verteidigung und Malusstufen des Angriffs."""
    ohne_krit = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                         _angriff(stufe_verteidigung=2))
    # Verteidigung 200: grund = floor(floor(22*100*100/200)/50)+2 = 24.
    assert ohne_krit.maximum == 24
    mit_krit = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                        _angriff(stufe_verteidigung=2, kritisch=True))
    # Stufe ignoriert, nur Krit 1,5: 46 -> 69.
    assert mit_krit.maximum == 69


def test_terrain_verstaerkt_nur_bodengebundene_angreifer() -> None:
    """Elektrofeld: Staerke 100 -> 130, grund = floor(2860/50)+2 = 59."""
    elektro = _angriff(typ="Electric", kategorie="special", terrain="Elektrofeld")
    geboostet = berechne(_kaempfer(), _kaempfer(typ1="Normal"), elektro)
    assert geboostet.maximum == 59

    fliegend = berechne(_kaempfer(typ1="Flying"), _kaempfer(typ1="Normal"), elektro)
    assert fliegend.maximum == 46  # nicht am Boden, kein Feldbonus

    ballon = berechne(_kaempfer(item_slug="airballoon"), _kaempfer(typ1="Normal"), elektro)
    assert ballon.maximum == 46  # Luftballon hebt vom Boden ab


def test_nebelfeld_daempft_drachen_gegen_bodenziele() -> None:
    """Staerke 100 -> 50, grund = floor(1100/50)+2 = 24."""
    drache = _angriff(typ="Dragon", kategorie="special", terrain="Nebelfeld")
    gedaempft = berechne(_kaempfer(), _kaempfer(typ1="Normal"), drache)
    assert gedaempft.maximum == 24
    fliegendes_ziel = berechne(_kaempfer(), _kaempfer(typ1="Flying"), drache)
    assert fliegendes_ziel.maximum == 46  # Ziel nicht am Boden


def test_helfende_hand_verstaerkt_die_staerke() -> None:
    """Staerke 100 -> 150, grund = floor(3300/50)+2 = 68."""
    spanne = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                      _angriff(helfende_hand=True))
    assert spanne.maximum == 68


def test_unheils_faehigkeiten_druecken_die_passende_seite() -> None:
    """Unheilsschwert: Verteidigung floor(100*3/4) = 75,
    grund = floor(floor(220000/75)/50)+2 = floor(2933/50)+2 = 60."""
    schwert = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                       _angriff(unheil=frozenset({"Unheilsschwert"})))
    assert schwert.maximum == 60
    # Das Schwert wirkt auf die physische Seite -- ein Spezialangriff bleibt
    # unberuehrt.
    speziell = berechne(_kaempfer(), _kaempfer(typ1="Grass"),
                        _angriff(kategorie="special",
                                 unheil=frozenset({"Unheilsschwert"})))
    assert speziell.maximum == 46


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


def test_kraftfaehigkeit_verdoppelt_nur_den_physischen_angriff() -> None:
    """Kraftkoloss: Angriff 100 -> 200, grund = floor(4400/50)+2 = 90."""
    physisch = berechne(_kaempfer(faehigkeit_slug="hugepower"),
                        _kaempfer(typ1="Grass"), _angriff())
    assert physisch.maximum == 90
    speziell = berechne(_kaempfer(faehigkeit_slug="hugepower"),
                        _kaempfer(typ1="Grass"), _angriff(kategorie="special"))
    assert speziell.maximum == 46


def test_anpassung_hebt_den_stab_auf_zwei() -> None:
    """STAB 2,0 statt 1,5: max 46 -> 92."""
    spanne = berechne(_kaempfer(typ1="Fighting", faehigkeit_slug="adaptability"),
                      _kaempfer(typ1="Grass"), _angriff())
    assert spanne.maximum == 92


def test_techniker_verstaerkt_nur_schwache_attacken() -> None:
    """Staerke 60 -> 90: grund = floor(1980/50)+2 = 41; Staerke 100 unveraendert."""
    schwach = berechne(_kaempfer(faehigkeit_slug="technician"),
                       _kaempfer(typ1="Grass"), _angriff(staerke=60))
    assert schwach.maximum == 41
    stark = berechne(_kaempfer(faehigkeit_slug="technician"),
                     _kaempfer(typ1="Grass"), _angriff())
    assert stark.maximum == 46


def test_facettenauge_verdoppelt_resistierten_schaden() -> None:
    """Kampf gegen Kaefer resistiert (23) -- Facettenauge holt es zurueck (46)."""
    ohne = berechne(_kaempfer(), _kaempfer(typ1="Bug"), _angriff())
    assert ohne.maximum == 23
    linse = berechne(_kaempfer(faehigkeit_slug="tintedlens"),
                     _kaempfer(typ1="Bug"), _angriff())
    assert linse.maximum == 46


def test_adrenalin_hebt_den_brandmalus_auf() -> None:
    """Adrenalin: Angriff x1,5 statt Brandhalbierung -- grund = floor(3300/50)+2 = 68."""
    mit_guts = berechne(_kaempfer(faehigkeit_slug="guts"),
                        _kaempfer(typ1="Grass"), _angriff(brand=True))
    assert mit_guts.maximum == 68
    ohne_guts = berechne(_kaempfer(), _kaempfer(typ1="Grass"), _angriff(brand=True))
    assert ohne_guts.maximum == 23


def test_eisflaechenschuppen_halbieren_speziellen_schaden() -> None:
    speziell = berechne(_kaempfer(), _kaempfer(typ1="Grass", faehigkeit_slug="icescales"),
                        _angriff(kategorie="special"))
    assert speziell.maximum == 23
    physisch = berechne(_kaempfer(), _kaempfer(typ1="Grass", faehigkeit_slug="icescales"),
                        _angriff())
    assert physisch.maximum == 46


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
