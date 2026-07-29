"""TRANSFORM -- Filterung, Harmonisierung, Aggregation und Anreicherung.

Die vier Teilschritte des Transformationsprozesses sind hier jeweils als eigene
Funktionsgruppe umgesetzt:

* **Filterung** -- Ausschluss unvollstaendiger oder fachlich unbrauchbarer Saetze
  (z.B. Pokemon ohne Typangabe, Nutzungsanteile ausserhalb des Wertebereichs).
* **Harmonisierung** -- Ueberfuehrung der beiden Quellbezeichnersysteme in einen
  gemeinsamen Schluessel (siehe :mod:`bi.etl.mapping`) sowie einheitliche
  Gross-/Kleinschreibung und Typbezeichnungen.
* **Aggregation** -- Verdichtung der gewichteten Smogon-Rohzaehler zu
  interpretierbaren Anteilen in Prozent.
* **Anreicherung** -- Ableitung fachlicher Zusatzmerkmale, die in keiner Quelle
  vorliegen: Basiswertsumme, offensives Profil, Rollen- und Speed-Klassifikation,
  defensive Resistenzkennzahl sowie die taktische Klasse einer Attacke.

Normalisierung der Smogon-Gewichte
----------------------------------
Smogon liefert gewichtete Zaehler, keine Prozentwerte. Als Bezugsgroesse dient die
Summe der Faehigkeitsgewichte, die dem Gesamtgewicht aller Sets eines Pokemon
entspricht (jedes Set hat genau eine Faehigkeit). Gegen die Quelldaten geprueft
gilt dann: Attackengewichte summieren auf das Vierfache, Item- und
Tera-Gewichte auf das Einfache und Partnergewichte auf das Fuenffache dieses
Bezugswerts -- konsistent mit vier Attacken, einem Item, einem Tera-Typ und fuenf
Teampartnern je Team.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from ..config import ALLE_TYPEN
from ..typechart import resistenz_kennzahl
from .mapping import loese_auf

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

STOER_FAEHIGKEITEN = {"intimidate", "unnerve", "trace", "download", "protosynthesis", "quarkdrive"}


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
    if zielbereich in ("all-opponents", "all-other-pokemon") and kategorie in ("physical", "special"):
        return "Flaechenschaden"
    if kategorie == "status":
        return "Status"
    return "Offensiv"


def faehigkeit_klasse(slug: str) -> str:
    """Ordnet einer Faehigkeit ihre Effektklasse zu."""
    if slug in WETTER_FAEHIGKEITEN:
        return "Wetter"
    if slug in TERRAIN_FAEHIGKEITEN:
        return "Terrain"
    if slug in STOER_FAEHIGKEITEN:
        return "Stoerung"
    return "Sonstige"


def item_kategorie(slug: str) -> str:
    """Grobe Warengruppe eines Items fuer die Auswertung."""
    if slug.startswith("choice"):
        return "Choice-Item"
    if slug.endswith("berry"):
        return "Beere"
    if slug in {"focussash", "assaultvest", "eviolite", "rockyhelmet", "safetygoggles",
                "covertcloak", "clearamulet", "loadeddice", "mentalherb"}:
        return "Defensiv/Utility"
    if slug in {"lifeorb", "expertbelt", "widelens", "muscleband", "wiseglasses",
                "boosterenergy", "throatspray", "weaknesspolicy"}:
        return "Offensiv"
    return "Sonstige"


def offensiv_profil(attack: int, sp_attack: int) -> str:
    """Bestimmt, ueber welche Angriffsart ein Pokemon Schaden austeilt."""
    if attack == 0 and sp_attack == 0:
        return "Kein Angriff"
    unterschied = abs(attack - sp_attack)
    if unterschied <= 15:
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
# Filterung + Harmonisierung + Anreicherung: Pokemon-Stammdaten
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


def _typ_normalisieren(name: str) -> str:
    """Vereinheitlicht Typbezeichner auf die Schreibweise der Regelbasis."""
    kandidat = name.strip().capitalize()
    return kandidat if kandidat in ALLE_TYPEN else name.strip().title()


def _anzeigename(slug: str) -> str:
    """Macht aus einem Slug einen lesbaren Namen (``iron-hands`` -> ``Iron Hands``)."""
    return " ".join(teil.capitalize() for teil in slug.replace("_", "-").split("-"))


def zeilen_hash(werte: tuple[Any, ...]) -> str:
    """Aenderungserkennung fuer die Delta-Historisierung.

    Der Hash umfasst genau die fachlich relevanten Attribute. Aendert sich eines
    davon, entsteht ein neuer Gueltigkeitszeitraum; technische Felder wie der
    Ladezeitpunkt bleiben bewusst aussen vor.
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

    hp, atk, df = werte["hp"], werte["attack"], werte["defense"]
    spa, spd, spe = werte["special-attack"], werte["special-defense"], werte["speed"]

    typ1 = _typ_normalisieren(typen[0]["type"]["name"])
    typ2 = _typ_normalisieren(typen[1]["type"]["name"]) if len(typen) > 1 else None
    spezies = (nutzlast.get("species") or {}).get("name", slug)

    satz = {
        "pokedex_id": nutzlast.get("id"),
        "slug": slug,
        "anzeigename": _anzeigename(slug),
        "spezies": spezies,
        "generation": generation_je_spezies.get(spezies, 0),
        "typ1": typ1,
        "typ2": typ2,
        "typ_kombination": f"{typ1} / {typ2}" if typ2 else typ1,
        "hp": hp, "attack": atk, "defense": df,
        "sp_attack": spa, "sp_defense": spd, "speed": spe,
        "basiswert_summe": hp + atk + df + spa + spd + spe,
        "offensiv_profil": offensiv_profil(atk, spa),
        "rolle": rolle(hp, atk, df, spa, spd, spe),
        "speed_klasse": speed_klasse(spe),
        "resistenz_wert": resistenz_kennzahl(typ1, typ2),
    }
    satz["row_hash"] = zeilen_hash((
        satz["pokedex_id"], typ1, typ2, hp, atk, df, spa, spd, spe, satz["generation"],
    ))
    return satz, None


