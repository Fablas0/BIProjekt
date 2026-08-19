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
und Zustandsmechaniken, deren Wirkung vom Kampfverlauf abhaengt (Multiscale
bei vollen KP, Kontaktabfragen). Sie machen im geladenen Metagame zusammen
unter fuenf Prozent der gespielten Attacken aus; ein Rechner, der neun Zehntel
der Faelle exakt trifft und den Rest ausweist, ist ehrlicher als einer, der
alles verspricht.

Items und Faehigkeiten werden ueber ihre **Wirkungsklasse** aus ``Dim_Item``
und ``Dim_Faehigkeit`` verrechnet -- die namentlich hinterlegten Mechaniken
(Leben-Orb, Wahlband, Feuerfaenger ...) sind genau die, deren Wirkung als
fester Multiplikator beschreibbar ist.

Umstaende des Angriffs
----------------------
Neben Wetter und Schirmen sind die im Doppelkampf entscheidenden Umstaende
abgebildet: Terrain (mit Bodenbindung ueber Typ, Schwebe und Luftballon),
Statusstufen (mit der Sonderregel kritischer Treffer), Helfende Hand und die
vier Unheils-Faehigkeiten der Schatztruhe -- sie wirken als Feldzustand und
stehen deshalb am Angriff, nicht am Pokemon.
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

# Angreifer-Faehigkeiten, die Attacken eines Typs verstaerken -- als
# Staerke-Modifikator im Festkommaformat der Spiele.
FAEHIGKEIT_TYPVERSTAERKUNG: dict[str, dict[str, tuple[int, int]]] = {
    "transistor": {"Electric": (5325, 4096)},     # 1.3 (ab Gen 9)
    "dragonsmaw": {"Dragon": (6144, 4096)},       # 1.5
    "rockypayload": {"Rock": (6144, 4096)},       # 1.5
    "steelworker": {"Steel": (6144, 4096)},       # 1.5
    "steelyspirit": {"Steel": (6144, 4096)},      # 1.5
    "waterbubble": {"Water": (8192, 4096)},       # 2.0 (offensive Seite)
}

# Statverdoppler: wirken auf den Angriffswert, nicht auf die Attacke.
KRAFT_FAEHIGKEITEN = frozenset({"hugepower", "purepower"})

# Die vier Unheils-Faehigkeiten der Schatztruhe (Gen 9). Sie druecken je einen
# Kampfwert **aller anderen** Pokemon auf dem Feld um ein Viertel und wirken
# damit wie ein Feldzustand: fuer die Rechnung zaehlt nur, ob eine davon aktiv
# ist -- nicht, wer sie mitbringt.
UNHEIL_WIRKUNG: dict[str, tuple[str, str]] = {
    # Name -> (betroffene Seite, betroffener Wert)
    "Unheilsschwert": ("verteidiger", "defense"),      # Chien-Pao
    "Unheilsjuwelen": ("verteidiger", "sp_defense"),   # Chi-Yu
    "Unheilstafeln": ("angreifer", "attack"),          # Wo-Chien
    "Unheilsgefaess": ("angreifer", "sp_attack"),      # Ting-Lu
}

# Terrain-Verstaerkung (ab Gen 8: Faktor 1,3), sofern der Angreifer am Boden
# steht. Der Nebelfeld-Malus auf Drachen-Attacken haengt dagegen am Ziel.
TERRAIN_VERSTAERKUNG: dict[tuple[str, str], tuple[int, int]] = {
    ("Elektrofeld", "Electric"): (5325, 4096),
    ("Grasfeld", "Grass"): (5325, 4096),
    ("Psychofeld", "Psychic"): (5325, 4096),
}

TERRAINS = ("Elektrofeld", "Grasfeld", "Psychofeld", "Nebelfeld")

# Erdattacken, die das Grasfeld daempft, weil sie ueber den Boden laufen.
GRASFELD_GEDAEMPFT = frozenset({"earthquake", "bulldoze", "magnitude"})


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
    """Die angreifende Attacke samt Umstaenden.

    Alles, was hier steht, ist Zustand des Feldes oder des Zuges -- nicht des
    Pokemon. Statusstufen stehen deshalb ebenfalls hier: sie beschreiben die
    Lage im Kampf (nach einem Schwerttanz, nach zweimal Bedroher), nicht das
    Set.
    """

    name: str
    typ: str
    kategorie: str                   # 'physical' | 'special'
    staerke: int
    mehrfachziel: bool = False       # Flaechenattacke trifft mehrere Ziele
    wetter: str | None = None        # 'Regen' | 'Sonne' | None
    terrain: str | None = None       # eines aus TERRAINS oder None
    kritisch: bool = False
    brand: bool = False              # Angreifer ist verbrannt
    schirm: bool = False             # Reflektor bzw. Lichtschild aktiv
    helfende_hand: bool = False      # Partner hat Helfende Hand gesetzt
    stufe_angriff: int = 0           # Statusstufen -6..+6 des Angriffswerts
    stufe_verteidigung: int = 0      # Statusstufen -6..+6 des Verteidigungswerts
    unheil: frozenset[str] = frozenset()  # aktive Unheils-Faehigkeiten


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


