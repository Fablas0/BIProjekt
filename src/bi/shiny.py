"""Shiny-Jagd: Regelbasis der Wahrscheinlichkeiten und die Statistik dazu.

Warum eine eigene Regelbasis
----------------------------
Keine der angebundenen Quellen kennt Shiny-Wahrscheinlichkeiten. Sie sind aber
seit Jahren durch Datamining belegt und aendern sich je Spielgeneration und
Methode -- also Stammdaten ohne Quellsystem, wie die Typen-Matrix in
:mod:`bi.typechart`. Hier stehen sie im Code, mit Herkunft im Kommentar und
durch Tests gegen Tippfehler gesichert.

Die meisten Methoden wirken ueber **Wuerfe**: das Spiel wuerfelt nicht einmal
mit 1/4096, sondern mehrfach, und jeder Treffer macht das Pokemon schillernd.
Das Schillerpin etwa gibt zwei zusaetzliche Wuerfe, die Masuda-Methode fuenf.
Die Wahrscheinlichkeit einer Methode ist damit keine Tabellenzahl, sondern
folgt aus ``1 - (1 - 1/N)^Wuerfe`` -- die im Netz kursierende Angabe
"Masuda 1/683" ist genau das Ergebnis dieser Rechnung fuer sechs Wuerfe mit
1/4096. Pokemon GO wuerfelt nicht; dort steht die Rate unmittelbar.

Die Statistik
-------------
Jeder Versuch ist ein unabhaengiges Bernoulli-Experiment mit Erfolgs-
wahrscheinlichkeit ``p``; die Zahl der Versuche bis zum ersten Treffer ist
damit geometrisch verteilt. Alles, was die Oberflaeche ausweist, folgt aus
dieser einen Annahme:

* Erwartungswert ``1/p`` -- der Wert, den jeder kennt ("im Schnitt 4096").
* Median ``ln(0,5) / ln(1 - p)`` -- die Zahl, die Haelfte der Jaeger nicht
  ueberschreitet. Er liegt bei rund 69 Prozent des Erwartungswerts; wer den
  Erwartungswert als "normale" Dauer erwartet, wird im Regelfall frueher
  fertig als gedacht und haelt sich fuer gluecklich.
* Kumulierte Wahrscheinlichkeit ``1 - (1 - p)^n`` -- wie viele Jaeger nach
  ``n`` Versuchen bereits fuendig waren. Das ist die Einordnung des eigenen
  Zaehlerstands: wer nach dem Erwartungswert noch sucht, teilt das Los von
  rund 37 Prozent aller Jaeger (``1/e``); von Pech laesst sich erst weit
  dahinter sprechen.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from .nutzerdaten import SCHEMA, _jetzt

# Grundwahrscheinlichkeit eines einzelnen Wurfs je Spielgeneration. Vor der
# zweiten Generation gab es keine schillernden Pokemon.
NENNER_ALT = 8192      # Generation 2 bis 5 (Gold/Silber bis Schwarz/Weiss 2)
NENNER_NEU = 4096      # ab Generation 6 (X/Y)


@dataclass(frozen=True)
class Methode:
    """Eine Jagdmethode mit ihrer Wahrscheinlichkeit je Versuch.

    ``wahrscheinlichkeit`` ist die Trefferchance **eines Versuchs**; was ein
    Versuch ist (eine Begegnung, ein Ei, ein Neustart), sagt ``einheit``.
    """

    schluessel: str
    bezeichnung: str
    spiel: str                 # Spielfamilie, fuer die Auswahl gruppiert
    wahrscheinlichkeit: float
    einheit: str               # "Begegnungen", "Eier", "Neustarts", "Kaempfe"
    erlaeuterung: str = ""

    @property
    def nenner(self) -> float:
        """Die gelaeufige Schreibweise '1 zu N'."""
        return 1.0 / self.wahrscheinlichkeit


def _wuerfe(nenner: int, anzahl: int) -> float:
    """Trefferchance bei ``anzahl`` unabhaengigen Wuerfen mit 1/``nenner``."""
    return 1.0 - (1.0 - 1.0 / nenner) ** anzahl


def _m(schluessel: str, bezeichnung: str, spiel: str, p: float, einheit: str,
       erlaeuterung: str = "") -> Methode:
    return Methode(schluessel, bezeichnung, spiel, p, einheit, erlaeuterung)


# Die Methoden, geordnet nach Spielfamilie. Die Wurfzahlen sind die durch
# Datamining belegten Werte; wo eine Methode einen Kettenbonus hat, steht die
# Hoechststufe, weil sie das Jagdziel ist.
METHODEN: dict[str, Methode] = {
    # -- Hauptspiele, aeltere Generationen ---------------------------------
    "gen2_voll": _m("gen2_voll", "Zufallsbegegnung (Gen. 2-5)", "Hauptspiele bis Gen. 5",
                    _wuerfe(NENNER_ALT, 1), "Begegnungen",
                    "Gold/Silber bis Schwarz/Weiss 2: ein Wurf mit 1/8192."),
    "gen4_masuda": _m("gen4_masuda", "Masuda-Methode (Gen. 4)", "Hauptspiele bis Gen. 5",
                      _wuerfe(NENNER_ALT, 5), "Eier",
                      "Diamant/Perl/Platin, HG/SS: Eltern aus zwei Sprachfassungen, "
                      "fuenf Wuerfe."),
    "gen5_masuda": _m("gen5_masuda", "Masuda-Methode (Gen. 5)", "Hauptspiele bis Gen. 5",
                      _wuerfe(NENNER_ALT, 6), "Eier",
                      "Schwarz/Weiss (2): sechs Wuerfe; mit Schillerpin acht."),
    "gen5_masuda_pin": _m("gen5_masuda_pin", "Masuda + Schillerpin (Gen. 5)",
                          "Hauptspiele bis Gen. 5", _wuerfe(NENNER_ALT, 8), "Eier"),
    "gen4_pokeradar": _m("gen4_pokeradar", "Pokeradar-Kette 40 (Gen. 4)",
                         "Hauptspiele bis Gen. 5", 1.0 / 200, "Begegnungen",
                         "Ab Kettenlaenge 40 ist der Hoechstwert erreicht."),
    # -- Hauptspiele ab Generation 6 ----------------------------------------
    "gen6_voll": _m("gen6_voll", "Zufallsbegegnung (ab Gen. 6)", "Hauptspiele ab Gen. 6",
                    _wuerfe(NENNER_NEU, 1), "Begegnungen",
                    "X/Y bis Karmesin/Purpur: ein Wurf mit 1/4096."),
    "gen6_pin": _m("gen6_pin", "Zufallsbegegnung + Schillerpin", "Hauptspiele ab Gen. 6",
                   _wuerfe(NENNER_NEU, 3), "Begegnungen",
                   "Der Schillerpin gibt zwei zusaetzliche Wuerfe."),
    "gen6_masuda": _m("gen6_masuda", "Masuda-Methode", "Hauptspiele ab Gen. 6",
                      _wuerfe(NENNER_NEU, 6), "Eier",
                      "Eltern aus zwei Sprachfassungen: sechs Wuerfe -- die "
                      "bekannte Angabe '1 zu 683'."),
    "gen6_masuda_pin": _m("gen6_masuda_pin", "Masuda + Schillerpin", "Hauptspiele ab Gen. 6",
                          _wuerfe(NENNER_NEU, 8), "Eier", "Acht Wuerfe, rund 1 zu 512."),
    "gen7_sos": _m("gen7_sos", "SOS-Kette 31+ (Gen. 7)", "Hauptspiele ab Gen. 6",
                   _wuerfe(NENNER_NEU, 13), "Begegnungen",
                   "Sonne/Mond: ab Kettenlaenge 31 zwoelf zusaetzliche Wuerfe."),
    "gen7_sos_pin": _m("gen7_sos_pin", "SOS-Kette 31+ mit Schillerpin (Gen. 7)",
                       "Hauptspiele ab Gen. 6", _wuerfe(NENNER_NEU, 15), "Begegnungen"),
    "gen8_pin": _m("gen8_pin", "Schwert/Schild: Schillerpin", "Hauptspiele ab Gen. 6",
                   _wuerfe(NENNER_NEU, 3), "Begegnungen",
                   "Der Kampfzaehler verbessert zusaetzlich die Chance auf "
                   "strahlende Pokemon, nicht die Grundrate je Wurf."),
    "gen9_pin": _m("gen9_pin", "Karmesin/Purpur: Schillerpin", "Hauptspiele ab Gen. 6",
                   _wuerfe(NENNER_NEU, 3), "Begegnungen"),
    "gen9_sandwich": _m("gen9_sandwich", "Karmesin/Purpur: Funkel-Kraft Stufe 3",
                        "Hauptspiele ab Gen. 6", _wuerfe(NENNER_NEU, 4), "Begegnungen",
                        "Das Sandwich gibt drei zusaetzliche Wuerfe."),
    "gen9_sandwich_pin": _m("gen9_sandwich_pin", "Karmesin/Purpur: Funkel-Kraft + Schillerpin",
                            "Hauptspiele ab Gen. 6", _wuerfe(NENNER_NEU, 6), "Begegnungen"),
    "gen9_massenauftreten": _m("gen9_massenauftreten",
                               "Karmesin/Purpur: Massenauftreten 60+ mit Sandwich und Pin",
                               "Hauptspiele ab Gen. 6", _wuerfe(NENNER_NEU, 8), "Begegnungen",
                               "Sechzig besiegte Pokemon geben zwei weitere Wuerfe; "
                               "mit Funkel-Kraft und Schillerpin acht insgesamt."),
    "legenden_arceus_massen": _m("legenden_arceus_massen",
                                 "Legenden Arceus: Massenauftreten + Schillerpin + Dex 10",
                                 "Hauptspiele ab Gen. 6", _wuerfe(NENNER_NEU, 32),
                                 "Begegnungen",
                                 "Massenauftreten (+25), Schillerpin (+3), "
                                 "Forschungsstufe 10 (+3)."),
    "neustart": _m("neustart", "Neustart (Starter, Legendaeres, Geschenk)",
                   "Hauptspiele ab Gen. 6", _wuerfe(NENNER_NEU, 1), "Neustarts",
                   "Ein Neustart ist ein Wurf -- sofern das Pokemon nicht "
                   "shiny-gesperrt ist."),
    # -- Pokemon GO ----------------------------------------------------------
    "go_wild": _m("go_wild", "Wildes Pokemon (Standardrate)", "Pokemon GO",
                  1.0 / 512, "Begegnungen",
                  "Grundrate ausserhalb von Ereignissen, durch Community-"
                  "Zaehlungen belegt."),
    "go_dauerbrenner": _m("go_dauerbrenner", "Dauerhaft erhoehte Rate (z. B. Nebelkinder)",
                          "Pokemon GO", 1.0 / 64, "Begegnungen"),
    "go_raid_legendaer": _m("go_raid_legendaer", "Legendaerer Raid", "Pokemon GO",
                            1.0 / 20, "Kaempfe"),
    "go_community_day": _m("go_community_day", "Community Day", "Pokemon GO",
                           1.0 / 25, "Begegnungen"),
    "go_eier": _m("go_eier", "Eier (Standardrate)", "Pokemon GO", 1.0 / 50, "Eier"),
}

SPIELE = tuple(dict.fromkeys(m.spiel for m in METHODEN.values()))

JAGD_STATUS = ("laeuft", "gefunden", "abgebrochen")


def methoden_je_spiel(spiel: str) -> list[Methode]:
    return [m for m in METHODEN.values() if m.spiel == spiel]


# --------------------------------------------------------------------------
# Statistik der geometrischen Verteilung
# --------------------------------------------------------------------------

def erwartungswert(p: float) -> float:
    """Mittlere Zahl der Versuche bis zum ersten Treffer."""
    return 1.0 / p


def median_versuche(p: float) -> int:
    """Die Versuchszahl, die die Haelfte aller Jaeger nicht ueberschreitet."""
    return math.ceil(math.log(0.5) / math.log(1.0 - p))


def kumuliert(p: float, versuche: int) -> float:
    """Wahrscheinlichkeit, in hoechstens ``versuche`` Versuchen fuendig zu werden."""
    return 1.0 - (1.0 - p) ** max(0, versuche)


def versuche_fuer(p: float, sicherheit: float) -> int:
    """Wie viele Versuche es braucht, um mit ``sicherheit`` fuendig zu sein.

    Der Wert fuer 99 Prozent liegt beim rund 4,6-fachen des Erwartungswerts --
    eine Zahl, die kaum jemand ahnt, der mit 'ungefaehr 4096' rechnet.
    """
    if not 0 < sicherheit < 1:
        raise ValueError("Die Sicherheit muss zwischen 0 und 1 liegen.")
    return math.ceil(math.log(1.0 - sicherheit) / math.log(1.0 - p))


@dataclass(frozen=True)
class Einordnung:
    """Der eigene Zaehlerstand vor dem Hintergrund aller Jaeger."""

    versuche: int
    erwartungswert: float
    median: int
    anteil_bereits_fuendig: float     # Anteil der Jaeger, die bis hier gefunden haetten
    stufe: str                        # 'frueh' | 'ueblich' | 'geduldig' | 'pech' | 'glueck'
    text: str


def einordnen(methode: Methode, versuche: int, gefunden: bool = False) -> Einordnung:
    """Ordnet einen Zaehlerstand ein -- als Anteil, nicht als Urteil.

    Die Stufen sind bewusst grob. Feiner aufgeloest ergaebe die Einordnung
    eine Zahl, die niemand fuehlt; "rund zwei Drittel aller Jaeger waren bis
    hier schon fertig" versteht dagegen jeder.
    """
    p = methode.wahrscheinlichkeit
    anteil = kumuliert(p, versuche)
    erwartet = erwartungswert(p)
    median = median_versuche(p)

    if gefunden:
        if anteil <= 0.25:
            stufe, text = "glueck", (
                f"Gefunden nach {versuche} {methode.einheit} -- nur rund "
                f"{anteil:.0%} aller Jaeger sind so frueh fertig.")
        elif anteil <= 0.75:
            stufe, text = "ueblich", (
                f"Gefunden nach {versuche} {methode.einheit}: ein gewoehnlicher "
                f"Verlauf, rund {anteil:.0%} aller Jaeger sind bis hier fertig.")
        else:
            stufe, text = "pech", (
                f"Gefunden nach {versuche} {methode.einheit} -- rund {anteil:.0%} "
                f"aller Jaeger waren bis hier schon fertig. Das war Geduld.")
    elif anteil < 0.5:
        stufe, text = "frueh", (
            f"{versuche} {methode.einheit} bisher: erst rund {anteil:.0%} aller "
            f"Jaeger sind bis hier fuendig geworden, der Median liegt bei {median}.")
    elif anteil < 0.9:
        stufe, text = "geduldig", (
            f"{versuche} {methode.einheit}: rund {anteil:.0%} aller Jaeger waren bis "
            f"hier schon fertig. Das ist noch kein Pech -- der Erwartungswert "
            f"liegt bei {erwartet:,.0f}.")
    else:
        stufe, text = "pech", (
            f"{versuche} {methode.einheit}: rund {anteil:.1%} aller Jaeger waren bis "
            f"hier schon fertig. Jeder weitere Versuch hat trotzdem dieselbe "
            f"Chance von 1 zu {methode.nenner:,.0f} -- die Verteilung hat kein "
            f"Gedaechtnis.")

    return Einordnung(versuche, erwartet, median, anteil, stufe, text)


def verteilung(p: float, bis: int | None = None, schritte: int = 60) -> list[tuple[int, float]]:
    """Stuetzpunkte der kumulierten Verteilung fuer ein Diagramm.

    Reicht standardmaessig bis zur 99-Prozent-Marke -- danach passiert im
    Diagramm nichts mehr, was das Auge unterscheiden koennte.
    """
    ende = bis or versuche_fuer(p, 0.99)
    schrittweite = max(1, ende // schritte)
    punkte = [(n, kumuliert(p, n)) for n in range(0, ende + 1, schrittweite)]
    if punkte[-1][0] != ende:
        punkte.append((ende, kumuliert(p, ende)))
    return punkte


# --------------------------------------------------------------------------
# Datenhaltung der Jagden
# --------------------------------------------------------------------------

def jagd_anlegen(conn: sqlite3.Connection, nutzer_id: int, slug: str, methode: str,
                 spiel: str | None = None, versuche: int = 0,
                 notiz: str | None = None) -> int:
    """Beginnt eine Jagd. Die Methode muss aus der Regelbasis stammen."""
    if methode not in METHODEN:
        raise ValueError(f"Unbekannte Jagdmethode: {methode}")
    if not slug:
        raise ValueError("Ohne Pokemon keine Jagd.")
    if versuche < 0:
        raise ValueError("Der Zaehler kann nicht negativ beginnen.")
    jetzt = _jetzt()
    cursor = conn.execute(
        f"""INSERT INTO {SCHEMA}.Shiny_Jagd
                (nutzer_id, slug, spiel, methode, versuche, status, notiz,
                 begonnen_am, geaendert_am)
            VALUES (?, ?, ?, ?, ?, 'laeuft', ?, ?, ?)""",
        (nutzer_id, slug, spiel or METHODEN[methode].spiel, methode, int(versuche),
         notiz, jetzt, jetzt))
    conn.commit()
    return int(cursor.lastrowid)


def jagd_zaehlen(conn: sqlite3.Connection, nutzer_id: int, jagd_id: int,
                 schritt: int = 1) -> int:
    """Erhoeht (oder senkt) den Zaehler und liefert den neuen Stand.

    Unter null geht es nicht -- ein negativer Versuch ist keiner.
    """
    zeile = conn.execute(
        f"SELECT versuche, status FROM {SCHEMA}.Shiny_Jagd WHERE jagd_id = ? AND nutzer_id = ?",
        (jagd_id, nutzer_id)).fetchone()
    if zeile is None:
        raise ValueError("Jagd nicht gefunden.")
    if zeile["status"] != "laeuft":
        raise ValueError("Diese Jagd ist abgeschlossen.")
    neu = max(0, int(zeile["versuche"]) + int(schritt))
    conn.execute(
        f"UPDATE {SCHEMA}.Shiny_Jagd SET versuche = ?, geaendert_am = ? WHERE jagd_id = ?",
        (neu, _jetzt(), jagd_id))
    conn.commit()
    return neu


def jagd_setzen(conn: sqlite3.Connection, nutzer_id: int, jagd_id: int, versuche: int) -> None:
    """Setzt den Zaehler auf einen Stand -- fuer nachgetragene Zaehlungen."""
    if versuche < 0:
        raise ValueError("Der Zaehler kann nicht negativ sein.")
    conn.execute(
        f"""UPDATE {SCHEMA}.Shiny_Jagd SET versuche = ?, geaendert_am = ?
             WHERE jagd_id = ? AND nutzer_id = ? AND status = 'laeuft'""",
        (int(versuche), _jetzt(), jagd_id, nutzer_id))
    conn.commit()


def jagd_abschliessen(conn: sqlite3.Connection, nutzer_id: int, jagd_id: int,
                      gefunden: bool) -> None:
    status = "gefunden" if gefunden else "abgebrochen"
    conn.execute(
        f"""UPDATE {SCHEMA}.Shiny_Jagd SET status = ?, beendet_am = ?, geaendert_am = ?
             WHERE jagd_id = ? AND nutzer_id = ?""",
        (status, _jetzt(), _jetzt(), jagd_id, nutzer_id))
    conn.commit()


def jagd_loeschen(conn: sqlite3.Connection, nutzer_id: int, jagd_id: int) -> None:
    conn.execute(f"DELETE FROM {SCHEMA}.Shiny_Jagd WHERE jagd_id = ? AND nutzer_id = ?",
                 (jagd_id, nutzer_id))
    conn.commit()


def jagden_lesen(conn: sqlite3.Connection, nutzer_id: int) -> list[dict[str, Any]]:
    """Alle Jagden eines Nutzers, laufende zuerst, angereichert aus den Stammdaten."""
    zeilen = conn.execute(f"""
        SELECT j.*, p.anzeigename, p.name_de, p.pokedex_id, p.typ1, p.typ2
          FROM {SCHEMA}.Shiny_Jagd j
          LEFT JOIN Dim_Pokemon p ON p.slug = j.slug AND p.ist_aktuell = 1
         WHERE j.nutzer_id = ?
         ORDER BY CASE j.status WHEN 'laeuft' THEN 0 ELSE 1 END, j.geaendert_am DESC
    """, (nutzer_id,)).fetchall()
    saetze = []
    for zeile in zeilen:
        satz = dict(zeile)
        methode = METHODEN.get(satz["methode"])
        satz["methode_name"] = methode.bezeichnung if methode else satz["methode"]
        satz["einheit"] = methode.einheit if methode else "Versuche"
        satz["einordnung"] = (
            einordnen(methode, int(satz["versuche"]), satz["status"] == "gefunden")
            if methode else None)
        saetze.append(satz)
    return saetze


def bilanz(jagden: list[dict[str, Any]]) -> dict[str, Any]:
    """Gesamtbild ueber alle Jagden eines Nutzers.

    Die Summe der Versuche ist zulaessig -- Versuche sind Zaehlungen, keine
    Raenge. Der 'Glueckswert' ist der Mittelwert der kumulierten Anteile aller
    gefundenen Jagden: 0,5 waere ein durchschnittlicher Jaeger, darunter ein
    gluecklicher.
    """
    gefunden = [j for j in jagden if j["status"] == "gefunden" and j.get("einordnung")]
    anteile = [j["einordnung"].anteil_bereits_fuendig for j in gefunden]
    return {
        "jagden": len(jagden),
        "laufend": sum(1 for j in jagden if j["status"] == "laeuft"),
        "gefunden": len(gefunden),
        "versuche_gesamt": sum(int(j["versuche"]) for j in jagden),
        "glueckswert": (sum(anteile) / len(anteile)) if anteile else None,
    }
