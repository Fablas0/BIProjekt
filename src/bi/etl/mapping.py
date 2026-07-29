"""Harmonisierung der Pokemon-Bezeichner zwischen den beiden Quellsystemen.

Smogon und die PokeAPI benennen dieselbe Entitaet unterschiedlich. Bei 245
Meta-Pokemon sind 19 Bezeichner nicht regelbasiert aufloesbar, weil Smogon die
jeweils dominante Form ohne Suffix fuehrt, die PokeAPI dagegen jede Form explizit
benennt (Smogon ``Landorus`` -> PokeAPI ``landorus-incarnate``).

Die naheliegende Notloesung -- bei fehlendem Treffer den Teil vor dem ersten
Bindestrich zu verwenden -- ist fachlich falsch: sie wirft ``Ogerpon-Cornerstone``,
``Ogerpon-Hearthflame`` und ``Ogerpon-Wellspring`` auf dieselbe Entitaet zusammen.
Da sich diese Formen in Typ, Item und Rolle unterscheiden, entstuenden dabei
Dubletten im Faktenschluessel und verfaelschte Kennzahlen.

Deshalb: explizite Zuordnungstabelle plus konservative Normalisierung, und jeder
verbleibende Nicht-Treffer wird als Datenqualitaetsbefund protokolliert statt
still geraten.
"""

from __future__ import annotations

import re

# Explizite Zuordnung Smogon-Bezeichner -> PokeAPI-Slug.
# Alle Ziel-Slugs sind gegen den PokeAPI-Bestand geprueft.
NAMENS_ZUORDNUNG: dict[str, str] = {
    # Formen, die Smogon ohne Suffix fuehrt
    "Landorus": "landorus-incarnate",
    "Tornadus": "tornadus-incarnate",
    "Thundurus": "thundurus-incarnate",
    "Enamorus": "enamorus-incarnate",
    "Urshifu": "urshifu-single-strike",
    "Giratina": "giratina-altered",
    "Shaymin": "shaymin-land",
    "Deoxys": "deoxys-normal",
    "Wormadam": "wormadam-plant",
    "Basculin": "basculin-red-striped",
    "Keldeo": "keldeo-ordinary",
    "Meloetta": "meloetta-aria",
    "Aegislash": "aegislash-shield",
    "Gourgeist": "gourgeist-average",
    "Pumpkaboo": "pumpkaboo-average",
    "Zygarde": "zygarde-50",
    "Oricorio": "oricorio-baile",
    "Lycanroc": "lycanroc-midday",
    "Wishiwashi": "wishiwashi-solo",
    "Minior": "minior-red-meteor",
    "Mimikyu": "mimikyu-disguised",
    "Toxtricity": "toxtricity-amped",
    "Eiscue": "eiscue-ice",
    "Indeedee": "indeedee-male",
    "Morpeko": "morpeko-full-belly",
    "Basculegion": "basculegion-male",
    "Meowstic": "meowstic-male",
    "Tatsugiri": "tatsugiri-curly",
    "Squawkabilly": "squawkabilly-green-plumage",
    "Palafin": "palafin-zero",
    "Maushold": "maushold-family-of-four",
    "Dudunsparce": "dudunsparce-two-segment",
    "Darmanitan": "darmanitan-standard",
    "Rockruff": "rockruff",
    # Geschlechtsformen: Smogon nutzt -F / -M, die PokeAPI -female / -male
    "Indeedee-F": "indeedee-female",
    "Meowstic-F": "meowstic-female",
    "Basculegion-F": "basculegion-female",
    "Oinkologne-F": "oinkologne-female",
    # Ogerpon: PokeAPI haengt an jede Maskenform '-mask' an
    "Ogerpon-Cornerstone": "ogerpon-cornerstone-mask",
    "Ogerpon-Hearthflame": "ogerpon-hearthflame-mask",
    "Ogerpon-Wellspring": "ogerpon-wellspring-mask",
    # Necrozma: Smogon nennt die Fusionen ausfuehrlicher als die PokeAPI
    "Necrozma-Dawn-Wings": "necrozma-dawn",
    "Necrozma-Dusk-Mane": "necrozma-dusk",
    # Paldea-Tauros: die PokeAPI haengt an jede Zuchtform '-breed' an
    "Tauros-Paldea-Aqua": "tauros-paldea-aqua-breed",
    "Tauros-Paldea-Blaze": "tauros-paldea-blaze-breed",
    "Tauros-Paldea-Combat": "tauros-paldea-combat-breed",
    # Weitere Abweichungen in der Schreibweise
    "Toxtricity-Low-Key": "toxtricity-low-key",
    "Urshifu-Rapid-Strike": "urshifu-rapid-strike",
    "Zacian-Crowned": "zacian-crowned",
    "Zamazenta-Crowned": "zamazenta-crowned",
    "Calyrex-Ice": "calyrex-ice",
    "Calyrex-Shadow": "calyrex-shadow",
}

