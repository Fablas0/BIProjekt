"""Datenqualitaetspruefung auf dem geladenen Data Warehouse.

Waehrend :mod:`bi.etl.transform` einzelne Saetze waehrend des Ladens prueft,
betrachtet dieses Modul den Bestand als Ganzes. Erst dort werden Maengel sichtbar,
die am Einzelsatz nicht auffallen: Luecken in der Zeitreihe, verwaiste
Fremdschluessel, unplausible Kennzahlensummen oder Dimensionen ohne Faktenbezug.

Die Pruefungen sind nach den ueblichen Datenqualitaetsdimensionen gegliedert:
Vollstaendigkeit, Konsistenz, Eindeutigkeit, Genauigkeit und Aktualitaet.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class Pruefergebnis:
    """Ergebnis einer einzelnen Qualitaetsregel."""

    regel: str
    dimension: str
    bestanden: bool
    befund: str
    betroffen: int = 0

    @property
    def ampel(self) -> str:
        """Ampelfarbe fuer die Anzeige im Qualitaetsbericht."""
        if self.bestanden:
            return "gruen"
        return "rot" if self.betroffen > 0 and self.dimension in (
            "Konsistenz", "Eindeutigkeit") else "gelb"


def _zaehle(conn: sqlite3.Connection, sql: str, *parameter) -> int:
    ergebnis = conn.execute(sql, parameter).fetchone()
    return int(ergebnis[0]) if ergebnis and ergebnis[0] is not None else 0


# --------------------------------------------------------------------------
# Einzelregeln
# --------------------------------------------------------------------------

def regel_verwaiste_fakten(conn: sqlite3.Connection) -> Pruefergebnis:
    """Jeder Faktensatz muss auf einen gueltigen Dimensionssatz verweisen."""
    anzahl = _zaehle(conn, """
        SELECT COUNT(*) FROM Fact_Usage f
        LEFT JOIN Dim_Pokemon    p ON p.pokemon_sk    = f.pokemon_sk
        LEFT JOIN Dim_Zeit       z ON z.zeit_sk       = f.zeit_sk
        LEFT JOIN Dim_Regulation r ON r.regulation_sk = f.regulation_sk
        LEFT JOIN Dim_Skill      s ON s.skill_sk      = f.skill_sk
        WHERE p.pokemon_sk IS NULL OR z.zeit_sk IS NULL
           OR r.regulation_sk IS NULL OR s.skill_sk IS NULL
    """)
    return Pruefergebnis(
        "Referenzielle Integritaet der Faktentabelle", "Konsistenz", anzahl == 0,
        "Alle Faktensaetze sind vollstaendig mit den Dimensionen verknuepft."
        if anzahl == 0 else f"{anzahl} Faktensaetze verweisen ins Leere.",
        anzahl,
    )


def regel_luecken_zeitreihe(conn: sqlite3.Connection) -> Pruefergebnis:
    """Die geladenen Monate muessen eine luekenlose Folge bilden.

    Ein fehlender Monat verfaelscht jede Trendaussage, weil die Veraenderung dann
    ueber einen doppelt so langen Zeitraum gemessen wird.
    """
    monate = [z[0] for z in conn.execute(
        "SELECT monat_iso FROM Dim_Zeit ORDER BY monat_iso"
    )]
    if len(monate) < 2:
        return Pruefergebnis(
            "Lueckenlosigkeit der Zeitreihe", "Vollstaendigkeit", True,
            "Weniger als zwei Monate geladen -- keine Luecke moeglich.", 0,
        )

    fehlend: list[str] = []
    for vorher, nachher in zip(monate, monate[1:], strict=False):
        jahr_v, monat_v = (int(t) for t in vorher.split("-"))
        jahr_n, monat_n = (int(t) for t in nachher.split("-"))
        abstand = (jahr_n - jahr_v) * 12 + (monat_n - monat_v)
        for versatz in range(1, abstand):
            gesamt = jahr_v * 12 + (monat_v - 1) + versatz
            fehlend.append(f"{gesamt // 12:04d}-{gesamt % 12 + 1:02d}")

    return Pruefergebnis(
        "Lueckenlosigkeit der Zeitreihe", "Vollstaendigkeit", not fehlend,
        f"{len(monate)} Monate von {monate[0]} bis {monate[-1]}, ohne Luecken."
        if not fehlend else f"Fehlende Monate: {', '.join(fehlend)}",
        len(fehlend),
    )


def regel_usage_wertebereich(conn: sqlite3.Connection) -> Pruefergebnis:
    """Nutzungsanteile muessen im Intervall 0 bis 100 Prozent liegen."""
    anzahl = _zaehle(conn, "SELECT COUNT(*) FROM Fact_Usage WHERE usage_rate < 0 OR usage_rate > 100")
    return Pruefergebnis(
        "Wertebereich der Kennzahl Usage Rate", "Genauigkeit", anzahl == 0,
        "Alle Nutzungsanteile liegen im gueltigen Bereich."
        if anzahl == 0 else f"{anzahl} Saetze mit unzulaessigem Nutzungsanteil.",
        anzahl,
    )


def regel_usage_summe(conn: sqlite3.Connection) -> Pruefergebnis:
    """Die Nutzungsanteile eines Monats muessen sich auf rund 600 Prozent summieren.

    Jedes Team besteht aus sechs Pokemon, folglich summiert sich der Anteil ueber
    alle Pokemon auf etwa 600 Prozent. Deutliche Abweichungen deuten auf einen
    unvollstaendig geladenen Monat hin.
    """
    zeilen = conn.execute("""
        SELECT z.monat_iso, SUM(f.usage_rate) AS summe
        FROM Fact_Usage f JOIN Dim_Zeit z ON z.zeit_sk = f.zeit_sk
        GROUP BY z.monat_iso ORDER BY z.monat_iso
    """).fetchall()

    auffaellig = [(z["monat_iso"], z["summe"]) for z in zeilen if not 480 <= z["summe"] <= 620]
    return Pruefergebnis(
        "Plausibilitaet der Nutzungssumme je Monat", "Genauigkeit", not auffaellig,
        "Die Nutzungsanteile summieren sich in allen Monaten plausibel auf rund 600 Prozent."
        if not auffaellig else "Auffaellige Monate: " + ", ".join(
            f"{m} ({s:.0f}%)" for m, s in auffaellig),
        len(auffaellig),
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
    """Gueltigkeitszeitraeume duerfen sich nicht ueberlappen oder invertiert sein."""
    anzahl = _zaehle(conn, "SELECT COUNT(*) FROM Dim_Pokemon WHERE gueltig_bis < gueltig_ab")
    return Pruefergebnis(
        "Konsistenz der Gueltigkeitszeitraeume", "Konsistenz", anzahl == 0,
        "Alle Gueltigkeitszeitraeume sind wohlgeformt."
        if anzahl == 0 else f"{anzahl} Saetze mit Endedatum vor Beginndatum.",
        anzahl,
    )


def regel_stammdatenabdeckung(conn: sqlite3.Connection) -> Pruefergebnis:
    """Anteil der Meta-Pokemon, denen Stammdaten zugeordnet werden konnten.

    Ein niedriger Wert deutet auf ein unvollstaendiges Harmonisierungs-Mapping hin.
    """
    fakten = _zaehle(conn, "SELECT COUNT(DISTINCT pokemon_sk) FROM Fact_Usage")
    ohne_typ = _zaehle(conn, """
        SELECT COUNT(DISTINCT f.pokemon_sk) FROM Fact_Usage f
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
    """Attacken der Dimension sollen mit Typ und Kategorie angereichert sein."""
    gesamt = _zaehle(conn, "SELECT COUNT(*) FROM Dim_Attacke")
    unvollstaendig = _zaehle(
        conn, "SELECT COUNT(*) FROM Dim_Attacke WHERE kategorie IS NULL OR typ IS NULL OR typ = ''"
    )
    quote = 1.0 if gesamt == 0 else (gesamt - unvollstaendig) / gesamt
    return Pruefergebnis(
        "Anreicherung der Attacken-Dimension", "Vollstaendigkeit", quote >= 0.95,
        f"{quote:.1%} der {gesamt} Attacken sind mit Typ und Kategorie angereichert.",
        unvollstaendig,
    )


