"""Tests der Typen-Regelbasis.

Die Regelbasis ist Grundlage der gesamten defensiven und offensiven Auswertung.
Ein Fehler darin wuerde sich durch alle abgeleiteten Kennzahlen ziehen, ohne
offensichtlich zu sein -- deshalb wird sie strukturell geprueft.
"""

from __future__ import annotations

import pytest

from bi.config import ALLE_TYPEN
from bi.typechart import (
    VERTEIDIGUNG,
    defensivprofil,
    eingehender_multiplikator,
    resistenz_kennzahl,
)

GUELTIGE_FAKTOREN = {0, 0.25, 0.5, 1, 2, 4}


def test_alle_typen_vollstaendig() -> None:
    """Fuer jeden der 18 Typen muss ein Eintrag bestehen."""
    assert set(VERTEIDIGUNG) == set(ALLE_TYPEN)
    assert len(ALLE_TYPEN) == 18


def test_nur_gueltige_multiplikatoren() -> None:
    """Es duerfen nur die im Spiel vorkommenden Faktoren auftreten."""
    for verteidiger, eintraege in VERTEIDIGUNG.items():
        for angreifer, faktor in eintraege.items():
            assert angreifer in ALLE_TYPEN, f"Unbekannter Angriffstyp {angreifer}"
            assert faktor in {0, 0.5, 2}, (
                f"{angreifer} gegen {verteidiger}: {faktor} ist kein Einzeltyp-Faktor"
            )


def test_keine_neutralen_eintraege() -> None:
    """Neutrale Kombinationen gehoeren nicht in die Tabelle.

    Sie sind der Standardwert; ein expliziter Eintrag mit 1.0 waere redundant und
    ein Hinweis auf einen Fluechtigkeitsfehler.
    """
    for verteidiger, eintraege in VERTEIDIGUNG.items():
        assert 1 not in eintraege.values(), f"{verteidiger} enthaelt einen neutralen Eintrag"


@pytest.mark.parametrize(
    ("angriff", "typ1", "typ2", "erwartet"),
    [
        # Einzeltypen
        ("Fighting", "Normal", None, 2.0),
        ("Ghost", "Normal", None, 0.0),
        ("Water", "Fire", None, 2.0),
        ("Electric", "Ground", None, 0.0),
        ("Psychic", "Dark", None, 0.0),
        # Doppeltypen: multiplikative Verrechnung
        ("Ice", "Dragon", "Flying", 4.0),        # 2 x 2
        ("Ground", "Fire", "Steel", 4.0),        # 2 x 2
        ("Fighting", "Dark", "Steel", 4.0),      # 2 x 2
        ("Water", "Fire", "Ground", 4.0),        # 2 x 2
        ("Grass", "Water", "Ground", 4.0),       # 2 x 2
        ("Electric", "Water", "Flying", 4.0),    # 2 x 2
        # Aufhebung
        ("Grass", "Water", "Fire", 1.0),         # 2 x 0.5
        ("Fire", "Grass", "Water", 1.0),         # 2 x 0.5
        # Immunitaet schlaegt Schwaeche
        ("Ground", "Electric", "Flying", 0.0),   # 2 x 0
        ("Fighting", "Normal", "Ghost", 0.0),    # 2 x 0
        # Vierfache Resistenz
        ("Grass", "Fire", "Flying", 0.25),       # 0.5 x 0.5
        ("Dragon", "Steel", "Fairy", 0.0),       # 0.5 x 0
    ],
)
def test_multiplikatoren(angriff: str, typ1: str, typ2: str | None, erwartet: float) -> None:
    """Bekannte Typenkombinationen muessen korrekt verrechnet werden."""
    assert eingehender_multiplikator(angriff, typ1, typ2) == pytest.approx(erwartet)


def test_defensivprofil_deckt_alle_typen_ab() -> None:
    """Ein Profil enthaelt genau einen Eintrag je Angriffstyp."""
    profil = defensivprofil("Water", "Fighting")
    assert set(profil) == set(ALLE_TYPEN)
    assert all(f in GUELTIGE_FAKTOREN for f in profil.values())


def test_unbekannter_typ_ist_neutral() -> None:
    """Ein nicht hinterlegter Typ darf keine Ausnahme ausloesen."""
    assert eingehender_multiplikator("Fire", None, None) == 1.0
    assert eingehender_multiplikator("Fire", "Unbekannt", None) == 1.0


def test_resistenz_kennzahl_ordnet_richtig() -> None:
    """Defensiv starke Typen muessen besser bewertet werden als schwache."""
    # Stahl/Fee gilt als eine der besten defensiven Kombinationen,
    # Eis als eine der schwaechsten.
    assert resistenz_kennzahl("Steel", "Fairy") > resistenz_kennzahl("Ice", None)
    assert resistenz_kennzahl("Steel", "Fairy") > resistenz_kennzahl("Normal", None)


def test_symmetrie_immunitaeten() -> None:
    """Die drei klassischen Immunitaetspaare muessen wechselseitig stimmen."""
    assert eingehender_multiplikator("Normal", "Ghost") == 0.0
    assert eingehender_multiplikator("Ghost", "Normal") == 0.0
    assert eingehender_multiplikator("Fighting", "Ghost") == 0.0
    assert eingehender_multiplikator("Psychic", "Dark") == 0.0
    assert eingehender_multiplikator("Dragon", "Fairy") == 0.0
    assert eingehender_multiplikator("Poison", "Steel") == 0.0
    assert eingehender_multiplikator("Ground", "Flying") == 0.0
    assert eingehender_multiplikator("Electric", "Ground") == 0.0
