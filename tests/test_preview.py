"""Tests des Team-Preview-Advisors.

Geprueft wird die Bewertungslogik mit synthetischen Kaempfern, deren Ausgang sich
fachlich eindeutig vorhersagen laesst -- damit ist belegbar, dass das Modell
nicht nur rechnet, sondern das Richtige rechnet.
"""

from __future__ import annotations

from math import comb

import pytest

from bi.analytics import preview
from bi.analytics.preview import Kaempfer


def _kaempfer(name: str, typ1: str, typ2: str | None = None, *,
              attack: int = 120, sp_attack: int = 80, speed: int = 100,
              attacken: list[tuple[str, str, str, int]] | None = None) -> Kaempfer:
    return Kaempfer(
        name=name, pokedex_id=1, typ1=typ1, typ2=typ2,
        attack=attack, sp_attack=sp_attack, speed=speed,
        attacken=attacken if attacken is not None else [],
    )


# --------------------------------------------------------------------------
# Offensivbewertung
# --------------------------------------------------------------------------

def test_sehr_effektive_attacke_schlaegt_neutrale() -> None:
    feuer = _kaempfer("Feuerangreifer", "Fire",
                      attacken=[("Flammenwurf", "Fire", "special", 90)],
                      sp_attack=150)
    pflanze = _kaempfer("Pflanzenziel", "Grass")
    wasser = _kaempfer("Wasserziel", "Water")

    # Feuer gegen Pflanze ist doppelt so wirksam wie gegen Wasser das Halbe.
    assert preview.offensivwert(feuer, pflanze) > preview.offensivwert(feuer, wasser)


def test_immunitaet_ergibt_keinen_druck() -> None:
    """Eine Attacke ohne Wirkung darf nicht in die Bewertung eingehen."""
    boden = _kaempfer("Bodenangreifer", "Ground",
                      attacken=[("Erdbeben", "Ground", "physical", 100)])
    flug = _kaempfer("Flugziel", "Flying")
    assert preview.offensivwert(boden, flug) == 0.0


def test_passende_angriffskategorie_wird_verwendet() -> None:
    """Eine physische Attacke nutzt den Angriffswert, keine spezielle."""
    physisch = _kaempfer("Physisch", "Normal", attack=180, sp_attack=40,
                         attacken=[("Ruckzuckhieb", "Normal", "physical", 80)])
    speziell = _kaempfer("Speziell", "Normal", attack=40, sp_attack=180,
                         attacken=[("Ruckzuckhieb", "Normal", "physical", 80)])
    ziel = _kaempfer("Ziel", "Water")

    assert preview.offensivwert(physisch, ziel) > preview.offensivwert(speziell, ziel)


def test_ohne_attackendaten_greift_die_ersatzabschaetzung() -> None:
    """Fehlende Attacken duerfen nicht zu einem Druck von null fuehren."""
    ohne = _kaempfer("Ohne Daten", "Normal", attack=150, attacken=[])
    ziel = _kaempfer("Ziel", "Water")
    assert preview.offensivwert(ohne, ziel) > 0


# --------------------------------------------------------------------------
# Paarungsbewertung
# --------------------------------------------------------------------------

def test_offensive_und_defensive_zaehlen_getrennt() -> None:
    """Der gegnerische Druck darf nicht doppelt in die Wertung eingehen."""
    a = _kaempfer("A", "Fire", attacken=[("Flammenwurf", "Fire", "special", 90)],
                  sp_attack=150)
    b = _kaempfer("B", "Grass", attacken=[("Rankenhieb", "Grass", "physical", 90)])

    offensive, defensive, _ = preview.bewerte_paarung(a, b)
    # Die Offensive misst ausschliesslich den selbst ausgeuebten Druck ...
    assert offensive == pytest.approx(preview.offensivwert(a, b))
    # ... die Defensive ausschliesslich den erlittenen.
    assert defensive == pytest.approx(-preview.offensivwert(b, a))


def test_initiativevorteil_wird_erkannt() -> None:
    schnell = _kaempfer("Schnell", "Normal", speed=150)
    langsam = _kaempfer("Langsam", "Normal", speed=50)

    _, _, ini_schnell = preview.bewerte_paarung(schnell, langsam)
    _, _, ini_langsam = preview.bewerte_paarung(langsam, schnell)

    assert ini_schnell > 0
    assert ini_langsam < 0


