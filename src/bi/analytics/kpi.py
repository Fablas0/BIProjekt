"""Kennzahlen der Analyseschicht.

Unterschieden werden nach der ueblichen Systematik:

* **Absolute Kennzahlen** -- Partienzahl, Anzahl gefuehrter Pokemon, Rohzaehler.
* **Relative Kennzahlen** (Verhaeltniszahlen) -- Nutzungsanteil, Anteil eines
  Archetyps, Anteil eines Items an den Sets eines Pokemon.
* **Zeitbezogene Kennzahlen** -- Veraenderung des Nutzungsanteils gegenueber dem
  Vormonat (Momentum), gleitende Entwicklung ueber die geladene Zeitreihe.
* **Verdichtete Kennzahlen (Kennzahlensystem)** -- Konzentrationsmass des
  Metagames auf Basis des Herfindahl-Hirschman-Index.

Zur fehlenden Siegquote
-----------------------
Die urspruengliche Umsetzung fuehrte eine Kennzahl ``win_rate``, die konstant mit
0 belegt wurde: die Smogon-Auswertung enthaelt keine Siegquote je Pokemon. An ihre
Stelle tritt hier das **Viability Ceiling**, das Smogon tatsaechlich liefert -- die
GXE-Werte (erwarteter Anteil gewonnener Partien) der besten, der oberen 25 Prozent
und der mittleren Spieler, die das jeweilige Pokemon einsetzen. Damit ist die
Fragestellung "wie erfolgreich ist dieses Pokemon?" belegbar beantwortbar, statt
sie mit einem Platzhalter zu bedienen.
"""

from __future__ import annotations

import sqlite3

import pandas as pd


def _lese(conn: sqlite3.Connection, sql: str, parameter: tuple | None = None) -> pd.DataFrame:
    return pd.read_sql(sql, conn, params=parameter or ())


# --------------------------------------------------------------------------
# Basisabfragen
# --------------------------------------------------------------------------

def verfuegbare_monate(conn: sqlite3.Connection) -> list[str]:
    """Alle in der Faktentabelle vertretenen Monate, aufsteigend."""
    return [z[0] for z in conn.execute(
        "SELECT DISTINCT z.monat_iso FROM Fact_Usage f "
        "JOIN Dim_Zeit z ON z.zeit_sk = f.zeit_sk ORDER BY z.monat_iso"
    )]


def aktueller_monat(conn: sqlite3.Connection) -> str | None:
    """Der juengste Monat mit Bewegungsdaten."""
    monate = verfuegbare_monate(conn)
    return monate[-1] if monate else None


def geladenes_format(conn: sqlite3.Connection) -> dict[str, object]:
    """Beschreibung des aktuell geladenen Formats fuer die Kopfzeile des Cockpits."""
    zeile = conn.execute("""
        SELECT r.anzeige, r.regulation, r.spielmodus, s.bezeichnung, s.elo_cutoff,
               COUNT(DISTINCT z.monat_iso) AS monate
        FROM Fact_Usage f
        JOIN Dim_Regulation r ON r.regulation_sk = f.regulation_sk
        JOIN Dim_Skill      s ON s.skill_sk      = f.skill_sk
        JOIN Dim_Zeit       z ON z.zeit_sk       = f.zeit_sk
        GROUP BY r.anzeige, r.regulation, r.spielmodus, s.bezeichnung, s.elo_cutoff
        ORDER BY COUNT(*) DESC LIMIT 1
    """).fetchone()
    if zeile is None:
        return {}
    return dict(zeile)


def meta_uebersicht(conn: sqlite3.Connection, monat_iso: str) -> pd.DataFrame:
    """Vollstaendige Faktensicht eines Monats -- Grundlage der meisten Auswertungen."""
    return _lese(conn, "SELECT * FROM V_Usage WHERE monat_iso = ? ORDER BY usage_rate DESC",
                 (monat_iso,))


# --------------------------------------------------------------------------
# Absolute und relative Kennzahlen
# --------------------------------------------------------------------------

