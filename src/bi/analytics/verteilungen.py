"""Pruefverteilungen fuer die Hypothesenpruefung -- ohne SciPy.

Warum eine eigene Umsetzung
---------------------------
Jede Hypothese braucht zum Wert der Pruefgroesse eine Ueberschreitungs-
wahrscheinlichkeit. Der uebliche Weg dorthin ist SciPy. Das Projekt hat
SciPy jedoch bereits einmal wieder ausgebaut, und der Grund gilt unveraendert:
es gibt **keine** SciPy-Fassung, die alle Zielumgebungen des Projekts bedient.
Fuer Python 3.10 endet SciPy bei 1.15.3, fuer 3.14 beginnt es erst bei 1.16.1.
Eine nicht festlegbare Abhaengigkeit fuer drei Verteilungsfunktionen waere ein
schlechtes Geschaeft -- zumal Streamlit Community Cloud SciPy bei fehlendem Rad
aus dem Quelltext uebersetzt.

Umgesetzt sind daher genau die drei Verteilungen, die der Hypothesenkatalog
braucht:

======================  ===================================  ====================
Verteilung              Verwendung                           Verfahren
======================  ===================================  ====================
Standardnormal          Mann-Whitney-U, Wilcoxon (Approx.)   ``math.erfc``
Student-t               Spearman-Korrelation                  regularisierte
                                                              unvollstaendige
                                                              Betafunktion
Chi-Quadrat             Anpassungs- und Unabhaengigkeitstest  regularisierte
                                                              unvollstaendige
                                                              Gammafunktion
======================  ===================================  ====================

Die beiden unvollstaendigen Funktionen sind nach dem Standardverfahren
umgesetzt: Reihenentwicklung im schnell konvergierenden Bereich, Kettenbruch
sonst. Beide Verfahren sind ueber Tabellenwerte abgesichert (siehe
``tests/test_verteilungen.py``), damit der Verzicht auf SciPy nicht mit einer
ungeprueften Eigenentwicklung erkauft ist.

Alle Funktionen liefern **Ueberschreitungswahrscheinlichkeiten** (obere
Schwanzflaeche). Ob ein- oder zweiseitig geprueft wird, entscheidet der
aufrufende Test und ist dort dokumentiert.
"""

from __future__ import annotations

import math

# Genauigkeitsschranke und Abbruch der Iteration. 200 Schritte werden von den
# hier auftretenden Argumenten nie ausgeschoepft; die Schranke greift zuerst.
_EPSILON = 3.0e-12
_MAX_SCHRITTE = 300
# Kleinste darstellbare Zwischengroesse im Kettenbruch -- verhindert Division
# durch null, ohne das Ergebnis messbar zu verschieben.
_WINZIG = 1.0e-300


# --------------------------------------------------------------------------
# Standardnormalverteilung
# --------------------------------------------------------------------------

def normal_ueberschreitung(z: float) -> float:
    """Obere Schwanzflaeche der Standardnormalverteilung: P(Z > z).

    ``math.erfc`` ist in der Standardbibliothek numerisch stabil umgesetzt und
    genau das Komplement, das hier gebraucht wird -- eine eigene Naeherung waere
    ungenauer.
    """
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def normal_zweiseitig(z: float) -> float:
    """Zweiseitige Ueberschreitungswahrscheinlichkeit: P(|Z| > |z|)."""
    return min(1.0, 2.0 * normal_ueberschreitung(abs(z)))


# --------------------------------------------------------------------------
# Unvollstaendige Gammafunktion -> Chi-Quadrat
# --------------------------------------------------------------------------

