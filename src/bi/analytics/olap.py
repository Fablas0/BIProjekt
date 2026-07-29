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
* Zeit: Jahr -> Quartal -> Monat -> Tag
* Pokemon: Generation -> Spezies -> Form
* Typ: Primaertyp -> Typ-Kombination
* Rolle: Offensivprofil -> Rolle -> Speed-Klasse
* Format: Saison -> Kampfformat

Messniveau
----------
Die Nutzung liegt als **Rang** vor. Zulaessig sind daher nur Kennzahlen, die auf
ordinalen Daten sinnvoll sind -- bester Rang, Median, Anzahl. Eine Summe ueber
Raenge waere fachlich nicht belastbar und wird deshalb nicht angeboten.
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
        Merkmal("tag_label", "Tag", "Zeit", 4),
    ],
    # Die Pokemon-Hierarchie hat bewusst nur zwei Stufen. Eine dritte Ebene fuer
    # die Spezies waere fast ueberall deckungsgleich: von 208 Spezies haben nur
    # 18 mehr als eine Form. Sie brachte damit einen zusaetzlichen Schritt im
    # Konsolidierungspfad, der bei neun von zehn Pokemon nichts veraendert --
    # und zeigte den technischen Bezeichner statt des lesbaren Namens.
    #
    # Gewaehlt ist die feinere Ebene, weil die Formen fachlich verschiedene
    # Kaempfer sind: Wolwerock Tag und Wolwerock Zwielicht unterscheiden sich in
    # Typ, Faehigkeit und Initiative.
    "Pokemon": [
        Merkmal("generation", "Generation", "Pokemon", 1),
        Merkmal("anzeigename", "Pokemon", "Pokemon", 2),
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
        Merkmal("kampfformat", "Kampfformat", "Format", 2),
    ],
}

ALLE_MERKMALE: dict[str, Merkmal] = {
    m.schluessel: m for merkmale in HIERARCHIEN.values() for m in merkmale
}


@dataclass(frozen=True)
class Kennzahl:
    """Eine verdichtbare Kennzahl samt zugehoeriger Aggregationsregel.

    Die Aggregationsregel gehoert zwingend zur Kennzahl: die Anzahl ist entlang
    der Pokemon-Dimension additiv, ein Rang dagegen nicht -- dort ist nur ein
    Extremwert oder der Median sinnvoll.

    Zwei weitere Eigenschaften entscheiden ueber die Darstellung und sind
    deshalb hier hinterlegt statt in der Oberflaeche verstreut:

    ``kleiner_ist_besser``
        Bei einem Rang ist 1 das beste Ergebnis. Wer "die besten zwanzig"
        auswaehlt, meint die *kleinsten* Werte. Ohne diese Angabe waehlte eine
        Bestenliste ausgerechnet die schwaechsten Auspraegungen aus.

    ``anteil_zulaessig``
        Ein Anteil setzt voraus, dass die Summe der Werte eine Bedeutung hat.
        Fuer Zaehlgroessen trifft das zu, fuer Raenge nicht: die Summe aller
        Raenge ist eine Zahl ohne fachlichen Gehalt, und ein daraus gebildeter
        Prozentsatz taeuschte eine Verhaeltnisskala vor, die die Quelle nicht
        liefert.
    """

    schluessel: str
    bezeichnung: str
    aggregation: str
    einheit: str = ""
    kleiner_ist_besser: bool = False
    anteil_zulaessig: bool = False

    @property
    def fehlwert(self) -> float | None:
        """Womit eine leere Zelle der Kreuztabelle zu fuellen ist.

        Bei einer Zaehlung bedeutet "nicht vorhanden" tatsaechlich null. Bei
        einem Rang bedeutet es "an diesem Tag nicht platziert" -- eine Null
        stuende dort faelschlich fuer ein Ergebnis besser als Rang 1.
        """
        return 0 if self.aggregation in ("nunique", "count", "sum") else None