def eckwerte(conn: sqlite3.Connection, monat_iso: str) -> dict[str, float]:
    """Verdichtete Eckwerte eines Monats fuer die Kennzahlenkacheln."""
    df = meta_uebersicht(conn, monat_iso)
    if df.empty:
        return {}

    top10 = df.nlargest(10, "usage_rate")["usage_rate"].sum()
    gesamt = df["usage_rate"].sum()

    return {
        "pokemon_gefuehrt": int(len(df)),
        "partien": int(df["partien_gesamt"].iloc[0]),
        "top10_anteil": round(100 * top10 / gesamt, 1) if gesamt else 0.0,
        "konzentration": herfindahl(df["usage_rate"]),
        "bestes_gxe": round(float(df["gxe_top"].max()), 1) if df["gxe_top"].notna().any() else 0.0,
        "typen_vielfalt": int(pd.concat([df["typ1"], df["typ2"].dropna()]).nunique()),
    }


def herfindahl(anteile: pd.Series) -> float:
    """Herfindahl-Hirschman-Index der Nutzungsverteilung, normiert auf 0 bis 100.

    Der Index misst, wie stark sich das Metagame auf wenige Pokemon konzentriert.
    Ein niedriger Wert steht fuer ein breites, vielfaeltiges Feld, ein hoher Wert
    fuer ein von wenigen Optionen dominiertes Format.

    Die Normierung erfolgt auf die relativen Anteile, damit der Wert unabhaengig
    von der Zahl der erfassten Pokemon vergleichbar bleibt.
    """
    summe = anteile.sum()
    if summe <= 0:
        return 0.0
    relativ = anteile / summe
    return round(float((relativ**2).sum()) * 100, 2)


def usage_verteilung(conn: sqlite3.Connection, monat_iso: str, grenze: int = 20) -> pd.DataFrame:
    """Die meistgenutzten Pokemon eines Monats."""
    return _lese(conn, """
        SELECT pokedex_id, anzeigename, typ1, typ2, usage_rate, raw_count,
               gxe_top, rolle, rang
        FROM V_Usage WHERE monat_iso = ? ORDER BY usage_rate DESC LIMIT ?
    """, (monat_iso, grenze))


# --------------------------------------------------------------------------
# Zeitbezogene Kennzahlen
# --------------------------------------------------------------------------

def zeitreihe(conn: sqlite3.Connection, namen: list[str] | None = None) -> pd.DataFrame:
    """Nutzungsanteil je Pokemon und Monat ueber den gesamten geladenen Zeitraum."""
    if namen:
        platzhalter = ",".join("?" * len(namen))
        return _lese(conn, f"""
            SELECT anzeigename, monat_iso, monat_name, usage_rate, rang, gxe_top
            FROM V_Usage WHERE anzeigename IN ({platzhalter})
            ORDER BY monat_iso, usage_rate DESC
        """, tuple(namen))  # noqa: S608
    return _lese(conn, """
        SELECT anzeigename, monat_iso, monat_name, usage_rate, rang, gxe_top
        FROM V_Usage ORDER BY monat_iso, usage_rate DESC
    """)


