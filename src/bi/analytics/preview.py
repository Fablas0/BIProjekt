"""Team-Preview-Advisor -- welche Pokemon sollen mitgenommen werden?

Im Turnier bringt jede Seite sechs Pokemon mit, sieht im Team-Preview die sechs
des Gegners und waehlt daraus die Kaempfer aus: **vier** im Doppelkampf, **drei**
im Einzelkampf. Diese Entscheidung faellt unter Zeitdruck und entscheidet die
Partie oft, bevor der erste Zug gemacht ist.

Warum das eine Rechnung und keine Abfrage ist
---------------------------------------------
Die Quelle veroeffentlicht nicht, welche Pokemon tatsaechlich mitgenommen
wurden -- diese Kennzahl existiert oeffentlich nicht. Sie wird hier auch nicht
gebraucht: eine Durchschnittsquote sagte ohnehin nur, was Spieler *im Mittel*
bringen, nicht was gegen *dieses eine* Team richtig ist.

Stattdessen wird die Entscheidung durchgerechnet. Bei sechs gegen sechs gibt es
im Doppelkampf 15 eigene und 15 gegnerische Auswahlmoeglichkeiten, also 225
Paarungen; im Einzelkampf 20 mal 20 gleich 400. Jede Paarung wird bewertet, und
zwar mit Daten, die bereits im Warehouse liegen: Typen, reale Initiative,
tatsaechlich gespielte Attacken und Statuswerte.

Bewertungsmodell
----------------
Je Paarung eines eigenen mit einem gegnerischen Pokemon werden drei Groessen
verrechnet:

* **Offensive** -- wie stark die eigenen gespielten Attacken gegen die Typen des
  Gegners wirken, gewichtet mit dem passenden Angriffswert.
* **Defensive** -- dasselbe in der Gegenrichtung.
* **Initiative** -- wer zuerst handelt. Der Vorteil zaehlt doppelt, wenn die
  eigene Seite offensiv ueberlegen ist: dann entscheidet die Reihenfolge, ob der
  Vorteil ueberhaupt zum Tragen kommt.

Der Wert einer eigenen Auswahl ist der Mittelwert ueber alle gegnerischen
Auswahlen -- ergaenzt um den ungueenstigsten Fall, damit eine Auswahl mit einem
katastrophalen Ausreisser nicht allein wegen guter Durchschnittswerte gewinnt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from itertools import combinations

import pandas as pd

from ..config import STANDARD_KAMPFFORMAT
from ..stats import handelt_zuerst
from ..typechart import eingehender_multiplikator

# Gewichtung der drei Teilaspekte. Offensive wiegt am schwersten: im
# Doppelkampf werden Partien ueber Druck entschieden, nicht ueber Aussitzen.
GEWICHT_OFFENSIVE = 0.45
GEWICHT_DEFENSIVE = 0.35
GEWICHT_INITIATIVE = 0.20

# Anteil, ab dem eine Attacke als verlaesslich gespielt gilt.
ATTACKEN_SCHWELLE = 20.0

# Wie stark der unguenstigste Fall in die Gesamtbewertung eingeht.
RISIKO_GEWICHT = 0.30


@dataclass
class Kaempfer:
    """Ein Pokemon mit allem, was fuer die Bewertung gebraucht wird."""

    name: str
    pokedex_id: int
    typ1: str
    typ2: str | None
    attack: int
    sp_attack: int
    speed: int
    rang: int = 0
    set_bezeichnung: str = ""
    attacken: list[tuple[str, str, str, int]] = field(default_factory=list)
    # je Attacke: (Anzeigename, Typ, Kategorie, Basisschaden)

    @property
    def typen(self) -> str:
        return f"{self.typ1} / {self.typ2}" if self.typ2 else self.typ1


@dataclass
class Paarung:
    """Bewertung einer eigenen Auswahl gegen eine gegnerische."""

    eigene: tuple[str, ...]
    gegnerische: tuple[str, ...]
    punktzahl: float
    offensive: float
    defensive: float
    initiative: float


@dataclass
class Empfehlung:
    """Ergebnis der Auswertung fuer eine eigene Auswahl."""

    auswahl: tuple[str, ...]
    mittelwert: float
    schlechtester_fall: float
    bester_fall: float
    gesamtwertung: float
    gewinnquote: float                  # Anteil gegnerischer Auswahlen mit Vorteil
    riskanteste_gegnerauswahl: tuple[str, ...]
    beitraege: dict[str, float] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Datenbeschaffung
# --------------------------------------------------------------------------

def _attacken_je_pokemon(conn: sqlite3.Connection, tag: str, kampfformat: str
                         ) -> dict[str, list[tuple[str, str, str, int]]]:
    """Laedt die verlaesslich gespielten Attacken je Pokemon."""
    df = pd.read_sql("""
        SELECT anzeigename AS pokemon, bezeichnung AS attacke, anteil,
               attacke_typ AS typ, attacke_kategorie AS kategorie, basisschaden
        FROM V_Merkmal
        WHERE kategorie = 'move' AND datum_iso = ? AND kampfformat = ?
          AND saison_aktuell = 1 AND anteil >= ?
    """, conn, params=(tag, kampfformat, ATTACKEN_SCHWELLE))

    # Statusattacken und Attacken ohne Stammdaten fallen heraus: nur Attacken mit
    # Typ und Schadenskategorie sind fuer die Matchup-Bewertung verwertbar.
    df = df[df["typ"].notna() & df["kategorie"].isin(["physical", "special"])]
    # Attacken mit veraenderlicher Staerke fuehrt die Quelle ohne Basisschaden;
    # 60 ist ein zurueckhaltender Ersatzwert.
    df = df.assign(basisschaden=df["basisschaden"].fillna(60).astype(int))

    return {
        name: list(
            zip(gruppe["attacke"], gruppe["typ"], gruppe["kategorie"],
                gruppe["basisschaden"], strict=True)
        )
        for name, gruppe in df.groupby("pokemon")
    }


def lade_kaempfer(conn: sqlite3.Connection, namen: list[str], tag: str,
                  kampfformat: str = STANDARD_KAMPFFORMAT) -> list[Kaempfer]:
    """Baut die Bewertungsobjekte zu einer Namensliste.

    Verwendet ausschliesslich den aktuellen Saisonstand: Pokemon aus abgelaufenen
    Saisons und veraltete Statuswerte fliessen nicht ein.
    """
    if not namen:
        return []

    platzhalter = ",".join("?" * len(namen))
    stamm = pd.read_sql(f"""
        SELECT u.anzeigename, u.pokedex_id, u.typ1, u.typ2, u.rang,
               COALESCE(m.wert_attack,    u.stufe50_attack)    AS attack,
               COALESCE(m.wert_sp_attack, u.stufe50_sp_attack) AS sp_attack,
               COALESCE(m.wert_speed,     u.stufe50_speed)     AS speed,
               m.bezeichnung AS set_bezeichnung
        FROM V_Usage u
        LEFT JOIN V_Merkmal m
               ON m.pokemon_sk = u.pokemon_sk AND m.zeit_sk = u.zeit_sk
              AND m.kampfformat_sk = u.kampfformat_sk AND m.saison_sk = u.saison_sk
              AND m.kategorie = 'spread' AND m.rang = 1
        WHERE u.anzeigename IN ({platzhalter}) AND u.datum_iso = ?
          AND u.kampfformat = ? AND u.saison_aktuell = 1
    """, conn, params=(*namen, tag, kampfformat))  # noqa: S608

    attacken = _attacken_je_pokemon(conn, tag, kampfformat)

    return [
        Kaempfer(
            name=z["anzeigename"], pokedex_id=int(z["pokedex_id"]),
            typ1=z["typ1"], typ2=z["typ2"],
            attack=int(z["attack"]), sp_attack=int(z["sp_attack"]),
            speed=int(z["speed"]), rang=int(z["rang"]),
            set_bezeichnung=z["set_bezeichnung"] or "",
            attacken=attacken.get(z["anzeigename"], []),
        )
        for _, z in stamm.iterrows()
    ]


# --------------------------------------------------------------------------
# Bewertung
# --------------------------------------------------------------------------

def offensivwert(angreifer: Kaempfer, verteidiger: Kaempfer) -> float:
    """Wie stark der Angreifer den Verteidiger unter Druck setzt.

    Massgeblich ist die beste tatsaechlich gespielte Attacke, nicht der
    theoretische Attackenvorrat. Fehlen Attackendaten, wird auf eine neutrale
    Abschaetzung ueber den Angriffswert zurueckgegriffen.
    """
    if not angreifer.attacken:
        return (max(angreifer.attack, angreifer.sp_attack) / 150) * 0.8

    beste = 0.0
    for _, typ, kategorie, basisschaden in angreifer.attacken:
        faktor = eingehender_multiplikator(typ, verteidiger.typ1, verteidiger.typ2)
        if faktor == 0:
            continue
        angriffswert = angreifer.attack if kategorie == "physical" else angreifer.sp_attack
        wirkung = faktor * (angriffswert / 150) * (basisschaden / 100)
        beste = max(beste, wirkung)
    return beste


def bewerte_paarung(eigener: Kaempfer, gegner: Kaempfer) -> tuple[float, float, float]:
    """Bewertet ein einzelnes Aufeinandertreffen.

    Rueckgabe: ``(offensive, defensive, initiative)``. Alle drei sind so
    normiert, dass 0 fuer ausgeglichen steht, positive Werte fuer einen Vorteil
    der eigenen Seite.
    """
    eigener_druck = offensivwert(eigener, gegner)
    gegner_druck = offensivwert(gegner, eigener)

    # Die beiden Groessen sind bewusst getrennt und ueberschneidungsfrei:
    # Offensive misst nur den ausgeuebten, Defensive nur den erlittenen Druck.
    # Wuerde die Offensive bereits die Differenz bilden, ginge der gegnerische
    # Druck doppelt in die Gesamtwertung ein.
    offensive = eigener_druck
    defensive = -gegner_druck

    reihenfolge = handelt_zuerst(eigener.speed, gegner.speed)
    tempo = {"schneller": 1.0, "gleichstand": 0.0, "langsamer": -1.0}[reihenfolge]
    # Der Initiativevorteil wiegt schwerer, wenn ohnehin offensiver Druck besteht:
    # dann entscheidet die Reihenfolge, ob er ueberhaupt zur Wirkung kommt.
    initiative = tempo * (1.0 + max(0.0, eigener_druck - gegner_druck))

    return offensive, defensive, initiative


def bewerte_auswahlen(eigene: list[Kaempfer], gegner: list[Kaempfer],
                      mitnahme: int) -> tuple[list[Empfehlung], list[Paarung]]:
    """Bewertet alle Kombinationen beider Seiten gegeneinander.

    Rueckgabe: die Empfehlungen absteigend nach Gesamtwertung sowie saemtliche
    Einzelpaarungen fuer die Detailansicht.
    """
    if len(eigene) < mitnahme or len(gegner) < mitnahme:
        return [], []

    eigene_auswahlen = list(combinations(eigene, mitnahme))
    gegner_auswahlen = list(combinations(gegner, mitnahme))

    # Paarungswerte einmal vorberechnen -- sie werden je Kombination mehrfach
    # gebraucht, und der Aufwand waechst sonst mit dem Produkt der Kombinationen.
    einzelwerte: dict[tuple[str, str], tuple[float, float, float]] = {}
    for a in eigene:
        for b in gegner:
            einzelwerte[(a.name, b.name)] = bewerte_paarung(a, b)

    alle_paarungen: list[Paarung] = []
    empfehlungen: list[Empfehlung] = []

    for eigene_auswahl in eigene_auswahlen:
        eigene_namen = tuple(k.name for k in eigene_auswahl)
        punktzahlen: list[float] = []
        beitrag_summe: dict[str, float] = dict.fromkeys(eigene_namen, 0.0)
        schlechteste: tuple[float, tuple[str, ...]] = (float("inf"), ())

        for gegner_auswahl in gegner_auswahlen:
            gegner_namen = tuple(k.name for k in gegner_auswahl)
            off = def_ = ini = 0.0

            for a in eigene_auswahl:
                beitrag = 0.0
                for b in gegner_auswahl:
                    o, d, i = einzelwerte[(a.name, b.name)]
                    off += o
                    def_ += d
                    ini += i
                    beitrag += (GEWICHT_OFFENSIVE * o + GEWICHT_DEFENSIVE * d
                                + GEWICHT_INITIATIVE * i)
                beitrag_summe[a.name] += beitrag / len(gegner_auswahl)

            anzahl = len(eigene_auswahl) * len(gegner_auswahl)
            off, def_, ini = off / anzahl, def_ / anzahl, ini / anzahl
            punktzahl = (GEWICHT_OFFENSIVE * off + GEWICHT_DEFENSIVE * def_
                         + GEWICHT_INITIATIVE * ini)

            punktzahlen.append(punktzahl)
            alle_paarungen.append(Paarung(eigene_namen, gegner_namen, punktzahl,
                                          off, def_, ini))
            if punktzahl < schlechteste[0]:
                schlechteste = (punktzahl, gegner_namen)

        mittelwert = sum(punktzahlen) / len(punktzahlen)
        gewinnquote = 100 * sum(1 for p in punktzahlen if p > 0) / len(punktzahlen)

        empfehlungen.append(Empfehlung(
            auswahl=eigene_namen,
            mittelwert=round(mittelwert, 3),
            schlechtester_fall=round(min(punktzahlen), 3),
            bester_fall=round(max(punktzahlen), 3),
            # Der unguenstigste Fall geht mit ein, damit eine Auswahl mit einem
            # katastrophalen Ausreisser nicht allein wegen guter Mittelwerte gewinnt.
            gesamtwertung=round(
                (1 - RISIKO_GEWICHT) * mittelwert + RISIKO_GEWICHT * min(punktzahlen), 3),
            gewinnquote=round(gewinnquote, 1),
            riskanteste_gegnerauswahl=schlechteste[1],
            beitraege={n: round(w / len(gegner_auswahlen), 3)
                       for n, w in beitrag_summe.items()},
        ))

    empfehlungen.sort(key=lambda e: e.gesamtwertung, reverse=True)
    return empfehlungen, alle_paarungen


# --------------------------------------------------------------------------
# Aufbereitung fuer die Anzeige
# --------------------------------------------------------------------------

def empfehlungen_als_tabelle(empfehlungen: list[Empfehlung]) -> pd.DataFrame:
    """Ueberfuehrt die Empfehlungen in eine anzeigbare Tabelle."""
    if not empfehlungen:
        return pd.DataFrame(columns=["Auswahl", "Gesamtwertung", "Mittelwert",
                                     "Schlechtester Fall", "Vorteil in %"])
    return pd.DataFrame([{
        "Auswahl": " · ".join(e.auswahl),
        "Gesamtwertung": e.gesamtwertung,
        "Mittelwert": e.mittelwert,
        "Schlechtester Fall": e.schlechtester_fall,
        "Vorteil in %": e.gewinnquote,
        "Riskanteste Gegnerauswahl": " · ".join(e.riskanteste_gegnerauswahl),
    } for e in empfehlungen])


def matchup_matrix(paarungen: list[Paarung], eigene_auswahl: tuple[str, ...]
                   ) -> pd.DataFrame:
    """Bewertung einer eigenen Auswahl gegen jede gegnerische Auswahl."""
    zeilen = [
        {"Gegnerische Auswahl": " · ".join(p.gegnerische), "Punktzahl": p.punktzahl,
         "Offensive": round(p.offensive, 3), "Defensive": round(p.defensive, 3),
         "Initiative": round(p.initiative, 3)}
        for p in paarungen if p.eigene == eigene_auswahl
    ]
    return (pd.DataFrame(zeilen).sort_values("Punktzahl").reset_index(drop=True)
            if zeilen else pd.DataFrame())


def einzelduelle(eigene: list[Kaempfer], gegner: list[Kaempfer]) -> pd.DataFrame:
    """Bewertung jedes eigenen Pokemon gegen jedes gegnerische.

    Diese Sicht macht die Empfehlung nachvollziehbar: sie zeigt, welche
    Einzelduelle die Gesamtbewertung tragen und welche sie belasten.
    """
    zeilen = []
    for a in eigene:
        for b in gegner:
            o, d, i = bewerte_paarung(a, b)
            gesamt = GEWICHT_OFFENSIVE * o + GEWICHT_DEFENSIVE * d + GEWICHT_INITIATIVE * i
            zeilen.append({
                "Eigenes Pokemon": a.name, "Gegner": b.name,
                "Bewertung": round(gesamt, 3),
                "Offensive": round(o, 3), "Defensive": round(d, 3),
                "Schneller": handelt_zuerst(a.speed, b.speed) == "schneller",
            })
    return pd.DataFrame(zeilen)


def begruendung(empfehlung: Empfehlung, eigene: list[Kaempfer],
                gegner: list[Kaempfer]) -> list[str]:
    """Formuliert, warum eine Auswahl empfohlen wird."""
    nach_name = {k.name: k for k in eigene}
    texte: list[str] = []

    sortiert = sorted(empfehlung.beitraege.items(), key=lambda kv: kv[1], reverse=True)
    if sortiert:
        traeger, wert = sortiert[0]
        texte.append(
            f"**{traeger}** traegt die Auswahl am staerksten (Beitrag {wert:+.2f}) -- "
            "gegen dieses gegnerische Team der verlaesslichste Angriffspunkt."
        )
        schwaechster, schwach_wert = sortiert[-1]
        if schwach_wert < 0 and len(sortiert) > 1:
            texte.append(
                f"**{schwaechster}** ist der Schwachpunkt der Auswahl "
                f"(Beitrag {schwach_wert:+.2f}). Falls du eine Alternative hast, "
                "ist das der Platz zum Tauschen."
            )

    schneller = [
        k.name for k in eigene if k.name in empfehlung.auswahl
        and sum(1 for g in gegner if k.speed > g.speed) >= len(gegner) / 2
    ]
    if schneller:
        texte.append(
            "Initiative: " + ", ".join(schneller) +
            f" {'handeln' if len(schneller) > 1 else 'handelt'} gegen die Mehrheit "
            "des gegnerischen Teams zuerst."
        )
    else:
        texte.append(
            "Initiative: keines der ausgewaehlten Pokemon ist gegen die Mehrheit des "
            "gegnerischen Teams schneller. Ohne Rueckenwind oder Bizarroraum handelst "
            "du meist als Zweiter."
        )

    if empfehlung.riskanteste_gegnerauswahl:
        namen = ", ".join(empfehlung.riskanteste_gegnerauswahl)
        texte.append(
            f"Achte auf die gegnerische Auswahl **{namen}** -- gegen sie faellt die "
            f"Bewertung auf {empfehlung.schlechtester_fall:+.2f} und damit am tiefsten."
        )

    fehlend = [k.name for k in eigene if k.name in empfehlung.auswahl
               and not nach_name[k.name].attacken]
    if fehlend:
        texte.append(
            "Hinweis: fuer " + ", ".join(fehlend) + " liegen keine belastbaren "
            "Attackendaten vor. Die Bewertung stuetzt sich dort nur auf Typen und "
            "Statuswerte und ist entsprechend unsicherer."
        )

    return texte