def test_gleichstand_ergibt_keinen_initiativevorteil() -> None:
    a = _kaempfer("A", "Normal", speed=100)
    b = _kaempfer("B", "Normal", speed=100)
    assert preview.bewerte_paarung(a, b)[2] == 0.0


def test_initiativevorteil_wiegt_bei_offensiver_ueberlegenheit_schwerer() -> None:
    """Nur wer Druck ausuebt, profitiert davon, zuerst zu handeln."""
    stark = _kaempfer("Stark", "Fire", speed=150, sp_attack=150,
                      attacken=[("Flammenwurf", "Fire", "special", 110)])
    schwach = _kaempfer("Schwach", "Grass", speed=50, attack=40,
                        attacken=[("Rankenhieb", "Grass", "physical", 35)])
    harmlos = _kaempfer("Harmlos", "Normal", speed=150, attack=40,
                        attacken=[("Tackle", "Normal", "physical", 35)])
    zaeh = _kaempfer("Zaeh", "Normal", speed=50, attack=40,
                     attacken=[("Tackle", "Normal", "physical", 35)])

    _, _, mit_druck = preview.bewerte_paarung(stark, schwach)
    _, _, ohne_druck = preview.bewerte_paarung(harmlos, zaeh)
    assert mit_druck > ohne_druck


# --------------------------------------------------------------------------
# Auswahlbewertung
# --------------------------------------------------------------------------

def _sechs(praefix: str, typ: str, **kwargs) -> list[Kaempfer]:
    return [_kaempfer(f"{praefix}{i}", typ, **kwargs) for i in range(1, 7)]


def test_anzahl_der_kombinationen_stimmt() -> None:
    """Vier aus sechs ergibt 15, drei aus sechs 20 Moeglichkeiten."""
    eigene = _sechs("E", "Fire")
    gegner = _sechs("G", "Grass")

    doppelt, paarungen = preview.bewerte_auswahlen(eigene, gegner, 4)
    assert len(doppelt) == comb(6, 4) == 15
    assert len(paarungen) == 15 * 15

    einzeln, _ = preview.bewerte_auswahlen(eigene, gegner, 3)
    assert len(einzeln) == comb(6, 3) == 20


def test_zu_kleines_team_liefert_kein_ergebnis() -> None:
    empfehlungen, paarungen = preview.bewerte_auswahlen(
        _sechs("E", "Fire")[:2], _sechs("G", "Grass"), 4)
    assert empfehlungen == []
    assert paarungen == []


def test_typenvorteil_setzt_sich_in_der_empfehlung_durch() -> None:
    """Gegen ein reines Pflanzen-Team muessen Feuer-Pokemon vorne liegen."""
    feuer = [_kaempfer(f"Feuer{i}", "Fire", sp_attack=150,
                       attacken=[("Flammenwurf", "Fire", "special", 90)])
             for i in range(1, 4)]
    wasser = [_kaempfer(f"Wasser{i}", "Water", sp_attack=150,
                        attacken=[("Aquawelle", "Water", "special", 90)])
              for i in range(1, 4)]
    gegner = [_kaempfer(f"Pflanze{i}", "Grass", attack=100,
                        attacken=[("Rankenhieb", "Grass", "physical", 90)])
              for i in range(1, 7)]

    empfehlungen, _ = preview.bewerte_auswahlen(feuer + wasser, gegner, 3)
    beste = empfehlungen[0].auswahl

    assert all(n.startswith("Feuer") for n in beste), (
        f"Erwartet wurden die drei Feuer-Pokemon, empfohlen wurde {beste}"
    )


def test_schlechteste_auswahl_ist_die_umgekehrte() -> None:
    feuer = [_kaempfer(f"Feuer{i}", "Fire", sp_attack=150,
                       attacken=[("Flammenwurf", "Fire", "special", 90)])
             for i in range(1, 4)]
    wasser = [_kaempfer(f"Wasser{i}", "Water", sp_attack=60,
                        attacken=[("Aquawelle", "Water", "special", 60)])
              for i in range(1, 4)]
    gegner = [_kaempfer(f"Pflanze{i}", "Grass", attack=120,
                        attacken=[("Rankenhieb", "Grass", "physical", 90)])
              for i in range(1, 7)]

    empfehlungen, _ = preview.bewerte_auswahlen(feuer + wasser, gegner, 3)
    assert all(n.startswith("Wasser") for n in empfehlungen[-1].auswahl)


