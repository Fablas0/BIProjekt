"""Tests der Statuswert-Berechnung nach den Regeln von Pokemon Champions.

Die Formel ist die Grundlage jeder Initiative-Aussage. Ein Rundungsfehler von
einem Punkt entscheidet im Kampf ueber die Zugreihenfolge -- deshalb wird gegen
Werte geprueft, die im Spiel als Referenz gelten.
"""

from __future__ import annotations

import pytest

from bi.stats import (
    DETERMINATIONSWERT,
    LANGSAME_WESEN,
    MAX_SP_JE_WERT,
    SCHNELLE_WESEN,
    SP_BUDGET,
    SZENARIEN,
    WESEN,
    alle_statuswerte,
    benoetigte_statuspunkte,
    handelt_zuerst,
    initiative_im_szenario,
    pruefe_statuspunkte,
    statuswert,
    stufe50_grundwerte,
    verteilung_kurzform,
    wesen_faktor,
)

# Basiswerte der Hauptreihe fuer Knackrack (Garchomp).
GARCHOMP = {"hp": 108, "attack": 130, "defense": 95,
            "sp_attack": 80, "sp_defense": 85, "speed": 102}


# --------------------------------------------------------------------------
# Wesen (im Spiel: Stat Alignment)
# --------------------------------------------------------------------------

def test_alle_25_wesen_hinterlegt() -> None:
    assert len(WESEN) == 25


def test_neutrale_wesen_veraendern_nichts() -> None:
    for wesen in ("Hardy", "Docile", "Serious", "Bashful", "Quirky"):
        assert WESEN[wesen] == (None, None)
        assert wesen_faktor(wesen, "speed") == 1.0


def test_jedes_nicht_neutrale_wesen_hebt_und_senkt_genau_einen_wert() -> None:
    for wesen, (angehoben, gesenkt) in WESEN.items():
        if angehoben is None:
            continue
        assert gesenkt is not None
        assert angehoben != gesenkt, f"{wesen} hebt und senkt denselben Wert"


def test_wesensfaktoren() -> None:
    """Jolly hebt die Initiative und senkt den Spezialangriff -- wie im Spiel."""
    assert wesen_faktor("Jolly", "speed") == 1.1
    assert wesen_faktor("Jolly", "sp_attack") == 0.9
    assert wesen_faktor("Jolly", "attack") == 1.0
    assert wesen_faktor("Adamant", "attack") == 1.1
    assert wesen_faktor("Adamant", "sp_attack") == 0.9


def test_initiative_wesensgruppen() -> None:
    assert {"Brave", "Relaxed", "Quiet", "Sassy"} == LANGSAME_WESEN
    assert {"Timid", "Hasty", "Jolly", "Naive"} == SCHNELLE_WESEN


# --------------------------------------------------------------------------
# Die im Spiel angezeigten Grundwerte
# --------------------------------------------------------------------------

def test_angezeigte_grundwerte_entsprechen_dem_spiel() -> None:
    """Champions zeigt als "Base stats" bereits die Werte auf Stufe 50.

    Fuer Knackrack zeigt das Spiel 183/150/115/100/105/122 -- diese Zahlen
    muessen sich aus den Basiswerten der Hauptreihe reproduzieren lassen.
    """
    assert stufe50_grundwerte(GARCHOMP) == {
        "hp": 183, "attack": 150, "defense": 115,
        "sp_attack": 100, "sp_defense": 105, "speed": 122,
    }


def test_grundwerte_sind_fuer_jeden_spieler_gleich() -> None:
    """Ohne Investition gibt es keine Unterschiede zwischen Spielern.

    Die Determinationswerte liegen fest bei 31; es wird weder gezuechtet noch
    trainiert.
    """
    assert DETERMINATIONSWERT == 31
    assert stufe50_grundwerte(GARCHOMP) == stufe50_grundwerte(dict(GARCHOMP))