def _stufenfaktor(wert: int, stufe: int) -> int:
    """Wendet eine Statusstufe (-6 bis +6) auf einen Kampfwert an.

    Die Spiele rechnen mit den Bruechen (2+n)/2 bzw. 2/(2+n) und runden ab --
    +1 ist also x1,5, -1 ist x2/3.
    """
    stufe = max(-6, min(6, stufe))
    if stufe >= 0:
        return math.floor(wert * (2 + stufe) / 2)
    return math.floor(wert * 2 / (2 - stufe))


def _am_boden(kaempfer: Kaempfer) -> bool:
    """Ob ein Pokemon von bodengebundenen Feldeffekten (Terrain) erfasst wird.

    Flug-Typen, Schwebe und ein getragener Luftballon heben vom Boden ab --
    genau die drei Befreiungen, die auch der Typenrechner fuer Bodenattacken
    kennt.
    """
    if "Flying" in (kaempfer.typ1, kaempfer.typ2):
        return False
    if kaempfer.faehigkeit_slug == "levitate":
        return False
    return kaempfer.item_slug != "airballoon"


def _effektive_staerke(angriff: Angriff, angreifer: Kaempfer, verteidiger: Kaempfer,
                       erklaerung: list[str]) -> int:
    """Attackenstaerke nach den Staerke-Modifikatoren des Spiels.

    Terrain, Helfende Hand und typverstaerkende Faehigkeiten setzen an der
    Staerke an, bevor der Grundschaden entsteht -- dieselbe Stelle wie im
    Spiel, damit die Rundung an derselben Stelle faellt.
    """
    staerke = angriff.staerke
    kompakt = "".join(c for c in angriff.name.lower() if c.isalnum())

    verstaerkung = FAEHIGKEIT_TYPVERSTAERKUNG.get(angreifer.faehigkeit_slug or "", {})
    if angriff.typ in verstaerkung:
        zaehler, nenner = verstaerkung[angriff.typ]
        staerke = _anwenden(staerke, zaehler, nenner)
        erklaerung.append(f"{angreifer.faehigkeit_slug}: Staerke x{zaehler / nenner:g}")

    if (angreifer.faehigkeit_slug == "technician" and angriff.staerke <= 60):
        staerke = _anwenden(staerke, 6144, 4096)
        erklaerung.append("Techniker: Staerke x1,5 bei Grundstaerke bis 60")

    if angriff.terrain and _am_boden(angreifer):
        boost = TERRAIN_VERSTAERKUNG.get((angriff.terrain, angriff.typ))
        if boost:
            staerke = _anwenden(staerke, *boost)
            erklaerung.append(f"{angriff.terrain}: Staerke x1,3")
    if (angriff.terrain == "Grasfeld" and kompakt in GRASFELD_GEDAEMPFT
            and _am_boden(verteidiger)):
        staerke = _anwenden(staerke, 2048, 4096)
        erklaerung.append("Grasfeld daempft Erdattacken: 0,5")
    if (angriff.terrain == "Nebelfeld" and angriff.typ == "Dragon"
            and _am_boden(verteidiger)):
        staerke = _anwenden(staerke, 2048, 4096)
        erklaerung.append("Nebelfeld gegen Bodenziel: Drachenschaden 0,5")

    if angriff.helfende_hand:
        staerke = _anwenden(staerke, 6144, 4096)
        erklaerung.append("Helfende Hand: Staerke x1,5")

    return staerke


