"""Tests der statistischen Pruefverfahren.

Geprueft wird gegen unabhaengige Rechenwege statt gegen selbst erzeugte Werte:

* die Rangkorrelation gegen die Produkt-Moment-Korrelation der Raenge, die
  pandas bildet (dieselbe Definition, andere Umsetzung),
* die Rangsummenverfahren gegen ihre algebraischen Identitaeten
  (``U_a + U_b = n1 * n2``, ``W+ + W- = n(n+1)/2``),
* Cliffs Delta gegen die vollstaendige paarweise Auszaehlung,
* der Chi-Quadrat-Test gegen eine von Hand gerechnete Kreuztabelle,
* Kruskal-Wallis gegen die direkt ausgeschriebene Formel.

Zusaetzlich wird geprueft, dass eine zu duenne Datenbasis eine Ausnahme
ausloest, statt still ein Ergebnis zu liefern -- eine Hypothese ohne Datenbasis
darf nicht als "nicht verworfen" durchgehen.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from bi.analytics.pruefverfahren import (
    DatenbasisFehlt,
    chi_quadrat_anpassung,
    chi_quadrat_unabhaengigkeit,
    holm_bonferroni,
    holm_schranken,
    kruskal_wallis,
    mann_whitney,
    raenge,
    spearman,
    wilcoxon,
)

# Eine feste, unregelmaessige Reihe -- kein Zufall, damit die Tests
# reproduzierbar bleiben.
REIHE_A = [12, 5, 33, 7, 21, 3, 44, 18, 9, 27, 15, 2, 38, 11, 25,
           6, 30, 14, 41, 8, 19, 23, 36, 4, 29]
REIHE_B = [14, 6, 30, 9, 19, 5, 40, 21, 7, 24, 17, 3, 35, 13, 28,
           8, 26, 16, 44, 10, 22, 20, 33, 2, 31]


def test_raenge_mitteln_bindungen() -> None:
    """Gleiche Werte teilen sich die von ihnen belegten Rangplaetze."""
    assert raenge([10, 20, 30]) == [1.0, 2.0, 3.0]
    assert raenge([10, 10, 30]) == [1.5, 1.5, 3.0]
    assert raenge([5, 5, 5, 5]) == [2.5, 2.5, 2.5, 2.5]
    # Die Rangsumme ist unabhaengig von Bindungen stets n(n+1)/2.
    assert sum(raenge([4, 4, 9, 1, 9, 9])) == pytest.approx(21.0)


def test_raenge_sind_reihenfolgeunabhaengig() -> None:
    werte = [3, 1, 3, 7, 1]
    zuordnung = dict(zip(werte, raenge(werte), strict=True))
    umgedreht = list(reversed(werte))
    zuordnung_umgedreht = dict(zip(umgedreht, raenge(umgedreht), strict=True))
    assert zuordnung == zuordnung_umgedreht


# --------------------------------------------------------------------------
# Spearman
# --------------------------------------------------------------------------

def test_spearman_entspricht_der_korrelation_der_raenge() -> None:
    """Gegenprobe mit pandas: Spearman ist Pearson auf den Raengen."""
    ergebnis = spearman(REIHE_A, REIHE_B)
    erwartet = pd.Series(REIHE_A).rank().corr(pd.Series(REIHE_B).rank())
    assert ergebnis.effekt == pytest.approx(erwartet, abs=1e-4)
    assert ergebnis.n == len(REIHE_A)


def test_spearman_bei_vollstaendiger_uebereinstimmung() -> None:
    reihe = list(range(20))
    ergebnis = spearman(reihe, [2 * x + 1 for x in reihe])
    assert ergebnis.effekt == 1.0
    assert ergebnis.p_wert == 0.0
    assert ergebnis.effekt_deutung == "gross"


def test_spearman_bei_umgekehrter_reihenfolge() -> None:
    reihe = list(range(25))
    ergebnis = spearman(reihe, list(reversed(reihe)))
    assert ergebnis.effekt == -1.0


def test_spearman_mit_bindungen_stimmt_mit_pandas_ueberein() -> None:
    """Bindungen sind der Normalfall -- 235 Pokemon teilen wenige Klassen."""
    a = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5] * 3
    b = [2, 1, 2, 3, 3, 4, 4, 5, 5, 5] * 3
    ergebnis = spearman(a, b)
    erwartet = pd.Series(a).rank().corr(pd.Series(b).rank())
    assert ergebnis.effekt == pytest.approx(erwartet, abs=1e-4)


def test_spearman_lehnt_zu_kleine_stichproben_ab() -> None:
    with pytest.raises(DatenbasisFehlt):
        spearman(list(range(10)), list(range(10)))


def test_spearman_lehnt_konstante_reihen_ab() -> None:
    with pytest.raises(DatenbasisFehlt):
        spearman(list(range(25)), [7] * 25)


# --------------------------------------------------------------------------
# Mann-Whitney
# --------------------------------------------------------------------------

def _cliffs_delta(a: list[float], b: list[float]) -> float:
    """Vollstaendige paarweise Auszaehlung als unabhaengige Gegenprobe."""
    groesser = sum(1 for x in a for y in b if x > y)
    kleiner = sum(1 for x in a for y in b if x < y)
    return (groesser - kleiner) / (len(a) * len(b))


def test_mann_whitney_identitaet_der_teilstatistiken() -> None:
    a, b = REIHE_A[:12], REIHE_B[:13]
    ergebnis = mann_whitney(a, b)
    # U ist das Minimum beider Teilstatistiken; ihre Summe ist n1 * n2.
    assert ergebnis.statistik <= len(a) * len(b) / 2
    assert ergebnis.effekt == pytest.approx(_cliffs_delta(a, b), abs=1e-4)


def test_mann_whitney_erkennt_deutlichen_unterschied() -> None:
    niedrig = list(range(10))
    hoch = list(range(50, 60))
    ergebnis = mann_whitney(niedrig, hoch)
    assert ergebnis.p_wert < 0.001
    assert ergebnis.effekt == pytest.approx(-1.0)
    assert ergebnis.effekt_deutung == "gross"


def test_mann_whitney_bei_gleicher_lage() -> None:
    """Zwei identische Gruppen duerfen keinen Unterschied anzeigen."""
    gleich = [3, 8, 1, 9, 4, 6, 2, 7, 5, 10]
    ergebnis = mann_whitney(gleich, list(gleich))
    assert ergebnis.p_wert > 0.9
    assert ergebnis.effekt == pytest.approx(0.0)


def test_mann_whitney_lehnt_kleine_gruppen_ab() -> None:
    with pytest.raises(DatenbasisFehlt):
        mann_whitney([1, 2, 3], [4, 5, 6])


# --------------------------------------------------------------------------
# Wilcoxon
# --------------------------------------------------------------------------

def test_wilcoxon_identitaet_der_rangsummen() -> None:
    paare = list(zip(REIHE_A[:20], REIHE_B[:20], strict=True))
    ergebnis = wilcoxon(paare)
    n = ergebnis.n
    assert (ergebnis.zusatz["W_plus"] + ergebnis.zusatz["W_minus"]
            == pytest.approx(n * (n + 1) / 2))


def test_wilcoxon_erkennt_gerichtete_verschiebung() -> None:
    """Jedes Paar verschiebt sich in dieselbe Richtung -- das kann kein Zufall sein."""
    paare = [(x, x + 3) for x in range(15)]
    ergebnis = wilcoxon(paare)
    assert ergebnis.p_wert < 0.01
    assert ergebnis.zusatz["W_minus"] == 0


def test_wilcoxon_schliesst_nulldifferenzen_aus() -> None:
    paare = [(5, 5)] * 8 + [(x, x + 2) for x in range(12)]
    ergebnis = wilcoxon(paare)
    assert ergebnis.n == 12


def test_wilcoxon_lehnt_zu_wenige_paare_ab() -> None:
    with pytest.raises(DatenbasisFehlt):
        wilcoxon([(1, 2), (3, 5), (4, 4)])


# --------------------------------------------------------------------------
# Kruskal-Wallis
# --------------------------------------------------------------------------

def test_kruskal_wallis_entspricht_der_ausgeschriebenen_formel() -> None:
    gruppen = [[27, 2, 4, 18, 7, 9], [20, 8, 14, 36, 21, 22], [34, 31, 3, 23, 30, 6]]
    ergebnis = kruskal_wallis(gruppen)

    # Unabhaengiger Rechenweg mit den Raengen aus pandas.
    alle = [w for g in gruppen for w in g]
    r = list(pd.Series(alle).rank())
    n = len(alle)
    h = 0.0
    position = 0
    for gruppe in gruppen:
        rangsumme = sum(r[position:position + len(gruppe)])
        h += rangsumme**2 / len(gruppe)
        position += len(gruppe)
    h = 12.0 / (n * (n + 1)) * h - 3 * (n + 1)

    assert ergebnis.statistik == pytest.approx(h, abs=1e-4)
    assert ergebnis.freiheitsgrade == 2


def test_kruskal_wallis_erkennt_getrennte_gruppen() -> None:
    ergebnis = kruskal_wallis([list(range(5)), list(range(20, 25)), list(range(40, 45))])
    assert ergebnis.p_wert < 0.01
    assert ergebnis.effekt > 0.5


def test_kruskal_wallis_verlangt_drei_gruppen() -> None:
    with pytest.raises(DatenbasisFehlt):
        kruskal_wallis([list(range(10)), list(range(10, 20))])


# --------------------------------------------------------------------------
# Chi-Quadrat
# --------------------------------------------------------------------------

def test_chi_quadrat_unabhaengigkeit_gegen_handrechnung() -> None:
    """Kreuztabelle mit von Hand gerechneten Erwartungswerten."""
    tabelle = [[30, 20], [20, 30]]
    # Erwartet je Zelle: 50 * 50 / 100 = 25. Chi^2 = 4 * (5^2 / 25) = 4.
    ergebnis = chi_quadrat_unabhaengigkeit(tabelle)
    assert ergebnis.statistik == pytest.approx(4.0)
    assert ergebnis.freiheitsgrade == 1
    assert ergebnis.p_wert == pytest.approx(0.0455, abs=1e-4)
    assert ergebnis.effekt == pytest.approx(0.2)


def test_chi_quadrat_unabhaengigkeit_bei_gleicher_verteilung() -> None:
    ergebnis = chi_quadrat_unabhaengigkeit([[25, 25], [50, 50]])
    assert ergebnis.statistik == pytest.approx(0.0)
    assert ergebnis.p_wert == 1.0


def test_chi_quadrat_lehnt_zu_duenne_besetzung_ab() -> None:
    """Die Faustregel verlangt erwartete Haeufigkeiten von mindestens fuenf."""
    with pytest.raises(DatenbasisFehlt):
        chi_quadrat_unabhaengigkeit([[1, 2], [2, 1]])


def test_chi_quadrat_anpassung_skaliert_die_erwartung() -> None:
    """Uebergeben werden duerfen auch Anteile -- sie werden hochgerechnet."""
    beobachtet = [30, 30, 40]
    aus_anteilen = chi_quadrat_anpassung(beobachtet, [1 / 3, 1 / 3, 1 / 3])
    aus_haeufigkeiten = chi_quadrat_anpassung(beobachtet, [100, 100, 100])
    assert aus_anteilen.statistik == pytest.approx(aus_haeufigkeiten.statistik)
    # Chi^2 = (30-33.33)^2/33.33 * 2 + (40-33.33)^2/33.33 = 2.0
    assert aus_anteilen.statistik == pytest.approx(2.0, abs=1e-6)


def test_chi_quadrat_anpassung_bei_perfekter_uebereinstimmung() -> None:
    ergebnis = chi_quadrat_anpassung([20, 20, 20], [20, 20, 20])
    assert ergebnis.statistik == pytest.approx(0.0)
    assert ergebnis.p_wert == 1.0


# --------------------------------------------------------------------------
# Holm-Bonferroni
# --------------------------------------------------------------------------

def test_holm_bonferroni_haelt_die_reihenfolge_ein() -> None:
    """Der kleinste p-Wert wird gegen alpha/m geprueft, der groesste gegen alpha."""
    p_werte = [0.001, 0.013, 0.04, 0.6]
    assert holm_schranken(p_werte, 0.05) == pytest.approx([0.0125, 0.05 / 3, 0.025, 0.05])
    assert holm_bonferroni(p_werte, 0.05) == [True, True, False, False]


def test_holm_bonferroni_bricht_nach_dem_ersten_scheitern_ab() -> None:
    """Ein einmal nicht verworfener Test sperrt alle groesseren p-Werte."""
    assert holm_bonferroni([0.5, 0.0001], 0.05) == [False, True]
    assert holm_bonferroni([0.03, 0.04, 0.045], 0.05) == [False, False, False]


def test_holm_bonferroni_ist_strenger_als_die_einzelpruefung() -> None:
    """Zwoelf Einzeltests zum Niveau 5 Prozent lieferten fast sicher einen Treffer."""
    p_werte = [0.04] * 12
    assert holm_bonferroni(p_werte, 0.05) == [False] * 12
    # Zum Vergleich: die unkorrigierte Pruefung haette alle zwoelf verworfen.
    assert all(p <= 0.05 for p in p_werte)
    # Die Wahrscheinlichkeit mindestens eines Zufallstreffers waere rund 46 Prozent.
    zufallstreffer = 1 - 0.95**12
    assert zufallstreffer == pytest.approx(0.46, abs=0.01)


def test_holm_bonferroni_bei_leerer_familie() -> None:
    assert holm_bonferroni([]) == []


def test_effektstaerken_deutung() -> None:
    ergebnis = spearman(list(range(25)), REIHE_B)
    assert ergebnis.effekt_deutung in {"vernachlaessigbar", "klein", "mittel", "gross"}
    assert math.isfinite(ergebnis.p_wert)
