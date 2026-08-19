"""Tests der Pokedex-Seite und der Generationen-Regelbasis.

Die Seite selbst rendert ueber die Oberflaechentests; hier stehen die reinen
Rechen- und Regelteile, die ohne Streamlit laufen: die Erscheinungsdaten der
Generationen und der Weg vom deutschen Formnamen zum Nachschlagewerk-Link.
"""

from __future__ import annotations

import pytest

from bi.generationen import GENERATIONEN_INFO
from bi.ui.seite_pokedex import artname_deutsch, nachschlage_links


def test_alle_neun_generationen_mit_plausiblen_jahren() -> None:
    """Die Regelbasis muss lueckenlos und chronologisch sein.

    Ein Tippfehler in einem Jahr faellt sonst erst dem Betrachter des
    Diagramms auf -- und der haelt ihn fuer einen Datenfehler.
    """
    assert sorted(GENERATIONEN_INFO) == list(range(1, 10))
    jahre = [GENERATIONEN_INFO[g].jahr for g in sorted(GENERATIONEN_INFO)]
    assert jahre == sorted(jahre)
    assert jahre[0] == 1999 and jahre[-1] == 2022
    for info in GENERATIONEN_INFO.values():
        # Der japanische Start liegt nie nach dem europaeischen.
        assert info.jahr_japan <= info.jahr
        assert info.spiele and info.region


@pytest.mark.parametrize(("name_de", "erwartet"), [
    ("Vulnona", "Vulnona"),
    ("Alola-Vulnona", "Vulnona"),
    ("Galar-Lahmus", "Lahmus"),
    ("Hisui-Arkani", "Arkani"),
    ("Paldea-Tauros (Aqua Breed)", "Tauros"),
    ("Demeteros (Therian)", "Demeteros"),
    ("Ho-Oh", "Ho-Oh"),
    ("Porygon-Z", "Porygon-Z"),
])
def test_artname_reduziert_formzusaetze(name_de: str, erwartet: str) -> None:
    """Die Nachschlagewerke fuehren Artikel je Art; Formzusaetze muessen weg --
    echte Bindestrichnamen wie Porygon-Z aber unangetastet bleiben."""
    assert artname_deutsch(name_de) == erwartet


def test_nachschlage_links_deutsch_und_englisch() -> None:
    links = dict(nachschlage_links("Alola-Vulnona", "ninetales"))
    assert links["Bisafans-Pokedex"] == "https://www.bisafans.de/pokedex/vulnona.php"
    assert links["PokeWiki"] == "https://www.pokewiki.de/Vulnona"
    assert links["Pokemon-DB (englisch)"] == "https://pokemondb.net/pokedex/ninetales"


def test_nachschlage_links_umlaute_und_fallback() -> None:
    """Bisafans-Pfade sind ASCII; ohne deutschen Namen bleibt der englische Weg."""
    links = dict(nachschlage_links("Mähikel", "cyclizar"))
    assert links["Bisafans-Pokedex"] == "https://www.bisafans.de/pokedex/maehikel.php"
    assert "M%C3%A4hikel" in links["PokeWiki"]

    nur_englisch = nachschlage_links(None, "cyclizar")
    assert [beschriftung for beschriftung, _ in nur_englisch] == ["Pokemon-DB (englisch)"]
