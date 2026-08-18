"""Schadensrechner nach der Formel der Hauptspiele.

Warum ein eigener Rechner
-------------------------
Der Team-Preview-Advisor bewertet Paarungen ueber Typen-Effektivitaet und
Initiative -- das reicht fuer eine Rangfolge in 60 Sekunden, beantwortet aber
nicht die Frage, an der eine Einwechselentscheidung tatsaechlich haengt:
**ueberlebt mein Pokemon diesen Treffer?** Dafuer braucht es die Schadensformel
selbst, nicht nur die Multiplikatoren.

Die Formel
----------
Umgesetzt ist die Schadensformel der Hauptspiele ab Generation V::

    grund = floor(floor(floor(2 * stufe / 5 + 2) * staerke * angriff / verteidigung) / 50) + 2

Auf den Grundschaden wirken danach die Multiplikatoren, jeder einzeln
abgerundet, in der Reihenfolge des Spiels: Mehrfachziel, Wetter, kritischer
Treffer, Zufallsspanne (85 bis 100 Prozent), gleicher Typ (STAB), Typen-
Effektivitaet, Brand, Sonstiges (Items, Faehigkeiten, Schirme). Die Reihenfolge
ist nicht Kosmetik: floor dazwischen macht sie ergebniswirksam.

Pokemon Champions uebernimmt das Kampfsystem der Hauptspiele; nur die
Wertermittlung (Statuspunkte statt Fleisspunkte) ist anders und liegt bereits
in :mod:`bi.stats`.

Was der Rechner bewusst nicht kann
----------------------------------
Attacken mit variabler Staerke (Gyro Ball, Grass Knot), mehrstufige Attacken
und Feldeffekte jenseits von Wetter und Schirmen. Sie machen im geladenen
Metagame zusammen unter fuenf Prozent der gespielten Attacken aus; ein Rechner,
der neun Zehntel der Faelle exakt trifft und den Rest ausweist, ist ehrlicher
als einer, der alles verspricht.

Items und Faehigkeiten werden ueber ihre **Wirkungsklasse** aus ``Dim_Item``
und ``Dim_Faehigkeit`` verrechnet -- die namentlich hinterlegten Mechaniken
(Leben-Orb, Wahlband, Feuerfaenger ...) sind genau die, deren Wirkung als
fester Multiplikator beschreibbar ist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..stats import TURNIERSTUFE
from ..typechart import eingehender_multiplikator

# Multiplikatoren namentlich bekannter Items, als Zaehler/Nenner-Paar. Die
# Spiele rechnen in 1/4096-Schritten; Brueche vermeiden die Rundungsfehler
# einer Gleitkommadarstellung.
ITEM_ANGRIFF: dict[str, tuple[int, int]] = {
    "lifeorb": (5324, 4096),        # 1.3
    "choiceband": (6144, 4096),     # 1.5, nur physisch
    "choicespecs": (6144, 4096),    # 1.5, nur speziell
    "expertbelt": (4915, 4096),     # 1.2, nur bei sehr effektiv
    "muscleband": (4505, 4096),     # 1.1, nur physisch
    "wiseglasses": (4505, 4096),    # 1.1, nur speziell
}

PHYSISCHE_ITEMS = frozenset({"choiceband", "muscleband"})
SPEZIELLE_ITEMS = frozenset({"choicespecs", "wiseglasses"})
NUR_SEHR_EFFEKTIV = frozenset({"expertbelt"})

# Faehigkeiten mit fester, als Multiplikator beschreibbarer Wirkung.
FAEHIGKEIT_VERTEIDIGUNG: dict[str, dict[str, float]] = {
    # Immunitaeten: Schaden dieses Typs faellt vollstaendig aus.
    "flashfire": {"Fire": 0.0},
    "voltabsorb": {"Electric": 0.0},
    "lightningrod": {"Electric": 0.0},
    "motordrive": {"Electric": 0.0},
    "waterabsorb": {"Water": 0.0},
    "stormdrain": {"Water": 0.0},
    "sapsipper": {"Grass": 0.0},
    "levitate": {"Ground": 0.0},
    # Abschwaechungen.
    "thickfat": {"Fire": 0.5, "Ice": 0.5},
    "heatproof": {"Fire": 0.5},
    "waterbubble": {"Fire": 0.5},
    "purifyingsalt": {"Ghost": 0.5},
}

WETTER_FAKTOR: dict[tuple[str, str], float] = {
    ("Regen", "Water"): 1.5, ("Regen", "Fire"): 0.5,
    ("Sonne", "Fire"): 1.5, ("Sonne", "Water"): 0.5,
}


@dataclass(frozen=True)
class Kaempfer:
    """Ein Pokemon im Schadensvergleich -- die bereits berechneten Endwerte.

    Die Werte kommen aus :func:`bi.stats.alle_statuswerte` (eigene Box) oder
    aus dem meistgespielten Set der Bewegungsdaten (Gegner). Der Rechner selbst
    kennt keine Statuspunkte mehr -- Wertermittlung und Schadensrechnung sind
    getrennte Schritte, wie im Spiel.
    """

    name: str
    typ1: str
    typ2: str | None
    hp: int
    attack: int
    defense: int
    sp_attack: int
    sp_defense: int
    item_slug: str | None = None
    faehigkeit_slug: str | None = None


@dataclass(frozen=True)
class Angriff:
    """Die angreifende Attacke samt Umstaenden."""

    name: str
    typ: str
    kategorie: str                   # 'physical' | 'special'
    staerke: int
    mehrfachziel: bool = False       # Flaechenattacke trifft mehrere Ziele
    wetter: str | None = None        # 'Regen' | 'Sonne' | None
    kritisch: bool = False
    brand: bool = False              # Angreifer ist verbrannt
    schirm: bool = False             # Reflektor bzw. Lichtschild aktiv


@dataclass(frozen=True)
class Schadensspanne:
    """Ergebnis einer Schadensrechnung."""

    minimum: int
    maximum: int
    ziel_hp: int
    effektivitaet: float
    erklaerung: list[str] = field(default_factory=list)

    @property
    def minimum_prozent(self) -> float:
        return round(100 * self.minimum / self.ziel_hp, 1) if self.ziel_hp else 0.0

    @property
    def maximum_prozent(self) -> float:
        return round(100 * self.maximum / self.ziel_hp, 1) if self.ziel_hp else 0.0

    @property
    def sicherer_ko(self) -> bool:
        """Faellt das Ziel auch beim schwaechsten Wurf?"""
        return self.minimum >= self.ziel_hp

    @property
    def moeglicher_ko(self) -> bool:
        return self.maximum >= self.ziel_hp

    @property
    def urteil(self) -> str:
        """Die Aussage, um die es im Kampf geht -- in einem Satz."""
        if self.effektivitaet == 0:
            return "Wirkt nicht."
        if self.sicherer_ko:
            return "Sicherer K.o. mit einem Treffer."
        if self.moeglicher_ko:
            return (f"Moeglicher K.o.: faellt bei hohem Wurf "
                    f"({self.minimum_prozent}-{self.maximum_prozent} %).")
        if self.maximum_prozent >= 50:
            return (f"Zwei Treffer genuegen "
                    f"({self.minimum_prozent}-{self.maximum_prozent} %).")
        return f"Chip-Schaden ({self.minimum_prozent}-{self.maximum_prozent} %)."


def _anwenden(wert: int, zaehler: int, nenner: int) -> int:
    """Ein Multiplikator im Festkommaformat der Spiele: halbrunden ab 0,5."""
    produkt = wert * zaehler
    ganz, rest = divmod(produkt, nenner)
    return int(ganz + (1 if rest * 2 > nenner else 0))


def berechne(angreifer: Kaempfer, verteidiger: Kaempfer, angriff: Angriff,
             stufe: int = TURNIERSTUFE) -> Schadensspanne:
    """Berechnet die Schadensspanne eines Angriffs.

    Rueckgabe ist immer die **Spanne** aus 16 Zufallswuerfen (85 bis 100
    Prozent), nie ein Einzelwert: die Frage "ueberlebt das?" ist nur gegen das
    Minimum und das Maximum beantwortbar.
    """
    erklaerung: list[str] = []

    if angriff.kategorie == "physical":
        angriffswert, verteidigungswert = angreifer.attack, verteidiger.defense
    else:
        angriffswert, verteidigungswert = angreifer.sp_attack, verteidiger.sp_defense

    # Typen-Effektivitaet einschliesslich Faehigkeit des Verteidigers.
    effektivitaet = eingehender_multiplikator(
        angriff.typ, verteidiger.typ1, verteidiger.typ2)
    faehigkeit = FAEHIGKEIT_VERTEIDIGUNG.get(verteidiger.faehigkeit_slug or "", {})
    if angriff.typ in faehigkeit:
        faktor = faehigkeit[angriff.typ]
        effektivitaet *= faktor
        erklaerung.append(
            f"{verteidiger.faehigkeit_slug}: "
            + ("Immunitaet" if faktor == 0 else f"Faktor {faktor}"))

    if effektivitaet == 0 or angriff.staerke <= 0:
        return Schadensspanne(0, 0, verteidiger.hp, effektivitaet, erklaerung)

    grund = math.floor(math.floor(math.floor(
        2 * stufe / 5 + 2) * angriff.staerke * angriffswert / verteidigungswert) / 50) + 2

    # Multiplikatoren in Spielreihenfolge, jeder einzeln gerundet.
    if angriff.mehrfachziel:
        grund = _anwenden(grund, 3072, 4096)
        erklaerung.append("Flaechenattacke gegen mehrere Ziele: 0,75")
    wetter = WETTER_FAKTOR.get((angriff.wetter or "", angriff.typ))
    if wetter:
        grund = _anwenden(grund, int(wetter * 4096), 4096)
        erklaerung.append(f"Wetter {angriff.wetter}: {wetter}")
    if angriff.kritisch:
        grund = _anwenden(grund, 6144, 4096)
        erklaerung.append("Kritischer Treffer: 1,5")

    def endschaden(zufall: int) -> int:
        schaden = math.floor(grund * zufall / 100)
        # Gleicher Typ (STAB).
        if angriff.typ in (angreifer.typ1, angreifer.typ2):
            schaden = _anwenden(schaden, 6144, 4096)
        # Typen-Effektivitaet: glatte Zweierpotenzen, floor genuegt.
        schaden = math.floor(schaden * effektivitaet)
        # Brand halbiert physischen Schaden.
        if angriff.brand and angriff.kategorie == "physical":
            schaden = _anwenden(schaden, 2048, 4096)
        # Schirme (Reflektor / Lichtschild): im Doppelkampf 2/3.
        if angriff.schirm and not angriff.kritisch:
            schaden = _anwenden(schaden, 2732, 4096)
        # Item des Angreifers.
        schaden = _item_faktor(schaden, angreifer, angriff, effektivitaet)
        return max(1, schaden)

    if angriff.typ in (angreifer.typ1, angreifer.typ2):
        erklaerung.append("Gleicher Typ (STAB): 1,5")
    erklaerung.append(f"Typen-Effektivitaet: {effektivitaet}")
    if angriff.brand and angriff.kategorie == "physical":
        erklaerung.append("Brand: 0,5")
    if angriff.schirm and not angriff.kritisch:
        erklaerung.append("Schirm: 2/3")

    minimum, maximum = endschaden(85), endschaden(100)
    return Schadensspanne(minimum, maximum, verteidiger.hp, effektivitaet, erklaerung)


def _item_faktor(schaden: int, angreifer: Kaempfer, angriff: Angriff,
                 effektivitaet: float) -> int:
    slug = angreifer.item_slug or ""
    if slug not in ITEM_ANGRIFF:
        return schaden
    if slug in PHYSISCHE_ITEMS and angriff.kategorie != "physical":
        return schaden
    if slug in SPEZIELLE_ITEMS and angriff.kategorie != "special":
        return schaden
    if slug in NUR_SEHR_EFFEKTIV and effektivitaet <= 1:
        return schaden
    zaehler, nenner = ITEM_ANGRIFF[slug]
    return _anwenden(schaden, zaehler, nenner)


def treffer_bis_ko(spanne: Schadensspanne) -> tuple[int, int]:
    """Wie viele Treffer bis zum K.o. -- im besten und im schlechtesten Fall."""
    if spanne.maximum == 0:
        return (0, 0)
    guenstig = math.ceil(spanne.ziel_hp / spanne.maximum)
    unguenstig = math.ceil(spanne.ziel_hp / spanne.minimum) if spanne.minimum else 0
    return (guenstig, unguenstig)
