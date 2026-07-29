"""EXTRACT -- Datenabzug aus den Quellsystemen.

Zwei Quellen mit sehr unterschiedlichem Charakter:

* **PokeAPI** (REST/JSON, ~1350 Ressourcen): saubere Stammdaten, aber nur
  einzelsatzweise abrufbar. Wird parallelisiert und im Prozess zwischengespeichert.
* **Smogon Usage Stats** (statisches Verzeichnis + JSON-Dumps): Bewegungsdaten
  ohne Schema-Zusage und ohne stabile Dateinamen. Die verfuegbaren Monate und
  Formate muessen aus dem HTML-Verzeichnisindex erschlossen werden.

Der Extract laedt ausschliesslich und transformiert nicht -- die Rohnutzlast geht
unveraendert in die Staging-Schicht.
"""

from __future__ import annotations

import re
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
    SMOGON_BASIS,
)

Fortschritt = Callable[[float, str], None]


def _kein_fortschritt(_anteil: float, _text: str) -> None:
    """Platzhalter, wenn kein Fortschritts-Callback uebergeben wird."""


def sitzung() -> requests.Session:
    """HTTP-Sitzung mit Wiederholungslogik und Verbindungs-Pooling.

    Ohne Pooling wuerde jeder der ~1350 Aufrufe einen neuen TLS-Handshake
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


def _parallel(s: requests.Session, urls: Iterable[str], fortschritt: Fortschritt,
              text: str) -> list[Any]:
    """Laedt eine URL-Liste nebenlaeufig und meldet den Fortschritt."""
    urls = list(urls)
    ergebnisse: list[Any] = [None] * len(urls)
    if not urls:
        return []

    with ThreadPoolExecutor(max_workers=HTTP_THREADS) as pool:
        for i, wert in enumerate(pool.map(lambda u: _sicher_json(s, u), urls)):
            ergebnisse[i] = wert
            if i % 25 == 0 or i == len(urls) - 1:
                fortschritt((i + 1) / len(urls), f"{text} ({i + 1}/{len(urls)})")
    return ergebnisse


def _sicher_json(s: requests.Session, url: str) -> Any | None:
    """Wie ``_hole_json``, gibt bei endgueltigem Fehlschlag aber ``None`` zurueck.

    Ein einzelner nicht erreichbarer Datensatz darf den Gesamtlauf nicht abbrechen;
    der Ausfall wird spaeter als Datenqualitaetsbefund sichtbar.
    """
    try:
        return _hole_json(s, url)
    except Exception:
        return None


# --------------------------------------------------------------------------
# PokeAPI
# --------------------------------------------------------------------------

@dataclass
class StammdatenAbzug:
    """Ergebnis des PokeAPI-Extrakts."""

    pokemon: list[dict[str, Any]] = field(default_factory=list)
    generation_je_spezies: dict[str, int] = field(default_factory=dict)
    attacken: list[dict[str, Any]] = field(default_factory=list)
    fehlversuche: list[str] = field(default_factory=list)


def hole_generationszuordnung(s: requests.Session, fortschritt: Fortschritt) -> dict[str, int]:
    """Ordnet jeder Spezies ihre Generation zu.

    Neun Sammelabfragen statt ~1000 Einzelabfragen auf ``/pokemon-species``.
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


def hole_pokemon_stammdaten(s: requests.Session, fortschritt: Fortschritt = _kein_fortschritt
                            ) -> StammdatenAbzug:
    """Laedt den vollstaendigen Pokemon-Bestand inklusive Basiswerten und Typen."""
    abzug = StammdatenAbzug()

    fortschritt(0.0, "Lese Ressourcenverzeichnis der PokeAPI ...")
    verzeichnis = _hole_json(s, f"{POKEAPI_BASIS}/pokemon?limit=20000")["results"]

    abzug.generation_je_spezies = hole_generationszuordnung(s, fortschritt)

    rohdaten = _parallel(s, (eintrag["url"] for eintrag in verzeichnis), fortschritt,
                         "Lade Pokemon-Stammdaten")
    for eintrag, daten in zip(verzeichnis, rohdaten, strict=True):
        if daten is None:
            abzug.fehlversuche.append(eintrag["name"])
        else:
            abzug.pokemon.append(daten)
    return abzug


