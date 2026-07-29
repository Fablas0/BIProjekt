"""Initiative-Analyse auf Basis der tatsaechlich gespielten Statuswerte.

Im Doppelkampf entscheidet die Zugreihenfolge einen erheblichen Teil der Partien:
Wer zuerst handelt, setzt seinen Plan durch, bevor der Gegner reagieren kann. Die
dafuer massgebliche Groesse ist nicht der Basiswert eines Pokemon, sondern der
Wert, den das konkret gespielte Exemplar erreicht -- also Basiswert plus Wesen
plus Fleisspunkte.

Dieses Modul wertet die Punkteverteilungen in ``Fact_Champions_Merkmal`` aus, in
denen genau diese berechneten Werte liegen. Damit werden drei Fragen
beantwortbar, die allein aus Basiswerten nicht zu klaeren sind:

1. **Speed-Tier-Liste** -- welche Initiativwerte im Metagame tatsaechlich
   vorkommen und wie haeufig.
2. **Szenario-Vergleich** -- wer unter Rueckenwind, Wahlschal, Bizarroraum oder
   Paralyse zuerst handelt.
3. **Benchmark** -- wie viele Fleisspunkte noetig sind, um ein bestimmtes Ziel
   zu ueberholen.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from ..config import STANDARD_KAMPFFORMAT
from ..stats import (
    SZENARIEN,
    benoetigte_statuspunkte,
    handelt_zuerst,
    initiative_im_szenario,
)
from . import saison


def speed_tier_liste(conn: sqlite3.Connection, tag: str,
                     kampfformat: str = STANDARD_KAMPFFORMAT,
                     ranggrenze: int = 80,
                     mindest_spread_anteil: float = 5.0) -> pd.DataFrame:
    """Alle im Metagame vorkommenden Initiativwerte mit ihrer Haeufigkeit.

    Je Pokemon koennen mehrere Werte auftreten, weil unterschiedliche Sets
    unterschiedlich stark in Initiative investieren. Genau das ist der
    Erkenntnisgewinn gegenueber einer Betrachtung der Basiswerte: dasselbe
    Pokemon kann je nach Set in verschiedenen Tiers liegen.

    ``gewicht`` verrechnet die Meta-Praesenz des Pokemon mit dem Anteil des Sets.
    Da die Quelle die Nutzung nur als Rang liefert, dient das Rangperzentil als
    Praesenzmass -- eine abgeleitete Groesse, ausdruecklich keine Nutzungsquote.
    """
    df = pd.read_sql(saison.anwenden("""
        SELECT m.anzeigename, m.pokedex_id, m.typ1, m.typ2,
               p.stufe50_speed AS speed_ohne_investition,
               m.bezeichnung AS kurzform, m.wesen, m.punkte_speed,
               m.wert_speed AS speed_real,
               m.anteil AS set_anteil, m.rang AS set_rang,
               u.rang AS usage_rang, u.rang_perzentil
        FROM V_Merkmal m
        JOIN V_Usage   u ON u.pokemon_sk = m.pokemon_sk AND u.zeit_sk = m.zeit_sk
                        AND u.kampfformat_sk = m.kampfformat_sk
                        AND u.saison_sk = m.saison_sk
        JOIN Dim_Pokemon p ON p.pokemon_sk = m.pokemon_sk AND p.ist_aktuell = 1
        WHERE m.kategorie = 'spread' AND m.datum_iso = ? AND m.kampfformat = ?
          AND m.saison_aktuell = 1 AND u.rang <= ? AND m.anteil >= ?
          AND m.wert_speed IS NOT NULL
        ORDER BY m.wert_speed DESC
    """, conn), conn, params=(tag, kampfformat, ranggrenze, mindest_spread_anteil))

    if df.empty:
        return df

    df["gewicht"] = (df["rang_perzentil"] * df["set_anteil"] / 100).round(2)
    # Ein bewusst langsames Set: senkendes Wesen ohne Investition in Initiative.
    # In Champions ist das der einzige Weg dorthin, weil die Determinationswerte
    # fest bei 31 liegen und nicht abgesenkt werden koennen.
    df["ist_bizarroraum_set"] = (
        df["wesen"].isin(["Brave", "Relaxed", "Quiet", "Sassy"]) & (df["punkte_speed"] == 0)
    )
    return df.reset_index(drop=True)


def tier_verteilung(tiers: pd.DataFrame, stufenbreite: int = 10) -> pd.DataFrame:
    """Fasst die Initiativwerte zu Baendern zusammen.

    Zeigt, wo sich das Metagame ballt -- an diesen Schwellen entscheidet sich,
    ob eine zusaetzliche Investition in Initiative lohnt oder verpufft.
    """
    if tiers.empty:
        return pd.DataFrame(columns=["band", "untergrenze", "gewicht", "anzahl_sets"])

    tiers = tiers.copy()
    tiers["untergrenze"] = (tiers["speed_real"] // stufenbreite) * stufenbreite

    verteilung = tiers.groupby("untergrenze").agg(
        gewicht=("gewicht", "sum"),
        anzahl_sets=("kurzform", "count"),
    ).reset_index()
    verteilung["band"] = verteilung["untergrenze"].map(
        lambda u: f"{int(u)}-{int(u) + stufenbreite - 1}")
    verteilung["gewicht"] = verteilung["gewicht"].round(1)
    return verteilung.sort_values("untergrenze", ascending=False).reset_index(drop=True)


def einordnung(tiers: pd.DataFrame, initiative: int, szenario: str = "normal"
               ) -> dict[str, float]:
    """Ordnet einen Initiativwert in das Metagame ein.

    Gibt an, welchen Anteil des Metagames der Wert ueberholt -- gewichtet nach
    Begegnungshaeufigkeit, nicht nach blosser Anzahl der Sets. Ein seltenes Set
    zu ueberholen ist weniger wert als ein haeufiges.
    """
    if tiers.empty:
        return {"schneller_als": 0.0, "gleichstand": 0.0, "langsamer_als": 0.0}

    gesamt = tiers["gewicht"].sum()
    if gesamt <= 0:
        return {"schneller_als": 0.0, "gleichstand": 0.0, "langsamer_als": 0.0}

    # Der Effekt wird genau auf der Seite angewandt, die er betrifft. Ein
    # einseitiger Effekt auf beide Seiten angewandt hoebe sich sonst auf.
    beschreibung = SZENARIEN.get(szenario, SZENARIEN["normal"])
    eigener_wert = (initiative_im_szenario(initiative, szenario)
                    if beschreibung.wirkt_auf == "eigene" else initiative)
    gegnerisch = (tiers["speed_real"].map(lambda w: initiative_im_szenario(w, szenario))
                  if beschreibung.wirkt_auf == "gegner" else tiers["speed_real"])

    vergleich = [handelt_zuerst(eigener_wert, wert, szenario) for wert in gegnerisch]
    reihe = pd.Series(vergleich, index=tiers.index)

    return {
        "schneller_als": round(100 * tiers.loc[reihe == "schneller", "gewicht"].sum() / gesamt, 1),
        "gleichstand": round(100 * tiers.loc[reihe == "gleichstand", "gewicht"].sum() / gesamt, 1),
        "langsamer_als": round(100 * tiers.loc[reihe == "langsamer", "gewicht"].sum() / gesamt, 1),
        "eigener_wert": eigener_wert,
    }


def team_einordnung(conn: sqlite3.Connection, namen: list[str], tag: str,
                    szenario: str = "normal",
                    kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Ordnet jedes Teammitglied mit seinem gaengigsten Set in das Metagame ein."""
    if not namen:
        return pd.DataFrame(columns=["Pokemon", "Set", "Ohne Investition", "Initiative",
                                     "Ueberholt (%)", "Gleichstand (%)",
                                     "Wird ueberholt (%)"])

    tiers = speed_tier_liste(conn, tag, kampfformat)
    platzhalter = ",".join("?" * len(namen))
    eigene = pd.read_sql(saison.anwenden(f"""
        SELECT m.anzeigename, m.bezeichnung AS kurzform, m.wesen,
               m.wert_speed AS speed_real, m.anteil,
               p.stufe50_speed AS speed_ohne_investition
        FROM V_Merkmal m
        JOIN Dim_Pokemon p ON p.pokemon_sk = m.pokemon_sk AND p.ist_aktuell = 1
        WHERE m.anzeigename IN ({platzhalter}) AND m.datum_iso = ?
          AND m.kampfformat = ? AND m.kategorie = 'spread' AND m.rang = 1
          AND m.saison_aktuell = 1 AND m.wert_speed IS NOT NULL
    """, conn), conn, params=(*namen, tag, kampfformat))  # noqa: S608

    if eigene.empty or tiers.empty:
        return pd.DataFrame(columns=["Pokemon", "Set", "Ohne Investition", "Initiative",
                                     "Ueberholt (%)", "Gleichstand (%)",
                                     "Wird ueberholt (%)"])

    zeilen = []
    for _, mitglied in eigene.iterrows():
        werte = einordnung(tiers, int(mitglied["speed_real"]), szenario)
        zeilen.append({
            "Pokemon": mitglied["anzeigename"],
            "Set": mitglied["kurzform"],
            "Ohne Investition": int(mitglied["speed_ohne_investition"]),
            "Initiative": werte["eigener_wert"],
            "Ueberholt (%)": werte["schneller_als"],
            "Gleichstand (%)": werte["gleichstand"],
            "Wird ueberholt (%)": werte["langsamer_als"],
        })

    return pd.DataFrame(zeilen).sort_values("Initiative", ascending=False).reset_index(drop=True)