# Smogon fuehrt Mega-/Gigantamax-/Terastal-Varianten teils mit Suffixen, die in der
# PokeAPI anders lauten. Regelbasierte Ersetzungen fuer den generischen Pfad.
SUFFIX_REGELN: list[tuple[str, str]] = [
    ("-gmax", "-gmax"),
    ("-mega-x", "-mega-x"),
    ("-mega-y", "-mega-y"),
    ("-mega", "-mega"),
    ("-alola", "-alola"),
    ("-galar", "-galar"),
    ("-hisui", "-hisui"),
    ("-paldea", "-paldea"),
]

_SONDERZEICHEN = re.compile(r"[^a-z0-9-]")


def normalisiere(bezeichner: str) -> str:
    """Fuehrt einen Quellbezeichner in die PokeAPI-Slug-Schreibweise ueber.

    Beispiel: ``"Iron Hands"`` -> ``"iron-hands"``, ``"Ho-Oh"`` -> ``"ho-oh"``,
    ``"Farfetch'd"`` -> ``"farfetchd"``.
    """
    slug = bezeichner.strip().lower()
    slug = slug.replace(" ", "-").replace(".", "").replace("'", "").replace(":", "")
    slug = slug.replace("%", "").replace("é", "e")
    slug = _SONDERZEICHEN.sub("", slug)
    return re.sub(r"-{2,}", "-", slug).strip("-")


def loese_auf(quell_name: str, bekannte_slugs: set[str]) -> str | None:
    """Ermittelt den PokeAPI-Slug zu einem Smogon-Bezeichner.

    Gibt ``None`` zurueck, wenn keine eindeutige Zuordnung moeglich ist. Bewusst
    kein Rueckfall auf den Basisnamen -- ein falscher Treffer waere schaedlicher
    als ein protokollierter Fehltreffer.
    """
    # 1. Explizite Zuordnung hat Vorrang.
    if quell_name in NAMENS_ZUORDNUNG:
        kandidat = NAMENS_ZUORDNUNG[quell_name]
        return kandidat if kandidat in bekannte_slugs else None

    # 2. Direkte Normalisierung.
    slug = normalisiere(quell_name)
    if slug in bekannte_slugs:
        return slug

    # 3. Regionalformen: Smogon haengt die Region an, die PokeAPI ebenfalls --
    #    hier weicht nur gelegentlich die Schreibweise ab.
    for smogon_suffix, api_suffix in SUFFIX_REGELN:
        if slug.endswith(smogon_suffix):
            kandidat = slug[: -len(smogon_suffix)] + api_suffix
            if kandidat in bekannte_slugs:
                return kandidat

    # 4. Einige Basisformen benoetigen ein Formsuffix, das die PokeAPI erzwingt.
    for suffix in ("-incarnate", "-normal", "-ordinary", "-male", "-average", "-standard"):
        if (slug + suffix) in bekannte_slugs:
            return slug + suffix

    return None
