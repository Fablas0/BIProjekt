"""Kennzahlen der Analyseschicht.

Das Messniveau bestimmt die Kennzahl
-------------------------------------
Pokemon Champions gibt die Nutzung eines Pokemon als **Rang** aus, nicht als
Anteil. Das ist eine ordinale Groesse: Rang 1 ist besser als Rang 2, aber *um
wie viel* besser sagt die Zahl nicht. Damit sind Summen und Mittelwerte ueber
Raenge fachlich nicht belastbar -- ein Konzentrationsmass wie der
Herfindahl-Index, das quadrierte Anteile aufsummiert, laesst sich darauf nicht
anwenden.

Die Kennzahlen sind deshalb auf zulaessige Statistiken fuer Rangdaten
ausgelegt:

===============================  ==========================================
Fragestellung                    Kennzahl
===============================  ==========================================
Wer steigt, wer faellt?          Rangveraenderung gegenueber einem Vortag
Wie stabil ist das Format?       Rangkorrelation nach Spearman zwischen
                                 zwei Tagen (0 bis 1)
Wie fest ist die Spitze?         Fluktuation der besten N
Wer haelt sich oben?             Verweildauer in den besten N
===============================  ==========================================

Auf der Merkmalsebene -- welche Attacke in wie viel Prozent der Sets vorkommt --
liefert die Quelle dagegen **echte Anteile**. Dort sind kardinale Kennzahlen
zulaessig, und genau dort wird der Herfindahl-Index eingesetzt: als Mass fuer die
Vorhersagbarkeit eines Sets.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from ..config import STANDARD_KAMPFFORMAT


def _lese(conn: sqlite3.Connection, sql: str, parameter: tuple = ()) -> pd.DataFrame:
    return pd.read_sql(sql, conn, params=parameter)


# --------------------------------------------------------------------------
# Basisabfragen
# --------------------------------------------------------------------------

def verfuegbare_tage(conn: sqlite3.Connection, kampfformat: str = STANDARD_KAMPFFORMAT
                     ) -> list[str]:
    """Alle Tage mit Bewegungsdaten der laufenden Saison, aufsteigend."""
    return [z[0] for z in conn.execute("""
        SELECT DISTINCT z.datum_iso
        FROM Fact_Champions_Usage f
        JOIN Dim_Zeit        z ON z.zeit_sk        = f.zeit_sk
        JOIN Dim_Kampfformat k ON k.kampfformat_sk = f.kampfformat_sk
        JOIN Dim_Saison      s ON s.saison_sk      = f.saison_sk
        WHERE k.schluessel = ? AND s.ist_aktuell = 1
        ORDER BY z.datum_iso
    """, (kampfformat,))]


def aktueller_tag(conn: sqlite3.Connection,
                  kampfformat: str = STANDARD_KAMPFFORMAT) -> str | None:
    """Der juengste Tag mit Bewegungsdaten."""
    tage = verfuegbare_tage(conn, kampfformat)
    return tage[-1] if tage else None


def verfuegbare_formate(conn: sqlite3.Connection) -> list[str]:
    """Kampfformate, zu denen Daten vorliegen."""
    return [z[0] for z in conn.execute("""
        SELECT DISTINCT k.schluessel FROM Fact_Champions_Usage f
        JOIN Dim_Kampfformat k ON k.kampfformat_sk = f.kampfformat_sk
        ORDER BY k.schluessel DESC
    """)]


def datenbasis(conn: sqlite3.Connection) -> dict[str, object]:
    """Beschreibung der geladenen Datenbasis fuer die Kopfzeile des Cockpits."""
    zeile = conn.execute("""
        SELECT s.schluessel AS saison, s.bezeichnung, s.beginn, s.ende,
               q.name AS quelle, q.messniveau_nutzung,
               COUNT(DISTINCT z.datum_iso) AS tage
        FROM Fact_Champions_Usage f
        JOIN Dim_Saison s ON s.saison_sk = f.saison_sk
        JOIN Dim_Quelle q ON q.quelle_sk = f.quelle_sk
        JOIN Dim_Zeit   z ON z.zeit_sk   = f.zeit_sk
        WHERE s.ist_aktuell = 1
        GROUP BY s.schluessel, s.bezeichnung, s.beginn, s.ende, q.name, q.messniveau_nutzung
    """).fetchone()
    return dict(zeile) if zeile else {}


def rangliste(conn: sqlite3.Connection, tag: str,
              kampfformat: str = STANDARD_KAMPFFORMAT,
              grenze: int | None = None) -> pd.DataFrame:
    """Vollstaendige Rangliste eines Tages -- Grundlage der meisten Auswertungen."""
    sql = """
        SELECT * FROM V_Usage
        WHERE datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
        ORDER BY rang
    """
    df = _lese(conn, sql, (tag, kampfformat))
    return df.head(grenze) if grenze else df


def meta_uebersicht(conn: sqlite3.Connection, tag: str,
                    kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Rangliste eines Tages, angereichert um die gaengigste Konfiguration.

    Die realen Statuswerte stammen aus dem meistgespielten Set; liegt keines vor,
    fallen sie auf die Werte ohne Investition zurueck.
    """
    return _lese(conn, """
        SELECT u.*,
               COALESCE(m.wert_speed,     u.stufe50_speed)     AS speed_real,
               COALESCE(m.wert_attack,    u.stufe50_attack)    AS attack_real,
               COALESCE(m.wert_sp_attack, u.stufe50_sp_attack) AS sp_attack_real,
               COALESCE(m.wert_hp,        u.stufe50_hp)        AS hp_real,
               m.bezeichnung AS top_set,
               m.wesen       AS top_wesen,
               m.anteil      AS top_set_anteil
        FROM V_Usage u
        LEFT JOIN V_Merkmal m
               ON m.pokemon_sk = u.pokemon_sk AND m.zeit_sk = u.zeit_sk
              AND m.saison_sk = u.saison_sk AND m.kampfformat_sk = u.kampfformat_sk
              AND m.kategorie = 'spread' AND m.rang = 1
        WHERE u.datum_iso = ? AND u.kampfformat = ? AND u.saison_aktuell = 1
        ORDER BY u.rang
    """, (tag, kampfformat))


