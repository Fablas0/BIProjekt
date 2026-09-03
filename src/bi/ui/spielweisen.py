"""Spielweisen: Was moechte jemand mit der Anwendung tun?

Die Anwendung begann als Turnierwerkzeug fuer Pokemon Champions. Inzwischen
bedient sie sechs Arten, Pokemon zu spielen -- und wer eine Nuzlocke-
Herausforderung auf Platin spielt, braucht keinen Speed-Tier-Rechner fuer das
Ranked von 2026. Vierzehn Seiten in einer Liste waeren fuer diese Person
dreizehn zu viel.

Eine **Spielweise** ist deshalb die oberste Gliederung: sie waehlt aus, welche
Seiten die Navigation zeigt, und mit welcher Aufgabe. Dieselbe Seite kann in
mehreren Spielweisen stehen (das PC-System in allen), mit einer je Spielweise
passenden Beschreibung. Die Seiten selbst wissen nichts davon -- eine Seite
ist eine Seite; die Spielweise ist ein Blick darauf.

Die Betriebsseite steht in keiner Spielweise, sondern immer am Ende der
Navigation: Ladelaeufe und Qualitaetsbericht gehoeren zum Betrieb, nicht zum
Spielen.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Spielweise:
    """Eine Art, Pokemon zu spielen, und die Seiten dazu."""

    schluessel: str
    name: str
    frage: str                      # die Frage, die diese Spielweise beantwortet
    beschreibung: str               # ein Satz fuer die Kachel der Startseite
    navigation: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]

    @property
    def seiten(self) -> list[str]:
        return [name for _, eintraege in self.navigation for name, _ in eintraege]

    @property
    def startseite(self) -> str:
        return self.seiten[0]


_PC = ("PC-System", "Eigene Pokemon, Box und Einsatzcheck ueber alle Spielformen")
_POKEDEX = ("Pokedex", "Steckbrief, Typen-Berater und Fundort-Links")
_SPIELFORMEN = ("Spielformen", "VGC, Pokemon GO und Sammelkartenspiel im Vergleich")

SPIELWEISEN: dict[str, Spielweise] = {
    "champions": Spielweise(
        "champions", "Pokemon Champions",
        "Wie bereite ich mich auf das Ranked vor?",
        "Meta-Analyse, Team-Vorbereitung, Speed-Tiers und Schadensrechner "
        "fuer die offizielle Wettkampfplattform.",
        (
            ("Ueberblick", (
                ("Meta-Cockpit", "Rangliste, Stabilitaet und Bewegung im Format"),
                ("Trends", "Typen, Items, Neuzugaenge und Dauerbrenner im Verlauf"),
            )),
            ("Vor dem Kampf", (
                ("Team-Preview-Advisor", "Welche vier von sechs nehme ich mit?"),
                ("Gegner-Scouting", "Womit ist bei diesem Gegner zu rechnen?"),
                ("Team-Builder", "Wo ist mein Team angreifbar?"),
                ("Speed-Tiers", "Wer handelt zuerst?"),
                ("Schadensrechner", "Ueberlebt mein Pokemon diesen Treffer?"),
            )),
            ("Eigener Bestand", (
                ("PC-System", "Eigene Pokemon, Sets und Teams -- dauerhaft gespeichert"),
            )),
            ("Nachschlagen", (
                ("Pokedex", "Steckbrief, Typen-Berater und Fundort-Links -- "
                            "ohne Ranked-Bezug nutzbar"),
            )),
            ("Vertiefung", (
                ("OLAP-Explorer", "Wuerfel frei navigieren: Slice, Dice, Drill-Down"),
                ("Meta-Playbook", "Verdichtete Handlungsempfehlungen"),
                _SPIELFORMEN,
                ("Hypothesen", "Vorab formulierte Aussagen, statistisch geprueft"),
            )),
        ),
    ),
    "go": Spielweise(
        "go", "Pokemon GO",
        "Was lohnt sich gerade in den PvP-Ligen?",
        "Die pvpoke-Ranglisten der Super-, Hyper- und Meisterliga -- und welche "
        "eigenen Pokemon darin auftauchen.",
        (
            ("Ligen", (
                ("GO-Meta", "Ranglisten je Liga und der Abgleich mit der eigenen Box"),
            )),
            ("Eigener Bestand", (_PC,)),
            ("Nachschlagen", (_POKEDEX, _SPIELFORMEN)),
        ),
    ),
    "tcg": Spielweise(
        "tcg", "Sammelkartenspiel",
        "Welche Decks werden gespielt, und was habe ich davon?",
        "Turnier-Meta nach Deck und Land, dazu die eigene Kartensammlung mit "
        "Bruecke zur Meta.",
        (
            ("Karten", (
                ("Sammelkartenspiel", "Turnierdecks, Laendervergleich und eigene Sammlung"),
            )),
            ("Nachschlagen", (_POKEDEX, _SPIELFORMEN)),
        ),
    ),
    "nuzlocke": Spielweise(
        "nuzlocke", "Nuzlocke",
        "Ueberlebt mein Team den naechsten Arenaleiter?",
        "Ein Lauf unter Nuzlocke-Regeln: erste Begegnung je Ort, gefallen ist "
        "gefallen. Mit Typen-Luecken des Teams und Friedhof.",
        (
            ("Der Lauf", (
                ("Nuzlocke-Lauf", "Begegnungen, Team, Friedhof und die Luecken im Team"),
            )),
            ("Nachschlagen", (
                ("Pokedex", "Was trifft dieses Pokemon -- die Frage vor jedem Arenaleiter"),
            )),
            ("Eigener Bestand", (_PC,)),
        ),
    ),
    "durchspielen": Spielweise(
        "durchspielen", "Durchspielen",
        "Wo stehe ich in meinem Spiel, und was fehlt noch?",
        "Ein Spielstand je Edition: Team, Orden, Begegnungen -- ohne "
        "Zusatzregeln, mit Typen-Berater.",
        (
            ("Der Lauf", (
                ("Spielstand", "Team, Orden und Begegnungen des laufenden Durchgangs"),
            )),
            ("Nachschlagen", (
                ("Pokedex", "Steckbrief, Typen-Berater und wo es das Pokemon gibt"),
            )),
            ("Eigener Bestand", (_PC,)),
        ),
    ),
    "sammeln": Spielweise(
        "sammeln", "Sammeln und Shiny-Jagd",
        "Wie viele Versuche noch -- und bin ich ein Pechvogel?",
        "Zaehler je Jagd, eingeordnet gegen die Wahrscheinlichkeit der Methode; "
        "die Box mit Shiny-Kennzeichen und Herkunft.",
        (
            ("Die Jagd", (
                ("Shiny-Jagd", "Versuche zaehlen und gegen die Statistik halten"),
            )),
            ("Eigener Bestand", (
                ("PC-System", "Die Box: was gefangen ist, woher es stammt, ob es schillert"),
            )),
            ("Nachschlagen", (_POKEDEX,)),
        ),
    ),
}

STANDARD = "champions"

# Seiten, die ausserhalb jeder Spielweise stehen.
BETRIEB: tuple[tuple[str, str], ...] = (
    ("ETL & Datenqualitaet", "Ladelaeufe, Archiv und Qualitaetsbericht"),
)
BETRIEB_SEITEN = tuple(name for name, _ in BETRIEB)


def spielweise_fuer_seite(seite: str) -> str:
    """Die erste Spielweise, die eine Seite fuehrt -- fuer Tests und Direktlinks."""
    for schluessel, spielweise in SPIELWEISEN.items():
        if seite in spielweise.seiten:
            return schluessel
    return STANDARD


def alle_seiten() -> list[str]:
    """Jede Seite genau einmal, in der Reihenfolge ihres ersten Auftretens."""
    gesehen: dict[str, None] = {}
    for spielweise in SPIELWEISEN.values():
        for seite in spielweise.seiten:
            gesehen.setdefault(seite, None)
    for seite, _ in BETRIEB:
        gesehen.setdefault(seite, None)
    return list(gesehen)
