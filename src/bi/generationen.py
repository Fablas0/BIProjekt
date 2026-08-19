"""Erscheinungsdaten der Spielgenerationen als fachliche Regelbasis.

Die Zeitdimension des Warehouse beginnt 2026, mit dem ersten gesicherten
Champions-Tagesstand. Die Frage "wie viele Pokemon kamen mit welcher
Generation dazu?" spielt aber auf einer anderen Zeitachse: der der
Hauptspiele, 1996 bis 2022. Ein Diagramm, das diese Frage auf der
Warehouse-Zeitachse beantwortet, zeigt zwangslaeufig nur 2026 -- und genau
das war der Befund aus dem Nutzerfeedback.

Diese Achse steht in keiner angebundenen Quelle: die PokeAPI kennt die
Generation eines Pokemon, aber kein Erscheinungsdatum. Deshalb liegt sie hier
als eigene Regelbasis, wie die Typen-Matrix in :mod:`bi.typechart` -- Stamm-
daten ohne Quellsystem, im Code dokumentiert und durch Tests gegen Tippfehler
gesichert.

Als ``jahr`` wird der **europaeische** Verkaufsstart der ersten Spiele einer
Generation gefuehrt: die Anwendung richtet sich an deutschsprachige Nutzer,
und deren "damals, 2007 mit Diamant" meint den hiesigen Verkaufsstart, nicht
den japanischen. Der steht daneben in ``jahr_japan``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Generation:
    """Eine Spielgeneration mit ihren Erstlingsspielen."""

    nummer: int
    jahr: int           # europaeischer Verkaufsstart der Erstlinge
    jahr_japan: int
    spiele: str         # die Erstlinge, unter denen die Generation bekannt ist
    region: str         # die Region, die die Generation einfuehrt


GENERATIONEN_INFO: dict[int, Generation] = {
    1: Generation(1, 1999, 1996, "Rote und Blaue Edition", "Kanto"),
    2: Generation(2, 2001, 1999, "Goldene und Silberne Edition", "Johto"),
    3: Generation(3, 2003, 2002, "Rubin und Saphir", "Hoenn"),
    4: Generation(4, 2007, 2006, "Diamant und Perl", "Sinnoh"),
    5: Generation(5, 2011, 2010, "Schwarz und Weiss", "Einall"),
    6: Generation(6, 2013, 2013, "X und Y", "Kalos"),
    7: Generation(7, 2016, 2016, "Sonne und Mond", "Alola"),
    8: Generation(8, 2019, 2019, "Schwert und Schild", "Galar"),
    9: Generation(9, 2022, 2022, "Karmesin und Purpur", "Paldea"),
}