def benchmark(conn: sqlite3.Connection, angreifer_name: str, ziel_name: str,
              tag: str, wesen: str = "Timid",
              kampfformat: str = STANDARD_KAMPFFORMAT) -> dict[str, object] | None:
    """Ermittelt die Investition, die noetig ist, um ein Ziel zu ueberholen.

    Das ist die konkrete Handlungsempfehlung fuer die Teamvorbereitung: nicht
    "investiere maximal", sondern "genau so viel wird gebraucht" -- die
    verbleibenden Statuspunkte stehen fuer Widerstandsfaehigkeit oder
    Durchschlagskraft zur Verfuegung.
    """
    daten = pd.read_sql(saison.anwenden("""
        SELECT m.anzeigename, p.speed AS basiswert, m.wert_speed AS speed_real,
               m.bezeichnung AS kurzform, m.anteil
        FROM V_Merkmal m
        JOIN Dim_Pokemon p ON p.pokemon_sk = m.pokemon_sk AND p.ist_aktuell = 1
        WHERE m.datum_iso = ? AND m.kampfformat = ? AND m.anzeigename IN (?, ?)
          AND m.kategorie = 'spread' AND m.rang = 1 AND m.saison_aktuell = 1
          AND m.wert_speed IS NOT NULL
    """, conn), conn, params=(tag, kampfformat, angreifer_name, ziel_name))

    angreifer = daten[daten["anzeigename"] == angreifer_name]
    ziel = daten[daten["anzeigename"] == ziel_name]
    if angreifer.empty or ziel.empty:
        return None

    basiswert = int(angreifer.iloc[0]["basiswert"])
    zielwert = int(ziel.iloc[0]["speed_real"])
    # Um zuerst zu handeln, genuegt ein Punkt mehr als das Ziel.
    noetig = benoetigte_statuspunkte(basiswert, zielwert + 1, wesen)

    return {
        "angreifer": angreifer_name,
        "angreifer_basiswert": basiswert,
        "ziel": ziel_name,
        "ziel_set": ziel.iloc[0]["kurzform"],
        "ziel_initiative": zielwert,
        "wesen": wesen,
        "benoetigte_punkte": noetig,
        "erreichbar": noetig is not None,
        "aktuelles_set": angreifer.iloc[0]["kurzform"],
        "aktuelle_initiative": int(angreifer.iloc[0]["speed_real"]),
    }


def szenario_uebersicht(conn: sqlite3.Connection, namen: list[str], tag: str,
                        kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Vergleicht die Einordnung des Teams ueber alle Szenarien hinweg.

    Macht sichtbar, wie stark ein Team von Initiative-Unterstuetzung abhaengt:
    ein Team, das erst unter Rueckenwind ueberholt, verliert seine Partien in den
    Runden davor.
    """
    if not namen:
        return pd.DataFrame()

    zeilen = []
    for schluessel, szenario in SZENARIEN.items():
        einordnungen = team_einordnung(conn, namen, tag, schluessel, kampfformat)
        if einordnungen.empty:
            continue
        zeilen.append({
            "Szenario": szenario.bezeichnung,
            "schluessel": schluessel,
            "Mittlere Initiative": round(float(einordnungen["Initiative"].mean()), 1),
            "Ueberholt im Mittel (%)": round(float(einordnungen["Ueberholt (%)"].mean()), 1),
            "Schnellstes Mitglied": einordnungen.iloc[0]["Pokemon"],
            "Erlaeuterung": szenario.erlaeuterung,
        })

    return pd.DataFrame(zeilen)
