"""Bedrohungs- und Abdeckungsanalyse.

Hintergrund
-----------
Die Smogon-Auswertung enthaelt formal ein Feld ``Checks and Counters``. Fuer die
VGC-Formate ist dieses Feld jedoch durchgaengig leer -- geprueft ueber alle
geladenen Monate hinweg fuer saemtliche erfassten Pokemon. Eine Auswertung, die
sich darauf stuetzt, liefert deshalb nie ein Ergebnis, ohne dass ein Fehler
sichtbar wuerde.

Statt diese Luecke unbemerkt zu lassen, wird die Bedrohungsanalyse hier aus
vorhandenen Daten **berechnet**: aus der Typen-Regelbasis, den Basiswerten der
Pokemon-Dimension, den tatsaechlich gespielten Attacken der Faktentabelle und der
Nutzungshaeufigkeit im Metagame. Das ist ein Anreicherungsschritt im Sinne des
ETL-Prozesses und liefert eine nachvollziehbare, begruendbare Kennzahl.

Gewichtung mit der Meta-Haeufigkeit
-----------------------------------
Eine Typenschwaeche ist nur so gefaehrlich, wie der entsprechende Angriffstyp
tatsaechlich gespielt wird. Eine Anfaelligkeit gegen Eis wiegt schwerer als eine
gegen Kaefer, wenn Eis-Attacken im Metagame um ein Vielfaches haeufiger vorkommen.
Die Auswertung gewichtet Schwaechen daher mit der aus der Faktentabelle
ermittelten Haeufigkeit des jeweiligen Angriffstyps.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from ..config import ALLE_TYPEN
from ..typechart import eingehender_multiplikator


def angriffstyp_haeufigkeit(conn: sqlite3.Connection, monat_iso: str) -> pd.DataFrame:
    """Wie haeufig ein Angriffstyp im Metagame tatsaechlich vorkommt.

    Verknuepft drei Fakten: wie oft ein Pokemon gespielt wird (Nutzungsanteil),
    wie oft es eine bestimmte Attacke fuehrt (Attackenanteil) und welchen Typ
    diese Attacke hat. Status-Attacken bleiben unberuecksichtigt, weil sie keinen
    typbasierten Schaden verursachen.
    """
    df = pd.read_sql("""
        SELECT a.attacke_typ, u.usage_rate, a.anteil
        FROM V_Attacken a
        JOIN V_Usage u ON u.pokemon_sk = a.pokemon_sk AND u.zeit_sk = a.zeit_sk
                      AND u.regulation_sk = a.regulation_sk AND u.skill_sk = a.skill_sk
        WHERE a.monat_iso = ? AND a.kategorie IN ('physical', 'special')
          AND a.attacke_typ IS NOT NULL AND a.attacke_typ != ''
    """, conn, params=(monat_iso,))

    if df.empty:
        return pd.DataFrame({"angriffstyp": ALLE_TYPEN, "haeufigkeit": 0.0, "anteil_prozent": 0.0})

    # Erwartete Praesenz eines Angriffstyps = Nutzung des Pokemon x Anteil der Attacke.
    df["gewicht"] = df["usage_rate"] * df["anteil"] / 100

    aggregiert = (df.groupby("attacke_typ")["gewicht"].sum()
                  .reindex(ALLE_TYPEN, fill_value=0.0).reset_index())
    aggregiert.columns = ["angriffstyp", "haeufigkeit"]

    gesamt = aggregiert["haeufigkeit"].sum()
    aggregiert["anteil_prozent"] = (
        (100 * aggregiert["haeufigkeit"] / gesamt).round(2) if gesamt else 0.0
    )
    aggregiert["haeufigkeit"] = aggregiert["haeufigkeit"].round(2)
    return aggregiert.sort_values("haeufigkeit", ascending=False).reset_index(drop=True)


def team_defensivprofil(team: pd.DataFrame, typ_haeufigkeit: pd.DataFrame | None = None
                        ) -> pd.DataFrame:
    """Defensive Analyse eines Teams gegen alle 18 Angriffstypen.

    Fuer jeden Angriffstyp wird ermittelt, wie viele Teammitglieder anfaellig
    beziehungsweise resistent sind. Die Spalte ``risiko`` verrechnet dies mit der
    Haeufigkeit des Angriffstyps im Metagame und macht die Schwaechen dadurch
    untereinander vergleichbar.
    """
    if team.empty:
        return pd.DataFrame(columns=["angriffstyp", "anfaellig", "resistent", "immun",
                                     "schlimmster_faktor", "meta_anteil", "risiko", "bewertung"])

    haeufigkeit = (
        dict(zip(typ_haeufigkeit["angriffstyp"], typ_haeufigkeit["anteil_prozent"], strict=False))
        if typ_haeufigkeit is not None and not typ_haeufigkeit.empty
        else dict.fromkeys(ALLE_TYPEN, 100 / len(ALLE_TYPEN))
    )

    zeilen = []
    for angriffstyp in ALLE_TYPEN:
        anfaellig = resistent = immun = 0
        schlimmster = 1.0

        for _, mitglied in team.iterrows():
            faktor = eingehender_multiplikator(
                angriffstyp, mitglied.get("typ1"), mitglied.get("typ2")
            )
            schlimmster = max(schlimmster, faktor)
            if faktor == 0:
                immun += 1
            elif faktor >= 2:
                anfaellig += 1
            elif faktor <= 0.5:
                resistent += 1

        meta_anteil = haeufigkeit.get(angriffstyp, 0.0)
        # Ungedeckte Anfaelligkeit: anfaellige Mitglieder ohne Gegengewicht durch
        # resistente oder immune. Genau diese Konstellation kostet Partien.
        ungedeckt = max(0, anfaellig - resistent - immun)
        risiko = round(ungedeckt * meta_anteil * (schlimmster / 2), 2)

        zeilen.append({
            "angriffstyp": angriffstyp,
            "anfaellig": anfaellig,
            "resistent": resistent,
            "immun": immun,
            "schlimmster_faktor": schlimmster,
            "meta_anteil": round(meta_anteil, 2),
            "risiko": risiko,
            "bewertung": _bewertung(anfaellig, resistent + immun, meta_anteil, len(team)),
        })

    return (pd.DataFrame(zeilen).sort_values("risiko", ascending=False)
            .reset_index(drop=True))


def _bewertung(anfaellig: int, gedeckt: int, meta_anteil: float, teamgroesse: int) -> str:
    """Ampeltext zu einer einzelnen Typenschwaeche."""
    if anfaellig == 0:
        return "Unbedenklich"
    if anfaellig >= max(3, teamgroesse // 2) and gedeckt == 0:
        return "Kritisch -- keine Deckung"
    if anfaellig >= 2 and gedeckt == 0 and meta_anteil >= 5:
        return "Kritisch -- haeufig im Meta"
    if anfaellig >= 2 and gedeckt == 0:
        return "Warnung -- ungedeckt"
    if anfaellig > gedeckt:
        return "Beobachten"
    return "Ausreichend gedeckt"


def offensive_abdeckung(conn: sqlite3.Connection, namen: list[str], monat_iso: str
                        ) -> pd.DataFrame:
    """Gegen welche Verteidigungstypen das Team effektiv Schaden anrichtet.

    Grundlage sind die tatsaechlich gespielten Attacken aus der Faktentabelle,
    nicht der theoretisch erlernbare Attackenvorrat -- entscheidend ist, was im
    Turnier auf dem Feld steht.
    """
    if not namen:
        return pd.DataFrame(columns=["verteidigungstyp", "beste_wirkung", "anzahl_angreifer",
                                     "bewertung"])

    platzhalter = ",".join("?" * len(namen))
    attacken = pd.read_sql(f"""
        SELECT DISTINCT anzeigename, attacke, attacke_typ
        FROM V_Attacken
        WHERE anzeigename IN ({platzhalter}) AND monat_iso = ?
          AND kategorie IN ('physical', 'special') AND anteil >= 15
    """, conn, params=(*namen, monat_iso))  # noqa: S608

    if attacken.empty:
        return pd.DataFrame(columns=["verteidigungstyp", "beste_wirkung", "anzahl_angreifer",
                                     "bewertung"])

    zeilen = []
    for verteidigungstyp in ALLE_TYPEN:
        beste = 0.0
        angreifer: set[str] = set()
        for _, attacke in attacken.iterrows():
            faktor = eingehender_multiplikator(attacke["attacke_typ"], verteidigungstyp, None)
            beste = max(beste, faktor)
            if faktor >= 2:
                angreifer.add(attacke["anzeigename"])

        zeilen.append({
            "verteidigungstyp": verteidigungstyp,
            "beste_wirkung": beste,
            "anzahl_angreifer": len(angreifer),
            "bewertung": ("Sehr effektiv" if beste >= 2 else
                          "Neutral" if beste >= 1 else
                          "Kaum Wirkung" if beste > 0 else "Wirkungslos"),
        })

    return pd.DataFrame(zeilen).sort_values("beste_wirkung").reset_index(drop=True)


def bedrohungsindex(conn: sqlite3.Connection, team: pd.DataFrame, monat_iso: str,
                    grenze: int = 10) -> pd.DataFrame:
    """Rangliste der fuer dieses Team gefaehrlichsten Pokemon des Metagames.

    Der Index setzt sich aus drei Faktoren zusammen:

    1. **Offensive Wirksamkeit** -- wie stark die tatsaechlich gespielten Attacken
       des Angreifers gegen die Typen des Teams wirken.
    2. **Initiative** -- ob der Angreifer schneller ist als die bedrohten
       Teammitglieder und dadurch zuerst handelt.
    3. **Meta-Relevanz** -- wie haeufig der Angreifer gespielt wird. Eine
       theoretische Bedrohung, die niemand einsetzt, ist keine praktische.

    Damit ersetzt die Auswertung die in der Quelle nicht befuellten
    ``Checks and Counters`` durch eine belegbare eigene Kennzahl.
    """
    if team.empty:
        return pd.DataFrame(columns=["anzeigename", "typ_kombination", "usage_rate",
                                     "bedrohungswert", "gefaehrdet", "beste_attacke"])

    meta = pd.read_sql("""
        SELECT pokemon_sk, pokedex_id, anzeigename, typ1, typ2, typ_kombination,
               attack, sp_attack, speed, usage_rate
        FROM V_Usage WHERE monat_iso = ? AND usage_rate >= 0.5
    """, conn, params=(monat_iso,))
    if meta.empty:
        return pd.DataFrame(columns=["anzeigename", "typ_kombination", "usage_rate",
                                     "bedrohungswert", "gefaehrdet", "beste_attacke"])

    attacken = pd.read_sql("""
        SELECT pokemon_sk, attacke, attacke_typ, kategorie, basisschaden, anteil
        FROM V_Attacken
        WHERE monat_iso = ? AND kategorie IN ('physical', 'special') AND anteil >= 20
    """, conn, params=(monat_iso,))
    attacken_je_pokemon = dict(list(attacken.groupby("pokemon_sk")))

    eigene = team[["anzeigename", "typ1", "typ2", "speed"]].to_dict("records")

    zeilen = []
    for _, angreifer in meta.iterrows():
        if angreifer["anzeigename"] in team["anzeigename"].values:
            continue

        repertoire = attacken_je_pokemon.get(angreifer["pokemon_sk"])
        if repertoire is None or repertoire.empty:
            continue

        gesamt = 0.0
        gefaehrdet: list[str] = []
        beste_attacke = ""
        beste_wirkung = 0.0

        for ziel in eigene:
            treffer = 0.0
            for _, attacke in repertoire.iterrows():
                faktor = eingehender_multiplikator(
                    attacke["attacke_typ"], ziel["typ1"], ziel["typ2"]
                )
                if faktor < 2:
                    continue
                # Angriffswert passend zur Schadenskategorie der Attacke.
                angriffswert = (angreifer["attack"] if attacke["kategorie"] == "physical"
                                else angreifer["sp_attack"])
                staerke = (attacke["basisschaden"] or 60) / 100
                wirkung = faktor * (angriffswert / 100) * staerke * (attacke["anteil"] / 100)
                if wirkung > treffer:
                    treffer = wirkung
                    if wirkung > beste_wirkung:
                        beste_wirkung = wirkung
                        beste_attacke = attacke["attacke"]

            if treffer > 0:
                # Initiativevorteil: wer zuerst handelt, setzt die Bedrohung um,
                # bevor das Ziel reagieren kann.
                tempo = 1.25 if angreifer["speed"] > ziel["speed"] else 0.85
                gesamt += treffer * tempo
                gefaehrdet.append(ziel["anzeigename"])

        if gesamt <= 0:
            continue

        # Meta-Relevanz daempfend gewichten: die Wurzel verhindert, dass die
        # Rangliste allein von den meistgespielten Pokemon bestimmt wird.
        relevanz = float(angreifer["usage_rate"]) ** 0.5
        zeilen.append({
            "pokedex_id": int(angreifer["pokedex_id"]),
            "anzeigename": angreifer["anzeigename"],
            "typ_kombination": angreifer["typ_kombination"],
            "usage_rate": round(float(angreifer["usage_rate"]), 2),
            "bedrohungswert": round(gesamt * relevanz, 2),
            "anzahl_gefaehrdet": len(gefaehrdet),
            "gefaehrdet": ", ".join(gefaehrdet),
            "beste_attacke": beste_attacke,
        })

    if not zeilen:
        return pd.DataFrame(columns=["anzeigename", "typ_kombination", "usage_rate",
                                     "bedrohungswert", "gefaehrdet", "beste_attacke"])

    return (pd.DataFrame(zeilen).sort_values("bedrohungswert", ascending=False)
            .head(grenze).reset_index(drop=True))


def strategie_radar(conn: sqlite3.Connection, namen: list[str], monat_iso: str
                    ) -> list[dict[str, object]]:
    """Erkennt bekannte VGC-Strategien im Attacken- und Faehigkeitsprofil eines Teams.

    Anders als eine fest verdrahtete Abfrage einzelner Attackennamen arbeitet die
    Erkennung ueber die im ETL angereicherte ``taktik_klasse``. Neue Attacken mit
    derselben Funktion werden dadurch automatisch erfasst.
    """
    if not namen:
        return []

    platzhalter = ",".join("?" * len(namen))
    attacken = pd.read_sql(f"""
        SELECT anzeigename, attacke, taktik_klasse, anteil
        FROM V_Attacken
        WHERE anzeigename IN ({platzhalter}) AND monat_iso = ? AND anteil >= 15
    """, conn, params=(*namen, monat_iso))  # noqa: S608

    faehigkeiten = pd.read_sql(f"""
        SELECT p.anzeigename, a.anzeigename AS faehigkeit, a.effekt_klasse, f.anteil
        FROM Fact_Faehigkeit_Nutzung f
        JOIN Dim_Pokemon    p ON p.pokemon_sk    = f.pokemon_sk
        JOIN Dim_Faehigkeit a ON a.faehigkeit_sk = f.faehigkeit_sk
        JOIN Dim_Zeit       z ON z.zeit_sk       = f.zeit_sk
        WHERE p.anzeigename IN ({platzhalter}) AND z.monat_iso = ?
          AND f.anteil >= 40 AND a.effekt_klasse != 'Sonstige' AND p.ist_aktuell = 1
    """, conn, params=(*namen, monat_iso))  # noqa: S608

    befunde: list[dict[str, object]] = []

    beschreibungen = {
        "Bizarroraum": ("Bizarroraum-Gefahr", "warnung",
                        "Die Initiative wird fuer fuenf Runden umgekehrt -- langsame Angreifer "
                        "handeln zuerst. Gegenmittel: Verhoehner, den Setzer fokussieren oder "
                        "selbst Bizarroraum einsetzen."),
        "Initiative-Kontrolle": ("Initiative-Kontrolle", "info",
                                 "Rueckenwind oder Tempo-Senkung verschieben die Zugreihenfolge. "
                                 "Gegenmittel: Prioritaetsattacken, eigener Rueckenwind oder "
                                 "Bizarroraum."),
        "Umleitung": ("Angriffs-Umleitung", "info",
                      "Attacken werden auf ein Ziel umgelenkt und schuetzen so den Partner. "
                      "Gegenmittel: Flaechenattacken oder Verhoehner."),
        "Flaechenschaden": ("Flaechenschaden", "warnung",
                            "Attacken treffen beide gegnerischen Pokemon gleichzeitig. "
                            "Gegenmittel: Breitenschutz oder gestaffeltes Einwechseln."),
        "Prioritaet": ("Prioritaetsattacken", "info",
                       "Diese Attacken handeln unabhaengig von der Initiative zuerst und "
                       "beenden angeschlagene Pokemon."),
        "Setup": ("Statuswert-Aufbau", "warnung",
                  "Das Team baut Statuswerte auf und wird mit jeder Runde gefaehrlicher. "
                  "Gegenmittel: Dunkelnebel, Verhoehner oder sofortiger Druck."),
    }

    for klasse, (titel, stufe, hinweis) in beschreibungen.items():
        treffer = attacken[attacken["taktik_klasse"] == klasse]
        if treffer.empty:
            continue
        befunde.append({
            "titel": titel,
            "stufe": stufe,
            "hinweis": hinweis,
            "traeger": sorted(set(treffer["anzeigename"])),
            "attacken": sorted(set(treffer["attacke"])),
        })

    for klasse, titel in (("Wetter", "Wetter-Team"), ("Terrain", "Terrain-Kontrolle")):
        treffer = faehigkeiten[faehigkeiten["effekt_klasse"] == klasse]
        if treffer.empty:
            continue
        befunde.append({
            "titel": titel,
            "stufe": "warnung",
            "hinweis": f"{klasse} wird passiv beim Einwechseln gesetzt und veraendert "
                       "Schaden sowie Faehigkeiten auf dem gesamten Feld. Gegenmittel: "
                       f"eigenes {klasse} etablieren oder den Setzer ausschalten.",
            "traeger": sorted(set(treffer["anzeigename"])),
            "attacken": sorted(set(treffer["faehigkeit"])),
        })

    return befunde