def test_empfehlungen_sind_absteigend_sortiert() -> None:
    empfehlungen, _ = preview.bewerte_auswahlen(
        _sechs("E", "Fire"), _sechs("G", "Grass"), 4)
    werte = [e.gesamtwertung for e in empfehlungen]
    assert werte == sorted(werte, reverse=True)


def test_kennzahlen_einer_empfehlung_sind_stimmig() -> None:
    empfehlungen, _ = preview.bewerte_auswahlen(
        _sechs("E", "Fire"), _sechs("G", "Grass"), 4)
    e = empfehlungen[0]

    assert e.schlechtester_fall <= e.mittelwert <= e.bester_fall
    assert 0 <= e.gewinnquote <= 100
    assert len(e.beitraege) == 4
    assert len(e.riskanteste_gegnerauswahl) == 4


def test_risikoabschlag_bestraft_ausreisser() -> None:
    """Die Gesamtwertung liegt zwischen Mittelwert und schlechtestem Fall."""
    empfehlungen, _ = preview.bewerte_auswahlen(
        _sechs("E", "Fire"), _sechs("G", "Grass"), 4)
    for e in empfehlungen:
        assert min(e.mittelwert, e.schlechtester_fall) <= e.gesamtwertung
        assert e.gesamtwertung <= max(e.mittelwert, e.schlechtester_fall)


def test_riskanteste_gegnerauswahl_ist_die_schlechteste() -> None:
    eigene = _sechs("E", "Fire", sp_attack=140,
                    attacken=[("Flammenwurf", "Fire", "special", 90)])
    gegner = ([_kaempfer(f"Pflanze{i}", "Grass") for i in range(1, 4)]
              + [_kaempfer(f"Wasser{i}", "Water", attack=150,
                           attacken=[("Aquawelle", "Water", "physical", 110)])
                 for i in range(1, 4)])

    empfehlungen, paarungen = preview.bewerte_auswahlen(eigene, gegner, 3)
    beste = empfehlungen[0]

    matrix = preview.matchup_matrix(paarungen, beste.auswahl)
    schlechteste_zeile = matrix.iloc[0]["Gegnerische Auswahl"]
    assert schlechteste_zeile == " · ".join(beste.riskanteste_gegnerauswahl)


# --------------------------------------------------------------------------
# Aufbereitung
# --------------------------------------------------------------------------

def test_einzelduelle_decken_alle_paare_ab() -> None:
    eigene = _sechs("E", "Fire")[:3]
    gegner = _sechs("G", "Grass")[:4]
    duelle = preview.einzelduelle(eigene, gegner)
    assert len(duelle) == 12
    assert set(duelle.columns) >= {"Eigenes Pokemon", "Gegner", "Bewertung", "Schneller"}


def test_begruendung_nennt_traeger_und_risiko() -> None:
    eigene = _sechs("E", "Fire", sp_attack=140,
                    attacken=[("Flammenwurf", "Fire", "special", 90)])
    gegner = _sechs("G", "Grass")
    empfehlungen, _ = preview.bewerte_auswahlen(eigene, gegner, 4)

    texte = preview.begruendung(empfehlungen[0], eigene, gegner)
    verbunden = " ".join(texte)
    assert "traegt die Auswahl am staerksten" in verbunden
    assert "Initiative" in verbunden
    assert "Achte auf die gegnerische Auswahl" in verbunden


def test_begruendung_weist_auf_fehlende_attackendaten_hin() -> None:
    """Eine Bewertung ohne Attackendaten ist unsicherer -- das muss gesagt werden."""
    eigene = _sechs("E", "Fire", attacken=[])
    gegner = _sechs("G", "Grass")
    empfehlungen, _ = preview.bewerte_auswahlen(eigene, gegner, 4)

    verbunden = " ".join(preview.begruendung(empfehlungen[0], eigene, gegner))
    assert "keine belastbaren Attackendaten" in verbunden


def test_tabelle_enthaelt_alle_auswahlen() -> None:
    empfehlungen, _ = preview.bewerte_auswahlen(
        _sechs("E", "Fire"), _sechs("G", "Grass"), 4)
    tabelle = preview.empfehlungen_als_tabelle(empfehlungen)
    assert len(tabelle) == 15
    assert "Riskanteste Gegnerauswahl" in tabelle.columns


def test_leere_eingabe_bleibt_stabil() -> None:
    assert preview.empfehlungen_als_tabelle([]).empty
    assert preview.matchup_matrix([], ("A",)).empty
    assert preview.einzelduelle([], []).empty