KENNZAHLEN: dict[str, Kennzahl] = {
    # Ordinale Kennzahlen: nur Extremwerte, Median und Anzahl sind zulaessig.
    "rang_bester": Kennzahl("rang", "Bester Rang", "min", "",
                            kleiner_ist_besser=True),
    "rang_median": Kennzahl("rang", "Medianer Rang", "median", "",
                            kleiner_ist_besser=True),
    # Das Perzentil ist auf 0 bis 100 normiert, 100 steht fuer den ersten Platz.
    "rang_perzentil": Kennzahl("rang_perzentil", "Rangperzentil (Median)", "median", "%"),
    "anzahl": Kennzahl("anzeigename", "Anzahl Pokemon", "nunique", "",
                       anteil_zulaessig=True),
    # Kardinale Merkmale der Pokemon-Dimension -- hier sind Mittelwerte zulaessig.
    "basiswert_summe": Kennzahl("basiswert_summe", "Basiswertsumme (Mittelwert)", "mean", ""),
    "stufe50_speed": Kennzahl("stufe50_speed", "Initiative Stufe 50 (Mittelwert)", "mean", ""),
    "resistenz_wert": Kennzahl("resistenz_wert", "Defensive Guete (Mittelwert)", "mean", ""),
}


def lade_wuerfel(conn: sqlite3.Connection) -> pd.DataFrame:
    """Laedt die Faktensicht als Grundlage aller Wuerfeloperationen.

    Bei der hier vorliegenden Groessenordnung (wenige tausend Zeilen) ist es
    guenstiger, den Wuerfel einmal vollstaendig zu laden und die Operationen im
    Speicher auszufuehren, als je Interaktion erneut zu verknuepfen.
    """
    wuerfel = pd.read_sql(
        "SELECT * FROM V_Usage WHERE saison_aktuell = 1", conn)
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

    for merkmal, quelle in (("monat_name", "monat_iso"), ("quartal_label", "monat_iso"),
                            ("tag_label", "datum_iso")):
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

    Leere Zellen bleiben leer, sofern die Kennzahl das verlangt: bei einem Rang
    heisst "nicht vorhanden", dass das Pokemon an diesem Tag nicht platziert war.
    Eine Null stuende dort fuer ein Ergebnis besser als Rang 1.
    """
    kennzahl = KENNZAHLEN[kennzahl_schluessel]
    if wuerfel.empty or zeilen_merkmal not in wuerfel.columns:
        return pd.DataFrame()

    # Achse und Kennzahl koennen auf dieselbe Spalte zeigen: "Anzahl Pokemon"
    # zaehlt ueber ``anzeigename`` und laesst sich zugleich nach ``anzeigename``
    # aufreissen. pandas kann eine Spalte nicht gleichzeitig als Gruppierung und
    # als Wert verwenden, deshalb bekommt der Wert hier eine eigene Kopie.
    daten, werte_spalte = wuerfel, kennzahl.schluessel
    if werte_spalte in (zeilen_merkmal, spalten_merkmal):
        werte_spalte = "_kennzahl"
        daten = wuerfel.assign(_kennzahl=wuerfel[kennzahl.schluessel])

    if spalten_merkmal and spalten_merkmal in wuerfel.columns:
        # observed=True: nach einem Slice sollen nur tatsaechlich vorhandene
        # Auspraegungen erscheinen, keine leeren Spalten der Kategorie.
        zusatz = ({} if kennzahl.fehlwert is None
                  else {"fill_value": kennzahl.fehlwert})
        tabelle = pd.pivot_table(
            daten, index=zeilen_merkmal, columns=spalten_merkmal,
            values=werte_spalte, aggfunc=kennzahl.aggregation,
            observed=True, **zusatz,
        )
        return tabelle.round(2)

    reihe = (daten.groupby(zeilen_merkmal, observed=True)[werte_spalte]
             .agg(kennzahl.aggregation))
    return reihe.round(2).reset_index(name=kennzahl.bezeichnung)


def _guetereihenfolge(werte: pd.Series, kennzahl: Kennzahl) -> pd.Series:
    """Sortiert eine Wertereihe von "am besten" nach "am schlechtesten"."""
    return werte.sort_values(ascending=kennzahl.kleiner_ist_besser)


def beste_auspraegungen(tabelle: pd.DataFrame, kennzahl_schluessel: str,
                        anzahl: int | None = None) -> pd.DataFrame:
    """Waehlt die fachlich staerksten Zeilen einer Kreuztabelle aus.

    Bewertet wird ueber den besten Wert je Zeile, nicht ueber deren Summe. Eine
    Summe ueber Raenge ist fachlich nicht belastbar, und sie benachteiligt genau
    die Pokemon, die nur an einem Teil der Tage platziert waren.

    ``anzahl=None`` liefert alle Zeilen, lediglich geordnet.
    """
    kennzahl = KENNZAHLEN[kennzahl_schluessel]
    if tabelle.empty:
        return tabelle

    kern = tabelle.min(axis=1) if kennzahl.kleiner_ist_besser else tabelle.max(axis=1)
    geordnet = tabelle.loc[_guetereihenfolge(kern, kennzahl).index]
    return geordnet if anzahl is None else geordnet.head(anzahl)


def kennzahl_mit_anteil(wuerfel: pd.DataFrame, merkmal: str,
                        kennzahl_schluessel: str = "anzahl") -> pd.DataFrame:
    """Verdichtung, geordnet von der besten zur schwaechsten Auspraegung.

    Die Spalten ``anteil_prozent`` und ``kumuliert_prozent`` entstehen **nur**,
    wenn die Kennzahl es zulaesst. Ein Anteil setzt voraus, dass die Summe der
    Werte etwas bedeutet; bei Raengen ist das nicht der Fall. Zuvor errechnete
    diese Funktion den Anteil unbesehen fuer jede Kennzahl -- ein Rang wurde
    dabei durch die Summe aller Raenge geteilt, und die daraus abgeleitete
    Aussage "N Auspraegungen decken 80 Prozent ab" war ohne Gehalt.
    """
    kennzahl = KENNZAHLEN[kennzahl_schluessel]
    if wuerfel.empty or merkmal not in wuerfel.columns:
        return pd.DataFrame()

    # ``rename`` vor ``reset_index``: Gruppierungsmerkmal und Kennzahl koennen
    # dieselbe Spalte sein -- "Anzahl Pokemon" je Pokemon zaehlt ueber
    # ``anzeigename`` und gruppiert zugleich danach. Ohne die Umbenennung
    # scheitert das Zuruecksetzen des Index an zwei gleichnamigen Spalten.
    daten = wuerfel.assign(_kennzahl=wuerfel[kennzahl.schluessel])
    reihe = (daten.groupby(merkmal, observed=True)["_kennzahl"]
             .agg(kennzahl.aggregation).rename("wert"))
    df = _guetereihenfolge(reihe, kennzahl).rename_axis(merkmal).reset_index()
    df["wert"] = df["wert"].round(2)

    if not kennzahl.anteil_zulaessig:
        return df

    gesamt = df["wert"].sum()
    df["anteil_prozent"] = (100 * df["wert"] / gesamt).round(1) if gesamt else 0.0
    df["kumuliert_prozent"] = df["anteil_prozent"].cumsum().round(1)
    return df


def wuerfel_kennzahlen(wuerfel: pd.DataFrame) -> dict[str, float]:
    """Eckwerte des aktuell ausgewaehlten Teilwuerfels."""
    if wuerfel.empty:
        return {"zeilen": 0, "pokemon": 0, "tage": 0, "bester_rang": 0}
    return {
        "zeilen": int(len(wuerfel)),
        "pokemon": int(wuerfel["anzeigename"].nunique()),
        "tage": int(wuerfel["datum_iso"].nunique()),
        "bester_rang": int(wuerfel["rang"].min()),
    }
