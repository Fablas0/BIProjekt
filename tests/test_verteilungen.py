"""Tests der Pruefverteilungen.

Die Verteilungsfunktionen sind selbst umgesetzt, weil SciPy sich nicht ueber
alle Zielumgebungen des Projekts festlegen laesst (siehe
:mod:`bi.analytics.verteilungen`). Genau deshalb muessen sie gegen unabhaengige
Werte geprueft werden: hier gegen die kritischen Werte aus den ueblichen
Verteilungstabellen. Ohne diese Tests waere der Verzicht auf SciPy mit einer
ungeprueften Eigenentwicklung erkauft -- ein schlechter Tausch.
"""

from __future__ import annotations

import pytest

from bi.analytics.verteilungen import (
    chi_quadrat_ueberschreitung,
    normal_ueberschreitung,
    normal_zweiseitig,
    regularisierte_beta,
    t_zweiseitig,
)


# Kritische Werte der Standardnormalverteilung.
@pytest.mark.parametrize(("z", "p"), [
    (1.959964, 0.05),
    (2.575829, 0.01),
    (1.644854, 0.10),
    (3.290527, 0.001),
])
def test_normalverteilung_trifft_tabellenwerte(z: float, p: float) -> None:
    assert normal_zweiseitig(z) == pytest.approx(p, abs=1e-6)


def test_normalverteilung_ist_symmetrisch() -> None:
    assert normal_ueberschreitung(0.0) == pytest.approx(0.5)
    assert normal_ueberschreitung(1.5) + normal_ueberschreitung(-1.5) == pytest.approx(1.0)


# Kritische Werte der Chi-Quadrat-Verteilung zum Niveau 5 Prozent.
@pytest.mark.parametrize(("chi_quadrat", "freiheitsgrade"), [
    (3.84146, 1),
    (5.99146, 2),
    (7.81473, 3),
    (9.48773, 4),
    (18.30704, 10),
    (31.41043, 20),
])
def test_chi_quadrat_trifft_tabellenwerte(chi_quadrat: float, freiheitsgrade: int) -> None:
    assert chi_quadrat_ueberschreitung(chi_quadrat, freiheitsgrade) == pytest.approx(0.05, abs=1e-5)


def test_chi_quadrat_einprozentschranke() -> None:
    assert chi_quadrat_ueberschreitung(6.63490, 1) == pytest.approx(0.01, abs=1e-5)
    assert chi_quadrat_ueberschreitung(23.20925, 10) == pytest.approx(0.01, abs=1e-5)


def test_chi_quadrat_randfaelle() -> None:
    """Eine Pruefgroesse von null spricht in keiner Weise gegen die Nullhypothese."""
    assert chi_quadrat_ueberschreitung(0.0, 3) == 1.0
    assert chi_quadrat_ueberschreitung(-1.0, 3) == 1.0
    assert chi_quadrat_ueberschreitung(5.0, 0) == 1.0


# Kritische Werte der t-Verteilung zum zweiseitigen Niveau 5 Prozent.
@pytest.mark.parametrize(("t", "freiheitsgrade"), [
    (12.7062, 1),
    (2.77645, 4),
    (2.22814, 10),
    (2.08596, 20),
    (2.00856, 50),
    (1.98397, 100),
])
def test_t_verteilung_trifft_tabellenwerte(t: float, freiheitsgrade: int) -> None:
    assert t_zweiseitig(t, freiheitsgrade) == pytest.approx(0.05, abs=1e-5)


def test_t_verteilung_naehert_sich_der_normalverteilung() -> None:
    """Mit wachsenden Freiheitsgraden geht die t- in die Normalverteilung ueber."""
    assert t_zweiseitig(1.959964, 10**7) == pytest.approx(0.05, abs=1e-5)


def test_t_verteilung_randfaelle() -> None:
    assert t_zweiseitig(0.0, 10) == pytest.approx(1.0)
    assert t_zweiseitig(2.0, 0) == 1.0


def test_beta_funktion_erfuellt_die_symmetrie() -> None:
    """I_x(a,b) = 1 - I_{1-x}(b,a) -- die Identitaet, auf der die Umsetzung beruht."""
    for a, b, x in [(2.0, 3.0, 0.4), (0.5, 5.0, 0.2), (7.0, 0.5, 0.9)]:
        assert regularisierte_beta(a, b, x) == pytest.approx(
            1.0 - regularisierte_beta(b, a, 1.0 - x), abs=1e-12)


def test_beta_funktion_randwerte() -> None:
    assert regularisierte_beta(2.0, 3.0, 0.0) == 0.0
    assert regularisierte_beta(2.0, 3.0, 1.0) == 1.0
    # I_x(1,1) ist die Gleichverteilung.
    assert regularisierte_beta(1.0, 1.0, 0.37) == pytest.approx(0.37, abs=1e-12)