def momentum(conn: sqlite3.Connection, monat_iso: str, vormonat_iso: str | None = None,
             mindestanteil: float = 1.0) -> pd.DataFrame:
    """Veraenderung des Nutzungsanteils gegenueber dem Vormonat.

    Diese Kennzahl beantwortet die eigentliche Planungsfrage: nicht was gerade
    stark ist, sondern was staerker *wird*. Wer ein Team fuer ein Turnier in
    einigen Wochen vorbereitet, muss den Trend kennen, nicht den Ist-Stand.

    ``mindestanteil`` filtert Nischen-Pokemon heraus, bei denen schon geringe
    absolute Schwankungen sehr grosse relative Veraenderungen ergeben.
    """
    monate = verfuegbare_monate(conn)
    if len(monate) < 2 or monat_iso not in monate:
        return pd.DataFrame(columns=["anzeigename", "usage_rate", "vormonat_rate",
                                     "differenz", "veraenderung_prozent", "richtung"])

    if vormonat_iso is None:
        vormonat_iso = monate[monate.index(monat_iso) - 1] if monate.index(monat_iso) > 0 else None
    if vormonat_iso is None:
        return pd.DataFrame(columns=["anzeigename", "usage_rate", "vormonat_rate",
                                     "differenz", "veraenderung_prozent", "richtung"])

    aktuell = _lese(conn, """
        SELECT anzeigename, typ1, typ2, usage_rate, rang, rolle
        FROM V_Usage WHERE monat_iso = ?
    """, (monat_iso,))
    vorher = _lese(conn, """
        SELECT anzeigename, usage_rate AS vormonat_rate, rang AS vormonat_rang
        FROM V_Usage WHERE monat_iso = ?
    """, (vormonat_iso,))

    df = aktuell.merge(vorher, on="anzeigename", how="outer")
    df["usage_rate"] = df["usage_rate"].fillna(0.0)
    df["vormonat_rate"] = df["vormonat_rate"].fillna(0.0)
    df["differenz"] = (df["usage_rate"] - df["vormonat_rate"]).round(2)

    # Bei einem Neueinsteiger ist die relative Veraenderung nicht definiert; er
    # wird gesondert gekennzeichnet statt mit einem unendlichen Wert gefuehrt.
    df["veraenderung_prozent"] = df.apply(
        lambda z: round(100 * z["differenz"] / z["vormonat_rate"], 1)
        if z["vormonat_rate"] > 0 else None, axis=1,
    )
    df["richtung"] = df.apply(
        lambda z: "Neu im Meta" if z["vormonat_rate"] == 0
        else "Ausgeschieden" if z["usage_rate"] == 0
        else "Steigend" if z["differenz"] > 0.2
        else "Fallend" if z["differenz"] < -0.2
        else "Stabil", axis=1,
    )
    df["rang_veraenderung"] = (df["vormonat_rang"] - df["rang"]).astype("Int64")

    relevant = df[(df["usage_rate"] >= mindestanteil) | (df["vormonat_rate"] >= mindestanteil)]
    return relevant.sort_values("differenz", ascending=False).reset_index(drop=True)


def konzentration_zeitverlauf(conn: sqlite3.Connection) -> pd.DataFrame:
    """Entwicklung der Meta-Konzentration ueber alle geladenen Monate.

    Ein steigender Index bedeutet, dass sich das Feld auf immer weniger Optionen
    verengt -- ein wichtiges Signal fuer die Formatgesundheit und fuer die Frage,
    wie riskant ein Nischen-Team ist.
    """
    df = _lese(conn, """
        SELECT z.monat_iso, z.monat_name, f.usage_rate, f.partien_gesamt
        FROM Fact_Usage f JOIN Dim_Zeit z ON z.zeit_sk = f.zeit_sk
    """)
    if df.empty:
        return pd.DataFrame(columns=["monat_iso", "monat_name", "konzentration",
                                     "top10_anteil", "anzahl_pokemon", "partien"])

    zeilen = []
    for monat, gruppe in df.groupby("monat_iso"):
        gesamt = gruppe["usage_rate"].sum()
        top10 = gruppe.nlargest(10, "usage_rate")["usage_rate"].sum()
        zeilen.append({
            "monat_iso": monat,
            "monat_name": gruppe["monat_name"].iloc[0],
            "konzentration": herfindahl(gruppe["usage_rate"]),
            "top10_anteil": round(100 * top10 / gesamt, 1) if gesamt else 0.0,
            "anzahl_pokemon": int(len(gruppe)),
            "partien": int(gruppe["partien_gesamt"].iloc[0]),
        })
    return pd.DataFrame(zeilen).sort_values("monat_iso").reset_index(drop=True)


# --------------------------------------------------------------------------
# Detailkennzahlen zu einzelnen Pokemon
# --------------------------------------------------------------------------

