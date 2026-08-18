"""ETL-Strecke fuer das Quellsystem Pokemon Champions.

Pokemon Champions ist seit April 2026 die offizielle Wettkampfplattform; die dort
gespielte Meta unterscheidet sich deutlich von der des Simulators Pokemon
Showdown. Fuer die Frage, welches Team im Turnier trägt, ist diese Quelle daher
die massgebliche.

Zwei Eigenheiten praegen die Umsetzung:

**Die Quelle vergisst.** Es werden nur rund zwei Wochen Tagesstaende vorgehalten.
Faellt ein Tag heraus, ist er nicht nachladbar. Jeder Lauf schreibt die
Rohnutzlast deshalb in ``Archiv_Champions``; diese Tabelle wird nie bereinigt.
Nach einigen Monaten Betrieb entsteht so eine Zeitreihe, die es an der Quelle
selbst nicht gibt -- der eigentliche Zweck eines Data Warehouse.

**Die Quelle liefert keine Nutzungsquote,** sondern nur einen Rang. Statt einen
Platzhalter zu erfinden, bleibt das Quotenfeld leer; ergaenzt wird ein auf 0 bis
100 normiertes Rangperzentil, das ausdruecklich als abgeleitete Groesse
gekennzeichnet ist.

**Champions rechnet anders.** Fleisspunkte und Determinationswerte der
Hauptreihe gibt es hier nicht. An ihre Stelle treten Statuspunkte: 0 bis 32 je
Wert bei einem Gesamtbudget von 66, wobei ein Punkt unmittelbar +1 auf den
Endwert bei Stufe 50 bedeutet. Die Determinationswerte sind fest auf 31 gesetzt.
Die Berechnung erfolgt daher ueber :func:`bi.stats.statuswert_champions` und
nicht ueber die Fleisspunkte-Formel der Smogon-Strecke.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from ..config import (
    CHAMPIONS_BASIS,
    HTTP_THREADS,
    HTTP_TIMEOUT,
    KAMPFFORMATE,
    QUELLE_VORHALTUNG_TAGE,
)
from ..stats import STATUSWERTE, WESEN, alle_statuswerte, pruefe_statuspunkte, verteilung_kurzform
from . import archivdatei
from .extract import sitzung
from .mapping import loese_auf
from .transform import Befund

BASIS = CHAMPIONS_BASIS

Fortschritt = Callable[[float, str], None]


def _still(_anteil: float, _text: str) -> None:
    """Standard-Callback, wenn kein Fortschritt gemeldet werden soll."""


# --------------------------------------------------------------------------
# EXTRACT
# --------------------------------------------------------------------------

@dataclass
class Tagesabzug:
    """Rohdaten eines Pokemon fuer einen Tag und ein Kampfformat."""

    quell_name: str
    saison: str
    datum_iso: str
    kampfformat: str
    zeilen: list[dict[str, Any]]


@dataclass
class ChampionsAbzug:
    """Ergebnis des Champions-Extrakts.

    ``tage`` ist das **Angebot der Quelle** -- alle Tage, die ihr Verzeichnis
    fuehrt, unabhaengig davon, wie viele davon abgeholt wurden. ``abzuege``
    enthaelt dagegen nur die tatsaechlich geladenen Tagesstaende.
    """

    saison: str = ""
    tage: list[str] = field(default_factory=list)
    abzuege: list[Tagesabzug] = field(default_factory=list)
    fehlversuche: list[str] = field(default_factory=list)
    stand: str = ""


def _datum_umformen(ordner: str) -> str:
    """Wandelt die Ordnerschreibweise ``28_07_2026`` in ``2026-07-28`` um."""
    tag, monat, jahr = ordner.split("_")
    return f"{jahr}-{monat}-{tag}"


def hole_index(s: requests.Session) -> dict[str, Any]:
    """Laedt das Ressourcenverzeichnis der Quelle."""
    antwort = s.get(f"{BASIS}/api/index", timeout=HTTP_TIMEOUT * 2)
    antwort.raise_for_status()
    return antwort.json()


def _hole_csv(s: requests.Session, pfad: str) -> list[dict[str, Any]] | None:
    """Laedt eine einzelne Tages-CSV und gibt sie als Satzliste zurueck."""
    url = f"{BASIS}/{pfad.replace(chr(92), '/')}"
    try:
        antwort = s.get(url, timeout=HTTP_TIMEOUT)
        if antwort.status_code != 200:
            return None
        return list(csv.DictReader(io.StringIO(antwort.text)))
    except Exception:
        return None


def extrahiere(s: requests.Session, bereits_archiviert: set[tuple[str, str, str]],
               max_tage: int | None = None,
               fortschritt: Fortschritt = _still) -> ChampionsAbzug:
    """Laedt alle noch nicht archivierten Tagesstaende.

    ``bereits_archiviert`` enthaelt Tripel aus Saison, Datum und Kampfformat, die
    im Archiv liegen. Sie werden uebersprungen: der Abzug ist damit inkrementell
    und ein taeglicher Lauf laedt nur den jeweils neuen Tag.
    """
    fortschritt(0.02, "Lese Verzeichnis der Champions-Daten ...")
    index = hole_index(s)

    abzug = ChampionsAbzug(stand=index.get("generatedAt", ""))
    ordner = index.get("dailyDataFolders") or []
    if not ordner:
        # Erreichbar, aber ohne Tagesstaende. Das ausdruecklich zu melden trennt
        # den Fall von einem Netzfehler -- der wuerde als Ausnahme enden.
        fortschritt(1.0, "Die Quelle fuehrt derzeit keine Tagesstaende.")
        return abzug

    # Ordner sind als 'M4/28_07_2026' notiert.
    tagesstaende: list[tuple[str, str]] = []
    for eintrag in ordner:
        saison, _, datum = eintrag.partition("/")
        if datum:
            tagesstaende.append((saison, _datum_umformen(datum)))
    tagesstaende.sort(key=lambda t: t[1], reverse=True)

    # ``tage`` beschreibt das Angebot der Quelle, nicht unseren Ausschnitt daraus:
    # ``max_tage`` begrenzt allein, wie viel davon abgeholt wird. Die
    # Qualitaetsregeln bewerten spaeter gegen dieses Angebot -- ein beschnittener
    # Stand wuerde ihnen Tage als "nicht vorhanden" melden, die es sehr wohl gibt.
    abzug.saison = tagesstaende[0][0] if tagesstaende else ""
    abzug.tage = sorted({d for _, d in tagesstaende})
    if not abzug.tage:
        # Ordner vorhanden, aber keiner in der erwarteten Schreibweise
        # 'Saison/Tag' -- ein Formatwechsel der Quelle, kein leeres Angebot.
        fortschritt(1.0, "Kein Ordner der Quelle folgt der Form 'Saison/Tag'.")
        return abzug

    if max_tage:
        tagesstaende = tagesstaende[:max_tage]

    # Alle benoetigten CSV-Pfade sammeln, unter Auslassung des Archivierten.
    auftraege: list[tuple[str, str, str, str, str]] = []
    erlaubt = {(s_, d_) for s_, d_ in tagesstaende}

    for eintrag in index.get("pokemon", []):
        for csv_eintrag in eintrag.get("battleDataCsvs", []):
            saison = csv_eintrag.get("season")
            datum_ordner = csv_eintrag.get("date")
            kampfformat = csv_eintrag.get("format")
            if not (saison and datum_ordner and kampfformat in KAMPFFORMATE):
                continue
            datum = _datum_umformen(datum_ordner)
            if (saison, datum) not in erlaubt:
                continue
            if (saison, datum, kampfformat) in bereits_archiviert:
                continue
            auftraege.append((eintrag["name"], saison, datum, kampfformat,
                              csv_eintrag["path"]))

    if not auftraege:
        # Den Umfang des Angebots mitnennen: ohne ihn ist diese Meldung nicht
        # von einem geaenderten Quellformat zu unterscheiden, das schlicht keine
        # Auftraege mehr erzeugt.
        fortschritt(1.0, f"Alle {len(abzug.tage)} von der Quelle angebotenen Tage "
                         f"(bis {abzug.tage[-1]}) sind bereits archiviert.")
        return abzug

    fortschritt(0.05, f"Lade {len(auftraege)} Tagesdateien ...")
    with ThreadPoolExecutor(max_workers=HTTP_THREADS) as pool:
        ergebnisse = list(pool.map(lambda a: _hole_csv(s, a[4]), auftraege))

    for (name, saison, datum, kampfformat, _), zeilen in zip(auftraege, ergebnisse, strict=True):
        if zeilen is None:
            abzug.fehlversuche.append(f"{name} / {datum} / {kampfformat}")
            continue
        abzug.abzuege.append(Tagesabzug(name, saison, datum, kampfformat, zeilen))

    fortschritt(0.45, f"{len(abzug.abzuege)} Tagesabzuege geladen.")
    return abzug


# --------------------------------------------------------------------------
# TRANSFORM
# --------------------------------------------------------------------------

# Die Quelle benennt Kategorien technisch; hier auf fachliche Begriffe gebracht.
KATEGORIE_ZUORDNUNG = {
    "move": "move",
    "held_item": "held_item",
    "ability": "ability",
    "stat_alignment": "nature",
    "stat_points": "spread",
    "teammate": "teammate",
}

_PUNKTFELDER = (
    ("punkte_hp", "hp_points"),
    ("punkte_attack", "attack_points"),
    ("punkte_defense", "defense_points"),
    ("punkte_sp_attack", "sp_atk_points"),
    ("punkte_sp_defense", "sp_def_points"),
    ("punkte_speed", "speed_points"),
)


def _als_anteil(rohwert: str | None) -> float | None:
    """Wandelt ``'85.6%'`` in ``85.6``. Leere Werte bleiben leer."""
    if not rohwert:
        return None
    text = rohwert.strip().rstrip("%").strip()
    if not text:
        return None
    try:
        return round(float(text), 3)
    except ValueError:
        return None


def _als_ganzzahl(rohwert: Any) -> int | None:
    if rohwert in ("", None):
        return None
    try:
        return int(rohwert)
    except (TypeError, ValueError):
        return None


@dataclass
class ChampionsSatz:
    """Ein transformierter Tagesstand eines Pokemon."""

    slug: str
    saison: str
    datum_iso: str
    kampfformat: str
    rang: int
    merkmale: list[dict[str, Any]]


def transformiere(abzuege: list[Tagesabzug], bekannte_slugs: set[str],
                  basiswerte_je_slug: dict[str, dict[str, int]]
                  ) -> tuple[list[ChampionsSatz], list[Befund]]:
    """Ueberfuehrt die Rohabzuege in Faktensaetze.

    Die tatsaechlichen Statuswerte werden dabei aus Basiswerten, Wesen und
    Statuspunkten nach den Champions-Regeln berechnet und als angereicherte
    Kennzahlen mitgefuehrt.
    """
    saetze: list[ChampionsSatz] = []
    befunde: list[Befund] = []
    nicht_zuordenbar: set[str] = set()

    for abzug in abzuege:
        if not abzug.zeilen:
            continue

        slug = loese_auf(abzug.quell_name, bekannte_slugs)
        if slug is None:
            nicht_zuordenbar.add(abzug.quell_name)
            continue

        rang = _als_ganzzahl(abzug.zeilen[0].get("column_position"))
        if rang is None:
            befunde.append(Befund(
                "Fact_Champions_Usage", abzug.quell_name, "Pflichtfeld Rang",
                "Kein Nutzungsrang in der Quelldatei -- Satz nicht ladbar",
                klasse="Mangel 1. Klasse", dimension="Vollstaendigkeit"))
            continue

        basis = basiswerte_je_slug.get(slug)
        merkmale: list[dict[str, Any]] = []
        letztes_wesen = "Hardy"

        for zeile in abzug.zeilen:
            kategorie = KATEGORIE_ZUORDNUNG.get((zeile.get("category") or "").strip())
            if kategorie is None:
                continue

            rang_merkmal = _als_ganzzahl(zeile.get("rank"))
            if rang_merkmal is None:
                continue

            satz: dict[str, Any] = {
                "kategorie": kategorie,
                "rang": rang_merkmal,
                "bezeichnung": (zeile.get("name") or "").strip(),
                "anteil": _als_anteil(zeile.get("percentage")),
                "wesen": None, "punkte_summe": None, "attacke_schluessel": None,
            }
            for feld, _ in _PUNKTFELDER:
                satz[feld] = None
            for name in STATUSWERTE:
                satz[f"wert_{name}"] = None

            if kategorie == "move":
                # Verknuepfungsschluessel zur Attacken-Dimension.
                satz["attacke_schluessel"] = attacken_schluessel(satz["bezeichnung"])

            if kategorie == "nature":
                wesen = satz["bezeichnung"].capitalize()
                if wesen in WESEN:
                    satz["wesen"] = wesen
                    if rang_merkmal == 1:
                        # Das haeufigste Wesen dient als Grundlage der
                        # Initiativeberechnung der Statuspunkt-Saetze.
                        letztes_wesen = wesen
                else:
                    befunde.append(Befund(
                        "Fact_Champions_Merkmal", f"{slug}/{satz['bezeichnung']}",
                        "Wertebereich Wesen",
                        f"Unbekanntes Wesen '{satz['bezeichnung']}' -- nicht verrechenbar",
                        klasse="Mangel 2. Klasse", dimension="Wertebereich",
                        verworfen=False))

            elif kategorie == "spread":
                punkte = {}
                for feld, quellfeld in _PUNKTFELDER:
                    wert = _als_ganzzahl(zeile.get(quellfeld)) or 0
                    satz[feld] = wert
                    punkte[feld] = wert

                # Gegen die Spielregeln pruefen: hoechstens 32 Punkte je Wert und
                # 66 insgesamt. Die Quelle haelt sich nicht durchgaengig daran.
                for text in pruefe_statuspunkte(
                    {name.removeprefix("punkte_"): wert for name, wert in punkte.items()}
                ):  # noqa: E501
                    befunde.append(Befund(
                        "Fact_Champions_Merkmal", slug, "Wertebereich Statuspunkte", text,
                        klasse="Mangel 1. Klasse", dimension="Wertebereich",
                        verworfen=False))

                nach_statusname = {
                    name.removeprefix("punkte_"): wert for name, wert in punkte.items()
                }
                satz["wesen"] = letztes_wesen
                satz["punkte_summe"] = sum(nach_statusname.values())
                satz["bezeichnung"] = verteilung_kurzform(letztes_wesen, nach_statusname)

                if basis:
                    # Champions-Regel: ein Statuspunkt hebt den Endwert um eins,
                    # die Determinationswerte liegen fest bei 31.
                    werte = alle_statuswerte(basis, nach_statusname, letztes_wesen)
                    for name in STATUSWERTE:
                        satz[f"wert_{name}"] = werte[name]

            merkmale.append(satz)

        saetze.append(ChampionsSatz(
            slug=slug, saison=abzug.saison, datum_iso=abzug.datum_iso,
            kampfformat=abzug.kampfformat, rang=rang, merkmale=merkmale,
        ))

    if nicht_zuordenbar:
        beispiele = ", ".join(sorted(nicht_zuordenbar)[:5])
        befunde.append(Befund(
            "Fact_Champions_Usage", "Namensharmonisierung", "Referenzielle Integritaet",
            f"{len(nicht_zuordenbar)} Champions-Bezeichner ohne Entsprechung in der "
            f"Pokemon-Dimension. Beispiele: {beispiele}",
            klasse="Mangel 2. Klasse", dimension="Referenzielle Integritaet"))

    return saetze, befunde


# --------------------------------------------------------------------------
# LOAD
# --------------------------------------------------------------------------

def archivierte_staende(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    """Bereits archivierte Kombinationen aus Saison, Datum und Kampfformat."""
    return {
        (z["saison"], z["datum_iso"], z["kampfformat"])
        for z in conn.execute(
            "SELECT DISTINCT saison, datum_iso, kampfformat FROM Archiv_Champions")
    }


def archiviere(conn: sqlite3.Connection, abzuege: list[Tagesabzug], lauf_id: int) -> int:
    """Sichert die Rohnutzlast dauerhaft.

    Dieser Schritt laeuft vor der Transformation. Sollte die Verarbeitung
    scheitern, sind die Rohdaten dennoch gesichert und koennen ohne erneuten
    Quellzugriff wiederverwendet werden -- was bei einer Quelle mit zwei Wochen
    Vorhaltezeit entscheidend ist.
    """
    jetzt = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        """INSERT INTO Archiv_Champions
               (saison, datum_iso, kampfformat, quell_name, nutzlast, archiviert_am, lauf_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(saison, datum_iso, kampfformat, quell_name) DO NOTHING""",
        [
            (a.saison, a.datum_iso, a.kampfformat, a.quell_name,
             json.dumps(a.zeilen, separators=(",", ":")), jetzt, lauf_id)
            for a in abzuege
        ],
    )
    conn.commit()
    return conn.total_changes


def exportiere_archiv(conn: sqlite3.Connection, ziel: Path) -> dict[str, int]:
    """Schreibt das Rohdatenarchiv als versionierbare Dateien auf die Platte.

    Je Saison, Tag und Kampfformat entsteht eine gzip-komprimierte
    NDJSON-Datei. Diese Form ist bewusst gewaehlt:

    * **Zeilenweise** -- ein Satz je Zeile, damit Aenderungen lesbar bleiben.
    * **Deterministisch sortiert** -- ein unveraenderter Tag erzeugt dieselbe
      Nutzlast und damit keinen neuen Commit.
    * **Komprimiert** -- gemessen rund 0,3 MB je Tag statt 6,5 MB roh; git
      komprimiert diese Tagesstaende von sich aus nicht nennenswert weiter.

    Die Datenbank selbst wird nicht gesichert: sie ist aus diesen Dateien
    jederzeit neu ableitbar, die Rohnutzlast dagegen nicht wiederbeschaffbar.
    """
    ziel.mkdir(parents=True, exist_ok=True)
    # ``dateien``/``saetze`` beschreiben den Umfang des Archivs, ``geschrieben``
    # nur die tatsaechlich veraenderten Dateien.
    zaehler = {"dateien": 0, "saetze": 0, "geschrieben": 0}

    gruppen: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for z in conn.execute("""
        SELECT saison, datum_iso, kampfformat, quell_name, nutzlast
        FROM Archiv_Champions ORDER BY saison, datum_iso, kampfformat, quell_name
    """):
        schluessel = (z["saison"], z["datum_iso"], z["kampfformat"])
        gruppen.setdefault(schluessel, []).append((z["quell_name"], z["nutzlast"]))

    for (saison, datum, kampfformat), saetze in gruppen.items():
        ordner = ziel / saison / kampfformat
        ordner.mkdir(parents=True, exist_ok=True)
        datei = ordner / f"{datum}.ndjson.gz"

        inhalt = archivdatei.als_ndjson([
            {"quell_name": name, "zeilen": json.loads(nutzlast)}
            for name, nutzlast in sorted(saetze)
        ])

        zaehler["dateien"] += 1
        zaehler["saetze"] += len(saetze)
        # Geschrieben wird nur bei geaenderter Nutzlast, verglichen ueber den
        # entpackten Inhalt -- zur Begruendung siehe :mod:`bi.etl.archivdatei`.
        if archivdatei.schreibe_wenn_geaendert(datei, inhalt):
            zaehler["geschrieben"] += 1

    return zaehler


def importiere_archiv(conn: sqlite3.Connection, quelle: Path,
                      lauf_id: int = 0) -> dict[str, int]:
    """Liest zuvor exportierte Rohdaten zurueck in die Archivtabelle.

    Damit startet ein frischer Lauf -- etwa auf einem leeren CI-Runner -- nicht
    bei null, sondern mit der gesamten bereits gesicherten Historie. Erst das
    macht die Archivierung ueber die Vorhaltezeit der Quelle hinaus wirksam.
    """
    zaehler = {"dateien": 0, "saetze": 0}
    if not quelle.exists():
        return zaehler

    jetzt = datetime.now().isoformat(timespec="seconds")
    for datei in sorted(quelle.glob("*/*/*.ndjson.gz")):
        kampfformat = datei.parent.name
        saison = datei.parent.parent.name
        datum = datei.stem.removesuffix(".ndjson")

        zeilen = []
        with gzip.open(datei, "rt", encoding="utf-8") as strom:
            for zeile in strom:
                if not zeile.strip():
                    continue
                satz = json.loads(zeile)
                zeilen.append((
                    saison, datum, kampfformat, satz["quell_name"],
                    json.dumps(satz["zeilen"], separators=(",", ":")), jetzt, lauf_id,
                ))

        conn.executemany(
            """INSERT INTO Archiv_Champions
                   (saison, datum_iso, kampfformat, quell_name, nutzlast,
                    archiviert_am, lauf_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(saison, datum_iso, kampfformat, quell_name) DO NOTHING""",
            zeilen,
        )
        zaehler["dateien"] += 1
        zaehler["saetze"] += len(zeilen)

    conn.commit()
    return zaehler


def lies_aus_archiv(conn: sqlite3.Connection, saison: str | None = None
                    ) -> list[Tagesabzug]:
    """Liest die Rohdaten aus dem Archiv zurueck.

    Ermoeglicht das erneute Transformieren und Laden ohne Quellzugriff -- etwa
    nach einer Aenderung der Ableitungsregeln oder fuer Tage, die die Quelle
    inzwischen nicht mehr fuehrt.
    """
    sql = "SELECT saison, datum_iso, kampfformat, quell_name, nutzlast FROM Archiv_Champions"
    parameter: tuple = ()
    if saison:
        sql += " WHERE saison = ?"
        parameter = (saison,)

    return [
        Tagesabzug(z["quell_name"], z["saison"], z["datum_iso"], z["kampfformat"],
                   json.loads(z["nutzlast"]))
        for z in conn.execute(sql, parameter)
    ]


_MERKMAL_SPALTEN = (
    "pokemon_sk", "zeit_sk", "saison_sk", "kampfformat_sk", "kategorie", "rang",
    "bezeichnung", "anteil", "attacke_sk", "wesen",
    "punkte_hp", "punkte_attack", "punkte_defense",
    "punkte_sp_attack", "punkte_sp_defense", "punkte_speed", "punkte_summe",
    "wert_hp", "wert_attack", "wert_defense",
    "wert_sp_attack", "wert_sp_defense", "wert_speed",
)


def lade_fakten(conn: sqlite3.Connection, saetze: list[ChampionsSatz],
                zeit_karte: dict[str, int], saison_sk: int,
                kampfformat_karten: dict[str, int], quelle_sk: int,
                pokemon_karte: dict[str, int], attacken_karte: dict[str, int],
                lauf_id: int) -> tuple[int, list[Befund]]:
    """Schreibt Usage- und Merkmalsfakten.

    Das Rangperzentil wird je Tag und Format gebildet: der beste Rang erhaelt 100,
    der schlechteste 0. Damit sind Tage mit unterschiedlich vielen erfassten
    Pokemon vergleichbar -- der Rohrang allein waere es nicht.
    """
    befunde: list[Befund] = []

    # Anzahl erfasster Pokemon je Tag und Format als Bezugsgroesse.
    umfang: dict[tuple[str, str], int] = {}
    for satz in saetze:
        schluessel = (satz.datum_iso, satz.kampfformat)
        umfang[schluessel] = max(umfang.get(schluessel, 0), satz.rang)

    usage_zeilen: list[tuple[Any, ...]] = []
    merkmal_zeilen: list[tuple[Any, ...]] = []
    fehlende_attacken: set[str] = set()

    for satz in saetze:
        pokemon_sk = pokemon_karte.get(satz.slug)
        zeit_sk = zeit_karte.get(satz.datum_iso)
        kampfformat_sk = kampfformat_karten.get(satz.kampfformat)
        if pokemon_sk is None or zeit_sk is None or kampfformat_sk is None:
            befunde.append(Befund(
                "Fact_Champions_Usage", satz.slug, "Referenzielle Integritaet",
                "Dimensionsschluessel fehlt -- Satz nicht ladbar",
                klasse="Mangel 1. Klasse", dimension="Referenzielle Integritaet"))
            continue

        gesamt = umfang.get((satz.datum_iso, satz.kampfformat), 1)
        # Bei nur einem erfassten Pokemon ist die Spannweite null; der einzige
        # Satz ist dann per Definition der beste und erhaelt den Hoechstwert.
        perzentil = (100.0 if gesamt <= 1
                     else round(100 * (gesamt - satz.rang) / (gesamt - 1), 2))

        usage_zeilen.append((pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, quelle_sk,
                             satz.rang, perzentil, gesamt, lauf_id))

        basis = (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk)
        for merkmal in satz.merkmale:
            attacke_sk = None
            if merkmal["attacke_schluessel"]:
                attacke_sk = attacken_karte.get(merkmal["attacke_schluessel"])
                if attacke_sk is None:
                    fehlende_attacken.add(merkmal["bezeichnung"])

            merkmal_zeilen.append((
                *basis, merkmal["kategorie"], merkmal["rang"], merkmal["bezeichnung"],
                merkmal["anteil"], attacke_sk, merkmal["wesen"],
                *(merkmal[f] for f, _ in _PUNKTFELDER), merkmal["punkte_summe"],
                *(merkmal[f"wert_{name}"] for name in STATUSWERTE),
            ))

    if fehlende_attacken:
        beispiele = ", ".join(sorted(fehlende_attacken)[:5])
        befunde.append(Befund(
            "Fact_Champions_Merkmal", "Attacken-Verknuepfung",
            "Referenzielle Integritaet",
            f"{len(fehlende_attacken)} Attacken ohne Eintrag in der Attacken-Dimension. "
            f"Ihre Typangabe fehlt damit fuer die Matchup-Bewertung. Beispiele: {beispiele}",
            klasse="Mangel 2. Klasse", dimension="Referenzielle Integritaet",
            verworfen=False))

    conn.executemany(
        """INSERT INTO Fact_Champions_Usage
               (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, quelle_sk,
                rang, rang_perzentil, erfasste_pokemon, etl_lauf_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(pokemon_sk, zeit_sk, saison_sk, kampfformat_sk) DO UPDATE SET
               rang = excluded.rang, rang_perzentil = excluded.rang_perzentil,
               erfasste_pokemon = excluded.erfasste_pokemon,
               etl_lauf_id = excluded.etl_lauf_id""",
        usage_zeilen,
    )

    schluesselspalten = {"pokemon_sk", "zeit_sk", "saison_sk", "kampfformat_sk",
                         "kategorie", "rang"}
    aktualisierung = ", ".join(
        f"{s} = excluded.{s}" for s in _MERKMAL_SPALTEN if s not in schluesselspalten)
    conn.executemany(
        f"""INSERT INTO Fact_Champions_Merkmal ({', '.join(_MERKMAL_SPALTEN)})
            VALUES ({', '.join('?' * len(_MERKMAL_SPALTEN))})
            ON CONFLICT(pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, kategorie, rang)
            DO UPDATE SET {aktualisierung}""",  # noqa: S608
        merkmal_zeilen,
    )

    conn.commit()
    return len(usage_zeilen), befunde


def attacken_schluessel(anzeigename: str) -> str:
    """Vereinheitlicht einen Attackennamen zum Verknuepfungsschluessel.

    Champions liefert ``"Dragon Claw"``, die Attacken-Dimension fuehrt
    ``"dragonclaw"``. Beide Seiten werden auf dieselbe kompakte Schreibweise
    gebracht.
    """
    return "".join(c for c in anzeigename.lower() if c.isalnum())


# --------------------------------------------------------------------------
# Orchestrierung
# --------------------------------------------------------------------------

def laden(conn: sqlite3.Connection, max_tage: int | None = None,
          aus_archiv: bool = False,
          fortschritt: Fortschritt = _still) -> dict[str, Any]:
    """Fuehrt den vollstaendigen Champions-Ladelauf aus.

    ``aus_archiv`` ueberspringt den Quellzugriff und verarbeitet ausschliesslich
    bereits gesicherte Rohdaten neu.
    """
    from . import load, pipeline

    parameter = "Archiv-Neuverarbeitung" if aus_archiv else f"max. {max_tage or 'alle'} Tage"
    lauf_id = load.lauf_beginnen(conn, "Champions", parameter)

    try:
        pokemon_karte = {
            z["slug"]: z["pokemon_sk"] for z in
            conn.execute("SELECT slug, pokemon_sk FROM Dim_Pokemon WHERE ist_aktuell = 1")
        }
        if not pokemon_karte:
            raise ValueError("Die Pokemon-Dimension ist leer. Bitte zuerst Stammdaten laden.")

        basiswerte = {
            z["slug"]: {"hp": z["hp"], "attack": z["attack"], "defense": z["defense"],
                        "sp_attack": z["sp_attack"], "sp_defense": z["sp_defense"],
                        "speed": z["speed"]}
            for z in conn.execute(
                "SELECT slug, hp, attack, defense, sp_attack, sp_defense, speed "
                "FROM Dim_Pokemon WHERE ist_aktuell = 1")
        }

        quelle_sk = load.lade_quelle(conn, "champions")
        kampfformat_karten = load.lade_alle_kampfformate(conn)

        neu_archiviert = 0
        # Tagesstaende, die die Quelle angeboten hat, deren Abruf aber
        # scheiterte. Sie werden weiter unten zu Qualitaetsbefunden -- ohne das
        # verschwaende ein solcher Tag lautlos: der Lauf meldete Erfolg, das
        # Archiv bliebe unvollstaendig, und aufgefallen waere es erst, wenn die
        # Vorhaltezeit der Quelle den Tag laengst vergessen hat.
        quell_fehlversuche: list[str] = []
        if aus_archiv:
            fortschritt(0.1, "Lese Rohdaten aus dem Archiv ...")
            abzuege = lies_aus_archiv(conn)
            saison = abzuege[0].saison if abzuege else ""
        else:
            with sitzung() as s:
                abzug = extrahiere(s, archivierte_staende(conn), max_tage, fortschritt)
            saison = abzug.saison
            quell_fehlversuche = abzug.fehlversuche
            # Festhalten, was die Quelle angeboten hat -- die Qualitaetsregeln
            # bewerten daran, ob eine Luecke ein eigenes Versaeumnis ist.
            load.quelle_stand_schreiben(conn, "Champions", abzug.tage, abzug.stand)
            if abzug.abzuege:
                fortschritt(0.5, f"Archiviere {len(abzug.abzuege)} Tagesabzuege ...")
                neu_archiviert = archiviere(conn, abzug.abzuege, lauf_id)
            # Immer den vollstaendigen Archivbestand verarbeiten: so wirken
            # geaenderte Ableitungsregeln auch auf frueher gesicherte Tage.
            abzuege = lies_aus_archiv(conn)
            if not saison and abzuege:
                saison = abzuege[0].saison

        if not abzuege:
            raise ValueError("Es liegen weder neue noch archivierte Champions-Daten vor.")

        fortschritt(0.65, "Transformiere Champions-Daten ...")
        saetze, befunde = transformiere(abzuege, set(pokemon_karte), basiswerte)
        if not saetze:
            raise ValueError("Kein einziger Champions-Satz konnte zugeordnet werden.")

        # Ein angebotener, aber nicht abrufbarer Tag ist die teuerste Art von
        # Fehler in diesem Projekt: er faellt erst auf, wenn er nicht mehr zu
        # beheben ist. Der Befund macht ihn sofort sichtbar -- im Bericht, im
        # Ladeprotokoll als abgewiesener Satz, und solange die Quelle den Tag
        # noch vorhaelt, holt ihn der naechste Lauf von selbst nach.
        for kennung in quell_fehlversuche:
            befunde.append(Befund(
                "Archiv_Champions", kennung, "Quellverfuegbarkeit",
                "Der Tagesstand wurde von der Quelle angeboten, war aber nach "
                "mehreren Versuchen nicht abrufbar. Er fehlt im Archiv und ist "
                f"nur noch rund {QUELLE_VORHALTUNG_TAGE} Tage lang nachholbar.",
                klasse="Mangel 2. Klasse", dimension="Vollstaendigkeit"))

        tage = sorted({s.datum_iso for s in saetze})
        zeit_karte = load.lade_zeit(conn, tage)
        saison_sk = load.lade_saison(
            conn, saison, f"Season {saison.lstrip('M')} (Pokemon Champions)",
            quelle_sk, tage,
        )

        # Die Attacken-Dimension traegt Typ, Kategorie und Basisschaden -- ohne
        # sie waere keine Matchup-Bewertung moeglich. Champions liefert nur den
        # Anzeigenamen, die Eigenschaften stammen aus der PokeAPI.
        #
        # Das gilt auch beim Neuaufbau aus dem Archiv: ``aus_archiv`` heisst
        # "die Tagesstaende nicht erneut bei Champions abrufen", nicht "keine
        # Stammdaten laden" -- die Pokemon-Stammdaten kommen dort ebenfalls
        # ueber das Netz. Ein Ueberspringen liess ``Dim_Attacke`` auf einem
        # frischen Rechner leer und damit jede Matchup-Bewertung ins Leere
        # laufen. Nachgeladen wird ohnehin nur Fehlendes.
        fortschritt(0.78, "Ergaenze fehlende Attacken-Stammdaten ...")
        benoetigt = {
            m["attacke_schluessel"] for s in saetze for m in s.merkmale
            if m["attacke_schluessel"]
        }
        try:
            pipeline.attacken_ergaenzen(conn, benoetigt)
        except Exception as fehler:  # noqa: BLE001 -- Netzfehler jeder Art
            # Ohne Attacken bleiben die Nutzungsfakten gueltig; nur die
            # Matchup-Bewertung ist eingeschraenkt. Das ist ein Qualitaets-
            # befund, kein Grund, den ganzen Lauf zu verwerfen.
            befunde.append(Befund(
                "Dim_Attacke", "PokeAPI", "Verfuegbarkeit der Stammdatenquelle",
                f"Attacken-Stammdaten konnten nicht nachgeladen werden: {fehler}. "
                "Die Matchup-Bewertung bleibt bis zum naechsten Lauf unvollstaendig.",
                klasse="Mangel 2. Klasse", dimension="Vollstaendigkeit",
                verworfen=False))

        attacken_karte = {
            z["slug"]: z["attacke_sk"]
            for z in conn.execute("SELECT slug, attacke_sk FROM Dim_Attacke")
        }

        fortschritt(0.85, "Schreibe Champions-Fakten ...")
        geladen, lade_befunde = lade_fakten(
            conn, saetze, zeit_karte, saison_sk, kampfformat_karten, quelle_sk,
            pokemon_karte, attacken_karte, lauf_id,
        )
        befunde.extend(lade_befunde)

        load.befunde_protokollieren(conn, lauf_id, befunde)
        verworfen = sum(1 for b in befunde if b.verworfen)
        load.lauf_abschliessen(
            conn, lauf_id, "erfolgreich", gelesen=len(abzuege), geladen=geladen,
            abgewiesen=verworfen,
            meldung=(f"Saison {saison}, {len(tage)} Tage "
                     f"({tage[0]} bis {tage[-1]}), {neu_archiviert} neu archiviert"),
        )
        fortschritt(1.0, "Champions-Daten geladen.")

        return {
            "erfolgreich": True, "lauf_id": lauf_id, "saison": saison,
            "tage": tage, "geladen": geladen, "abgewiesen": verworfen,
            "neu_archiviert": neu_archiviert,
            "quelle_stand": load.quelle_stand_lesen(conn, "Champions"),
            "meldung": (f"Saison {saison}: {len(tage)} Tage von {tage[0]} bis {tage[-1]}, "
                        f"{geladen} Faktensaetze."),
        }

    except Exception as fehler:  # noqa: BLE001 - Ladefehler wird protokolliert
        load.lauf_abschliessen(conn, lauf_id, "fehler", meldung=str(fehler))
        return {"erfolgreich": False, "lauf_id": lauf_id, "meldung": str(fehler)}
