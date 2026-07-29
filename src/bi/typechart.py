"""Typen-Effektivitaet als fachliche Regelbasis.

Die Matrix ist defensiv notiert: ``VERTEIDIGUNG[verteidiger][angreifer]`` gibt den
Schadensmultiplikator an, den ein Pokemon des Typs ``verteidiger`` durch eine
Attacke des Typs ``angreifer`` erleidet. Nicht eingetragene Kombinationen sind
neutral (1.0).

Diese Regelbasis ist eine Stammdaten-Quelle ohne eigenes Quellsystem und wird im
ETL-Schritt "Anreicherung" verwendet, um aus den reinen Nutzungsdaten von Smogon
defensive und offensive Kennzahlen abzuleiten.
"""

from __future__ import annotations

from .config import ALLE_TYPEN

VERTEIDIGUNG: dict[str, dict[str, float]] = {
    "Normal": {"Fighting": 2, "Ghost": 0},
    "Fire": {"Fire": 0.5, "Water": 2, "Grass": 0.5, "Ice": 0.5, "Ground": 2, "Bug": 0.5,
             "Rock": 2, "Steel": 0.5, "Fairy": 0.5},
    "Water": {"Fire": 0.5, "Water": 0.5, "Electric": 2, "Grass": 2, "Ice": 0.5, "Steel": 0.5},
    "Electric": {"Electric": 0.5, "Ground": 2, "Flying": 0.5, "Steel": 0.5},
    "Grass": {"Fire": 2, "Water": 0.5, "Electric": 0.5, "Grass": 0.5, "Ice": 2, "Poison": 2,
              "Ground": 0.5, "Flying": 2, "Bug": 2},
    "Ice": {"Fire": 2, "Ice": 0.5, "Fighting": 2, "Rock": 2, "Steel": 2},
    "Fighting": {"Flying": 2, "Psychic": 2, "Bug": 0.5, "Rock": 0.5, "Dark": 0.5, "Fairy": 2},
    "Poison": {"Grass": 0.5, "Fighting": 0.5, "Poison": 0.5, "Ground": 2, "Psychic": 2,
               "Bug": 0.5, "Fairy": 0.5},
    "Ground": {"Water": 2, "Electric": 0, "Grass": 2, "Ice": 2, "Poison": 0.5, "Rock": 0.5},
    "Flying": {"Electric": 2, "Grass": 0.5, "Ice": 2, "Fighting": 0.5, "Ground": 0, "Bug": 0.5,
               "Rock": 2},
    "Psychic": {"Fighting": 0.5, "Psychic": 0.5, "Bug": 2, "Ghost": 2, "Dark": 2},
    "Bug": {"Fire": 2, "Grass": 0.5, "Fighting": 0.5, "Ground": 0.5, "Flying": 2, "Rock": 2},
    "Rock": {"Normal": 0.5, "Fire": 0.5, "Water": 2, "Grass": 2, "Fighting": 2, "Poison": 0.5,
             "Ground": 2, "Flying": 0.5, "Steel": 2},
    "Ghost": {"Normal": 0, "Fighting": 0, "Poison": 0.5, "Bug": 0.5, "Ghost": 2, "Dark": 2},
    "Dragon": {"Fire": 0.5, "Water": 0.5, "Electric": 0.5, "Grass": 0.5, "Ice": 2, "Dragon": 2,
               "Fairy": 2},
    "Dark": {"Fighting": 2, "Psychic": 0, "Bug": 2, "Ghost": 0.5, "Dark": 0.5, "Fairy": 2},
    "Steel": {"Normal": 0.5, "Fire": 2, "Grass": 0.5, "Ice": 0.5, "Fighting": 2, "Poison": 0,
              "Ground": 2, "Flying": 0.5, "Psychic": 0.5, "Bug": 0.5, "Rock": 0.5,
              "Dragon": 0.5, "Steel": 0.5, "Fairy": 0.5},
    "Fairy": {"Fighting": 0.5, "Poison": 2, "Bug": 0.5, "Dragon": 0, "Dark": 0.5, "Steel": 2},
}


def eingehender_multiplikator(angriffstyp: str, typ1: str | None, typ2: str | None = None) -> float:
    """Schaden, den ein (Doppel-)Typ durch ``angriffstyp`` erleidet."""
    faktor = VERTEIDIGUNG.get(typ1 or "", {}).get(angriffstyp, 1.0)
    if typ2:
        faktor *= VERTEIDIGUNG.get(typ2, {}).get(angriffstyp, 1.0)
    return float(faktor)


def ausgehender_multiplikator(angriffstyp: str, typ1: str | None, typ2: str | None = None) -> float:
    """Schaden, den ``angriffstyp`` gegen den Zieltyp anrichtet.

    Identisch zu :func:`eingehender_multiplikator`, aber aus Angreifersicht benannt --
    die Unterscheidung haelt den aufrufenden Analytics-Code lesbar.
    """
    return eingehender_multiplikator(angriffstyp, typ1, typ2)


def defensivprofil(typ1: str | None, typ2: str | None = None) -> dict[str, float]:
    """Vollstaendiges Schadensprofil eines Pokemon gegen alle 18 Angriffstypen."""
    return {t: eingehender_multiplikator(t, typ1, typ2) for t in ALLE_TYPEN}


def resistenz_kennzahl(typ1: str | None, typ2: str | None = None) -> float:
    """Verdichtete defensive Guete eines Typenpaars.

    Zaehlt Resistenzen positiv und Schwaechen negativ. Immunitaeten wiegen doppelt,
    weil sie im Doppelkampf ein sicheres Umschalten erlauben. Wertebereich in der
    Praxis etwa -6 bis +8.
    """
    punkte = 0.0
    for multiplikator in defensivprofil(typ1, typ2).values():
        if multiplikator == 0:
            punkte += 2.0
        elif multiplikator <= 0.25:
            punkte += 1.5
        elif multiplikator <= 0.5:
            punkte += 1.0
        elif multiplikator >= 4:
            punkte -= 2.0
        elif multiplikator >= 2:
            punkte -= 1.0
    return round(punkte, 2)