# --------------------------------------------------------------------------
# Eckwerte
# --------------------------------------------------------------------------

def eckwerte(conn: sqlite3.Connection, tag: str,
             kampfformat: str = STANDARD_KAMPFFORMAT) -> dict[str, object]:
    """Verdichtete Eckwerte eines Tages fuer die Kennzahlenkacheln."""
    df = rangliste(conn, tag, kampfformat)
    if df.empty:
        return {}

    tage = verfuegbare_tage(conn, kampfformat)
    stabilitaet = (meta_stabilitaet(conn, tage[0], tag, kampfformat)
                   if len(tage) > 1 else None)

    return {
        "erfasste_pokemon": int(df["erfasste_pokemon"].iloc[0]),
        "typen_vielfalt": int(pd.concat([df["typ1"], df["typ2"].dropna()]).nunique()),
        "beobachtete_tage": len(tage),
        "stabilitaet": stabilitaet,
        "spitzenreiter": df.iloc[0]["anzeigename"],
        "rollen_vielfalt": int(df.head(20)["rolle"].nunique()),
    }


# --------------------------------------------------------------------------
# Zeitbezogene Kennzahlen auf Rangbasis
# --------------------------------------------------------------------------

def rangverlauf(conn: sqlite3.Connection, namen: list[str] | None = None,
                kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Rang je Pokemon und Tag ueber den gesamten geladenen Zeitraum."""
    sql = """
        SELECT anzeigename, datum_iso, tag_label, rang, rang_perzentil
        FROM V_Usage WHERE kampfformat = ? AND saison_aktuell = 1
    """
    parameter: tuple = (kampfformat,)
    if namen:
        sql += f" AND anzeigename IN ({','.join('?' * len(namen))})"
        parameter += tuple(namen)
    return _lese(conn, sql + " ORDER BY datum_iso, rang", parameter)


def rangbewegung(conn: sqlite3.Connection, tag: str, vergleichstag: str | None = None,
                 kampfformat: str = STANDARD_KAMPFFORMAT,
                 ranggrenze: int = 60) -> pd.DataFrame:
    """Veraenderung des Nutzungsrangs gegenueber einem frueheren Tag.

    Diese Kennzahl beantwortet die eigentliche Planungsfrage: nicht was gerade
    stark ist, sondern was staerker *wird*. Bei Rangdaten ist die Differenz
    zweier Raenge die zulaessige Vergleichsgroesse -- ein positiver Wert bedeutet
    einen Aufstieg (kleinerer Rang).

    ``ranggrenze`` blendet Nischen-Pokemon aus, bei denen schon geringe
    Schwankungen grosse Rangspruenge ergeben.
    """
    tage = verfuegbare_tage(conn, kampfformat)
    leer = pd.DataFrame(columns=["anzeigename", "rang", "vorher_rang", "veraenderung",
                                 "richtung", "typ1", "typ2", "rolle", "pokedex_id"])
    if len(tage) < 2 or tag not in tage:
        return leer

    if vergleichstag is None:
        vergleichstag = tage[tage.index(tag) - 1]
    if vergleichstag not in tage:
        return leer

    aktuell = _lese(conn, """
        SELECT pokedex_id, anzeigename, typ1, typ2, rolle, rang, rang_perzentil
        FROM V_Usage WHERE datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
    """, (tag, kampfformat))
    vorher = _lese(conn, """
        SELECT anzeigename, rang AS vorher_rang
        FROM V_Usage WHERE datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
    """, (vergleichstag, kampfformat))

    df = aktuell.merge(vorher, on="anzeigename", how="outer")
    # Ein kleinerer Rang ist besser; die Veraenderung wird deshalb so gebildet,
    # dass positive Werte einen Aufstieg bedeuten.
    df["veraenderung"] = (df["vorher_rang"] - df["rang"]).astype("Int64")
    df["richtung"] = df.apply(
        lambda z: "Neu erfasst" if pd.isna(z["vorher_rang"])
        else "Nicht mehr erfasst" if pd.isna(z["rang"])
        else "Aufgestiegen" if z["veraenderung"] > 0
        else "Abgestiegen" if z["veraenderung"] < 0
        else "Unveraendert", axis=1,
    )

    relevant = df[(df["rang"] <= ranggrenze) | (df["vorher_rang"] <= ranggrenze)]
    return relevant.sort_values("veraenderung", ascending=False,
                                na_position="last").reset_index(drop=True)


def meta_stabilitaet(conn: sqlite3.Connection, tag_a: str, tag_b: str,
                     kampfformat: str = STANDARD_KAMPFFORMAT) -> float | None:
    """Rangkorrelation nach Spearman zwischen zwei Tagen.

    Das ordinale Gegenstueck zu einem Konzentrationsmass: der Wert gibt an, wie
    stark sich die Reihenfolge des Metagames zwischen den beiden Tagen erhalten
    hat. 1 bedeutet eine unveraenderte Rangfolge, 0 keinerlei Zusammenhang.

    Da beide Reihen bereits Raenge sind, ist die Spearman-Korrelation hier
    definitionsgemaess die Produkt-Moment-Korrelation der Raenge.
    """
    a = _lese(conn, """
        SELECT anzeigename, rang FROM V_Usage
        WHERE datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
    """, (tag_a, kampfformat))
    b = _lese(conn, """
        SELECT anzeigename, rang AS rang_b FROM V_Usage
        WHERE datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
    """, (tag_b, kampfformat))

    gemeinsam = a.merge(b, on="anzeigename", how="inner")
    if len(gemeinsam) < 3:
        return None

    korrelation = gemeinsam["rang"].corr(gemeinsam["rang_b"], method="spearman")
    return None if pd.isna(korrelation) else round(float(korrelation), 4)


def stabilitaet_verlauf(conn: sqlite3.Connection,
                        kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Entwicklung der Meta-Stabilitaet ueber alle geladenen Tage.

    Verglichen wird jeweils mit dem ersten geladenen Tag. Ein fallender Wert
    bedeutet, dass sich das Feld zunehmend umsortiert.
    """
    tage = verfuegbare_tage(conn, kampfformat)
    if len(tage) < 2:
        return pd.DataFrame(columns=["datum_iso", "stabilitaet_zum_start",
                                     "stabilitaet_zum_vortag", "top10_fluktuation"])

    zeilen = []
    for i, tag in enumerate(tage[1:], start=1):
        zeilen.append({
            "datum_iso": tag,
            "stabilitaet_zum_start": meta_stabilitaet(conn, tage[0], tag, kampfformat),
            "stabilitaet_zum_vortag": meta_stabilitaet(conn, tage[i - 1], tag, kampfformat),
            "top10_fluktuation": top_n_fluktuation(conn, tage[i - 1], tag, 10, kampfformat),
        })
    return pd.DataFrame(zeilen)


def top_n_fluktuation(conn: sqlite3.Connection, tag_a: str, tag_b: str,
                      n: int = 10, kampfformat: str = STANDARD_KAMPFFORMAT) -> int:
    """Wie viele der besten N zwischen zwei Tagen ausgetauscht wurden.

    Ein unmittelbar verstaendliches Mass fuer die Bewegung an der Spitze: null
    bedeutet eine unveraenderte Spitzengruppe.
    """
    def besten(tag: str) -> set[str]:
        return {z[0] for z in conn.execute("""
            SELECT anzeigename FROM V_Usage
            WHERE datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
              AND rang <= ?
        """, (tag, kampfformat, n))}

    return len(besten(tag_b) - besten(tag_a))


def verweildauer(conn: sqlite3.Connection, n: int = 10,
                 kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """An wie vielen Tagen sich ein Pokemon in den besten N gehalten hat.

    Unterscheidet dauerhaft etablierte Pokemon von kurzzeitigen Ausreissern --
    fuer die Turniervorbereitung ein wichtiger Unterschied.
    """
    tage = verfuegbare_tage(conn, kampfformat)
    if not tage:
        return pd.DataFrame(columns=["anzeigename", "tage_in_top", "anteil_tage",
                                     "bester_rang", "schlechtester_rang", "aktueller_rang"])

    df = _lese(conn, """
        SELECT anzeigename, pokedex_id, typ1, typ2, datum_iso, rang
        FROM V_Usage WHERE kampfformat = ? AND saison_aktuell = 1 AND rang <= ?
    """, (kampfformat, n))
    if df.empty:
        return pd.DataFrame(columns=["anzeigename", "tage_in_top", "anteil_tage",
                                     "bester_rang", "schlechtester_rang", "aktueller_rang"])

    aktuell = dict(_lese(conn, """
        SELECT anzeigename, rang FROM V_Usage
        WHERE datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
    """, (tage[-1], kampfformat)).values)

    ergebnis = df.groupby(["anzeigename", "pokedex_id", "typ1", "typ2"],
                          dropna=False).agg(
        tage_in_top=("datum_iso", "nunique"),
        bester_rang=("rang", "min"),
        schlechtester_rang=("rang", "max"),
    ).reset_index()

    ergebnis["anteil_tage"] = (100 * ergebnis["tage_in_top"] / len(tage)).round(1)
    ergebnis["aktueller_rang"] = ergebnis["anzeigename"].map(aktuell).astype("Int64")
    ergebnis["bestaendigkeit"] = ergebnis["anteil_tage"].map(
        lambda a: "Dauerhaft" if a >= 90 else
                  "Etabliert" if a >= 60 else
                  "Schwankend" if a >= 25 else "Kurzzeitig")

    return ergebnis.sort_values(["tage_in_top", "bester_rang"],
                                ascending=[False, True]).reset_index(drop=True)


# --------------------------------------------------------------------------
# Merkmalsebene: hier liegen echte Anteile vor
# --------------------------------------------------------------------------

def herfindahl(anteile: pd.Series) -> float:
    """Herfindahl-Hirschman-Index einer Anteilsverteilung, normiert auf 0 bis 100.

    Wird ausschliesslich auf **echte Anteile** angewandt -- also auf der
    Merkmalsebene, wo die Quelle Prozentwerte liefert. Auf Raenge waere der Index
    nicht anwendbar, weil er quadrierte Anteile aufsummiert.
    """
    summe = anteile.sum()
    if summe <= 0:
        return 0.0
    relativ = anteile / summe
    return round(float((relativ**2).sum()) * 100, 2)


def standardset(conn: sqlite3.Connection, anzeigename: str, tag: str,
                kampfformat: str = STANDARD_KAMPFFORMAT) -> dict[str, pd.DataFrame]:
    """Meistgespielte Konfiguration eines Pokemon.

    Liefert die vollstaendige Verteilung statt einer festen Anzahl von Attacken:
    daran ist ablesbar, wie einheitlich ein Set tatsaechlich gespielt wird.
    """
    df = _lese(conn, """
        SELECT kategorie, rang, bezeichnung, anteil, wesen,
               punkte_hp, punkte_attack, punkte_defense,
               punkte_sp_attack, punkte_sp_defense, punkte_speed,
               wert_speed, attacke_typ, attacke_kategorie, basisschaden, taktik_klasse
        FROM V_Merkmal
        WHERE anzeigename = ? AND datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
        ORDER BY kategorie, rang
    """, (anzeigename, tag, kampfformat))

    return {
        art: df[df["kategorie"] == schluessel].reset_index(drop=True)
        for art, schluessel in (
            ("attacken", "move"), ("items", "held_item"), ("faehigkeiten", "ability"),
            ("wesen", "nature"), ("spreads", "spread"), ("partner", "teammate"),
        )
    }


def vorhersagbarkeit(conn: sqlite3.Connection, tag: str,
                     kampfformat: str = STANDARD_KAMPFFORMAT,
                     ranggrenze: int = 30) -> pd.DataFrame:
    """Wie einheitlich die fuehrenden Pokemon gespielt werden.

    Grundlage ist die Verteilung der Punkteverteilungen je Pokemon -- echte
    Anteile, auf die der Herfindahl-Index anwendbar ist. Ein hoher Wert bedeutet,
    dass sich eine Standardkonfiguration durchgesetzt hat und das Verhalten des
    Gegners gut vorhersagbar ist.
    """
    df = _lese(conn, """
        SELECT m.anzeigename, m.pokedex_id, m.bezeichnung, m.anteil, m.rang AS set_rang,
               m.wert_speed, u.rang AS usage_rang
        FROM V_Merkmal m
        JOIN V_Usage u ON u.pokemon_sk = m.pokemon_sk AND u.zeit_sk = m.zeit_sk
                      AND u.kampfformat_sk = m.kampfformat_sk AND u.saison_sk = m.saison_sk
        WHERE m.kategorie = 'spread' AND m.datum_iso = ? AND m.kampfformat = ?
          AND m.saison_aktuell = 1 AND u.rang <= ?
    """, (tag, kampfformat, ranggrenze))

    if df.empty:
        return pd.DataFrame(columns=["anzeigename", "usage_rang", "top_anteil",
                                     "top_set", "konzentration", "einstufung"])

    zeilen = []
    for name, gruppe in df.groupby("anzeigename"):
        oben = gruppe.nsmallest(1, "set_rang").iloc[0]
        zeilen.append({
            "anzeigename": name,
            "pokedex_id": int(oben["pokedex_id"]),
            "usage_rang": int(oben["usage_rang"]),
            "top_set": oben["bezeichnung"],
            "top_anteil": round(float(oben["anteil"] or 0), 1),
            "initiative": int(oben["wert_speed"]) if pd.notna(oben["wert_speed"]) else None,
            "erfasste_sets": int(len(gruppe)),
            "konzentration": herfindahl(gruppe["anteil"].fillna(0)),
        })

    ergebnis = pd.DataFrame(zeilen)
    ergebnis["einstufung"] = ergebnis["top_anteil"].map(
        lambda a: "Sehr hoch" if a >= 60 else
                  "Hoch" if a >= 35 else
                  "Mittel" if a >= 20 else "Gering")
    return ergebnis.sort_values("usage_rang").reset_index(drop=True)


def teampartner(conn: sqlite3.Connection, namen: list[str], tag: str,
                kampfformat: str = STANDARD_KAMPFFORMAT, grenze: int = 8) -> pd.DataFrame:
    """Haeufigste Teampartner der uebergebenen Pokemon.

    Die Quelle liefert Partner nur als **Rangfolge ohne Gewicht**. Es wird daher
    nicht gemittelt, sondern ausgezaehlt: wie oft ein Partner in den Listen der
    gewaehlten Pokemon auftaucht und auf welchem Rang. Ein Partner, der bei
    mehreren Teammitgliedern vorne steht, ist der bessere Vorschlag.
    """
    leer = pd.DataFrame(columns=["partner", "nennungen", "bester_rang",
                                 "mittlerer_rang", "passt_zu"])
    if not namen:
        return leer

    platzhalter = ",".join("?" * len(namen))
    df = _lese(conn, f"""
        SELECT anzeigename AS pokemon, bezeichnung AS partner, rang
        FROM V_Merkmal
        WHERE kategorie = 'teammate' AND anzeigename IN ({platzhalter})
          AND datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
    """, (*namen, tag, kampfformat))  # noqa: S608

    if df.empty:
        return leer

    df = df[~df["partner"].isin(namen)]
    if df.empty:
        return leer

    aggregiert = df.groupby("partner").agg(
        nennungen=("pokemon", "nunique"),
        bester_rang=("rang", "min"),
        mittlerer_rang=("rang", "mean"),
        passt_zu=("pokemon", lambda s: ", ".join(sorted(set(s)))),
    ).reset_index()
    aggregiert["mittlerer_rang"] = aggregiert["mittlerer_rang"].round(1)

    # Sortiert nach Zahl der Nennungen, bei Gleichstand nach bestem Rang.
    return (aggregiert.sort_values(["nennungen", "bester_rang"], ascending=[False, True])
            .head(grenze).reset_index(drop=True))