def standardset(conn: sqlite3.Connection, anzeigename: str, monat_iso: str) -> dict[str, pd.DataFrame]:
    """Meistgespielte Konfiguration eines Pokemon.

    Ersetzt die frueheren Einzelspalten ``move1`` bis ``move4``: statt vier fest
    verdrahteter Attacken liefert die Faktentabelle die vollstaendige Verteilung
    samt Anteil, sodass sichtbar wird, wie einheitlich ein Set tatsaechlich ist.
    """
    attacken = _lese(conn, """
        SELECT attacke, attacke_typ, kategorie, basisschaden, taktik_klasse, anteil
        FROM V_Attacken WHERE anzeigename = ? AND monat_iso = ?
        ORDER BY anteil DESC LIMIT 10
    """, (anzeigename, monat_iso))

    loadout = _lese(conn, """
        SELECT l.auspraegung_art, l.auspraegung, l.anteil
        FROM V_Loadout l
        JOIN Dim_Pokemon p ON p.pokemon_sk = l.pokemon_sk
        JOIN Dim_Zeit    z ON z.zeit_sk    = l.zeit_sk
        WHERE p.anzeigename = ? AND z.monat_iso = ? AND p.ist_aktuell = 1
        ORDER BY l.auspraegung_art, l.anteil DESC
    """, (anzeigename, monat_iso))

    return {
        "attacken": attacken,
        "items": loadout[loadout["auspraegung_art"] == "Item"].head(5),
        "faehigkeiten": loadout[loadout["auspraegung_art"] == "Faehigkeit"].head(3),
        "tera": loadout[loadout["auspraegung_art"] == "Tera-Typ"].head(5),
    }


def teampartner(conn: sqlite3.Connection, namen: list[str], monat_iso: str,
                grenze: int = 8) -> pd.DataFrame:
    """Statistisch haeufigste Partner der uebergebenen Pokemon.

    Der Synergiewert gibt an, in wie viel Prozent der Teams mit dem jeweiligen
    Pokemon der Partner ebenfalls vertreten ist. Ueber mehrere ausgewaehlte
    Pokemon hinweg wird gemittelt, sodass ein Partner bevorzugt wird, der zum
    gesamten Team passt und nicht nur zu einem einzelnen Mitglied.
    """
    if not namen:
        return pd.DataFrame(columns=["partner", "partner_pokedex_id", "mittlerer_anteil",
                                     "passt_zu", "partner_typ1", "partner_typ2"])

    platzhalter = ",".join("?" * len(namen))
    df = _lese(conn, f"""
        SELECT partner, partner_pokedex_id, partner_typ1, partner_typ2,
               pokemon, synergie_wert
        FROM V_Teampartner
        WHERE pokemon IN ({platzhalter}) AND monat_iso = ?
    """, (*namen, monat_iso))  # noqa: S608

    if df.empty:
        return pd.DataFrame(columns=["partner", "partner_pokedex_id", "mittlerer_anteil",
                                     "passt_zu", "partner_typ1", "partner_typ2"])

    # Bereits gewaehlte Teammitglieder sind keine Vorschlaege mehr.
    df = df[~df["partner"].isin(namen)]
    if df.empty:
        return pd.DataFrame(columns=["partner", "partner_pokedex_id", "mittlerer_anteil",
                                     "passt_zu", "partner_typ1", "partner_typ2"])

    aggregiert = df.groupby(
        ["partner", "partner_pokedex_id", "partner_typ1", "partner_typ2"], dropna=False
    ).agg(
        mittlerer_anteil=("synergie_wert", "mean"),
        passt_zu=("pokemon", lambda s: ", ".join(sorted(set(s)))),
        treffer=("pokemon", "nunique"),
    ).reset_index()

    # Gewichtung: ein Partner, der zu mehreren Teammitgliedern passt, ist
    # wertvoller als einer mit hohem Anteil bei nur einem Mitglied.
    aggregiert["punktzahl"] = (
        aggregiert["mittlerer_anteil"] * (1 + 0.35 * (aggregiert["treffer"] - 1))
    ).round(2)
    aggregiert["mittlerer_anteil"] = aggregiert["mittlerer_anteil"].round(1)

    return aggregiert.sort_values("punktzahl", ascending=False).head(grenze).reset_index(drop=True)