def regel_aktualitaet(conn: sqlite3.Connection) -> Pruefergebnis:
    """Der juengste geladene Monat soll nicht aelter als zwei Monate sein.

    Smogon veroeffentlicht die Auswertung eines Monats erst im Folgemonat; ein
    Rueckstand von einem Monat ist daher normal, mehr deutet auf einen
    ausgebliebenen Ladelauf hin.
    """
    jueng = conn.execute("SELECT MAX(monat_iso) FROM Dim_Zeit").fetchone()[0]
    if not jueng:
        return Pruefergebnis("Aktualitaet der Bewegungsdaten", "Aktualitaet", False,
                             "Keine Bewegungsdaten geladen.", 1)

    jahr, monat = (int(t) for t in jueng.split("-"))
    heute = date.today()
    abstand = (heute.year - jahr) * 12 + (heute.month - monat)
    return Pruefergebnis(
        "Aktualitaet der Bewegungsdaten", "Aktualitaet", abstand <= 2,
        f"Juengster geladener Monat: {jueng} (Rueckstand {abstand} Monate).",
        max(0, abstand - 2),
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
    regel_luecken_zeitreihe,
    regel_usage_wertebereich,
    regel_usage_summe,
    regel_stammdatenabdeckung,
    regel_attackenabdeckung,
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