def _effektive_werte(angriff: Angriff, angreifer: Kaempfer, verteidiger: Kaempfer,
                     erklaerung: list[str]) -> tuple[int, int]:
    """Angriffs- und Verteidigungswert unter den Umstaenden des Zuges.

    Statusstufen, Statverdoppler, Wetter- und Brandfaehigkeiten sowie die
    Unheils-Faehigkeiten setzen an den Kampfwerten an, nicht am Schaden.
    """
    if angriff.kategorie == "physical":
        angriffswert, verteidigungswert = angreifer.attack, verteidiger.defense
        eigener_wert, fremder_wert = "attack", "defense"
    else:
        angriffswert, verteidigungswert = angreifer.sp_attack, verteidiger.sp_defense
        eigener_wert, fremder_wert = "sp_attack", "sp_defense"

    slug = angreifer.faehigkeit_slug or ""
    if slug in KRAFT_FAEHIGKEITEN and angriff.kategorie == "physical":
        angriffswert *= 2
        erklaerung.append(f"{slug}: Angriff verdoppelt")
    if slug == "solarpower" and angriff.wetter == "Sonne" and angriff.kategorie == "special":
        angriffswert = _anwenden(angriffswert, 6144, 4096)
        erklaerung.append("Solarkraft bei Sonne: Spezialangriff x1,5")
    if slug == "guts" and angriff.brand and angriff.kategorie == "physical":
        angriffswert = _anwenden(angriffswert, 6144, 4096)
        erklaerung.append("Adrenalin: Angriff x1,5 trotz Brand")

    for name in sorted(angriff.unheil):
        seite, wert = UNHEIL_WIRKUNG.get(name, (None, None))
        if seite == "angreifer" and wert == eigener_wert:
            angriffswert = math.floor(angriffswert * 3 / 4)
            erklaerung.append(f"{name}: Angriffsseite 0,75")
        elif seite == "verteidiger" and wert == fremder_wert:
            verteidigungswert = math.floor(verteidigungswert * 3 / 4)
            erklaerung.append(f"{name}: Verteidigungsseite 0,75")

    # Statusstufen zuletzt, mit der Sonderregel des kritischen Treffers: er
    # ignoriert, was den Schaden druecken wuerde -- Malusstufen des Angreifers
    # und Bonusstufen des Verteidigers.
    stufe_an = angriff.stufe_angriff
    stufe_vert = angriff.stufe_verteidigung
    if angriff.kritisch:
        stufe_an = max(0, stufe_an)
        stufe_vert = min(0, stufe_vert)
    if stufe_an:
        angriffswert = _stufenfaktor(angriffswert, stufe_an)
        erklaerung.append(f"Angriffsstufe {stufe_an:+d}")
    if stufe_vert:
        verteidigungswert = _stufenfaktor(verteidigungswert, stufe_vert)
        erklaerung.append(f"Verteidigungsstufe {stufe_vert:+d}")

    return angriffswert, max(1, verteidigungswert)


def berechne(angreifer: Kaempfer, verteidiger: Kaempfer, angriff: Angriff,
             stufe: int = TURNIERSTUFE) -> Schadensspanne:
    """Berechnet die Schadensspanne eines Angriffs.

    Rueckgabe ist immer die **Spanne** aus 16 Zufallswuerfen (85 bis 100
    Prozent), nie ein Einzelwert: die Frage "ueberlebt das?" ist nur gegen das
    Minimum und das Maximum beantwortbar.
    """
    erklaerung: list[str] = []

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

    staerke = _effektive_staerke(angriff, angreifer, verteidiger, erklaerung)
    angriffswert, verteidigungswert = _effektive_werte(
        angriff, angreifer, verteidiger, erklaerung)

    grund = math.floor(math.floor(math.floor(
        2 * stufe / 5 + 2) * staerke * angriffswert / verteidigungswert) / 50) + 2

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

    stab_faktor = (8192, 4096) if angreifer.faehigkeit_slug == "adaptability" else (6144, 4096)
    brand_wirkt = (angriff.brand and angriff.kategorie == "physical"
                   and angreifer.faehigkeit_slug != "guts")

    def endschaden(zufall: int) -> int:
        schaden = math.floor(grund * zufall / 100)
        # Gleicher Typ (STAB).
        if angriff.typ in (angreifer.typ1, angreifer.typ2):
            schaden = _anwenden(schaden, *stab_faktor)
        # Typen-Effektivitaet: glatte Zweierpotenzen, floor genuegt.
        schaden = math.floor(schaden * effektivitaet)
        # Facettenauge verdoppelt resistierten Schaden.
        if angreifer.faehigkeit_slug == "tintedlens" and effektivitaet < 1:
            schaden = _anwenden(schaden, 8192, 4096)
        # Brand halbiert physischen Schaden -- ausser bei Adrenalin.
        if brand_wirkt:
            schaden = _anwenden(schaden, 2048, 4096)
        # Schirme (Reflektor / Lichtschild): im Doppelkampf 2/3.
        if angriff.schirm and not angriff.kritisch:
            schaden = _anwenden(schaden, 2732, 4096)
        # Eisflaechenschuppen halbieren speziellen Schaden.
        if (verteidiger.faehigkeit_slug == "icescales"
                and angriff.kategorie == "special"):
            schaden = _anwenden(schaden, 2048, 4096)
        # Item des Angreifers.
        schaden = _item_faktor(schaden, angreifer, angriff, effektivitaet)
        return max(1, schaden)

    if angriff.typ in (angreifer.typ1, angreifer.typ2):
        erklaerung.append("Gleicher Typ (STAB): "
                          + ("2,0 durch Anpassung" if stab_faktor == (8192, 4096) else "1,5"))
    erklaerung.append(f"Typen-Effektivitaet: {effektivitaet}")
    if angreifer.faehigkeit_slug == "tintedlens" and effektivitaet < 1:
        erklaerung.append("Facettenauge: resistierter Schaden verdoppelt")
    if brand_wirkt:
        erklaerung.append("Brand: 0,5")
    if angriff.schirm and not angriff.kritisch:
        erklaerung.append("Schirm: 2/3")
    if verteidiger.faehigkeit_slug == "icescales" and angriff.kategorie == "special":
        erklaerung.append("Eisflaechenschuppen: spezieller Schaden 0,5")

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