# --------------------------------------------------------------------------
# Statusformel
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("bezeichnung", "basiswert", "sp", "wesen", "statusname", "erwartet"),
    [
        ("Knackrack volle Initiative", 102, 32, "Jolly", "speed", 169),
        ("Knackrack ohne Investition", 102, 0, "Hardy", "speed", 122),
        ("Dragapult volle Initiative", 142, 32, "Jolly", "speed", 213),
        ("Regieleki volle Initiative", 200, 32, "Timid", "speed", 277),
        ("Incineroar volle Kraftpunkte", 95, 32, "Adamant", "hp", 202),
        ("Knackrack voller Angriff", 130, 32, "Adamant", "attack", 200),
    ],
)
def test_statuswert_gegen_referenzwerte(bezeichnung: str, basiswert: int, sp: int,
                                        wesen: str, statusname: str,
                                        erwartet: int) -> None:
    assert statuswert(basiswert, sp, wesen, statusname) == erwartet, bezeichnung


def test_ein_statuspunkt_ergibt_genau_einen_punkt() -> None:
    """Die zentrale Regel des Champions-Systems.

    Anders als bei Fleisspunkten der Hauptreihe, wo erst je vier Punkte wirken,
    hebt hier jeder einzelne Statuspunkt den Endwert um genau eins.
    """
    ohne = statuswert(100, 0, "Hardy", "speed")
    for sp in range(1, MAX_SP_JE_WERT + 1):
        assert statuswert(100, sp, "Hardy", "speed") == ohne + sp


def test_kraftpunkte_ohne_wesenseinfluss() -> None:
    """Das Wesen wirkt sich nicht auf die Kraftpunkte aus."""
    assert (statuswert(100, 32, "Adamant", "hp")
            == statuswert(100, 32, "Timid", "hp")
            == statuswert(100, 32, "Hardy", "hp"))


def test_beispiel_aus_dem_spiel() -> None:
    """Knackrack mit Jolly und der Verteilung 2/32/0/0/0/32.

    Das ist die im Spiel meistgespielte Konfiguration: zwei Werte auf das
    Maximum von 32, die verbleibenden zwei Punkte auf einen dritten.
    """
    punkte = {"hp": 2, "attack": 32, "defense": 0,
              "sp_attack": 0, "sp_defense": 0, "speed": 32}
    assert pruefe_statuspunkte(punkte) == [], "Die Verteilung muss zulaessig sein."
    assert sum(punkte.values()) == SP_BUDGET

    werte = alle_statuswerte(GARCHOMP, punkte, "Jolly")
    assert werte["speed"] == 169     # 122 Grundwert + 32 Punkte, dann x1,1
    assert werte["attack"] == 182    # 150 Grundwert + 32 Punkte
    assert werte["hp"] == 185        # 183 Grundwert + 2 Punkte
    assert werte["sp_attack"] == 90  # 100 Grundwert, durch Jolly gesenkt


def test_kurzform_der_verteilung() -> None:
    punkte = {"hp": 2, "attack": 32, "defense": 0,
              "sp_attack": 0, "sp_defense": 0, "speed": 32}
    assert verteilung_kurzform("Jolly", punkte) == "Jolly 2/32/0/0/0/32"


# --------------------------------------------------------------------------
# Regelpruefung der Punkteverteilung
# --------------------------------------------------------------------------

def test_zulaessige_verteilungen_ohne_befund() -> None:
    assert pruefe_statuspunkte({"hp": 2, "attack": 32, "speed": 32}) == []
    assert pruefe_statuspunkte({"hp": 32, "defense": 32, "sp_defense": 2}) == []
    assert pruefe_statuspunkte({}) == []


def test_ueberschrittenes_einzelmaximum() -> None:
    """Kommt in den Quelldaten tatsaechlich vor: 200 Punkte in einem Wert."""
    befunde = pruefe_statuspunkte({"hp": 200})
    assert befunde
    assert "200" in befunde[0]
    assert str(MAX_SP_JE_WERT) in befunde[0]


def test_ueberschrittenes_gesamtbudget() -> None:
    """Ebenfalls belegt: Verteilungen mit Summen bis 130 statt hoechstens 66."""
    befunde = pruefe_statuspunkte(
        {"hp": 32, "attack": 32, "defense": 32, "speed": 32})   # Summe 128
    assert any("Gesamtbudget" in b for b in befunde)
    assert any(str(SP_BUDGET) in b for b in befunde)


def test_ausgeschoepftes_budget_ist_zulaessig() -> None:
    """Genau 66 Punkte sind erlaubt, ein Punkt mehr nicht."""
    assert pruefe_statuspunkte({"hp": 2, "attack": 32, "speed": 32}) == []
    assert pruefe_statuspunkte({"hp": 3, "attack": 32, "speed": 32}) != []


