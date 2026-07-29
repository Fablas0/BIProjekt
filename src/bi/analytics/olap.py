"""OLAP-Auswertung auf dem Datenwuerfel.

Der Wuerfel wird relational gehalten (ROLAP): die Faktentabelle bleibt die
Datenbasis, die multidimensionale Sicht entsteht zur Laufzeit ueber Verknuepfung
und Verdichtung. Das ist bei der hier vorliegenden Datenmenge angemessen und
erspart die Materialisierung eines eigenen Wuerfels.

Umgesetzt sind die klassischen OLAP-Operationen:

===============  ==========================================================
Operation        Umsetzung
===============  ==========================================================
Drill-Down       Wechsel zu einem feineren Merkmal einer Dimensionshierarchie
Roll-Up          Wechsel zu einem groeberen Merkmal derselben Hierarchie
Slice            Filter auf genau einer Dimension
Dice             Filter auf mehreren Dimensionen gleichzeitig
Pivot / Rotation Vertauschen der Achsen der Auswertung
Split / Merge    Hinzunehmen bzw. Entfernen einer Dimension
===============  ==========================================================

Dimensionshierarchien
---------------------
* Zeit: Jahr -> Quartal -> Monat
* Pokemon: Generation -> Spezies -> Form
* Typ: Typ-Kombination -> Primaertyp
* Rolle: Offensivprofil -> Rolle -> Speed-Klasse
* Format: Saison -> Regulation -> Spielmodus
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Merkmal:
    """Ein auswertbares Merkmal einer Dimension."""

    schluessel: str      # Spaltenname in der Sicht V_Usage
    bezeichnung: str     # Beschriftung in der Oberflaeche
    dimension: str       # zugehoerige Dimension
    ebene: int           # Position im Konsolidierungspfad (1 = groebste Ebene)


# Konsolidierungspfade. Die Reihenfolge innerhalb einer Dimension bestimmt,
# welches Merkmal ein Drill-Down bzw. Roll-Up als naechstes ansteuert.
HIERARCHIEN: dict[str, list[Merkmal]] = {
    "Zeit": [
        Merkmal("jahr", "Jahr", "Zeit", 1),
        Merkmal("quartal_label", "Quartal", "Zeit", 2),
        Merkmal("monat_name", "Monat", "Zeit", 3),
    ],
    "Pokemon": [
        Merkmal("generation", "Generation", "Pokemon", 1),
        Merkmal("spezies", "Spezies", "Pokemon", 2),
        Merkmal("anzeigename", "Pokemon (Form)", "Pokemon", 3),
    ],
    "Typ": [
        Merkmal("typ1", "Primaertyp", "Typ", 1),
        Merkmal("typ_kombination", "Typ-Kombination", "Typ", 2),
    ],
    "Rolle": [
        Merkmal("offensiv_profil", "Offensivprofil", "Rolle", 1),
        Merkmal("rolle", "Teamrolle", "Rolle", 2),
        Merkmal("speed_klasse", "Speed-Klasse", "Rolle", 3),
    ],
    "Format": [
        Merkmal("saison", "Saison", "Format", 1),
        Merkmal("regulation", "Regulation", "Format", 2),
        Merkmal("spielmodus", "Spielmodus", "Format", 3),
    ],
}

ALLE_MERKMALE: dict[str, Merkmal] = {
    m.schluessel: m for merkmale in HIERARCHIEN.values() for m in merkmale
}


@dataclass(frozen=True)
class Kennzahl:
    """Eine verdichtbare Kennzahl samt zugehoeriger Aggregationsregel.

    Die Aggregationsregel gehoert zwingend zur Kennzahl: der Nutzungsanteil ist
    entlang der Pokemon-Dimension additiv, das Viability Ceiling dagegen nicht --
    dort ist nur das Maximum sinnvoll, weil sich Spielstaerken nicht addieren.
    """

    schluessel: str
    bezeichnung: str
    aggregation: str
    einheit: str = ""


KENNZAHLEN: dict[str, Kennzahl] = {
    "usage_rate": Kennzahl("usage_rate", "Nutzungsanteil (Summe)", "sum", "%"),
    "usage_rate_mittel": Kennzahl("usage_rate", "Nutzungsanteil (Mittelwert)", "mean", "%"),
    "raw_count": Kennzahl("raw_count", "Teamnennungen (absolut)", "sum", ""),
    "gxe_top": Kennzahl("gxe_top", "Bestes GXE", "max", "%"),
    "gxe_p50": Kennzahl("gxe_p50", "Medianes GXE", "mean", "%"),
    "basiswert_summe": Kennzahl("basiswert_summe", "Basiswertsumme (Mittelwert)", "mean", ""),
    "speed": Kennzahl("speed", "Basis-Initiative (Mittelwert)", "mean", ""),
    "resistenz_wert": Kennzahl("resistenz_wert", "Defensive Guete (Mittelwert)", "mean", ""),
    "anzahl": Kennzahl("anzeigename", "Anzahl Pokemon", "nunique", ""),
}


def lade_wuerfel(conn: sqlite3.Connection) -> pd.DataFrame:
    """Laedt die Faktensicht als Grundlage aller Wuerfeloperationen.

    Bei der hier vorliegenden Groessenordnung (wenige tausend Zeilen) ist es
    guenstiger, den Wuerfel einmal vollstaendig zu laden und die Operationen im
    Speicher auszufuehren, als je Interaktion erneut zu verknuepfen.
    """
    wuerfel = pd.read_sql("SELECT * FROM V_Usage", conn)
    return _zeitachse_ordnen(wuerfel)


def _zeitachse_ordnen(wuerfel: pd.DataFrame) -> pd.DataFrame:
    """Versieht die Zeitmerkmale mit ihrer fachlichen Reihenfolge.

    ``monat_name`` und ``quartal_label`` sind Texte. Ohne explizite Ordnung
    sortieren Gruppierung und Kreuztabelle sie alphabetisch, sodass auf der
    Zeitachse April vor Januar erschiene. Die Umwandlung in eine geordnete
    Kategorie leitet die Reihenfolge aus dem zugehoerigen ISO-Monat ab.
    """
    if wuerfel.empty:
        return wuerfel

    for merkmal, quelle in (("monat_name", "monat_iso"), ("quartal_label", "monat_iso")):
        if merkmal not in wuerfel.columns or quelle not in wuerfel.columns:
            continue
        reihenfolge = (wuerfel[[merkmal, quelle]].drop_duplicates()
                       .sort_values(quelle)[merkmal].tolist())
        # drop_duplicates auf beiden Spalten kann ein Label mehrfach liefern
        # (ein Quartal umfasst drei Monate) -- die Reihenfolge bleibt erhalten.
        eindeutig = list(dict.fromkeys(reihenfolge))
        wuerfel[merkmal] = pd.Categorical(wuerfel[merkmal], categories=eindeutig, ordered=True)

    return wuerfel


# --------------------------------------------------------------------------
# Slice und Dice
# --------------------------------------------------------------------------

def slice_wuerfel(wuerfel: pd.DataFrame, merkmal: str, werte: list) -> pd.DataFrame:
    """**Slice** -- schneidet eine Scheibe entlang genau einer Dimension heraus."""
    if not werte or merkmal not in wuerfel.columns:
        return wuerfel
    return wuerfel[wuerfel[merkmal].isin(werte)]


def dice_wuerfel(wuerfel: pd.DataFrame, filter_bedingungen: dict[str, list]) -> pd.DataFrame:
    """**Dice** -- schneidet einen Teilwuerfel ueber mehrere Dimensionen heraus."""
    ergebnis = wuerfel
    for merkmal, werte in filter_bedingungen.items():
        ergebnis = slice_wuerfel(ergebnis, merkmal, werte)
    return ergebnis


# --------------------------------------------------------------------------
# Drill-Down und Roll-Up
# --------------------------------------------------------------------------

def naechste_ebene(merkmal_schluessel: str, richtung: str) -> str | None:
    """Ermittelt das Zielmerkmal eines Drill-Down oder Roll-Up.

    ``richtung`` ist ``"drill_down"`` (feiner) oder ``"roll_up"`` (groeber).
    Gibt ``None`` zurueck, wenn das Ende des Konsolidierungspfades erreicht ist.
    """
    merkmal = ALLE_MERKMALE.get(merkmal_schluessel)
    if merkmal is None:
        return None

    pfad = HIERARCHIEN[merkmal.dimension]
    versatz = 1 if richtung == "drill_down" else -1
    ziel_ebene = merkmal.ebene + versatz
    for kandidat in pfad:
        if kandidat.ebene == ziel_ebene:
            return kandidat.schluessel
    return None


def hierarchiepfad(merkmal_schluessel: str) -> list[Merkmal]:
    """Vollstaendiger Konsolidierungspfad, zu dem ein Merkmal gehoert."""
    merkmal = ALLE_MERKMALE.get(merkmal_schluessel)
    return HIERARCHIEN[merkmal.dimension] if merkmal else []


# --------------------------------------------------------------------------
# Verdichtung und Pivotierung
# --------------------------------------------------------------------------

def verdichte(wuerfel: pd.DataFrame, zeilen_merkmal: str, kennzahl_schluessel: str,
              spalten_merkmal: str | None = None) -> pd.DataFrame:
    """Verdichtet den Wuerfel auf die gewaehlten Achsen.

    Ohne ``spalten_merkmal`` entsteht eine eindimensionale Auswertung (**Merge**),
    mit ``spalten_merkmal`` eine Kreuztabelle (**Split**). Das Vertauschen der
    beiden Argumente entspricht der **Pivot**-Operation.
    """
    kennzahl = KENNZAHLEN[kennzahl_schluessel]
    if wuerfel.empty or zeilen_merkmal not in wuerfel.columns:
        return pd.DataFrame()

    if spalten_merkmal and spalten_merkmal in wuerfel.columns:
        # observed=True: nach einem Slice sollen nur tatsaechlich vorhandene
        # Auspraegungen erscheinen, keine leeren Spalten der Kategorie.
        tabelle = pd.pivot_table(
            wuerfel, index=zeilen_merkmal, columns=spalten_merkmal,
            values=kennzahl.schluessel, aggfunc=kennzahl.aggregation, fill_value=0,
            observed=True,
        )
        return tabelle.round(2)

    reihe = (wuerfel.groupby(zeilen_merkmal, observed=True)[kennzahl.schluessel]
             .agg(kennzahl.aggregation))
    return reihe.round(2).reset_index(name=kennzahl.bezeichnung)


def kennzahl_mit_anteil(wuerfel: pd.DataFrame, merkmal: str,
                        kennzahl_schluessel: str = "usage_rate") -> pd.DataFrame:
    """Verdichtung samt relativem Anteil und kumuliertem Anteil.

    Der kumulierte Anteil beantwortet Fragen der Form "wie viele Merkmalswerte
    decken 80 Prozent des Metagames ab?" und macht die Konzentration unmittelbar
    ablesbar.
    """
    kennzahl = KENNZAHLEN[kennzahl_schluessel]
    if wuerfel.empty or merkmal not in wuerfel.columns:
        return pd.DataFrame()

    df = (wuerfel.groupby(merkmal, observed=True)[kennzahl.schluessel]
          .agg(kennzahl.aggregation).sort_values(ascending=False).reset_index())
    df.columns = [merkmal, "wert"]

    gesamt = df["wert"].sum()
    df["anteil_prozent"] = (100 * df["wert"] / gesamt).round(1) if gesamt else 0.0
    df["kumuliert_prozent"] = df["anteil_prozent"].cumsum().round(1)
    df["wert"] = df["wert"].round(2)
    return df


def wuerfel_kennzahlen(wuerfel: pd.DataFrame) -> dict[str, float]:
    """Eckwerte des aktuell ausgewaehlten Teilwuerfels."""
    if wuerfel.empty:
        return {"zeilen": 0, "pokemon": 0, "monate": 0, "usage_summe": 0.0}
    return {
        "zeilen": int(len(wuerfel)),
        "pokemon": int(wuerfel["anzeigename"].nunique()),
        "monate": int(wuerfel["monat_iso"].nunique()),
        "usage_summe": round(float(wuerfel["usage_rate"].sum()), 1),
    }
