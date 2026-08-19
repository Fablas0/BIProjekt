"""EXTRACT -- Datenabzug der Stammdaten aus der PokeAPI.

Die PokeAPI ist die Quelle fuer alles, was aus den **Hauptspielen** stammt:
Pokemon mit Typen und Basiswerten, Attacken, Items und Faehigkeiten. Pokemon
Champions liefert zu Items und Faehigkeiten ausschliesslich den Anzeigenamen --
ihre Wirkung, Kategorie und Staerke existieren nur in den Hauptspielen.

Sie ist sauber strukturiert, aber nur einzelsatzweise abrufbar: rund 1350 Pokemon bedeuten
ebenso viele Aufrufe. Der Abzug wird daher parallelisiert und ueber eine
wiederverwendete Sitzung abgewickelt.

Die Bewegungsdaten stammen aus einem eigenen Quellsystem und werden in
:mod:`bi.etl.champions` abgezogen.

Der Extract laedt ausschliesslich und transformiert nicht.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import (
    GENERATIONEN,
    HTTP_THREADS,
    HTTP_TIMEOUT,
    HTTP_WIEDERHOLUNGEN,
    POKEAPI_BASIS,
)

Fortschritt = Callable[[float, str], None]


def _kein_fortschritt(_anteil: float, _text: str) -> None:
    """Platzhalter, wenn kein Fortschritts-Callback uebergeben wird."""


def sitzung() -> requests.Session:
    """HTTP-Sitzung mit Wiederholungslogik und Verbindungs-Pooling.

    Ohne Pooling wuerde jeder der rund 1350 Aufrufe einen neuen TLS-Handshake
    ausloesen; das dominiert sonst die Laufzeit des Erstimports.
    """
    s = requests.Session()
    strategie = Retry(
        total=HTTP_WIEDERHOLUNGEN,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=strategie, pool_connections=HTTP_THREADS,
                          pool_maxsize=HTTP_THREADS)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": "VGC-BI/1.0 (Hochschulprojekt Business Intelligence)"})
    return s


def _hole_json(s: requests.Session, url: str) -> Any:
    antwort = s.get(url, timeout=HTTP_TIMEOUT)
    antwort.raise_for_status()
    return antwort.json()


def _sicher_json(s: requests.Session, url: str) -> Any | None:
    """Wie ``_hole_json``, gibt bei endgueltigem Fehlschlag aber ``None`` zurueck.

    Ein einzelner nicht erreichbarer Datensatz darf den Gesamtlauf nicht abbrechen;
    der Ausfall wird spaeter als Datenqualitaetsbefund sichtbar.
    """
    try:
        return _hole_json(s, url)
    except Exception:
        return None


def _parallel(s: requests.Session, urls: Iterable[str], fortschritt: Fortschritt,
              text: str) -> list[Any]:
    """Laedt eine URL-Liste nebenlaeufig und meldet den Fortschritt."""
    urls = list(urls)
    if not urls:
        return []

    ergebnisse: list[Any] = [None] * len(urls)
    with ThreadPoolExecutor(max_workers=HTTP_THREADS) as pool:
        for i, wert in enumerate(pool.map(lambda u: _sicher_json(s, u), urls)):
            ergebnisse[i] = wert
            if i % 25 == 0 or i == len(urls) - 1:
                fortschritt((i + 1) / len(urls), f"{text} ({i + 1}/{len(urls)})")
    return ergebnisse


@dataclass
class StammdatenAbzug:
    """Ergebnis des PokeAPI-Extrakts."""

    pokemon: list[dict[str, Any]] = field(default_factory=list)
    generation_je_spezies: dict[str, int] = field(default_factory=dict)
    namen_de: dict[str, str] = field(default_factory=dict)
    fehlversuche: list[str] = field(default_factory=list)


def hole_generationszuordnung(s: requests.Session, fortschritt: Fortschritt) -> dict[str, int]:
    """Ordnet jeder Spezies ihre Generation zu.

    Neun Sammelabfragen statt rund 1000 Einzelabfragen auf ``/pokemon-species``.
    """
    zuordnung: dict[str, int] = {}
    for i, gen in enumerate(GENERATIONEN):
        daten = _sicher_json(s, f"{POKEAPI_BASIS}/generation/{gen}")
        if not daten:
            continue
        for spezies in daten.get("pokemon_species", []):
            zuordnung[spezies["name"]] = gen
        fortschritt((i + 1) / len(GENERATIONEN), f"Generationen ({i + 1}/{len(GENERATIONEN)})")
    return zuordnung


def hole_speziesnamen(s: requests.Session, fortschritt: Fortschritt = _kein_fortschritt,
                      ueberspringen: frozenset[str] = frozenset()) -> dict[str, str]:
    """Laedt die deutschen Namen der Spezies -- bedarfsgesteuert.

    Die Uebersetzungen stehen ausschliesslich an der Spezies-Ressource, nicht
    an ``/pokemon``. Ein voller Durchlauf waeren rund 1000 weitere, wegen der
    Beschreibungstexte grosse Ressourcen -- und der Stammdatenlauf faehrt
    taeglich. ``ueberspringen`` nennt deshalb die bereits uebersetzten
    Spezies: abgerufen wird nur, was fehlt, im Regelbetrieb also nichts bis
    eine neue Spielgeneration erscheint. Fuer die uebersprungenen schreibt der
    Ladeschritt die vorhandenen Namen fort; ein Fehlschlag einzelner Saetze
    laesst die Anzeige auf den englischen Namen zurueckfallen.
    """
    verzeichnis = _sicher_json(s, f"{POKEAPI_BASIS}/pokemon-species?limit=20000")
    eintraege = [eintrag for eintrag in (verzeichnis or {}).get("results", [])
                 if eintrag["name"] not in ueberspringen]
    rohdaten = _parallel(s, (eintrag["url"] for eintrag in eintraege), fortschritt,
                         "Lade deutsche Namen")

    namen: dict[str, str] = {}
    for eintrag, daten in zip(eintraege, rohdaten, strict=True):
        for uebersetzung in (daten or {}).get("names", []):
            if (uebersetzung.get("language") or {}).get("name") == "de":
                namen[eintrag["name"]] = uebersetzung["name"]
                break
    return namen


def hole_pokemon_stammdaten(s: requests.Session, fortschritt: Fortschritt = _kein_fortschritt,
                            uebersetzte_spezies: frozenset[str] = frozenset()
                            ) -> StammdatenAbzug:
    """Laedt den vollstaendigen Pokemon-Bestand inklusive Basiswerten und Typen.

    ``uebersetzte_spezies`` begrenzt den Namensabzug auf das Fehlende --
    siehe :func:`hole_speziesnamen`.
    """
    abzug = StammdatenAbzug()

    fortschritt(0.0, "Lese Ressourcenverzeichnis der PokeAPI ...")
    verzeichnis = _hole_json(s, f"{POKEAPI_BASIS}/pokemon?limit=20000")["results"]

    abzug.generation_je_spezies = hole_generationszuordnung(s, fortschritt)
    abzug.namen_de = hole_speziesnamen(s, fortschritt, uebersetzte_spezies)

    rohdaten = _parallel(s, (eintrag["url"] for eintrag in verzeichnis), fortschritt,
                         "Lade Pokemon-Stammdaten")
    for eintrag, daten in zip(verzeichnis, rohdaten, strict=True):
        if daten is None:
            abzug.fehlversuche.append(eintrag["name"])
        else:
            abzug.pokemon.append(daten)
    return abzug


def verzeichnis_kompakt(s: requests.Session, ressource: str) -> dict[str, str]:
    """Bildet bindestrichlose Bezeichner auf die PokeAPI-Slugs ab.

    Pokemon Champions liefert Attackennamen als Anzeigetext (``"Dragon Claw"``),
    die PokeAPI erwartet einen Slug (``"dragon-claw"``). Die Wortgrenze ist aus
    dem kompakten Namen nicht rekonstruierbar, daher wird einmalig das
    Ressourcenverzeichnis geladen und darueber abgeglichen.
    """
    antwort = s.get(f"{POKEAPI_BASIS}/{ressource}?limit=3000", timeout=HTTP_TIMEOUT)
    if antwort.status_code != 200:
        return {}
    return {
        eintrag["name"].replace("-", ""): eintrag["name"]
        for eintrag in antwort.json().get("results", [])
    }


def hole_attacken(s: requests.Session, slugs: Iterable[str],
                  fortschritt: Fortschritt = _kein_fortschritt) -> list[dict[str, Any]]:
    """Laedt Detaildaten zu den uebergebenen Attacken.

    Bewusst auf die im Metagame vorkommenden Attacken beschraenkt: das sind rund
    400 statt ueber 900 Ressourcen.
    """
    urls = [f"{POKEAPI_BASIS}/move/{slug}" for slug in sorted(set(slugs))]
    ergebnisse = _parallel(s, urls, fortschritt, "Lade Attacken-Stammdaten")
    return [e for e in ergebnisse if e is not None]


def hole_items(s: requests.Session, slugs: Iterable[str],
               fortschritt: Fortschritt = _kein_fortschritt) -> list[dict[str, Any]]:
    """Laedt Detaildaten zu den uebergebenen Items.

    Wie bei den Attacken bedarfsgesteuert: geladen wird, was in den
    Bewegungsdaten tatsaechlich vorkommt. Von den rund 2100 Items der PokeAPI
    sind das etwa 60 -- der Rest sind Basisbaelle, Entwicklungssteine und
    Questgegenstaende ohne Kampfbezug.
    """
    urls = [f"{POKEAPI_BASIS}/item/{slug}" for slug in sorted(set(slugs))]
    ergebnisse = _parallel(s, urls, fortschritt, "Lade Item-Stammdaten")
    return [e for e in ergebnisse if e is not None]


def hole_faehigkeiten(s: requests.Session, slugs: Iterable[str],
                      fortschritt: Fortschritt = _kein_fortschritt) -> list[dict[str, Any]]:
    """Laedt Detaildaten zu den uebergebenen Faehigkeiten."""
    urls = [f"{POKEAPI_BASIS}/ability/{slug}" for slug in sorted(set(slugs))]
    ergebnisse = _parallel(s, urls, fortschritt, "Lade Faehigkeiten-Stammdaten")
    return [e for e in ergebnisse if e is not None]