def transformiere_attacke(nutzlast: dict[str, Any]) -> dict[str, Any]:
    """Erzeugt aus einer PokeAPI-Attackennutzlast einen Dimensionssatz."""
    slug = nutzlast["name"]
    kategorie = (nutzlast.get("damage_class") or {}).get("name")
    prioritaet = nutzlast.get("priority")
    zielbereich = (nutzlast.get("target") or {}).get("name")
    # Der Slug in den Smogon-Daten enthaelt keine Bindestriche.
    return {
        "slug": slug.replace("-", ""),
        "anzeigename": _anzeigename(slug),
        "typ": _typ_normalisieren((nutzlast.get("type") or {}).get("name", "")),
        "kategorie": kategorie,
        "basisschaden": nutzlast.get("power"),
        "genauigkeit": nutzlast.get("accuracy"),
        "prioritaet": prioritaet,
        "zielbereich": zielbereich,
        "taktik_klasse": taktik_klasse(slug.replace("-", ""), kategorie, prioritaet, zielbereich),
    }


# --------------------------------------------------------------------------
# Aggregation + Harmonisierung: Smogon-Bewegungsdaten
# --------------------------------------------------------------------------

# Erwartete Gewichtssummen je Merkmalsgruppe, ausgedrueckt als Vielfaches des
# Bezugsgewichts. Sie dienen nicht als Divisor -- geteilt wird stets durch das
# Bezugsgewicht selbst, damit ein Anteil von 100 Prozent "kommt in jedem Set vor"
# bedeutet. Die Vielfachen sind die Sollwerte der Plausibilitaetspruefung.
ERWARTETE_SUMMEN: dict[str, float] = {
    "Moves": 4.0,        # vier Attacken je Set
    "Items": 1.0,        # ein Item je Set
    "Tera Types": 1.0,   # ein Tera-Typ je Set
    "Abilities": 1.0,    # eine Faehigkeit je Set
    "Teammates": 5.0,    # fuenf Mitglieder neben dem betrachteten Pokemon
}

# Zulaessige relative Abweichung der Gewichtssumme vom Sollwert.
SUMMEN_TOLERANZ = 0.05

_LEERER_SLUG = re.compile(r"^\s*$")


def pruefe_gewichtssummen(roh: dict[str, Any], bezugsgewicht: float) -> dict[str, float]:
    """Plausibilitaetspruefung der Smogon-Gewichte gegen ihre Sollsummen.

    Weicht eine Summe deutlich ab, ist entweder das Quellformat geaendert oder der
    Datensatz unvollstaendig. Beides muss auffallen, bevor daraus Kennzahlen
    berechnet werden.

    Rueckgabe: je auffaelligem Merkmal die relative Abweichung. Ein leeres
    Ergebnis bedeutet, dass alle Summen im Toleranzband liegen.
    """
    abweichungen: dict[str, float] = {}
    if bezugsgewicht <= 0:
        return abweichungen

    for merkmal, sollfaktor in ERWARTETE_SUMMEN.items():
        werte = roh.get(merkmal) or {}
        ist = sum(v for v in werte.values() if isinstance(v, (int, float)))
        soll = bezugsgewicht * sollfaktor
        if soll <= 0:
            continue
        abweichung = abs(ist - soll) / soll
        if abweichung > SUMMEN_TOLERANZ:
            abweichungen[merkmal] = abweichung
    return abweichungen


