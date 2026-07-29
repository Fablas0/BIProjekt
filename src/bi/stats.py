"""Statuswert-Berechnung nach den Regeln von Pokemon Champions.

Die Basiswerte sagen nur, wie stark ein Pokemon von Natur aus ist -- nicht, wie
stark das im Turnier gespielte Exemplar tatsaechlich ist. Zwischen beidem liegen
bis zu 130 Punkte.

Das Trainingssystem von Champions
---------------------------------
Champions hat die Fleisspunkte und Determinationswerte der Hauptreihe ersetzt:

* **Statuspunkte** treten an die Stelle der Fleisspunkte. Es stehen **66 Punkte**
  zur Verfuegung, hoechstens **32 je Einzelwert**. Ein Statuspunkt hebt den
  Endwert bei Turnierstufe 50 um **genau eins** -- er wird nach der
  Stufenskalierung addiert. In der Praxis werden meist zwei Werte auf 32 gesetzt
  und die verbleibenden zwei Punkte auf einen dritten verteilt.
* **Determinationswerte** entfallen: sie liegen fest bei 31 und lassen sich weder
  zuechten noch trainieren. Damit gibt es in Champions keine Moeglichkeit, ein
  Pokemon fuer Bizarroraum ueber niedrige Determinationswerte bewusst langsam zu
  machen -- dafuer bleibt allein das Wesen.
* **Wesen** heissen im Spiel *Stat Alignment* und wirken unveraendert: ein Wert
  steigt um zehn Prozent, ein anderer sinkt um zehn Prozent.

Die im Spiel als "Base stats" angezeigten Werte sind bereits die Werte auf Stufe
50 ohne Investition. Fuer Knackrack etwa zeigt das Spiel 183/150/115/100/105/122;
:func:`stufe50_grundwerte` reproduziert genau diese Zahlen aus den Basiswerten
der Hauptreihe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TURNIERSTUFE = 50

# Wesen veraendern je einen Statuswert um +10 Prozent und einen anderen um
# -10 Prozent. Fuenf Wesen sind neutral.
# Abbildung: Wesen -> (angehobener Wert, gesenkter Wert)
WESEN: dict[str, tuple[str | None, str | None]] = {
    "Hardy": (None, None), "Docile": (None, None), "Serious": (None, None),
    "Bashful": (None, None), "Quirky": (None, None),
    "Lonely": ("attack", "defense"),
    "Brave": ("attack", "speed"),
    "Adamant": ("attack", "sp_attack"),
    "Naughty": ("attack", "sp_defense"),
    "Bold": ("defense", "attack"),
    "Relaxed": ("defense", "speed"),
    "Impish": ("defense", "sp_attack"),
    "Lax": ("defense", "sp_defense"),
    "Timid": ("speed", "attack"),
    "Hasty": ("speed", "defense"),
    "Jolly": ("speed", "sp_attack"),
    "Naive": ("speed", "sp_defense"),
    "Modest": ("sp_attack", "attack"),
    "Mild": ("sp_attack", "defense"),
    "Quiet": ("sp_attack", "speed"),
    "Rash": ("sp_attack", "sp_defense"),
    "Calm": ("sp_defense", "attack"),
    "Gentle": ("sp_defense", "defense"),
    "Sassy": ("sp_defense", "speed"),
    "Careful": ("sp_defense", "sp_attack"),
}

LANGSAME_WESEN = frozenset(
    wesen for wesen, (_, gesenkt) in WESEN.items() if gesenkt == "speed"
)
SCHNELLE_WESEN = frozenset(
    wesen for wesen, (angehoben, _) in WESEN.items() if angehoben == "speed"
)

STATUSWERTE = ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")

# Regeln des Trainingssystems.
MAX_SP_JE_WERT = 32
SP_BUDGET = 66
DETERMINATIONSWERT = 31        # unveraenderlich, nicht zuechtbar


def wesen_faktor(wesen: str, statuswert: str) -> float:
    """Multiplikator, den ein Wesen auf einen Statuswert anwendet."""
    angehoben, gesenkt = WESEN.get(wesen, (None, None))
    if statuswert == angehoben:
        return 1.1
    if statuswert == gesenkt:
        return 0.9
    return 1.0


def statuswert(basiswert: int, statuspunkte: int, wesen: str, statusname: str,
               stufe: int = TURNIERSTUFE) -> int:
    """Berechnet einen Statuswert nach den Champions-Regeln.

    Der investierte Wert wird **nach** der Stufenskalierung addiert: ein
    Statuspunkt hebt den Endwert um genau eins. Bei den Kraftpunkten wirkt das
    Wesen nicht mit.

    Abgerundet wird an genau den Stellen, an denen es auch das Spiel tut --
    andernfalls entstuenden Abweichungen von einem Punkt, und exakt daran
    entscheiden sich Initiativevergleiche.
    """
    kern = math.floor(((2 * basiswert + DETERMINATIONSWERT) * stufe) / 100)

    if statusname == "hp":
        return kern + stufe + 10 + statuspunkte

    return math.floor((kern + 5 + statuspunkte) * wesen_faktor(wesen, statusname))


def stufe50_grundwerte(basiswerte: dict[str, int],
                       stufe: int = TURNIERSTUFE) -> dict[str, int]:
    """Die im Spiel als "Base stats" angezeigten Werte.

    Das sind die Statuswerte auf Turnierstufe 50 ohne investierte Punkte und mit
    neutralem Wesen -- fuer jeden Spieler identisch.
    """
    return {name: statuswert(basiswerte[name], 0, "Hardy", name, stufe)
            for name in STATUSWERTE}


def alle_statuswerte(basiswerte: dict[str, int], punkte: dict[str, int],
                     wesen: str, stufe: int = TURNIERSTUFE) -> dict[str, int]:
    """Berechnet alle sechs Statuswerte fuer eine Punkteverteilung."""
    return {name: statuswert(basiswerte[name], punkte.get(name, 0), wesen, name, stufe)
            for name in STATUSWERTE}


def pruefe_statuspunkte(punkte: dict[str, int]) -> list[str]:
    """Prueft eine Punkteverteilung gegen die Regeln des Spiels.

    Zwei Grenzen gelten: hoechstens 32 Punkte je Einzelwert und 66 insgesamt.
    Rueckgabe ist eine Liste von Befundtexten (leer = zulaessig).
    """
    befunde: list[str] = []

    for name, wert in punkte.items():
        if wert < 0:
            befunde.append(f"{name}: negativer Wert {wert}")
        elif wert > MAX_SP_JE_WERT:
            befunde.append(
                f"{name}: {wert} Punkte ueberschreiten das Maximum von "
                f"{MAX_SP_JE_WERT} je Wert")

    summe = sum(max(0, w) for w in punkte.values())
    if summe > SP_BUDGET:
        befunde.append(
            f"Summe {summe} ueberschreitet das Gesamtbudget von {SP_BUDGET} Punkten")

    return befunde


def benoetigte_statuspunkte(basiswert: int, zielwert: int, wesen: str = "Timid",
                            stufe: int = TURNIERSTUFE) -> int | None:
    """Statuspunkte, die noetig sind, um einen Zielwert zu erreichen.

    Beantwortet die klassische Frage der Teamvorbereitung: "Wie viel muss ich
    investieren, um dieses Pokemon zu ueberholen?" Gibt ``None`` zurueck, wenn
    der Zielwert auch mit voller Investition nicht erreichbar ist.
    """
    for punkte in range(MAX_SP_JE_WERT + 1):
        if statuswert(basiswert, punkte, wesen, "speed", stufe) >= zielwert:
            return punkte
    return None


def verteilung_kurzform(wesen: str, punkte: dict[str, int]) -> str:
    """Kompakte Schreibweise einer Punkteverteilung, wie im Turnierumfeld ueblich."""
    return f"{wesen} " + "/".join(str(punkte.get(name, 0)) for name in STATUSWERTE)


# --------------------------------------------------------------------------
# Initiative im Kampfgeschehen
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Szenario:
    """Eine Kampfsituation, die die Initiative veraendert.

    ``wirkt_auf`` ist entscheidend fuer die Auswertung und leicht zu uebersehen:

    * ``"eigene"`` -- der Effekt betrifft nur die eigene Seite (Rueckenwind,
      Wahlschal, Statuswert-Erhoehungen, eine Paralyse des eigenen Pokemon).
    * ``"gegner"`` -- der Effekt betrifft die gegnerische Seite (eine selbst
      eingesetzte Tempo-Senkung wie Eissturm).
    * ``"feld"`` -- der Effekt betrifft beide Seiten gleichermassen und
      veraendert die Reihenfolge nur strukturell (Bizarroraum).

    Wuerde ein einseitiger Effekt auf beide Seiten angewandt, hoebe er sich in
    der Auswertung auf und das Szenario zeigte keinerlei Wirkung.
    """

    schluessel: str
    bezeichnung: str
    faktor: float
    wirkt_auf: str = "eigene"
    kehrt_reihenfolge_um: bool = False
    erlaeuterung: str = ""


SZENARIEN: dict[str, Szenario] = {
    "normal": Szenario(
        "normal", "Ohne Effekt", 1.0, wirkt_auf="feld",
        erlaeuterung="Die Initiative entscheidet unveraendert."),
    "rueckenwind": Szenario(
        "rueckenwind", "Rueckenwind (eigene Seite)", 2.0, wirkt_auf="eigene",
        erlaeuterung="Verdoppelt die Initiative der eigenen Seite fuer vier Runden."),
    "wahlschal": Szenario(
        "wahlschal", "Wahlschal", 1.5, wirkt_auf="eigene",
        erlaeuterung="Erhoeht die eigene Initiative um die Haelfte, bindet aber "
                     "an eine einzige Attacke."),
    "rueckenwind_schal": Szenario(
        "rueckenwind_schal", "Rueckenwind + Wahlschal", 3.0, wirkt_auf="eigene",
        erlaeuterung="Beide Effekte wirken nacheinander."),
    "boost_1": Szenario(
        "boost_1", "Eigene Initiative +1 Stufe", 1.5, wirkt_auf="eigene",
        erlaeuterung="Etwa durch Drachentanz oder Beschleunigung."),
    "boost_2": Szenario(
        "boost_2", "Eigene Initiative +2 Stufen", 2.0, wirkt_auf="eigene",
        erlaeuterung="Etwa durch Kommandant oder zwei Runden Beschleunigung."),
    "paralyse": Szenario(
        "paralyse", "Eigenes Pokemon paralysiert", 0.5, wirkt_auf="eigene",
        erlaeuterung="Halbiert die eigene Initiative."),
    "eissturm": Szenario(
        "eissturm", "Eissturm gegen den Gegner (-1 Stufe)", 2 / 3, wirkt_auf="gegner",
        erlaeuterung="Senkt die gegnerische Initiative um eine Stufe."),
    "bizarroraum": Szenario(
        "bizarroraum", "Bizarroraum", 1.0, wirkt_auf="feld", kehrt_reihenfolge_um=True,
        erlaeuterung="Gilt fuer beide Seiten: das langsamere Pokemon handelt zuerst."),
}


def initiative_im_szenario(basis_initiative: int, szenario: str = "normal") -> int:
    """Wendet den Effekt eines Szenarios auf einen Initiativwert an.

    Das Spiel rundet nach jeder Multiplikation ab; bei zusammengesetzten
    Szenarien wird diese Reihenfolge nachgebildet.
    """
    beschreibung = SZENARIEN.get(szenario, SZENARIEN["normal"])

    if szenario == "rueckenwind_schal":
        # Zuerst der Feldeffekt, dann das Item -- so wertet es das Spiel aus.
        return math.floor(math.floor(basis_initiative * 2) * 1.5)

    return math.floor(basis_initiative * beschreibung.faktor)


def handelt_zuerst(eigene_initiative: int, gegnerische_initiative: int,
                   szenario: str = "normal") -> str:
    """Vergleicht zwei Initiativwerte unter einem Szenario.

    Rueckgabe: ``"schneller"``, ``"langsamer"`` oder ``"gleichstand"``. Bei
    Gleichstand entscheidet im Spiel der Zufall -- das wird als eigener Fall
    ausgewiesen statt willkuerlich zugunsten einer Seite aufgeloest.
    """
    umkehr = SZENARIEN.get(szenario, SZENARIEN["normal"]).kehrt_reihenfolge_um

    if eigene_initiative == gegnerische_initiative:
        return "gleichstand"

    schneller = eigene_initiative > gegnerische_initiative
    if umkehr:
        schneller = not schneller
    return "schneller" if schneller else "langsamer"
