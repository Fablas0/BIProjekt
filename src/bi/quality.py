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
from .etl.load import quelle_stand_lesen
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


def _angebot_der_quelle(conn: sqlite3.Connection) -> set[str] | None:
    """Die Tage, die die Quelle beim letzten Zugriff gefuehrt hat.

    ``None`` heisst "unbekannt": es liegt kein Quellstand vor, weil dieser
    Bestand noch nie gegen die Quelle geladen wurde -- die Regeln bewerten dann
    nicht. Eine *leere* Menge ist etwas anderes: die Quelle war erreichbar und
    fuehrte nichts.
    """
    stand = quelle_stand_lesen(conn, "Champions")
    return None if stand is None else set(stand["tage"])


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
    """Das Archiv soll jeden Tag enthalten, den die Quelle noch anbietet.

    Die Quelle haelt nur rund zwei Wochen vor. Ein ausgelassener Ladelauf
    hinterlaesst deshalb eine dauerhafte Luecke -- das muss auffallen, solange
    sich noch etwas retten laesst.

    Genau darauf ist die Regel begrenzt. Ein Tag, den die Quelle nicht mehr
    fuehrt, ist unwiederbringlich verloren; ihn taeglich erneut zu melden macht
    ihn nicht wieder abrufbar, faerbt aber jeden Lauf dauerhaft rot und
    entwertet damit das Qualitaetstor. Solche Tage bleiben im Befundtext
    sichtbar, ohne die Regel zu reissen. Gerissen wird sie fuer jeden Tag, den
    die Quelle noch fuehrt und der im Archiv fehlt -- ob er zwischen zwei
    archivierten Tagen liegt oder hinter dem juengsten, macht keinen
    Unterschied: geholt haette der Ladelauf ihn so oder so muessen.
    """
    tage = [z[0] for z in conn.execute(
        "SELECT DISTINCT datum_iso FROM Archiv_Champions ORDER BY datum_iso")]
    if len(tage) < 2:
        return Pruefergebnis(
            "Lueckenlosigkeit des Archivs", "Vollstaendigkeit", True,
            "Weniger als zwei archivierte Tage -- keine Luecke moeglich.", 0,
        )

    archiviert = set(tage)
    erster, letzter = date.fromisoformat(tage[0]), date.fromisoformat(tage[-1])
    erwartet = {(erster + timedelta(days=i)).isoformat()
                for i in range((letzter - erster).days + 1)}

    angebot = _angebot_der_quelle(conn)
    if angebot is None:
        # Ohne Quellzugriff ist nicht zu beantworten, was noch zu holen waere.
        # Es zu raten -- etwa ueber die Vorhaltezeit -- hiesse, unwiederbringliche
        # Tage als Versaeumnis auszuweisen. Ein Bestand allein aus dem Archiv wird
        # deshalb nicht bewertet; :func:`beobachte_quellenlage` weist darauf hin.
        fehlend = sorted(erwartet - archiviert)
        return Pruefergebnis(
            "Lueckenlosigkeit des Archivs", "Vollstaendigkeit", True,
            f"{len(tage)} Tage von {tage[0]} bis {tage[-1]}, {len(fehlend)} fehlende "
            f"({', '.join(fehlend[:5])}). Ohne Zugriff auf die Quelle ist nicht "
            f"bewertbar, ob sie noch abrufbar waeren."
            if fehlend else
            f"{len(tage)} Tage von {tage[0]} bis {tage[-1]}, ohne Luecken.", 0,
        )

    # Holbar ist alles, was die Quelle fuehrt und uns fehlt -- gleich, ob es
    # zwischen zwei archivierten Tagen liegt oder hinter dem juengsten. Beides
    # ist derselbe Mangel: ein angebotener Tag, den der Ladelauf nicht geholt hat.
    holbar = sorted(angebot - archiviert)
    # Verloren sind Luecken der bisherigen Reihe, die die Quelle nicht mehr fuehrt.
    verloren = sorted(erwartet - archiviert - angebot)

    if holbar:
        befund = (f"{len(holbar)} von der Quelle angebotene Tage fehlen im Archiv und "
                  f"haetten geladen werden muessen: {', '.join(holbar[:5])}.")
        if verloren:
            befund += f" Weitere {len(verloren)} Tage sind endgueltig verloren."
    elif verloren:
        befund = (f"Alle {len(tage)} noch abrufbaren Tage sind archiviert. "
                  f"{len(verloren)} frueher ausgefallene Tage "
                  f"({', '.join(verloren[:5])}) fuehrt die Quelle nicht mehr; sie "
                  f"bleiben endgueltig verloren.")
    else:
        befund = f"{len(tage)} Tage von {tage[0]} bis {tage[-1]}, ohne Luecken."

    return Pruefergebnis(
        "Lueckenlosigkeit des Archivs", "Vollstaendigkeit", not holbar,
        befund, len(holbar),
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


def _abdeckung(conn: sqlite3.Connection, kategorie: str, spalte: str,
               regel: str, zweck: str) -> Pruefergebnis:
    """Gemeinsame Pruefung der Verknuepfung eines Merkmals mit seiner Dimension."""
    gesamt = _zaehle(
        conn, "SELECT COUNT(*) FROM Fact_Champions_Merkmal WHERE kategorie = ?", kategorie)
    if gesamt == 0:
        return Pruefergebnis(regel, "Vollstaendigkeit", True,
                             f"Keine Fakten der Kategorie {kategorie} geladen.", 0)

    ohne = _zaehle(
        conn,
        f"SELECT COUNT(*) FROM Fact_Champions_Merkmal "  # noqa: S608
        f"WHERE kategorie = ? AND {spalte} IS NULL", kategorie)
    quote = 100 * (gesamt - ohne) / gesamt
    return Pruefergebnis(
        regel, "Vollstaendigkeit", quote >= 95.0,
        f"{quote:.1f}% der {gesamt} Fakten sind mit ihrer Dimension verknuepft "
        f"und damit {zweck}.",
        ohne,
    )


def regel_itemabdeckung(conn: sqlite3.Connection) -> Pruefergebnis:
    """Getragene Items muessen mit den Stammdaten der Hauptspiele verknuepft sein.

    Champions liefert nur den Namen des Items. Ohne die Verknuepfung waere die
    Itemauswertung eine Auszaehlung von Zeichenketten, und der Schadensrechner
    koennte einen Wahlschal nicht von einem Fokusgurt unterscheiden.
    """
    return _abdeckung(
        conn, "held_item", "item_sk",
        "Verknuepfung der Items mit ihren Stammdaten",
        "nach ihrer Wirkung auswertbar")


def regel_faehigkeitsabdeckung(conn: sqlite3.Connection) -> Pruefergebnis:
    """Gespielte Faehigkeiten muessen mit den Stammdaten verknuepft sein."""
    return _abdeckung(
        conn, "ability", "faehigkeit_sk",
        "Verknuepfung der Faehigkeiten mit ihren Stammdaten",
        "nach ihrer Wirkungsklasse auswertbar")


def regel_go_wertebereich(conn: sqlite3.Connection) -> Pruefergebnis:
    """GO-Scores muessen im dokumentierten Bereich von 0 bis 100 liegen."""
    gesamt = _zaehle(conn, "SELECT COUNT(*) FROM Fact_GO_Meta")
    if gesamt == 0:
        return Pruefergebnis("Wertebereich der GO-Scores", "Wertebereich", True,
                             "Keine GO-Daten geladen.", 0)
    ausserhalb = _zaehle(
        conn, "SELECT COUNT(*) FROM Fact_GO_Meta WHERE score < 0 OR score > 100")
    return Pruefergebnis(
        "Wertebereich der GO-Scores", "Wertebereich", ausserhalb == 0,
        "Alle GO-Scores liegen zwischen 0 und 100."
        if ausserhalb == 0 else f"{ausserhalb} von {gesamt} Scores ausserhalb von 0-100.",
        ausserhalb)


def regel_go_aufloesungsquote(conn: sqlite3.Connection) -> Pruefergebnis:
    """GO-Bezeichner sollen auf die konforme Pokemon-Dimension zeigen.

    Ohne die Verknuepfung traegt der Satz nur innerhalb von GO; die
    spieluebergreifenden Auswertungen (H13) sehen ihn nicht.
    """
    gesamt = _zaehle(conn, "SELECT COUNT(*) FROM Fact_GO_Meta WHERE ist_schatten = 0")
    if gesamt == 0:
        return Pruefergebnis("Aufloesung der GO-Bezeichner", "Konsistenz", True,
                             "Keine GO-Daten geladen.", 0)
    ohne = _zaehle(conn, """
        SELECT COUNT(*) FROM Fact_GO_Meta
        WHERE ist_schatten = 0 AND pokemon_sk IS NULL
    """)
    quote = 100 * (gesamt - ohne) / gesamt
    return Pruefergebnis(
        "Aufloesung der GO-Bezeichner", "Konsistenz", quote >= 90.0,
        f"{quote:.1f}% der GO-Saetze sind mit der konformen Pokemon-Dimension "
        "verknuepft.", ohne)


def regel_tcg_plausibilitaet(conn: sqlite3.Connection) -> Pruefergebnis:
    """Im TCG-Fakt darf die Top-8-Zahl die Spielerzahl nicht uebersteigen."""
    gesamt = _zaehle(conn, "SELECT COUNT(*) FROM Fact_TCG_Meta")
    if gesamt == 0:
        return Pruefergebnis("Plausibilitaet der TCG-Zaehlung", "Konsistenz", True,
                             "Keine TCG-Daten geladen.", 0)
    verletzt = _zaehle(
        conn, "SELECT COUNT(*) FROM Fact_TCG_Meta WHERE top8 > spieler OR spieler < 1")
    return Pruefergebnis(
        "Plausibilitaet der TCG-Zaehlung", "Konsistenz", verletzt == 0,
        "Alle TCG-Zaehlungen sind in sich stimmig."
        if verletzt == 0 else f"{verletzt} Saetze mit top8 > spieler oder spieler < 1.",
        verletzt)


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
    """Das Warehouse soll so aktuell sein wie die Quelle.

    Gemessen wird gegen den juengsten Tag, den die Quelle **anbietet**, nicht
    gegen das heutige Datum. Beides faellt nur auseinander, wenn die Quelle
    selbst nicht liefert -- ein fremder Ausfall, den kein Ladelauf beheben kann.
    Was diese Regel prueft, ist das Eigene: Haben wir jeden angebotenen Tag auch
    geholt? Wie alt die Quelle insgesamt ist, meldet
    :func:`beobachte_quellenlage`.

    Ohne hinterlegten Quellstand -- etwa bei einem Aufbau allein aus dem Archiv
    -- fehlt die Vergleichsgroesse; der Rueckstand wird dann nur benannt. Ein
    *leerer* Stand dagegen heisst, dass wir das Angebot der Quelle nicht mehr
    lesen koennen, und gilt als Mangel.
    """
    jueng = conn.execute("SELECT MAX(datum_iso) FROM Dim_Zeit").fetchone()[0]
    if not jueng:
        return Pruefergebnis("Aktualitaet der Bewegungsdaten", "Aktualitaet", False,
                             "Keine Bewegungsdaten geladen.", 1)

    stand = quelle_stand_lesen(conn, "Champions")
    if stand is None:
        rueckstand = (date.today() - date.fromisoformat(jueng)).days
        return Pruefergebnis(
            "Aktualitaet der Bewegungsdaten", "Aktualitaet", True,
            f"Juengster geladener Tag: {jueng} ({rueckstand} Tage alt). Ohne Zugriff auf "
            f"die Quelle ist nicht bewertbar, ob es einen neueren Tag gaebe; die Quelle "
            f"haelt {QUELLE_VORHALTUNG_TAGE} Tage vor.", 0,
        )

    if not stand["letzter_tag"]:
        return Pruefergebnis(
            "Aktualitaet der Bewegungsdaten", "Aktualitaet", False,
            f"Die Quelle bot beim letzten Zugriff am {stand['abgerufen_am'][:10]} keinen "
            f"einzigen Tag an -- vermutlich hat sich ihr Format geaendert. Juengster "
            f"geladener Tag: {jueng}.", 1,
        )

    offen = [t for t in stand["tage"] if t > jueng]
    return Pruefergebnis(
        "Aktualitaet der Bewegungsdaten", "Aktualitaet", not offen,
        f"Juengster geladener Tag: {jueng}; die Quelle bietet nichts Neueres an."
        if not offen else
        f"{len(offen)} von der Quelle angebotene Tage sind nicht geladen: "
        f"{', '.join(offen[:5])}. Juengster geladener Tag: {jueng}.",
        len(offen),
    )


def beobachte_quellenlage(conn: sqlite3.Connection) -> Pruefergebnis | None:
    """Meldet, wenn die Quelle selbst seit Tagen nichts Neues veroeffentlicht.

    Das ist kein Mangel **unserer** Verarbeitung und zaehlt deshalb nicht in den
    Qualitaetsindex -- ein fremder Ausfall darf ein Qualitaetstor nicht dauerhaft
    schliessen. Sichtbar bleiben muss er trotzdem: die Auswertungen altern mit
    der Quelle, und ein Formatwechsel saehe zunaechst genauso aus.

    Liefert ``None``, wenn es nichts zu berichten gibt.
    """
    stand = quelle_stand_lesen(conn, "Champions")
    if stand is None:
        # Ein Bestand allein aus dem Archiv -- etwa in der Cloud, die bei jedem
        # Start neu aufbaut. Zwei Regeln koennen dann nicht greifen; das gehoert
        # in den Bericht, sonst liest sich ihr Bestehen als Unbedenklichkeit.
        if not _zaehle(conn, "SELECT COUNT(*) FROM Archiv_Champions"):
            return None
        return Pruefergebnis(
            "Quellenlage", "Aktualitaet", False,
            "Kein Zugriff auf die Quelle hinterlegt -- der Bestand stammt aus dem "
            "Archiv. Lueckenlosigkeit und Aktualitaet sind daran nicht bewertbar.", 1)

    zeitpunkt = stand["abgerufen_am"][:10]
    if not stand["letzter_tag"]:
        return Pruefergebnis(
            "Quellenlage", "Aktualitaet", False,
            f"Die Quelle bot beim Zugriff am {zeitpunkt} keinen Tagesstand an.", 1)

    rueckstand = (date.today() - date.fromisoformat(stand["letzter_tag"])).days
    if rueckstand <= 3:
        return None

    return Pruefergebnis(
        "Quellenlage", "Aktualitaet", False,
        f"Die Quelle fuehrt seit {stand['letzter_tag']} keinen neuen Tag mehr "
        f"({rueckstand} Tage; Zugriff am {zeitpunkt}). Ein fremder Ausfall -- die "
        f"Auswertungen altern mit, holbar ist nichts.",
        rueckstand,
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
    regel_itemabdeckung,
    regel_faehigkeitsabdeckung,
    regel_go_wertebereich,
    regel_go_aufloesungsquote,
    regel_tcg_plausibilitaet,
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


def beobachte_alles(conn: sqlite3.Connection) -> list[Pruefergebnis]:
    """Fuehrt die Beobachtungen aus -- Befunde ausserhalb des Qualitaetsindex.

    Beobachtungen betreffen Umstaende, die das Ergebnis beeintraechtigen, aber
    nicht in der eigenen Verarbeitung liegen. Sie gehoeren in den Bericht, nicht
    in die Bewertung: sonst hinge der Index am Wohlverhalten Dritter.
    """
    ergebnisse: list[Pruefergebnis] = []
    for beobachtung in (beobachte_quellenlage,):
        try:
            ergebnis = beobachtung(conn)
        except Exception as fehler:  # noqa: BLE001
            ergebnis = Pruefergebnis(
                beobachtung.__name__, "Aktualitaet", False,
                f"Die Beobachtung konnte nicht ausgefuehrt werden: {fehler}", 1)
        if ergebnis is not None:
            ergebnisse.append(ergebnis)
    return ergebnisse


def qualitaetsindex(ergebnisse: list[Pruefergebnis]) -> float:
    """Anteil bestandener Regeln in Prozent -- verdichtete Kennzahl fuer das Cockpit."""
    if not ergebnisse:
        return 0.0
    return round(100 * sum(1 for e in ergebnisse if e.bestanden) / len(ergebnisse), 1)