def test_negative_punkte_werden_gemeldet() -> None:
    assert any("negativ" in b for b in pruefe_statuspunkte({"speed": -4}))


# --------------------------------------------------------------------------
# Benchmark
# --------------------------------------------------------------------------

def test_benoetigte_statuspunkte() -> None:
    """Die Grundlage des Benchmark-Rechners."""
    # Basiswert 120 erreicht mit Timid schon ohne Investition 154; das Ziel muss
    # darueber liegen, damit ueberhaupt investiert werden muss.
    ziel = 170
    sp = benoetigte_statuspunkte(120, ziel, "Timid")
    assert sp is not None and sp > 0
    assert statuswert(120, sp, "Timid", "speed") >= ziel
    assert statuswert(120, sp - 1, "Timid", "speed") < ziel, (
        "Ein Punkt weniger darf das Ziel nicht mehr erreichen."
    )


def test_keine_punkte_noetig_wenn_ziel_bereits_erreicht() -> None:
    assert benoetigte_statuspunkte(120, 100, "Timid") == 0


def test_unerreichbares_ziel() -> None:
    """Das Maximum von 32 Punkten je Wert begrenzt, was erreichbar ist."""
    assert benoetigte_statuspunkte(50, 250, "Timid") is None


# --------------------------------------------------------------------------
# Szenarien
# --------------------------------------------------------------------------

def test_szenario_faktoren() -> None:
    assert initiative_im_szenario(100, "normal") == 100
    assert initiative_im_szenario(100, "rueckenwind") == 200
    assert initiative_im_szenario(100, "wahlschal") == 150
    assert initiative_im_szenario(100, "rueckenwind_schal") == 300
    assert initiative_im_szenario(100, "paralyse") == 50
    assert initiative_im_szenario(150, "eissturm") == 100


def test_szenario_rundet_ab() -> None:
    """Das Spiel rundet nach jeder Multiplikation ab."""
    assert initiative_im_szenario(101, "wahlschal") == 151   # 151.5 -> 151
    assert initiative_im_szenario(101, "eissturm") == 67     # 67.33 -> 67


def test_unbekanntes_szenario_faellt_auf_normal_zurueck() -> None:
    assert initiative_im_szenario(123, "gibtesnicht") == 123


def test_wirkrichtung_ist_hinterlegt() -> None:
    """Jedes Szenario muss angeben, welche Seite es betrifft.

    Ohne diese Angabe wuerde ein einseitiger Effekt auf beide Seiten angewandt
    und hoebe sich in der Auswertung auf.
    """
    for schluessel, szenario in SZENARIEN.items():
        assert szenario.wirkt_auf in ("eigene", "gegner", "feld"), schluessel

    assert SZENARIEN["rueckenwind"].wirkt_auf == "eigene"
    assert SZENARIEN["eissturm"].wirkt_auf == "gegner"
    assert SZENARIEN["bizarroraum"].wirkt_auf == "feld"


def test_reihenfolge_ohne_effekt() -> None:
    assert handelt_zuerst(200, 150) == "schneller"
    assert handelt_zuerst(150, 200) == "langsamer"
    assert handelt_zuerst(150, 150) == "gleichstand"


def test_bizarroraum_kehrt_reihenfolge_um() -> None:
    assert handelt_zuerst(200, 150, "bizarroraum") == "langsamer"
    assert handelt_zuerst(150, 200, "bizarroraum") == "schneller"


def test_gleichstand_bleibt_auch_im_bizarroraum_gleichstand() -> None:
    """Bei Gleichstand entscheidet der Zufall -- auch bei umgekehrter Reihenfolge."""
    assert handelt_zuerst(150, 150, "bizarroraum") == "gleichstand"


def test_bizarroraum_nur_ueber_das_wesen_erreichbar() -> None:
    """In Champions gibt es keinen anderen Weg, bewusst langsam zu sein.

    Die Determinationswerte liegen fest bei 31 und lassen sich nicht absenken --
    anders als in der Hauptreihe, wo dafuer null Determinationswerte gezuechtet
    werden. Es bleibt allein das senkende Wesen.
    """
    langsamst = statuswert(50, 0, "Brave", "speed")
    neutral = statuswert(50, 0, "Hardy", "speed")
    assert langsamst < neutral
    # Der Abstand entspricht genau dem Wesensfaktor von 0,9.
    assert langsamst == int(neutral * 0.9)
