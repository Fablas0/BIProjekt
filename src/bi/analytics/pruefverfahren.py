"""Statistische Pruefverfahren fuer den Hypothesenkatalog.

Die Auswahl folgt demselben Grundsatz wie die Kennzahlen des Projekts: **das
Messniveau bestimmt das Verfahren.** Pokemon Champions liefert die Nutzung als
Rang, also ordinal. Verfahren, die Intervallskala und Normalverteilung
voraussetzen -- t-Test, Pearson-Korrelation, Varianzanalyse --, sind darauf
nicht anwendbar. Umgesetzt sind deshalb ausschliesslich verteilungsfreie
Verfahren:

=================================  ==================================  ==============
Verfahren                          Fragestellung                       Messniveau
=================================  ==================================  ==============
Spearman-Rangkorrelation           Zusammenhang zweier Reihen          ordinal
Mann-Whitney-U                     Lageunterschied zweier Gruppen      ordinal
Wilcoxon-Vorzeichen-Rang           Lageunterschied verbundener Paare   ordinal
Kruskal-Wallis-H                   Lageunterschied mehrerer Gruppen    ordinal
Chi-Quadrat (Unabhaengigkeit)      Zusammenhang zweier Merkmale        nominal
Chi-Quadrat (Anpassung)            Abweichung von einer Erwartung      nominal
=================================  ==================================  ==============

Zu jeder Pruefgroesse gehoert eine **Effektstaerke**. Ein p-Wert allein sagt
nur, ob ein Unterschied zufaellig erklaerbar ist -- bei 235 Pokemon und 16 Tagen
wird nahezu jeder noch so kleine Unterschied signifikant. Erst die
Effektstaerke sagt, ob er auch bedeutsam ist. Beides wird deshalb immer
gemeinsam ausgewiesen.

Die Verteilungsfunktionen liegen in :mod:`bi.analytics.verteilungen`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from .verteilungen import chi_quadrat_ueberschreitung, normal_zweiseitig, t_zweiseitig


class DatenbasisFehlt(ValueError):
    """Die Daten reichen fuer das Verfahren nicht aus.

    Eigene Ausnahme statt eines Rueckgabewerts ``None``: eine Hypothese ohne
    ausreichende Datenbasis darf nicht stillschweigend als "nicht verworfen"
    durchgehen. Sie wird ausdruecklich als ungeprueft ausgewiesen.
    """


@dataclass(frozen=True)
class Pruefgroesse:
    """Ergebnis eines statistischen Tests.

    ``p_wert`` ist die Wahrscheinlichkeit, die beobachtete oder eine noch
    extremere Auspraegung der Pruefgroesse zu erhalten, **wenn die
    Nullhypothese zutrifft**. Er ist ausdruecklich nicht die
    Wahrscheinlichkeit, dass die Nullhypothese zutrifft.
    """

    verfahren: str
    statistik_name: str
    statistik: float
    p_wert: float
    n: int
    effekt_name: str
    effekt: float
    freiheitsgrade: float | None = None
    zusatz: dict[str, float] = field(default_factory=dict)

    @property
    def effekt_deutung(self) -> str:
        """Einordnung der Effektstaerke nach den ueblichen Konventionen."""
        return deutung(self.effekt_name, self.effekt)


# Schwellen nach Cohen. Sie sind Konvention, keine Naturkonstante -- deshalb
# stehen sie hier sichtbar und nicht verstreut im Code.
_SCHWELLEN = {
    "Spearman rho": (0.1, 0.3, 0.5),
    "r (Z/Wurzel N)": (0.1, 0.3, 0.5),
    "Cliffs delta": (0.147, 0.33, 0.474),
    "Cramers V": (0.1, 0.3, 0.5),
    "eta^2": (0.01, 0.06, 0.14),
}


def deutung(effekt_name: str, wert: float) -> str:
    """Verbale Einordnung einer Effektstaerke."""
    schwellen = _SCHWELLEN.get(effekt_name)
    if schwellen is None:
        return "-"
    betrag = abs(wert)
    klein, mittel, gross = schwellen
    if betrag < klein:
        return "vernachlaessigbar"
    if betrag < mittel:
        return "klein"
    if betrag < gross:
        return "mittel"
    return "gross"


# --------------------------------------------------------------------------
# Rangbildung
# --------------------------------------------------------------------------

def raenge(werte: Sequence[float]) -> list[float]:
    """Mittlere Raenge mit Bindungsausgleich.

    Bindungen -- gleiche Werte -- erhalten den Mittelwert der von ihnen
    belegten Rangplaetze. Ohne diesen Ausgleich haengt das Ergebnis von der
    Eingabereihenfolge ab, und genau das darf ein Rangverfahren nicht.
    """
    sortiert = sorted(range(len(werte)), key=lambda i: werte[i])
    ergebnis = [0.0] * len(werte)
    i = 0
    while i < len(sortiert):
        j = i
        while j + 1 < len(sortiert) and werte[sortiert[j + 1]] == werte[sortiert[i]]:
            j += 1
        mittlerer_rang = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ergebnis[sortiert[k]] = mittlerer_rang
        i = j + 1
    return ergebnis


def _bindungskorrektur(werte: Sequence[float]) -> float:
    """Summe ``t^3 - t`` ueber alle Bindungsgruppen.

    Geht in die Varianz der Rangsummen ein: Bindungen verringern die Streuung
    der Raenge, ohne Korrektur waere der Test zu liberal.
    """
    haeufigkeit: dict[float, int] = {}
    for wert in werte:
        haeufigkeit[wert] = haeufigkeit.get(wert, 0) + 1
    return sum(t**3 - t for t in haeufigkeit.values() if t > 1)


# --------------------------------------------------------------------------
# Zusammenhangsmasse
# --------------------------------------------------------------------------

def spearman(x: Sequence[float], y: Sequence[float]) -> Pruefgroesse:
    """Spearman-Rangkorrelation samt Signifikanzpruefung.

    Berechnet als Produkt-Moment-Korrelation der Raenge -- die Definition, die
    auch bei Bindungen gilt. Die verbreitete Kurzformel ueber die Rangdifferenzen
    setzt Bindungsfreiheit voraus und ist hier deshalb nicht verwendbar: 235
    Pokemon teilen sich wenige Speed-Klassen, Bindungen sind der Normalfall.

    Die Signifikanz wird ueber die t-Approximation geprueft
    (``t = rho * Wurzel((n-2)/(1-rho^2))`` mit ``n-2`` Freiheitsgraden). Sie ist
    ab etwa 20 Beobachtungen ausreichend genau; darunter wird die Pruefung
    abgelehnt, statt einen scheingenauen Wert auszuweisen.
    """
    if len(x) != len(y):
        raise DatenbasisFehlt("Beide Reihen muessen gleich lang sein.")
    n = len(x)
    if n < 20:
        raise DatenbasisFehlt(
            f"Fuer die t-Approximation der Rangkorrelation sind mindestens 20 "
            f"Beobachtungen noetig, vorhanden sind {n}.")

    rx, ry = raenge(x), raenge(y)
    mx, my = sum(rx) / n, sum(ry) / n
    zaehler = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    nenner = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    if nenner == 0:
        raise DatenbasisFehlt("Mindestens eine Reihe ist konstant -- keine Rangfolge.")

    rho = zaehler / nenner
    # Bei vollstaendiger Uebereinstimmung ist die Pruefgroesse nicht definiert;
    # der Zusammenhang ist dann so deutlich, wie er sein kann.
    if abs(rho) >= 1.0:
        p_wert = 0.0
        t = math.inf
    else:
        t = rho * math.sqrt((n - 2) / (1 - rho**2))
        p_wert = t_zweiseitig(t, n - 2)

    return Pruefgroesse(
        verfahren="Spearman-Rangkorrelation",
        statistik_name="t", statistik=round(t, 4) if math.isfinite(t) else t,
        p_wert=p_wert, n=n, freiheitsgrade=n - 2,
        effekt_name="Spearman rho", effekt=round(rho, 4),
    )


# --------------------------------------------------------------------------
# Lagevergleiche
# --------------------------------------------------------------------------

def mann_whitney(a: Sequence[float], b: Sequence[float]) -> Pruefgroesse:
    """Mann-Whitney-U fuer zwei unabhaengige Stichproben.

    Prueft, ob die Werte der einen Gruppe systematisch groesser sind als die der
    anderen -- das verteilungsfreie Gegenstueck zum t-Test fuer unabhaengige
    Stichproben. Die Pruefung erfolgt ueber die Normalapproximation mit
    Stetigkeitskorrektur und Bindungsausgleich; ab je acht Beobachtungen je
    Gruppe ist sie hinreichend genau.

    Als Effektstaerke wird Cliffs Delta ausgewiesen: der Anteil der Paare, in
    denen die eine Gruppe die andere uebertrifft, abzueglich des umgekehrten
    Anteils. Anders als die Differenz der Mittelwerte setzt es kein
    Intervallskalenniveau voraus.
    """
    n1, n2 = len(a), len(b)
    if n1 < 8 or n2 < 8:
        raise DatenbasisFehlt(
            f"Beide Gruppen brauchen mindestens 8 Beobachtungen "
            f"(vorhanden: {n1} und {n2}).")

    gemeinsam = list(a) + list(b)
    r = raenge(gemeinsam)
    rangsumme_a = sum(r[:n1])

    u_a = rangsumme_a - n1 * (n1 + 1) / 2.0
    u_b = n1 * n2 - u_a
    u = min(u_a, u_b)

    mittelwert = n1 * n2 / 2.0
    n = n1 + n2
    korrektur = _bindungskorrektur(gemeinsam)
    varianz = (n1 * n2 / 12.0) * ((n + 1) - korrektur / (n * (n - 1)))
    if varianz <= 0:
        raise DatenbasisFehlt("Alle Werte sind gleich -- kein Lageunterschied pruefbar.")

    # Stetigkeitskorrektur: die diskrete Pruefgroesse wird durch eine stetige
    # Verteilung angenaehert, ein halber Schritt gleicht das aus.
    z = (abs(u_a - mittelwert) - 0.5) / math.sqrt(varianz)
    p_wert = normal_zweiseitig(z)

    delta = (u_a - u_b) / (n1 * n2)

    return Pruefgroesse(
        verfahren="Mann-Whitney-U-Test",
        statistik_name="U", statistik=round(u, 2), p_wert=p_wert, n=n,
        effekt_name="Cliffs delta", effekt=round(delta, 4),
        zusatz={"z": round(z, 4), "n_gruppe_1": n1, "n_gruppe_2": n2},
    )


def wilcoxon(paare: Sequence[tuple[float, float]]) -> Pruefgroesse:
    """Wilcoxon-Vorzeichen-Rang-Test fuer verbundene Stichproben.

    Verbunden heisst hier: dasselbe Pokemon in zwei Auspraegungen -- etwa an
    zwei Tagen oder in zwei Kampfformaten. Der Test nutzt diese Paarung und ist
    dadurch trennschaerfer als ein Vergleich unabhaengiger Gruppen.

    Paare ohne Differenz tragen keine Information ueber die Richtung und werden
    ausgeschlossen (Verfahren nach Wilcoxon); die Fallzahl sinkt entsprechend.
    """
    differenzen = [b - a for a, b in paare if b != a]
    n = len(differenzen)
    if n < 10:
        raise DatenbasisFehlt(
            f"Nach Ausschluss der Nulldifferenzen bleiben {n} Paare; "
            f"fuer die Normalapproximation sind mindestens 10 noetig.")

    betraege = [abs(d) for d in differenzen]
    r = raenge(betraege)
    w_plus = sum(rang for rang, d in zip(r, differenzen, strict=True) if d > 0)
    w_minus = sum(rang for rang, d in zip(r, differenzen, strict=True) if d < 0)
    w = min(w_plus, w_minus)

    mittelwert = n * (n + 1) / 4.0
    varianz = n * (n + 1) * (2 * n + 1) / 24.0 - _bindungskorrektur(betraege) / 48.0
    if varianz <= 0:
        raise DatenbasisFehlt("Keine Streuung in den Differenzen.")

    z = (abs(w_plus - mittelwert) - 0.5) / math.sqrt(varianz)
    p_wert = normal_zweiseitig(z)

    return Pruefgroesse(
        verfahren="Wilcoxon-Vorzeichen-Rang-Test",
        statistik_name="W", statistik=round(w, 2), p_wert=p_wert, n=n,
        effekt_name="r (Z/Wurzel N)", effekt=round(z / math.sqrt(n), 4),
        zusatz={"z": round(z, 4), "W_plus": round(w_plus, 2), "W_minus": round(w_minus, 2)},
    )


def kruskal_wallis(gruppen: Sequence[Sequence[float]]) -> Pruefgroesse:
    """Kruskal-Wallis-H fuer mehr als zwei unabhaengige Gruppen.

    Die Verallgemeinerung des Mann-Whitney-Tests. Sie wird gebraucht, wo mehr
    als zwei Auspraegungen zu vergleichen sind -- etwa mehrere Sprachmaerkte des
    Sammelkartenspiels oder mehrere Ligen von Pokemon GO. Einzelvergleiche
    stattdessen paarweise zu rechnen wuerde die Zahl der Tests und damit die
    Wahrscheinlichkeit eines Zufallstreffers vervielfachen.

    Als Effektstaerke dient Eta-Quadrat: der Anteil der Rangvarianz, den die
    Gruppenzugehoerigkeit erklaert.
    """
    gefiltert = [list(g) for g in gruppen if len(g) > 0]
    if len(gefiltert) < 3:
        raise DatenbasisFehlt("Fuer den Kruskal-Wallis-Test sind mindestens drei "
                              "besetzte Gruppen noetig.")
    n = sum(len(g) for g in gefiltert)
    if n < 15:
        raise DatenbasisFehlt(f"Zu wenige Beobachtungen insgesamt ({n}).")

    gemeinsam = [wert for gruppe in gefiltert for wert in gruppe]
    r = raenge(gemeinsam)

    h = 0.0
    position = 0
    for gruppe in gefiltert:
        rangsumme = sum(r[position:position + len(gruppe)])
        h += rangsumme**2 / len(gruppe)
        position += len(gruppe)
    h = 12.0 / (n * (n + 1)) * h - 3 * (n + 1)

    korrektur = 1 - _bindungskorrektur(gemeinsam) / (n**3 - n)
    if korrektur > 0:
        h /= korrektur

    freiheitsgrade = len(gefiltert) - 1
    p_wert = chi_quadrat_ueberschreitung(h, freiheitsgrade)
    eta_quadrat = max(0.0, (h - freiheitsgrade + 1) / (n - freiheitsgrade))

    return Pruefgroesse(
        verfahren="Kruskal-Wallis-H-Test",
        statistik_name="H", statistik=round(h, 4), p_wert=p_wert, n=n,
        freiheitsgrade=freiheitsgrade,
        effekt_name="eta^2", effekt=round(eta_quadrat, 4),
        zusatz={"gruppen": len(gefiltert)},
    )


# --------------------------------------------------------------------------
# Haeufigkeitsvergleiche
# --------------------------------------------------------------------------

def chi_quadrat_unabhaengigkeit(tabelle: Sequence[Sequence[float]]) -> Pruefgroesse:
    """Chi-Quadrat-Test auf Unabhaengigkeit zweier nominaler Merkmale.

    Erwartet eine Kreuztabelle beobachteter Haeufigkeiten. Geprueft wird, ob
    die Verteilung ueber die Spalten von der Zeile abhaengt -- etwa, ob sich die
    Typenverteilung der Spitzengruppe zwischen Einzel- und Doppelkampf
    unterscheidet.

    Die uebliche Faustregel verlangt eine erwartete Haeufigkeit von mindestens
    fuenf je Zelle. Zellen darunter werden gezaehlt und ausgewiesen; sind es
    mehr als ein Fuenftel, ist die Approximation nicht mehr belastbar und der
    Test wird abgelehnt statt beschoenigt.
    """
    zeilen = [list(z) for z in tabelle if sum(z) > 0]
    if len(zeilen) < 2:
        raise DatenbasisFehlt("Die Kreuztabelle braucht mindestens zwei besetzte Zeilen.")

    spalten_anzahl = len(zeilen[0])
    spaltensummen = [sum(z[j] for z in zeilen) for j in range(spalten_anzahl)]
    behalten = [j for j, summe in enumerate(spaltensummen) if summe > 0]
    if len(behalten) < 2:
        raise DatenbasisFehlt("Die Kreuztabelle braucht mindestens zwei besetzte Spalten.")

    zeilen = [[z[j] for j in behalten] for z in zeilen]
    gesamt = sum(sum(z) for z in zeilen)
    zeilensummen = [sum(z) for z in zeilen]
    spaltensummen = [sum(z[j] for z in zeilen) for j in range(len(behalten))]

    chi_quadrat = 0.0
    zu_kleine_zellen = 0
    for i, zeile in enumerate(zeilen):
        for j, beobachtet in enumerate(zeile):
            erwartet = zeilensummen[i] * spaltensummen[j] / gesamt
            if erwartet < 5:
                zu_kleine_zellen += 1
            chi_quadrat += (beobachtet - erwartet) ** 2 / erwartet

    zellen = len(zeilen) * len(behalten)
    if zu_kleine_zellen > zellen / 5:
        raise DatenbasisFehlt(
            f"{zu_kleine_zellen} von {zellen} Zellen haben eine erwartete Haeufigkeit "
            f"unter 5 -- die Chi-Quadrat-Approximation ist nicht belastbar.")

    freiheitsgrade = (len(zeilen) - 1) * (len(behalten) - 1)
    p_wert = chi_quadrat_ueberschreitung(chi_quadrat, freiheitsgrade)
    # Cramers V normiert die Pruefgroesse auf 0 bis 1 und macht Tabellen
    # unterschiedlicher Groesse vergleichbar.
    v = math.sqrt(chi_quadrat / (gesamt * min(len(zeilen) - 1, len(behalten) - 1)))

    return Pruefgroesse(
        verfahren="Chi-Quadrat-Unabhaengigkeitstest",
        statistik_name="Chi^2", statistik=round(chi_quadrat, 4), p_wert=p_wert,
        n=int(gesamt), freiheitsgrade=freiheitsgrade,
        effekt_name="Cramers V", effekt=round(v, 4),
        zusatz={"zellen": zellen, "zellen_unter_5": zu_kleine_zellen},
    )


def chi_quadrat_anpassung(beobachtet: Sequence[float],
                          erwartet: Sequence[float]) -> Pruefgroesse:
    """Chi-Quadrat-Anpassungstest gegen eine vorgegebene Verteilung.

    Prueft, ob sich eine beobachtete Haeufigkeitsverteilung von einer erwarteten
    unterscheidet -- etwa die Typenverteilung der Spitzengruppe gegenueber der
    des gesamten Pokemon-Bestands.

    Die erwarteten Haeufigkeiten werden auf die beobachtete Gesamtzahl skaliert;
    uebergeben werden duerfen daher auch Anteile.
    """
    if len(beobachtet) != len(erwartet):
        raise DatenbasisFehlt("Beobachtung und Erwartung muessen gleich viele Klassen haben.")

    gesamt_beobachtet = sum(beobachtet)
    gesamt_erwartet = sum(erwartet)
    if gesamt_beobachtet <= 0 or gesamt_erwartet <= 0:
        raise DatenbasisFehlt("Leere Verteilung.")

    skaliert = [e * gesamt_beobachtet / gesamt_erwartet for e in erwartet]
    paare = [(b, e) for b, e in zip(beobachtet, skaliert, strict=True) if e > 0]
    if len(paare) < 2:
        raise DatenbasisFehlt("Weniger als zwei besetzte Klassen.")

    zu_kleine_zellen = sum(1 for _, e in paare if e < 5)
    if zu_kleine_zellen > len(paare) / 5:
        raise DatenbasisFehlt(
            f"{zu_kleine_zellen} von {len(paare)} Klassen haben eine erwartete "
            f"Haeufigkeit unter 5 -- die Approximation ist nicht belastbar.")

    chi_quadrat = sum((b - e) ** 2 / e for b, e in paare)
    freiheitsgrade = len(paare) - 1
    p_wert = chi_quadrat_ueberschreitung(chi_quadrat, freiheitsgrade)
    # Cramers V fuer eine Zeile entspricht dem Kontingenzkoeffizienten Phi.
    v = math.sqrt(chi_quadrat / gesamt_beobachtet)

    return Pruefgroesse(
        verfahren="Chi-Quadrat-Anpassungstest",
        statistik_name="Chi^2", statistik=round(chi_quadrat, 4), p_wert=p_wert,
        n=int(gesamt_beobachtet), freiheitsgrade=freiheitsgrade,
        effekt_name="Cramers V", effekt=round(v, 4),
        zusatz={"klassen": len(paare), "klassen_unter_5": zu_kleine_zellen},
    )


# --------------------------------------------------------------------------
# Korrektur fuer multiples Testen
# --------------------------------------------------------------------------

def holm_bonferroni(p_werte: Sequence[float], alpha: float = 0.05) -> list[bool]:
    """Holm-Bonferroni-Korrektur fuer eine Familie von Hypothesen.

    Wird ein Katalog von zwoelf Hypothesen jeweils zum Niveau 5 Prozent
    geprueft, liegt die Wahrscheinlichkeit mindestens eines falschen Treffers
    nicht bei 5, sondern bei rund 46 Prozent. Ohne Korrektur waere ein Katalog
    dieser Groesse also fast garantiert "erfolgreich" -- und wertlos.

    Das Holm-Verfahren ordnet die p-Werte aufsteigend und vergleicht den
    ``i``-ten mit ``alpha / (m - i)``. Es haelt dieselbe familienweise
    Fehlerwahrscheinlichkeit ein wie die einfache Bonferroni-Korrektur, ist
    dabei aber trennschaerfer und ohne Zusatzannahmen gueltig.

    Rueckgabe: je Hypothese in der **Eingabereihenfolge**, ob die Nullhypothese
    verworfen wird.
    """
    m = len(p_werte)
    if m == 0:
        return []

    reihenfolge = sorted(range(m), key=lambda i: p_werte[i])
    entscheidung = [False] * m
    for position, index in enumerate(reihenfolge):
        schranke = alpha / (m - position)
        if p_werte[index] <= schranke:
            entscheidung[index] = True
        else:
            # Sobald eine Hypothese scheitert, bleiben alle folgenden
            # (groesseren p-Werte) ebenfalls unverworfen.
            break
    return entscheidung


def holm_schranken(p_werte: Sequence[float], alpha: float = 0.05) -> list[float]:
    """Die individuelle Schranke, gegen die jede Hypothese geprueft wurde."""
    m = len(p_werte)
    reihenfolge = sorted(range(m), key=lambda i: p_werte[i])
    schranken = [alpha] * m
    for position, index in enumerate(reihenfolge):
        schranken[index] = alpha / (m - position)
    return schranken