def _anteile(rohwerte: dict[str, float], bezugsgewicht: float, grenze: int | None = None
             ) -> list[tuple[str, float, int]]:
    """Rechnet gewichtete Zaehler in Prozentanteile um und vergibt Raenge.

    Liefert ``(slug, anteil_prozent, rang)`` absteigend nach Anteil.
    """
    if bezugsgewicht <= 0:
        return []
    bereinigt = {
        k: v for k, v in rohwerte.items()
        if k and not _LEERER_SLUG.match(k) and isinstance(v, (int, float)) and v > 0
    }
    sortiert = sorted(bereinigt.items(), key=lambda kv: kv[1], reverse=True)
    if grenze:
        sortiert = sortiert[:grenze]
    return [(slug, round(wert / bezugsgewicht * 100, 3), rang)
            for rang, (slug, wert) in enumerate(sortiert, start=1)]


@dataclass
class UsageSatz:
    """Vollstaendig transformierter Datensatz eines Pokemon fuer einen Monat."""

    slug: str
    usage_rate: float
    raw_count: int
    gxe_top: float | None
    gxe_p75: float | None
    gxe_p50: float | None
    rang: int
    attacken: list[tuple[str, float, int]]
    items: list[tuple[str, float, int]]
    faehigkeiten: list[tuple[str, float, int]]
    tera_typen: list[tuple[str, float, int]]
    partner: list[tuple[str, float, int]]      # Partner-Slugs, bereits harmonisiert


