"""Datenqualitaetspruefung auf dem geladenen Data Warehouse.

Waehrend die Transformationsschritte einzelne Saetze waehrend des Ladens pruefen,
betrachtet dieses Modul den Bestand als Ganzes. Erst dort werden Maengel sichtbar,
die am Einzelsatz nicht auffallen: Luecken in der Zeitreihe, verwaiste
Fremdschluessel, Verletzungen der Spielregeln oder Dimensionen ohne Faktenbezug.

Die Pruefungen sind nach den ueblichen Datenqualitaetsdimensionen gegliedert:
Vollstaendigkeit, Konsistenz, Eindeutigkeit, Wertebereich und Aktualitaet.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .config import QUELLE_VORHALTUNG_TAGE
from .stats import MAX_SP_JE_WERT, SP_BUDGET

# Qualitaetstor: ab diesem Index gilt der Bestand als brauchbar. Der Wert stand
# zuvor nur als Aufrufparameter in den beiden Workflows -- damit konnte die
# Oberflaeche eine Kachel gruen faerben, waehrend der naechtliche Lauf an
# derselben Zahl scheiterte.
MINDESTINDEX = 90.0


@dataclass
class Pruefergebnis:
    """Ergebnis einer einzelnen Qualitaetsregel."""

    regel: str
    dimension: str
    bestanden: bool
    befund: str
    betroffen: int = 0

    @property
    def stufe(self) -> str:
        """Schweregrad fuer die Anzeige im Qualitaetsbericht.

        Drei Stufen, aber nur zwei Aussagen: bestanden oder nicht. Die
        Unterscheidung zwischen ``warnung`` und ``fehler`` ist die Schwere des
        Verstosses, keine dritte Bewertung -- die Oberflaeche stellt sie
        deshalb als zwei Staerken derselben Farbe dar und nicht als eigene.
        """
        if self.bestanden:
            return "bestanden"
        return "fehler" if self.betroffen > 0 and self.dimension in (
            "Konsistenz", "Eindeutigkeit") else "warnung"


def _zaehle(conn: sqlite3.Connection, sql: str, *parameter) -> int:
    ergebnis = conn.execute(sql, parameter).fetchone()
    return int(ergebnis[0]) if ergebnis and ergebnis[0] is not None else 0


# --------------------------------------------------------------------------
# Konsistenz und Eindeutigkeit
# --------------------------------------------------------------------------

def regel_verwaiste_fakten(conn: sqlite3.Connection) -> Pruefergebnis:
    """Jeder Faktensatz muss auf einen gueltigen Dimensionssatz verweisen."""
    anzahl = _zaehle(conn, """
        SELECT COUNT(*) FROM Fact_Champions_Usage f
        LEFT JOIN Dim_Pokemon     p ON p.pokemon_sk     = f.pokemon_sk
        LEFT JOIN Dim_Zeit        z ON z.zeit_sk        = f.zeit_sk
        LEFT JOIN Dim_Saison      s ON s.saison_sk      = f.saison_sk
        LEFT JOIN Dim_Kampfformat k ON k.kampfformat_sk = f.kampfformat_sk
        WHERE p.pokemon_sk IS NULL OR z.zeit_sk IS NULL
           OR s.saison_sk IS NULL OR k.kampfformat_sk IS NULL
    """)
    return Pruefergebnis(
        "Referenzielle Integritaet der Faktentabelle", "Konsistenz", anzahl == 0,
        "Alle Faktensaetze sind vollstaendig mit den Dimensionen verknuepft."
        if anzahl == 0 else f"{anzahl} Faktensaetze verweisen ins Leere.",
        anzahl,
    )


def regel_dimension_eindeutig(conn: sqlite3.Connection) -> Pruefergebnis:
    """Je Bezeichner darf hoechstens ein aktueller Dimensionssatz bestehen.

    Diese Regel sichert die Historisierung ab: mehrere gleichzeitig als aktuell
    markierte Saetze wuerden die Faktenzuordnung mehrdeutig machen.
    """
    anzahl = _zaehle(conn, """
        SELECT COUNT(*) FROM (
            SELECT slug FROM Dim_Pokemon WHERE ist_aktuell = 1
            GROUP BY slug HAVING COUNT(*) > 1)
    """)
    return Pruefergebnis(
        "Eindeutigkeit des aktuellen Dimensionssatzes", "Eindeutigkeit", anzahl == 0,
        "Je Pokemon existiert genau ein aktueller Satz."
        if anzahl == 0 else f"{anzahl} Bezeichner mit mehreren aktuellen Saetzen.",
        anzahl,
    )


def regel_historisierung_intervalle(conn: sqlite3.Connection) -> Pruefergebnis:
    """Gueltigkeitszeitraeume duerfen nicht invertiert sein."""
    anzahl = _zaehle(conn, "SELECT COUNT(*) FROM Dim_Pokemon WHERE gueltig_bis < gueltig_ab")
    return Pruefergebnis(
        "Konsistenz der Gueltigkeitszeitraeume", "Konsistenz", anzahl == 0,
        "Alle Gueltigkeitszeitraeume sind wohlgeformt."
        if anzahl == 0 else f"{anzahl} Saetze mit Endedatum vor Beginndatum.",
        anzahl,
    )


def regel_saison_zuordnung(conn: sqlite3.Connection) -> Pruefergebnis:
    """Jeder Faktensatz muss einer Saison zugeordnet sein.

    Ohne Saisonbezug liessen sich Pokemon aus abgelaufenen Regulationen nicht von
    den aktuell zugelassenen trennen.
    """
    ohne = _zaehle(conn, """
        SELECT COUNT(*) FROM Fact_Champions_Usage f
        LEFT JOIN Dim_Saison s ON s.saison_sk = f.saison_sk
        WHERE s.saison_sk IS NULL
    """)
    aktuelle = _zaehle(conn, "SELECT COUNT(*) FROM Dim_Saison WHERE ist_aktuell = 1")

    return Pruefergebnis(
        "Saisonzuordnung der Fakten", "Konsistenz", ohne == 0 and aktuelle <= 1,
        "Alle Faktensaetze sind einer Saison zugeordnet; genau eine gilt als aktuell."
        if ohne == 0 and aktuelle <= 1
        else f"{ohne} Saetze ohne Saison, {aktuelle} gleichzeitig aktuelle Saisons.",
        ohne + max(0, aktuelle - 1),
    )


def regel_rang_eindeutig(conn: sqlite3.Connection) -> Pruefergebnis:
    """Je Tag und Format darf jeder Rang nur einmal vergeben sein.

    Ein doppelt vergebener Rang wuerde die gesamte ordinale Auswertung
    verfaelschen -- Rangvergleiche setzen eine strenge Ordnung voraus.
    """
    anzahl = _zaehle(conn, """
        SELECT COUNT(*) FROM (
            SELECT zeit_sk, kampfformat_sk, rang
            FROM Fact_Champions_Usage
            GROUP BY zeit_sk, kampfformat_sk, rang HAVING COUNT(*) > 1)
    """)
    return Pruefergebnis(
        "Eindeutigkeit der Nutzungsraenge", "Eindeutigkeit", anzahl == 0,
        "Je Tag und Format ist jeder Rang genau einmal vergeben."
        if anzahl == 0 else f"{anzahl} mehrfach vergebene Raenge.",
        anzahl,
    )


# --------------------------------------------------------------------------
# Vollstaendigkeit
# --------------------------------------------------------------------------

def regel_archiv_lueckenlos(conn: sqlite3.Connection) -> Pruefergebnis:
    """Das Archiv soll eine lueckenlose Tagesfolge enthalten.

    Die Quelle haelt nur rund zwei Wochen vor. Ein ausgelassener Ladelauf
    hinterlaesst deshalb eine dauerhafte Luecke, die sich nicht mehr schliessen
    laesst -- das muss auffallen, solange sich noch etwas retten laesst.
    """
    tage = [z[0] for z in conn.execute(
        "SELECT DISTINCT datum_iso FROM Archiv_Champions ORDER BY datum_iso")]
    if len(tage) < 2:
        return Pruefergebnis(
            "Lueckenlosigkeit des Archivs", "Vollstaendigkeit", True,
            "Weniger als zwei archivierte Tage -- keine Luecke moeglich.", 0,
        )

    erster, letzter = date.fromisoformat(tage[0]), date.fromisoformat(tage[-1])
    erwartet = {(erster + timedelta(days=i)).isoformat()
                for i in range((letzter - erster).days + 1)}
    fehlend = sorted(erwartet - set(tage))

    return Pruefergebnis(
        "Lueckenlosigkeit des Archivs", "Vollstaendigkeit", not fehlend,
        f"{len(tage)} Tage von {tage[0]} bis {tage[-1]}, ohne Luecken."
        if not fehlend else
        f"{len(fehlend)} fehlende Tage, darunter {', '.join(fehlend[:5])}. "
        "Diese Staende sind an der Quelle nicht mehr abrufbar.",
        len(fehlend),
    )


def regel_archivdeckung(conn: sqlite3.Connection) -> Pruefergebnis:
    """Jeder geladene Faktentag muss auch im Archiv liegen.

    Andernfalls waeren die Fakten nach einem Zuruecksetzen nicht wiederherstellbar.
    """
    fakt_tage = {z[0] for z in conn.execute("""
        SELECT DISTINCT z.datum_iso FROM Fact_Champions_Usage f
        JOIN Dim_Zeit z ON z.zeit_sk = f.zeit_sk
    """)}
    if not fakt_tage:
        return Pruefergebnis(
            "Archivdeckung der Fakten", "Vollstaendigkeit", True,
            "Keine Fakten geladen.", 0,
        )

    archiv_tage = {z[0] for z in conn.execute(
        "SELECT DISTINCT datum_iso FROM Archiv_Champions")}
    ungedeckt = fakt_tage - archiv_tage

    return Pruefergebnis(
        "Archivdeckung der Fakten", "Vollstaendigkeit", not ungedeckt,
        f"Alle {len(fakt_tage)} geladenen Tage liegen im Archiv."
        if not ungedeckt else
        f"{len(ungedeckt)} Tage sind geladen, aber nicht archiviert: "
        + ", ".join(sorted(ungedeckt)[:5]),
        len(ungedeckt),
    )


def regel_beide_formate(conn: sqlite3.Connection) -> Pruefergebnis:
    """Einzel- und Doppelkampf sollen gleichermassen geladen sein.

    Fehlt ein Format, laeuft der Team-Preview-Advisor dafuer ins Leere.
    """
    formate = {z[0]: z[1] for z in conn.execute("""
        SELECT k.schluessel, COUNT(DISTINCT z.datum_iso)
        FROM Fact_Champions_Usage f
        JOIN Dim_Kampfformat k ON k.kampfformat_sk = f.kampfformat_sk
        JOIN Dim_Zeit        z ON z.zeit_sk        = f.zeit_sk
        GROUP BY k.schluessel
    """)}
    fehlend = {"Singles", "Doubles"} - set(formate)

    return Pruefergebnis(
        "Abdeckung beider Kampfformate", "Vollstaendigkeit", not fehlend,
        "Beide Formate geladen: " + ", ".join(f"{f} ({t} Tage)" for f, t in formate.items())
        if not fehlend else f"Fehlende Formate: {', '.join(sorted(fehlend))}",
        len(fehlend),
    )


def regel_stammdatenabdeckung(conn: sqlite3.Connection) -> Pruefergebnis:
    """Anteil der Meta-Pokemon, denen Stammdaten zugeordnet werden konnten.

    Ein niedriger Wert deutet auf ein unvollstaendiges Harmonisierungs-Mapping hin.
    """
    fakten = _zaehle(conn, "SELECT COUNT(DISTINCT pokemon_sk) FROM Fact_Champions_Usage")
    ohne_typ = _zaehle(conn, """
        SELECT COUNT(DISTINCT f.pokemon_sk) FROM Fact_Champions_Usage f
        JOIN Dim_Pokemon p ON p.pokemon_sk = f.pokemon_sk
        WHERE p.typ1 IS NULL OR p.typ1 = ''
    """)
    quote = 1.0 if fakten == 0 else (fakten - ohne_typ) / fakten
    return Pruefergebnis(
        "Abdeckung der Meta-Pokemon mit Stammdaten", "Vollstaendigkeit", quote >= 0.99,
        f"{quote:.1%} der {fakten} Meta-Pokemon haben vollstaendige Typangaben.",
        ohne_typ,
    )


def regel_attackenabdeckung(conn: sqlite3.Connection) -> Pruefergebnis:
    """Gespielte Attacken muessen mit Typ und Kategorie verknuepft sein.

    Ohne diese Angaben ist keine Matchup-Bewertung moeglich -- der Team-Preview-
    Advisor stuetzt sich unmittelbar darauf.
    """
    gesamt = _zaehle(
        conn, "SELECT COUNT(*) FROM Fact_Champions_Merkmal WHERE kategorie = 'move'")
    if gesamt == 0:
        return Pruefergebnis(
            "Verknuepfung der Attacken mit ihren Stammdaten", "Vollstaendigkeit", True,
            "Keine Attackenfakten geladen.", 0,
        )

    ohne = _zaehle(conn, """
        SELECT COUNT(*) FROM Fact_Champions_Merkmal
        WHERE kategorie = 'move' AND attacke_sk IS NULL
    """)
    quote = 100 * (gesamt - ohne) / gesamt
    return Pruefergebnis(
        "Verknuepfung der Attacken mit ihren Stammdaten", "Vollstaendigkeit",
        quote >= 95.0,
        f"{quote:.1f}% der {gesamt} Attackenfakten sind mit der Attacken-Dimension "
        "verknuepft und damit fuer die Matchup-Bewertung verwertbar.",
        ohne,
    )


# --------------------------------------------------------------------------
# Wertebereich
# --------------------------------------------------------------------------

def regel_statuspunkte_budget(conn: sqlite3.Connection) -> Pruefergebnis:
    """Punkteverteilungen muessen den Spielregeln entsprechen.

    Das Spiel erlaubt hoechstens 32 Punkte je Einzelwert und 66 insgesamt. Die
    Quelle liefert vereinzelt Verteilungen darueber -- im Spiel unmoeglich. Die
    Saetze werden geladen, aber ausgewiesen: sie verfaelschen abgeleitete
    Statuswerte nach oben.
    """
    gesamt = _zaehle(
        conn, "SELECT COUNT(*) FROM Fact_Champions_Merkmal WHERE kategorie = 'spread'")
    if gesamt == 0:
        return Pruefergebnis(
            "Regelkonformitaet der Statuspunkte", "Wertebereich", True,
            "Keine Punkteverteilungen geladen.", 0,
        )

    verletzt = _zaehle(conn, f"""
        SELECT COUNT(*) FROM Fact_Champions_Merkmal
        WHERE kategorie = 'spread' AND (
            COALESCE(punkte_summe, 0)        > {SP_BUDGET}
            OR COALESCE(punkte_hp,0)         > {MAX_SP_JE_WERT}
            OR COALESCE(punkte_attack,0)     > {MAX_SP_JE_WERT}
            OR COALESCE(punkte_defense,0)    > {MAX_SP_JE_WERT}
            OR COALESCE(punkte_sp_attack,0)  > {MAX_SP_JE_WERT}
            OR COALESCE(punkte_sp_defense,0) > {MAX_SP_JE_WERT}
            OR COALESCE(punkte_speed,0)      > {MAX_SP_JE_WERT})
    """)  # noqa: S608 - Konstanten aus dem Modul, keine Nutzereingabe

    quote = 100 * (gesamt - verletzt) / gesamt
    # Einzelne fehlerhafte Saetze sind bei einer Fremdquelle hinnehmbar; ein
    # nennenswerter Anteil deutet dagegen auf ein geaendertes Quellformat hin.
    return Pruefergebnis(
        "Regelkonformitaet der Statuspunkte", "Wertebereich", quote >= 99.0,
        f"{quote:.2f}% der {gesamt} Punkteverteilungen halten die Grenzen ein "
        f"({MAX_SP_JE_WERT} je Wert, {SP_BUDGET} gesamt); {verletzt} Saetze darueber.",
        verletzt,
    )


def regel_rangperzentil_wertebereich(conn: sqlite3.Connection) -> Pruefergebnis:
    """Das abgeleitete Rangperzentil muss zwischen 0 und 100 liegen."""
    anzahl = _zaehle(conn, """
        SELECT COUNT(*) FROM Fact_Champions_Usage
        WHERE rang_perzentil < 0 OR rang_perzentil > 100 OR rang < 1
    """)
    return Pruefergebnis(
        "Wertebereich von Rang und Rangperzentil", "Wertebereich", anzahl == 0,
        "Alle Raenge und Perzentile liegen im gueltigen Bereich."
        if anzahl == 0 else f"{anzahl} Saetze mit unzulaessigem Wert.",
        anzahl,
    )


def regel_merkmalsanteile(conn: sqlite3.Connection) -> Pruefergebnis:
    """Merkmalsanteile muessen zwischen 0 und 100 Prozent liegen.

    Anders als die Nutzung sind die Merkmalsanteile echte Anteile; hier ist eine
    Wertebereichspruefung fachlich sinnvoll.
    """
    anzahl = _zaehle(conn, """
        SELECT COUNT(*) FROM Fact_Champions_Merkmal
        WHERE anteil IS NOT NULL AND (anteil < 0 OR anteil > 100)
    """)
    return Pruefergebnis(
        "Wertebereich der Merkmalsanteile", "Wertebereich", anzahl == 0,
        "Alle Anteile liegen zwischen 0 und 100 Prozent."
        if anzahl == 0 else f"{anzahl} Anteile ausserhalb des gueltigen Bereichs.",
        anzahl,
    )


# --------------------------------------------------------------------------
# Aktualitaet
# --------------------------------------------------------------------------

def regel_aktualitaet(conn: sqlite3.Connection) -> Pruefergebnis:
    """Der juengste geladene Tag soll nicht aelter als drei Tage sein.

    Die Quelle haelt nur rund zwei Wochen vor. Wer laenger nicht laedt, verliert
    Tage endgueltig -- die Regel warnt, bevor das geschieht.
    """
    jueng = conn.execute("SELECT MAX(datum_iso) FROM Dim_Zeit").fetchone()[0]
    if not jueng:
        return Pruefergebnis("Aktualitaet der Bewegungsdaten", "Aktualitaet", False,
                             "Keine Bewegungsdaten geladen.", 1)

    rueckstand = (date.today() - date.fromisoformat(jueng)).days
    return Pruefergebnis(
        "Aktualitaet der Bewegungsdaten", "Aktualitaet", rueckstand <= 3,
        f"Juengster geladener Tag: {jueng} (Rueckstand {rueckstand} Tage). "
        f"Die Quelle haelt {QUELLE_VORHALTUNG_TAGE} Tage vor.",
        max(0, rueckstand - 3),
    )


def regel_letzter_lauf(conn: sqlite3.Connection) -> Pruefergebnis:
    """Der letzte Ladelauf muss erfolgreich abgeschlossen sein."""
    zeile = conn.execute(
        "SELECT status, quelle, gestartet_am, meldung FROM ETL_Lauf ORDER BY lauf_id DESC LIMIT 1"
    ).fetchone()
    if zeile is None:
        return Pruefergebnis("Status des letzten Ladelaufs", "Aktualitaet", False,
                             "Es wurde noch kein Ladelauf durchgefuehrt.", 1)

    erfolgreich = zeile["status"] == "erfolgreich"
    zeitpunkt = datetime.fromisoformat(zeile["gestartet_am"]).strftime("%d.%m.%Y %H:%M")
    return Pruefergebnis(
        "Status des letzten Ladelaufs", "Aktualitaet", erfolgreich,
        f"Letzter Lauf ({zeile['quelle']}, {zeitpunkt}): {zeile['status']}."
        + (f" {zeile['meldung']}" if zeile["meldung"] else ""),
        0 if erfolgreich else 1,
    )


ALLE_REGELN = (
    regel_verwaiste_fakten,
    regel_dimension_eindeutig,
    regel_historisierung_intervalle,
    regel_saison_zuordnung,
    regel_rang_eindeutig,
    regel_archiv_lueckenlos,
    regel_archivdeckung,
    regel_beide_formate,
    regel_stammdatenabdeckung,
    regel_attackenabdeckung,
    regel_statuspunkte_budget,
    regel_rangperzentil_wertebereich,
    regel_merkmalsanteile,
    regel_aktualitaet,
    regel_letzter_lauf,
)


def pruefe_alles(conn: sqlite3.Connection) -> list[Pruefergebnis]:
    """Fuehrt saemtliche Qualitaetsregeln aus.

    Eine fehlschlagende Regel darf die uebrigen nicht verhindern -- der Bericht
    soll auch dann vollstaendig sein, wenn eine Pruefung selbst auf einen Fehler
    laeuft.
    """
    ergebnisse: list[Pruefergebnis] = []
    for regel in ALLE_REGELN:
        try:
            ergebnisse.append(regel(conn))
        except Exception as fehler:  # noqa: BLE001
            ergebnisse.append(Pruefergebnis(
                regel.__name__, "Konsistenz", False,
                f"Die Pruefung konnte nicht ausgefuehrt werden: {fehler}", 1,
            ))
    return ergebnisse


def qualitaetsindex(ergebnisse: list[Pruefergebnis]) -> float:
    """Anteil bestandener Regeln in Prozent -- verdichtete Kennzahl fuer das Cockpit."""
    if not ergebnisse:
        return 0.0
    return round(100 * sum(1 for e in ergebnisse if e.bestanden) / len(ergebnisse), 1)