def _gamma_reihe(a: float, x: float) -> float:
    """Regularisierte untere Gammafunktion P(a, x) ueber die Reihenentwicklung.

    Konvergiert schnell, solange ``x`` kleiner als ``a + 1`` ist.
    """
    summand = 1.0 / a
    summe = summand
    ap = a
    for _ in range(_MAX_SCHRITTE):
        ap += 1.0
        summand *= x / ap
        summe += summand
        if abs(summand) < abs(summe) * _EPSILON:
            break
    return summe * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_kettenbruch(a: float, x: float) -> float:
    """Regularisierte obere Gammafunktion Q(a, x) ueber den Kettenbruch.

    Der zur Reihenentwicklung komplementaere Bereich: ``x`` groesser als
    ``a + 1``. Umgesetzt im modifizierten Lentz-Verfahren.
    """
    b = x + 1.0 - a
    c = 1.0 / _WINZIG
    d = 1.0 / b
    h = d
    for i in range(1, _MAX_SCHRITTE):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _WINZIG:
            d = _WINZIG
        c = b + an / c
        if abs(c) < _WINZIG:
            c = _WINZIG
        d = 1.0 / d
        veraenderung = d * c
        h *= veraenderung
        if abs(veraenderung - 1.0) < _EPSILON:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))


def chi_quadrat_ueberschreitung(chi_quadrat: float, freiheitsgrade: int) -> float:
    """Obere Schwanzflaeche der Chi-Quadrat-Verteilung: P(X > chi_quadrat).

    Chi-Quadrat-Tests sind ihrer Konstruktion nach **einseitig**: nur grosse
    Werte der Pruefgroesse sprechen gegen die Nullhypothese, weil sie eine
    grosse Abweichung von den erwarteten Haeufigkeiten bedeuten.
    """
    if freiheitsgrade < 1:
        return 1.0
    if chi_quadrat <= 0:
        return 1.0

    a = freiheitsgrade / 2.0
    x = chi_quadrat / 2.0
    if x < a + 1.0:
        return max(0.0, min(1.0, 1.0 - _gamma_reihe(a, x)))
    return max(0.0, min(1.0, _gamma_kettenbruch(a, x)))


# --------------------------------------------------------------------------
# Unvollstaendige Betafunktion -> Student-t
# --------------------------------------------------------------------------

def _beta_kettenbruch(a: float, b: float, x: float) -> float:
    """Kettenbruchentwicklung fuer die regularisierte Betafunktion."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _WINZIG:
        d = _WINZIG
    d = 1.0 / d
    h = d

    for m in range(1, _MAX_SCHRITTE):
        m2 = 2 * m
        # Gerader Schritt.
        an = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + an * d
        if abs(d) < _WINZIG:
            d = _WINZIG
        c = 1.0 + an / c
        if abs(c) < _WINZIG:
            c = _WINZIG
        d = 1.0 / d
        h *= d * c
        # Ungerader Schritt.
        an = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + an * d
        if abs(d) < _WINZIG:
            d = _WINZIG
        c = 1.0 + an / c
        if abs(c) < _WINZIG:
            c = _WINZIG
        d = 1.0 / d
        veraenderung = d * c
        h *= veraenderung
        if abs(veraenderung - 1.0) < _EPSILON:
            break
    return h


def regularisierte_beta(a: float, b: float, x: float) -> float:
    """Regularisierte unvollstaendige Betafunktion I_x(a, b).

    Der Kettenbruch konvergiert nur fuer kleine ``x`` rasch; jenseits der
    Schwelle wird die Symmetrie ``I_x(a,b) = 1 - I_{1-x}(b,a)`` genutzt.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    vorfaktor = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return vorfaktor * _beta_kettenbruch(a, b, x) / a
    return 1.0 - vorfaktor * _beta_kettenbruch(b, a, 1.0 - x) / b


def t_zweiseitig(t: float, freiheitsgrade: float) -> float:
    """Zweiseitige Ueberschreitungswahrscheinlichkeit der t-Verteilung.

    Zweiseitig, weil die zugehoerigen Hypothesen ungerichtet formuliert sind:
    geprueft wird auf einen Zusammenhang, nicht auf dessen Vorzeichen. Eine
    einseitige Pruefung waere nur zulaessig, wenn die Richtung **vor** dem Blick
    in die Daten festgelegt worden waere.
    """
    if freiheitsgrade <= 0:
        return 1.0
    if math.isinf(t) or math.isnan(t):
        return 0.0 if math.isinf(t) else 1.0
    return regularisierte_beta(
        freiheitsgrade / 2.0, 0.5, freiheitsgrade / (freiheitsgrade + t * t)
    )