def hole_attacken(s: requests.Session, slugs: Iterable[str],
                  fortschritt: Fortschritt = _kein_fortschritt) -> list[dict[str, Any]]:
    """Laedt Detaildaten zu den tatsaechlich gespielten Attacken.

    Bewusst nachgelagert und auf die im Meta vorkommenden Attacken beschraenkt:
    das sind rund 400 statt ueber 900 Ressourcen.
    """
    slugs = sorted(set(slugs))
    urls = [f"{POKEAPI_BASIS}/move/{slug}" for slug in slugs]
    ergebnisse = _parallel(s, urls, fortschritt, "Lade Attacken-Stammdaten")
    return [e for e in ergebnisse if e is not None]


# --------------------------------------------------------------------------
# Smogon Usage Stats
# --------------------------------------------------------------------------

_MONAT_MUSTER = re.compile(r'href="(\d{4}-\d{2})/"')
_DATEI_MUSTER = re.compile(r'href="(gen\d+vgc[^"]+\.json)"')
_REG_MUSTER = re.compile(r"reg([a-z])(bo3)?", re.IGNORECASE)
_SAISON_MUSTER = re.compile(r"vgc(\d{4})")


@dataclass(frozen=True)
class Datenabzugsziel:
    """Ein konkret ladbarer Smogon-Datensatz."""

    monat_iso: str
    format_code: str      # 'gen9vgc2026regi'
    elo_cutoff: int
    url: str

    @property
    def regulation(self) -> str:
        treffer = _REG_MUSTER.search(self.format_code)
        return f"Reg {treffer.group(1).upper()}" if treffer else "Unbekannt"

    @property
    def spielmodus(self) -> str:
        return "Bo3" if self.format_code.endswith("bo3") else "Bo1"

    @property
    def saison(self) -> str:
        treffer = _SAISON_MUSTER.search(self.format_code)
        return f"VGC {treffer.group(1)}" if treffer else "VGC"

    @property
    def generation(self) -> str:
        treffer = re.match(r"gen(\d+)", self.format_code)
        return f"Gen {treffer.group(1)}" if treffer else "Gen 9"

    @property
    def anzeige(self) -> str:
        return f"{self.saison} {self.regulation} ({self.spielmodus})"


def verfuegbare_monate(s: requests.Session, grenze: int = 24) -> list[str]:
    """Liest die im Smogon-Verzeichnis vorhandenen Monate, absteigend sortiert."""
    text = s.get(f"{SMOGON_BASIS}/", timeout=HTTP_TIMEOUT).text
    monate = sorted(set(_MONAT_MUSTER.findall(text)), reverse=True)
    return monate[:grenze]


def verfuegbare_formate(s: requests.Session, monat_iso: str) -> list[tuple[str, int]]:
    """Listet die VGC-Dateien eines Monats als ``(format_code, elo_cutoff)``."""
    antwort = s.get(f"{SMOGON_BASIS}/{monat_iso}/chaos/", timeout=HTTP_TIMEOUT)
    if antwort.status_code != 200:
        return []

    ergebnis: list[tuple[str, int]] = []
    for datei in _DATEI_MUSTER.findall(antwort.text):
        stamm = datei.removesuffix(".json")
        format_code, _, elo = stamm.rpartition("-")
        if format_code and elo.isdigit():
            ergebnis.append((format_code, int(elo)))
    return sorted(set(ergebnis))


def finde_ziele(s: requests.Session, format_code: str, elo_cutoff: int,
                anzahl_monate: int) -> list[Datenabzugsziel]:
    """Sucht die letzten ``anzahl_monate`` Datensaetze eines Formats.

    Das gewuenschte Format existiert nicht in jedem Monat (Regulationen wechseln
    im Turnierkalender). Es wird daher rueckwaerts gesucht, bis genug Monate
    beisammen sind oder das Archiv erschoepft ist.
    """
    ziele: list[Datenabzugsziel] = []
    for monat in verfuegbare_monate(s):
        if len(ziele) >= anzahl_monate:
            break
        if (format_code, elo_cutoff) in verfuegbare_formate(s, monat):
            ziele.append(Datenabzugsziel(
                monat_iso=monat,
                format_code=format_code,
                elo_cutoff=elo_cutoff,
                url=f"{SMOGON_BASIS}/{monat}/chaos/{format_code}-{elo_cutoff}.json",
            ))
    return sorted(ziele, key=lambda z: z.monat_iso)


def hole_usage_dump(s: requests.Session, ziel: Datenabzugsziel) -> dict[str, Any] | None:
    """Laedt einen einzelnen Chaos-Dump (5-15 MB JSON)."""
    return _sicher_json(s, ziel.url)
