"""TRANSFORM -- Filterung, Harmonisierung und Anreicherung der Stammdaten.

Die Teilschritte des Transformationsprozesses:

* **Filterung** -- Ausschluss unvollstaendiger oder fachlich unbrauchbarer Saetze
  (Pokemon ohne Typangabe oder ohne vollstaendige Basiswerte).
* **Harmonisierung** -- Ueberfuehrung der Bezeichner beider Quellsysteme in einen
  gemeinsamen Schluessel (siehe :mod:`bi.etl.mapping`) sowie einheitliche
  Typbezeichnungen.
* **Anreicherung** -- Ableitung fachlicher Zusatzmerkmale, die in keiner Quelle
  vorliegen: Basiswertsumme, Statuswerte auf Turnierstufe 50, offensives Profil,
  Rollen- und Speed-Klassifikation, defensive Resistenzkennzahl sowie die
  taktische Klasse einer Attacke.

Die Transformation der Bewegungsdaten liegt in :mod:`bi.etl.champions`, weil sie
eng an das Satzformat jener Quelle gebunden ist.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..config import ALLE_TYPEN
from ..stats import STATUSWERTE, stufe50_grundwerte
from ..typechart import resistenz_kennzahl

# --------------------------------------------------------------------------
# Anreicherung: fachliche Klassifikationen
# --------------------------------------------------------------------------

# Attacken, die eine Strategie definieren und nicht ueber Strukturmerkmale der
# PokeAPI erkennbar sind.
TAKTIK_ATTACKEN: dict[str, str] = {
    "trickroom": "Bizarroraum",
    "tailwind": "Initiative-Kontrolle",
    "icywind": "Initiative-Kontrolle",
    "electroweb": "Initiative-Kontrolle",
    "thunderwave": "Initiative-Kontrolle",
    "stringshot": "Initiative-Kontrolle",
    "bulldoze": "Initiative-Kontrolle",
    "followme": "Umleitung",
    "ragepowder": "Umleitung",
    "spotlight": "Umleitung",
    "protect": "Schutz",
    "detect": "Schutz",
    "spikyshield": "Schutz",
    "banefulbunker": "Schutz",
    "burningbulwark": "Schutz",
    "silktrap": "Schutz",
    "wideguard": "Schutz",
    "quickguard": "Schutz",
    "haze": "Feldkontrolle",
    "clearsmog": "Feldkontrolle",
    "taunt": "Feldkontrolle",
    "encore": "Feldkontrolle",
    "helpinghand": "Unterstuetzung",
    "lightscreen": "Unterstuetzung",
    "reflect": "Unterstuetzung",
    "auroraveil": "Unterstuetzung",
    "trick": "Feldkontrolle",
    "switcheroo": "Feldkontrolle",
}

SETUP_ATTACKEN = {
    "swordsdance", "nastyplot", "dragondance", "calmmind", "bulkup", "irondefense",
    "shellsmash", "quiverdance", "victorydance", "tidyup", "curse", "howl",
}

WETTER_FAEHIGKEITEN = {
    "drizzle": "Regen", "drought": "Sonne", "sandstream": "Sandsturm",
    "snowwarning": "Schnee", "orichalcumpulse": "Sonne",
    "primordialsea": "Regen", "desolateland": "Sonne", "deltastream": "Luftstrom",
}

TERRAIN_FAEHIGKEITEN = {
    "grassysurge": "Grasfeld", "psychicsurge": "Psychofeld",
    "electricsurge": "Elektrofeld", "mistysurge": "Nebelfeld",
    # Hadronen-Motor setzt Elektrofeld, nicht Wetter.
    "hadronengine": "Elektrofeld",
}

STOER_FAEHIGKEITEN = {"intimidate", "unnerve", "trace", "download", "protosynthesis",
                      "quarkdrive"}


def taktik_klasse(slug: str, kategorie: str | None, prioritaet: int | None,
                  zielbereich: str | None) -> str:
    """Ordnet einer Attacke ihre taktische Funktion zu.

    Kombiniert eine Liste strategiedefinierender Attacken mit Strukturmerkmalen der
    PokeAPI (Prioritaet, Zielbereich, Schadenskategorie). Dadurch erkennt der
    Strategie-Radar auch Attacken, die nicht namentlich hinterlegt sind.
    """
    if slug in TAKTIK_ATTACKEN:
        return TAKTIK_ATTACKEN[slug]
    if slug in SETUP_ATTACKEN:
        return "Setup"
    if prioritaet and prioritaet > 0 and kategorie in ("physical", "special"):
        return "Prioritaet"
    if zielbereich in ("all-opponents", "all-other-pokemon") and kategorie in (
            "physical", "special"):
        return "Flaechenschaden"
    if kategorie == "status":
        return "Status"
    return "Offensiv"


def faehigkeit_klasse(name: str) -> str:
    """Ordnet einer Faehigkeit ihre Effektklasse zu."""
    slug = "".join(c for c in name.lower() if c.isalnum())
    if slug in WETTER_FAEHIGKEITEN:
        return "Wetter"
    if slug in TERRAIN_FAEHIGKEITEN:
        return "Terrain"
    if slug in STOER_FAEHIGKEITEN:
        return "Stoerung"
    return "Sonstige"


# Wirkungsklassen der Items. Die PokeAPI fuehrt eine eigene Kategorisierung,
# die aber am Verkaufsort ausgerichtet ist ("bad-held-items", "in-a-pinch") und
# fuer die Auswertung wenig hergibt. Massgeblich ist hier, *was das Item im
# Kampf tut* -- danach fragt die Itemauswertung, und danach rechnet der
# Schadensrechner.
ITEM_KLASSEN: dict[str, str] = {
    "choiceband": "Wahl-Item", "choicespecs": "Wahl-Item", "choicescarf": "Wahl-Item",
    "lifeorb": "Schadensverstaerkung", "expertbelt": "Schadensverstaerkung",
    "muscleband": "Schadensverstaerkung", "wiseglasses": "Schadensverstaerkung",
    "metronome": "Schadensverstaerkung", "punchingglove": "Schadensverstaerkung",
    "focussash": "Ueberleben", "focusband": "Ueberleben", "sitrusberry": "Ueberleben",
    "leftovers": "Ueberleben", "assaultvest": "Ueberleben", "eviolite": "Ueberleben",
    "rockyhelmet": "Ueberleben", "safetygoggles": "Ueberleben",
    "covertcloak": "Ueberleben", "clearamulet": "Ueberleben",
    "lightclay": "Unterstuetzung", "mentalherb": "Unterstuetzung",
    "whiteherb": "Unterstuetzung", "ejectbutton": "Unterstuetzung",
    "quickclaw": "Initiative", "roomservice": "Initiative", "boosterenergy": "Initiative",
    "widelens": "Praezision", "zoomlens": "Praezision", "scopelens": "Praezision",
}

# Kategorien der PokeAPI, deren Items im Kampf getragen werden koennen. Alles
# uebrige -- Basisbaelle, Entwicklungssteine, Questgegenstaende -- ist fuer die
# Auswertung ohne Belang und wird gekennzeichnet, nicht verworfen: die Quelle
# soll vollstaendig abgebildet bleiben.
KAMPFRELEVANTE_ITEM_KATEGORIEN = frozenset({
    "held-items", "effort-training", "bad-held-items", "training", "plates",
    "species-specific", "type-enhancement", "choice", "in-a-pinch", "picky-healing",
    "type-protection", "baking-only", "collectibles", "jewels", "mega-stones",
    "memories", "other", "effort-drop", "medicine", "vitamins", "healing",
    "status-cures", "revival", "field-effects",
})


def item_klasse(slug: str, kategorie: str | None) -> str:
    """Ordnet einem Item seine Wirkung im Kampf zu.

    Zuerst ueber die namentliche Liste, danach ueber die Kategorie der PokeAPI.
    Beeren sind der Grenzfall: sie sind eine eigene Kategorie und wirken sehr
    unterschiedlich, tragen aber alle dieselbe Bedienlogik -- sie loesen bei
    einer Bedingung einmalig aus.
    """
    if slug in ITEM_KLASSEN:
        return ITEM_KLASSEN[slug]
    if slug.endswith("berry"):
        return "Beere"
    if kategorie in ("plates", "type-enhancement", "jewels"):
        return "Typverstaerkung"
    if kategorie in ("mega-stones", "species-specific", "memories"):
        return "Formwandel"
    return "Sonstige"


def _englischer_text(eintraege: list[dict[str, Any]], feld: str) -> str | None:
    """Zieht den englischen Kurztext aus den mehrsprachigen Eintraegen der PokeAPI.

    Deutsch waere naheliegender, ist bei Items und Faehigkeiten aber nur
    lueckenhaft gepflegt; ein fehlender Text waere schlechter als ein
    englischer.
    """
    for eintrag in eintraege or []:
        if (eintrag.get("language") or {}).get("name") == "en" and eintrag.get(feld):
            return " ".join(str(eintrag[feld]).split())
    return None


def transformiere_item(nutzlast: dict[str, Any]) -> dict[str, Any]:
    """Ueberfuehrt eine PokeAPI-Itemnutzlast in einen Dimensionssatz.

    Der Schluessel ist der kompakte Bezeichner ohne Bindestriche -- dieselbe
    Schreibweise, auf die die Champions-Anzeigenamen gebracht werden. Nur so
    lassen sich beide Quellen verknuepfen.
    """
    pokeapi_slug = nutzlast.get("name", "")
    slug = "".join(c for c in pokeapi_slug.lower() if c.isalnum())
    kategorie = (nutzlast.get("category") or {}).get("name")
    return {
        "slug": slug,
        "pokeapi_slug": pokeapi_slug,
        "anzeigename": " ".join(w.capitalize() for w in pokeapi_slug.split("-")),
        "kategorie": kategorie,
        "wirkung_klasse": item_klasse(slug, kategorie),
        "effekt_kurz": _englischer_text(nutzlast.get("effect_entries", []), "short_effect"),
        "ist_kampfrelevant": int(kategorie in KAMPFRELEVANTE_ITEM_KATEGORIEN),
        "fling_staerke": nutzlast.get("fling_power"),
    }


def transformiere_faehigkeit(nutzlast: dict[str, Any]) -> dict[str, Any]:
    """Ueberfuehrt eine PokeAPI-Faehigkeitsnutzlast in einen Dimensionssatz."""
    pokeapi_slug = nutzlast.get("name", "")
    generation = (nutzlast.get("generation") or {}).get("name", "")
    ziffern = "".join(c for c in generation if c.isdigit())
    return {
        "slug": "".join(c for c in pokeapi_slug.lower() if c.isalnum()),
        "pokeapi_slug": pokeapi_slug,
        "anzeigename": " ".join(w.capitalize() for w in pokeapi_slug.split("-")),
        "wirkung_klasse": faehigkeit_klasse(pokeapi_slug),
        "effekt_kurz": _englischer_text(nutzlast.get("effect_entries", []), "short_effect"),
        "generation": _roemisch_zu_zahl(generation) if not ziffern else int(ziffern),
    }


# Die PokeAPI gibt Generationen als 'generation-vii' aus.
_ROEMISCH = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
             "vi": 6, "vii": 7, "viii": 8, "ix": 9}


def _roemisch_zu_zahl(generation: str) -> int | None:
    return _ROEMISCH.get(generation.rpartition("-")[2])


def offensiv_profil(attack: int, sp_attack: int) -> str:
    """Bestimmt, ueber welche Angriffsart ein Pokemon Schaden austeilt."""
    if attack == 0 and sp_attack == 0:
        return "Kein Angriff"
    if abs(attack - sp_attack) <= 15:
        return "Gemischt"
    return "Physisch" if attack > sp_attack else "Speziell"


def speed_klasse(speed: int) -> str:
    """Klassifiziert die Basis-Initiative in Turnier-uebliche Baender."""
    if speed >= 120:
        return "Sehr schnell (120+)"
    if speed >= 100:
        return "Schnell (100-119)"
    if speed >= 80:
        return "Mittel (80-99)"
    if speed >= 60:
        return "Langsam (60-79)"
    return "Sehr langsam (<60)"


def rolle(hp: int, attack: int, defense: int, sp_attack: int, sp_defense: int,
          speed: int) -> str:
    """Leitet eine Teamrolle aus dem Verhaeltnis der Basiswerte ab.

    Heuristik, keine amtliche Klassifikation -- sie dient der Gruppierung im
    OLAP-Bericht und macht die Dimension entlang einer fachlichen Achse
    auswertbar.
    """
    offensive = max(attack, sp_attack)
    defensive = (hp + defense + sp_defense) / 3

    if speed >= 100 and offensive >= 110:
        return "Schneller Sweeper"
    if speed <= 55 and offensive >= 110:
        return "Bizarroraum-Angreifer"
    if offensive >= 120:
        return "Wallbreaker"
    if defensive >= 95 and offensive < 95:
        return "Defensive Wand"
    if defensive >= 85:
        return "Bulky Offense"
    if offensive < 85 and defensive < 85:
        return "Support/Utility"
    return "Allrounder"


# --------------------------------------------------------------------------
# Datenqualitaetsbefunde
# --------------------------------------------------------------------------

@dataclass
class Befund:
    """Ein Datenqualitaetsbefund aus dem Transformationsschritt.

    ``verworfen`` unterscheidet die beiden Konsequenzen: entweder wird der Satz
    nicht geladen (Mangel, der die Auswertung verfaelschen wuerde), oder er wird
    geladen und der Befund lediglich protokolliert (Auffaelligkeit ohne
    unmittelbare Auswirkung auf die Kennzahlen).
    """

    entitaet: str
    schluessel: str
    regel: str
    meldung: str
    klasse: str = "Mangel 2. Klasse"
    dimension: str = "Konsistenz"
    verworfen: bool = True


# --------------------------------------------------------------------------
# Pokemon-Stammdaten
# --------------------------------------------------------------------------

def _typ_normalisieren(name: str) -> str:
    """Vereinheitlicht Typbezeichner auf die Schreibweise der Regelbasis."""
    kandidat = name.strip().capitalize()
    return kandidat if kandidat in ALLE_TYPEN else name.strip().title()


def anzeigename(slug: str) -> str:
    """Macht aus einem Slug einen lesbaren Namen (``iron-hands`` -> ``Iron Hands``)."""
    return " ".join(teil.capitalize() for teil in slug.replace("_", "-").split("-"))


def zeilen_hash(werte: tuple[Any, ...]) -> str:
    """Aenderungserkennung fuer die Delta-Historisierung.

    Der Hash umfasst genau die fachlich relevanten Attribute. Aendert sich eines
    davon -- etwa durch eine Balance-Anpassung zwischen zwei Saisons --, entsteht
    ein neuer Gueltigkeitszeitraum; technische Felder wie der Ladezeitpunkt
    bleiben bewusst aussen vor.
    """
    roh = "|".join("" if w is None else str(w) for w in werte)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32]


def transformiere_pokemon(nutzlast: dict[str, Any], generation_je_spezies: dict[str, int]
                          ) -> tuple[dict[str, Any] | None, Befund | None]:
    """Erzeugt aus einer PokeAPI-Nutzlast einen Dimensionssatz.

    Gibt ``(satz, None)`` oder ``(None, befund)`` zurueck.
    """
    slug = nutzlast.get("name")
    if not slug:
        return None, Befund(
            "Dim_Pokemon", "?", "Pflichtfeld name", "Satz ohne Bezeichner",
            klasse="Mangel 1. Klasse", dimension="Vollstaendigkeit")

    typen = nutzlast.get("types") or []
    if not typen:
        return None, Befund(
            "Dim_Pokemon", slug, "Pflichtfeld types",
            "Kein Typ hinterlegt -- fuer die Typenanalyse unbrauchbar",
            klasse="Mangel 1. Klasse", dimension="Vollstaendigkeit")

    werte = {s["stat"]["name"]: s["base_stat"] for s in nutzlast.get("stats", [])}
    pflicht = ("hp", "attack", "defense", "special-attack", "special-defense", "speed")
    if not all(k in werte for k in pflicht):
        fehlend = [k for k in pflicht if k not in werte]
        return None, Befund(
            "Dim_Pokemon", slug, "Vollstaendigkeit Basiswerte",
            f"Fehlende Basiswerte: {', '.join(fehlend)}",
            klasse="Mangel 1. Klasse", dimension="Vollstaendigkeit")

    basis = {
        "hp": werte["hp"], "attack": werte["attack"], "defense": werte["defense"],
        "sp_attack": werte["special-attack"], "sp_defense": werte["special-defense"],
        "speed": werte["speed"],
    }
    typ1 = _typ_normalisieren(typen[0]["type"]["name"])
    typ2 = _typ_normalisieren(typen[1]["type"]["name"]) if len(typen) > 1 else None
    spezies = (nutzlast.get("species") or {}).get("name", slug)

    # Anreicherung: die im Spiel angezeigten Werte auf Turnierstufe 50.
    stufe50 = stufe50_grundwerte(basis)

    satz = {
        "pokedex_id": nutzlast.get("id"),
        "slug": slug,
        "anzeigename": anzeigename(slug),
        "spezies": spezies,
        "generation": generation_je_spezies.get(spezies, 0),
        "typ1": typ1,
        "typ2": typ2,
        "typ_kombination": f"{typ1} / {typ2}" if typ2 else typ1,
        **basis,
        **{f"stufe50_{name}": stufe50[name] for name in STATUSWERTE},
        "basiswert_summe": sum(basis.values()),
        "offensiv_profil": offensiv_profil(basis["attack"], basis["sp_attack"]),
        "rolle": rolle(**basis),
        "speed_klasse": speed_klasse(basis["speed"]),
        "resistenz_wert": resistenz_kennzahl(typ1, typ2),
    }
    satz["row_hash"] = zeilen_hash(
        (satz["pokedex_id"], typ1, typ2, *(basis[n] for n in STATUSWERTE),
         satz["generation"]))
    return satz, None


def transformiere_attacke(nutzlast: dict[str, Any]) -> dict[str, Any]:
    """Erzeugt aus einer PokeAPI-Attackennutzlast einen Dimensionssatz."""
    slug = nutzlast["name"]
    kategorie = (nutzlast.get("damage_class") or {}).get("name")
    prioritaet = nutzlast.get("priority")
    zielbereich = (nutzlast.get("target") or {}).get("name")
    kompakt = slug.replace("-", "")

    return {
        # Kompakte Schreibweise als Schluessel -- so laesst sich der von Champions
        # gelieferte Anzeigename ohne Umweg verknuepfen.
        "slug": kompakt,
        "anzeigename": anzeigename(slug),
        "typ": _typ_normalisieren((nutzlast.get("type") or {}).get("name", "")),
        "kategorie": kategorie,
        "basisschaden": nutzlast.get("power"),
        "genauigkeit": nutzlast.get("accuracy"),
        "prioritaet": prioritaet,
        "zielbereich": zielbereich,
        "taktik_klasse": taktik_klasse(kompakt, kategorie, prioritaet, zielbereich),
    }


# --------------------------------------------------------------------------
# Zeitdimension
# --------------------------------------------------------------------------

MONATSNAMEN = ["Januar", "Februar", "Maerz", "April", "Mai", "Juni",
               "Juli", "August", "September", "Oktober", "November", "Dezember"]

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag"]


def zeitdimension(datum_iso: str) -> dict[str, Any]:
    """Dimensionssatz zu einem Tag inklusive Konsolidierungspfad.

    Die Quelle liefert taeglich; Monat, Quartal und Jahr sind die
    Verdichtungsstufen darueber.
    """
    from datetime import date

    tag_datum = date.fromisoformat(datum_iso)
    quartal = (tag_datum.month - 1) // 3 + 1

    return {
        "zeit_sk": tag_datum.year * 10000 + tag_datum.month * 100 + tag_datum.day,
        "datum_iso": datum_iso,
        "jahr": tag_datum.year,
        "quartal": quartal,
        "monat": tag_datum.month,
        "tag": tag_datum.day,
        "monat_iso": f"{tag_datum.year:04d}-{tag_datum.month:02d}",
        "monat_name": f"{MONATSNAMEN[tag_datum.month - 1]} {tag_datum.year}",
        "quartal_label": f"Q{quartal} {tag_datum.year}",
        "tag_label": f"{tag_datum.day:02d}.{tag_datum.month:02d}.{tag_datum.year}",
        "wochentag": WOCHENTAGE[tag_datum.weekday()],
    }