def transformiere_usage_dump(
    dump: dict[str, Any],
    bekannte_slugs: set[str],
    partner_grenze: int = 12,
    auspraegungs_grenze: int = 12,
) -> tuple[list[UsageSatz], list[Befund], int]:
    """Ueberfuehrt einen Smogon-Chaos-Dump in Faktensaetze.

    Rueckgabe: ``(saetze, befunde, partien_gesamt)``.

    Die Beschraenkung auf die jeweils fuehrenden Auspraegungen ist eine bewusste
    Aggregation: die Verteilungen haben lange, praktisch bedeutungslose Auslaeufer
    (Attacken mit Anteilen unter 0,01 Prozent), deren Speicherung das Faktenvolumen
    vervielfachen wuerde, ohne die Auswertung zu verbessern.
    """
    daten: dict[str, Any] = dump.get("data") or {}
    partien = int((dump.get("info") or {}).get("number of battles") or 0)

    befunde: list[Befund] = []
    zwischenergebnis: list[tuple[str, dict[str, Any]]] = []

    # Schritt 1: Harmonisierung der Bezeichner.
    for quell_name, roh in daten.items():
        slug = loese_auf(quell_name, bekannte_slugs)
        if slug is None:
            befunde.append(Befund(
                "Fact_Usage", quell_name, "Referenzielle Integritaet",
                f"Bezeichner '{quell_name}' konnte keinem Eintrag der Pokemon-Dimension "
                "zugeordnet werden -- Satz wird nicht geladen",
                klasse="Mangel 2. Klasse", dimension="Referenzielle Integritaet"))
            continue
        zwischenergebnis.append((slug, roh))

    # Schritt 2: Dublettenpruefung auf dem harmonisierten Schluessel.
    gesehen: dict[str, str] = {}
    eindeutig: list[tuple[str, dict[str, Any]]] = []
    for slug, roh in zwischenergebnis:
        if slug in gesehen:
            befunde.append(Befund(
                "Fact_Usage", slug, "Eindeutigkeit",
                f"Mehrere Quellbezeichner zeigen auf '{slug}' -- Satz verworfen, "
                "um den Faktenschluessel eindeutig zu halten",
                klasse="Mangel 1. Klasse", dimension="Eindeutigkeit"))
            continue
        gesehen[slug] = slug
        eindeutig.append((slug, roh))

    # Schritt 3: Filterung, Aggregation und Rangvergabe.
    saetze: list[UsageSatz] = []
    summen_auffaelligkeiten: dict[str, list[float]] = {}
    for slug, roh in eindeutig:
        usage = float(roh.get("usage") or 0) * 100
        if not 0 <= usage <= 100:
            befunde.append(Befund(
                "Fact_Usage", slug, "Wertebereich",
                f"Nutzungsanteil {usage:.2f} liegt ausserhalb von 0-100 Prozent",
                klasse="Mangel 1. Klasse", dimension="Wertebereich"))
            continue

        faehigkeiten_roh: dict[str, float] = roh.get("Abilities") or {}
        bezugsgewicht = sum(v for v in faehigkeiten_roh.values() if isinstance(v, (int, float)))
        if bezugsgewicht <= 0:
            befunde.append(Befund(
                "Fact_Usage", slug, "Plausibilitaet",
                "Bezugsgewicht der Faehigkeiten ist 0 -- Anteile nicht berechenbar",
                klasse="Mangel 1. Klasse", dimension="Plausibilitaet"))
            continue

        # Auffaelligkeiten werden gesammelt und weiter unten je Merkmal zu einem
        # Befund verdichtet. Ein Eintrag je Pokemon wuerde das Protokoll fluten,
        # ohne mehr auszusagen als die Quote ueber alle Saetze.
        for merkmal, abweichung in pruefe_gewichtssummen(roh, bezugsgewicht).items():
            summen_auffaelligkeiten.setdefault(merkmal, []).append(abweichung)

        viability = roh.get("Viability Ceiling") or []
        gxe = [float(v) if isinstance(v, (int, float)) else None for v in viability[1:4]]
        gxe += [None] * (3 - len(gxe))

        partner_roh: dict[str, float] = roh.get("Teammates") or {}
        partner_harmonisiert: dict[str, float] = {}
        for partner_name, wert in partner_roh.items():
            partner_slug = loese_auf(partner_name, bekannte_slugs)
            if partner_slug:
                partner_harmonisiert[partner_slug] = float(wert)

        saetze.append(UsageSatz(
            slug=slug,
            usage_rate=round(usage, 4),
            raw_count=int(roh.get("Raw count") or 0),
            gxe_top=gxe[0], gxe_p75=gxe[1], gxe_p50=gxe[2],
            rang=0,  # wird nachgelagert vergeben
            # Divisor ist durchgehend das Bezugsgewicht: 100 Prozent bedeutet
            # damit "kommt in jedem Set beziehungsweise Team vor".
            attacken=_anteile(roh.get("Moves") or {}, bezugsgewicht, auspraegungs_grenze),
            items=_anteile(roh.get("Items") or {}, bezugsgewicht, auspraegungs_grenze),
            faehigkeiten=_anteile(faehigkeiten_roh, bezugsgewicht, 5),
            tera_typen=_anteile(roh.get("Tera Types") or {}, bezugsgewicht, auspraegungs_grenze),
            partner=_anteile(partner_harmonisiert, bezugsgewicht, partner_grenze),
        ))

    # Schritt 4: Anreicherung um den Usage-Rang des Monats.
    saetze.sort(key=lambda s: s.usage_rate, reverse=True)
    for rang, satz in enumerate(saetze, start=1):
        satz.rang = rang

    # Schritt 5: Verdichtung der Plausibilitaetsauffaelligkeiten zu je einem
    # Befund pro Merkmal.
    for merkmal, werte in sorted(summen_auffaelligkeiten.items()):
        werte.sort()
        median = werte[len(werte) // 2]
        befunde.append(Befund(
            "Fact_Usage", merkmal, "Plausibilitaet Gewichtssummen",
            f"{len(werte)} von {len(saetze)} Saetzen weichen bei '{merkmal}' um mehr als "
            f"{SUMMEN_TOLERANZ:.0%} von der erwarteten Gewichtssumme ab "
            f"(Median der Abweichung {median:.1%}). Die Anteile bleiben untereinander "
            "vergleichbar; die Quelle liefert die Verteilung offenbar gekuerzt.",
            klasse="Mangel 2. Klasse", dimension="Plausibilitaet", verworfen=False,
        ))

    return saetze, befunde, partien


def zeitdimension(monat_iso: str) -> dict[str, Any]:
    """Baut den Dimensionssatz zu einem Monat inklusive Konsolidierungspfad."""
    jahr, monat = (int(t) for t in monat_iso.split("-"))
    namen = ["Januar", "Februar", "Maerz", "April", "Mai", "Juni",
             "Juli", "August", "September", "Oktober", "November", "Dezember"]
    quartal = (monat - 1) // 3 + 1
    return {
        "zeit_sk": jahr * 100 + monat,   # sprechender Schluessel, z.B. 202606
        "monat_iso": monat_iso,
        "jahr": jahr,
        "quartal": quartal,
        "monat": monat,
        "monat_name": f"{namen[monat - 1]} {jahr}",
        "quartal_label": f"Q{quartal} {jahr}",
    }
