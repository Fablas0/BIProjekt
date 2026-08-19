"""Hypothesenkatalog und dessen Pruefung.

Warum ueberhaupt Hypothesen
---------------------------
Ein Dashboard zeigt, *was* der Fall ist. Es beantwortet nicht, ob das Gezeigte
mehr ist als Rauschen. Bei 235 Pokemon, zwei Kampfformaten und sechzehn
Tagesstaenden findet das Auge in jeder Grafik ein Muster -- die Frage ist, ob es
auch eines ist.

Der Katalog macht daraus eine pruefbare Aussage. Jede Hypothese ist **vor** dem
Blick in die Daten formuliert, benennt Null- und Alternativhypothese, das
Verfahren und die Datenbasis. Geprueft wird gegen ein Signifikanzniveau von
5 Prozent, familienweise korrigiert nach Holm-Bonferroni.

Aufbau einer Hypothese
----------------------
======================  ==============================================
Feld                    Inhalt
======================  ==============================================
``titel``               die Frage, die die Hypothese beantwortet
``art``                 Erkenntnis oder Datenprobe (siehe unten)
``anwendungsfall``      welche Entscheidung am Ergebnis haengt
``nullhypothese``       die Aussage, die widerlegt werden soll
``alternativhypothese`` was gilt, wenn die Nullhypothese faellt
``begruendung``         warum die Frage fachlich zaehlt
``verfahren``           welches Verfahren und warum dieses
``datenbasis``          welche Quelle, welche Tabelle, welcher Umfang
======================  ==============================================

Zwei Arten von Hypothesen
-------------------------
Der Katalog enthaelt zwei Arten, und der Unterschied gehoert ausgewiesen,
weil sie sonst gegeneinander abfaerben:

* **Erkenntnis** -- das Ergebnis ist offen; die Antwort aendert eine
  Entscheidung beim Teambau, im Scouting oder im Betrieb.
* **Datenprobe** -- das erwartete Ergebnis steht durch die Spielregeln
  fest ("Flaechenattacken gehoeren in den Doppelkampf"). Genau deshalb
  taugt die Pruefung als Known-Answer-Test: bleibt der zwingende Effekt
  aus, liegt der Fehler in der eigenen Datenkette, nicht im Spiel. Eine
  Datenprobe, die anschlaegt, ist der Beleg, dass die uebrigen
  Auswertungen auf einer tragfaehigen Verarbeitung stehen.

Ohne diese Trennung wirkte eine Datenprobe wie eine banale Erkenntnis
("natuerlich sind das zwei Formate") -- ihr Wert liegt aber nicht in der
Antwort, sondern darin, dass die Datenverarbeitung die bekannte Antwort
reproduziert.

Drei Grundsaetze
----------------
1. **Das Messniveau bestimmt das Verfahren.** Die Nutzung liegt als Rang vor,
   also kommen ausschliesslich verteilungsfreie Verfahren zum Einsatz.
2. **Kein p-Wert ohne Effektstaerke.** Bei dieser Fallzahl wird fast jeder
   Unterschied signifikant. Erst die Effektstaerke sagt, ob er zaehlt.
3. **Fehlende Datenbasis ist ein eigenes Ergebnis.** Eine Hypothese, deren
   Quelle nicht geladen ist, wird als *nicht pruefbar* ausgewiesen und nicht
   stillschweigend als "nicht verworfen" gezaehlt. Sie geht auch nicht in die
   Holm-Korrektur ein, weil sie die Familie sonst kuenstlich vergroessern und
   die uebrigen Hypothesen unnoetig streng pruefen wuerde.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pandas as pd

from ..config import ALPHA, STANDARD_KAMPFFORMAT
from . import kpi, saison
from .pruefverfahren import (
    DatenbasisFehlt,
    Pruefgroesse,
    chi_quadrat_unabhaengigkeit,
    holm_bonferroni,
    holm_schranken,
    kruskal_wallis,
    mann_whitney,
    spearman,
)

# --------------------------------------------------------------------------
# Datenmodell
# --------------------------------------------------------------------------

# Themenbereiche des Katalogs. Sie gliedern die Ausgabe und machen sichtbar,
# welche Quelle eine Hypothese traegt.
BEREICH_VGC = "Wettkampf-Metagame (Pokemon Champions)"
BEREICH_STAMM = "Stammdaten der Hauptspiele (PokeAPI)"
BEREICH_QUELLEN = "Quellenvergleich ueber die Spielformen"
BEREICH_MAERKTE = "Laender- und Marktvergleich"

# Die zwei Arten einer Hypothese (siehe Moduldocstring). Eine Datenprobe traegt
# ein durch die Spielregeln festgelegtes Soll-Ergebnis und prueft damit die
# eigene Verarbeitung; eine Erkenntnisfrage ist ergebnisoffen.
ART_ERKENNTNIS = "erkenntnis"
ART_DATENPROBE = "datenprobe"


@dataclass(frozen=True)
class Hypothese:
    """Eine vor der Auswertung formulierte, pruefbare Aussage."""

    schluessel: str
    titel: str
    bereich: str
    nullhypothese: str
    alternativhypothese: str
    begruendung: str
    verfahren: str
    datenbasis: str
    berechnung: Callable[[sqlite3.Connection], Pruefgroesse]
    # Welche Entscheidung am Ergebnis haengt -- aus Sicht dessen, der die
    # Anwendung benutzt. Eine Hypothese ohne Abnehmer ihres Ergebnisses
    # gehoert nicht in den Katalog.
    anwendungsfall: str = ""
    # Erkenntnisfrage oder Datenprobe (Known-Answer-Test der Datenkette).
    art: str = ART_ERKENNTNIS
    # Formulierung des Befunds. Beide Faelle stehen im Katalog, damit die
    # Auslegung nicht erst nach Blick auf das Ergebnis entsteht.
    bei_verwerfung: str = ""
    bei_beibehaltung: str = ""
    # Was das Ergebnis nicht hergibt. Steht im Katalog und nicht in einer
    # Fussnote: eine Einschraenkung, die erst nach dem Ergebnis formuliert
    # wird, ist keine Einschraenkung mehr, sondern eine Ausrede.
    einschraenkung: str = ""


@dataclass
class HypothesenErgebnis:
    """Ergebnis einer geprueften Hypothese."""

    hypothese: Hypothese
    pruefgroesse: Pruefgroesse | None = None
    verworfen: bool = False
    schranke: float = ALPHA
    hinweis: str = ""

    @property
    def pruefbar(self) -> bool:
        return self.pruefgroesse is not None

    @property
    def status(self) -> str:
        if not self.pruefbar:
            return "nicht pruefbar"
        return "H0 verworfen" if self.verworfen else "H0 beibehalten"

    @property
    def befund(self) -> str:
        """Der Befund in einem Satz -- die Formulierung stammt aus dem Katalog."""
        if not self.pruefbar:
            return f"Nicht pruefbar: {self.hinweis}"
        return (self.hypothese.bei_verwerfung if self.verworfen
                else self.hypothese.bei_beibehaltung)


# --------------------------------------------------------------------------
# Datenzugriff
# --------------------------------------------------------------------------

def _lese(conn: sqlite3.Connection, sql: str, parameter: tuple = ()) -> pd.DataFrame:
    """Leseabfrage, auf die gewaehlte Saison eingeschraenkt."""
    return pd.read_sql(saison.anwenden(sql, conn), conn, params=parameter)


def _rangliste(conn: sqlite3.Connection, kampfformat: str,
               tag: str | None = None) -> pd.DataFrame:
    """Rangliste eines Tages mit den Stammdatenmerkmalen des Pokemon."""
    tag = tag or kpi.aktueller_tag(conn, kampfformat)
    if not tag:
        raise DatenbasisFehlt("Es liegen keine Bewegungsdaten vor.")
    df = _lese(conn, """
        SELECT anzeigename, slug, rang, rang_perzentil, typ1, typ2, generation,
               basiswert_summe, offensiv_profil, rolle, speed_klasse,
               stufe50_speed, stufe50_hp, stufe50_attack, stufe50_sp_attack
        FROM V_Usage
        WHERE datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
    """, (tag, kampfformat))
    if df.empty:
        raise DatenbasisFehlt(f"Keine Rangliste fuer {kampfformat} am {tag}.")
    return df


def _merkmalsanteile(conn: sqlite3.Connection, kategorie: str, kampfformat: str,
                     tag: str | None = None) -> pd.DataFrame:
    """Merkmalssaetze einer Kategorie fuer einen Tag."""
    tag = tag or kpi.aktueller_tag(conn, kampfformat)
    if not tag:
        raise DatenbasisFehlt("Es liegen keine Bewegungsdaten vor.")
    return _lese(conn, """
        SELECT anzeigename, bezeichnung, anteil, rang, zielbereich, attacke_typ,
               taktik_klasse
        FROM V_Merkmal
        WHERE kategorie = ? AND datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
    """, (kategorie, tag, kampfformat))


# --------------------------------------------------------------------------
# Die einzelnen Pruefungen
# --------------------------------------------------------------------------

def _pruefe_drift(conn: sqlite3.Connection) -> Pruefgroesse:
    """Nimmt die Uebereinstimmung zweier Tagesranglisten mit deren Abstand ab?

    Aus 16 Tagen entstehen 120 Tagespaare. Zu jedem Paar wird die Spearman-
    Rangkorrelation der beiden Ranglisten gebildet und gegen den zeitlichen
    Abstand in Tagen gestellt. Sinkt die Uebereinstimmung mit wachsendem
    Abstand, bewegt sich das Format gerichtet -- es driftet. Bleibt sie
    unabhaengig vom Abstand, schwankt es nur um einen festen Zustand.

    Das ist der Grund, warum hier nicht einfach zwei Tage verglichen werden:
    ein einzelnes Paar kann beides bedeuten.
    """
    tage = kpi.verfuegbare_tage(conn, STANDARD_KAMPFFORMAT)
    if len(tage) < 6:
        raise DatenbasisFehlt(
            f"Fuer die Driftpruefung sind mindestens 6 Tage noetig, geladen sind {len(tage)}.")

    abstaende: list[float] = []
    uebereinstimmung: list[float] = []
    for i, tag_a in enumerate(tage):
        for tag_b in tage[i + 1:]:
            rho = kpi.meta_stabilitaet(conn, tag_a, tag_b, STANDARD_KAMPFFORMAT)
            if rho is None:
                continue
            abstaende.append(
                (pd.Timestamp(tag_b) - pd.Timestamp(tag_a)).days)
            uebereinstimmung.append(rho)

    return spearman(abstaende, uebereinstimmung)


def _pruefe_initiative(conn: sqlite3.Connection) -> Pruefgroesse:
    """Haengt der Nutzungsrang mit der Initiative zusammen?

    Verglichen wird der Rang mit der Initiative auf Turnierstufe 50 ohne
    Investition -- also mit der Anlage des Pokemon, nicht mit dem gespielten
    Set. Damit misst der Test die Eigenschaft des Pokemon und nicht die
    Entscheidung des Spielers.

    Ein kleiner Rang ist der bessere. Ein negativer Zusammenhang bedeutet
    demnach: schnellere Pokemon stehen weiter oben.
    """
    df = _rangliste(conn, STANDARD_KAMPFFORMAT)
    return spearman(df["stufe50_speed"].tolist(), df["rang"].tolist())


def _pruefe_basiswerte(conn: sqlite3.Connection) -> Pruefgroesse:
    """Haengt der Nutzungsrang mit der Basiswertsumme zusammen?

    Die Gegenprobe zur Initiative: waere allein die Rohstaerke entscheidend,
    muesste die Basiswertsumme den Rang bestimmen. Ein nur schwacher
    Zusammenhang spraeche dafuer, dass das Format ueber Rollen und Typen
    entschieden wird und nicht ueber die Summe der Werte.
    """
    df = _rangliste(conn, STANDARD_KAMPFFORMAT)
    return spearman(df["basiswert_summe"].tolist(), df["rang"].tolist())


def _pruefe_formatunterschied(conn: sqlite3.Connection) -> Pruefgroesse:
    """Sortieren Einzel- und Doppelkampf dasselbe Feld gleich?

    Beide Formate greifen auf denselben Pokemon-Bestand zu. Waeren sie
    fachlich austauschbar, muesste die Rangfolge weitgehend uebereinstimmen.
    Die Effektstaerke ist hier wichtiger als der p-Wert: dass ueberhaupt ein
    Zusammenhang besteht, ist zu erwarten -- interessant ist, wie weit er von
    der vollstaendigen Uebereinstimmung entfernt bleibt.
    """
    doubles = _rangliste(conn, "Doubles")[["anzeigename", "rang"]]
    singles = _rangliste(conn, "Singles")[["anzeigename", "rang"]]
    gemeinsam = doubles.merge(singles, on="anzeigename", suffixes=("_d", "_s"))
    if len(gemeinsam) < 20:
        raise DatenbasisFehlt("Zu wenige in beiden Formaten erfasste Pokemon.")
    return spearman(gemeinsam["rang_d"].tolist(), gemeinsam["rang_s"].tolist())


def _pruefe_flaechenattacken(conn: sqlite3.Connection) -> Pruefgroesse:
    """Werden im Doppelkampf mehr Flaechenattacken gespielt?

    Im Doppelkampf stehen zwei gegnerische Pokemon auf dem Feld; eine Attacke
    mit Zielbereich *all-opponents* trifft beide. Im Einzelkampf ist derselbe
    Zielbereich wertlos. Die Erwartung ist also fachlich klar -- und genau
    deshalb ist die Hypothese wertvoll: bestaetigt sie sich, zeigt das, dass
    die Kette aus Champions-Merkmalen und PokeAPI-Attackenstammdaten die
    Spielrealitaet korrekt abbildet.

    Verglichen wird je Pokemon die Summe der Anteile aller Attacken mit
    Flaechenwirkung -- ein Wert zwischen 0 und 400, weil vier Attackenplaetze
    zur Verfuegung stehen.
    """
    def anteil_flaeche(kampfformat: str) -> list[float]:
        df = _merkmalsanteile(conn, "move", kampfformat)
        if df.empty:
            raise DatenbasisFehlt("Keine Attackenmerkmale geladen.")
        flaeche = df[df["zielbereich"].isin(["all-opponents", "all-other-pokemon"])]
        je_pokemon = flaeche.groupby("anzeigename")["anteil"].sum()
        # Pokemon ohne Flaechenattacke tragen den Wert null und duerfen nicht
        # herausfallen -- sonst waere der Vergleich auf beiden Seiten verzerrt.
        alle = df["anzeigename"].drop_duplicates()
        return je_pokemon.reindex(alle, fill_value=0.0).tolist()

    return mann_whitney(anteil_flaeche("Doubles"), anteil_flaeche("Singles"))


def _pruefe_typenverteilung(conn: sqlite3.Connection) -> Pruefgroesse:
    """Haengt der Nutzungsrang vom Primaertyp ab?

    Naheliegend waere ein Chi-Quadrat-Anpassungstest gewesen: Typenverteilung
    der besten 50 gegen die des Gesamtfeldes. Er scheitert an der eigenen
    Voraussetzung -- bei 18 Typen und 50 Plaetzen liegt die erwartete
    Haeufigkeit in 17 von 18 Klassen unter fuenf, und damit ist die
    Chi-Quadrat-Approximation nicht mehr belastbar. Die Pruefung wuerde einen
    Wert liefern, den man nicht verwenden darf.

    Statt die Klassen zusammenzulegen, bis die Faustregel erfuellt ist -- was
    die Aussage verwaessert --, wird die Frage auf dem Messniveau der Daten
    gestellt: nicht "wie viele stehen oben?", sondern "wie stehen sie?". Der
    Kruskal-Wallis-Test vergleicht die Rangverteilung aller 18 Typgruppen
    gleichzeitig und nutzt dabei jedes Pokemon, nicht nur die Spitzengruppe.

    Typen mit weniger als fuenf Vertretern bleiben aussen vor: eine Gruppe aus
    zwei Pokemon traegt keine Verteilung.
    """
    df = _rangliste(conn, STANDARD_KAMPFFORMAT)
    gruppen = [
        teil["rang"].tolist()
        for _, teil in df.groupby("typ1")
        if len(teil) >= 5
    ]
    return kruskal_wallis(gruppen)


def _pruefe_vorhersagbarkeit(conn: sqlite3.Connection) -> Pruefgroesse:
    """Sind die Sets haeufig gespielter Pokemon festgelegter?

    Gemessen wird die Konzentration der Attackenanteile eines Pokemon ueber den
    Herfindahl-Index. Auf dieser Ebene liefert die Quelle echte Anteile, der
    Index ist hier also zulaessig -- anders als auf der Rangebene.

    Fachlich zaehlt die Frage im Team-Preview: ist bei einem verbreiteten
    Pokemon eher absehbar, was es traegt, oder gerade nicht?
    """
    df = _merkmalsanteile(conn, "move", STANDARD_KAMPFFORMAT)
    if df.empty:
        raise DatenbasisFehlt("Keine Attackenmerkmale geladen.")

    konzentration = df.groupby("anzeigename")["anteil"].apply(kpi.herfindahl)
    rangliste = _rangliste(conn, STANDARD_KAMPFFORMAT).set_index("anzeigename")["rang"]
    gemeinsam = pd.concat([konzentration.rename("hhi"), rangliste], axis=1).dropna()
    return spearman(gemeinsam["rang"].tolist(), gemeinsam["hhi"].tolist())


def _pruefe_itemwahl(conn: sqlite3.Connection) -> Pruefgroesse:
    """Haengt die Itemwahl vom Offensivprofil des Pokemon ab?

    Kreuztabelle aus dem angereicherten Offensivprofil (physisch, speziell,
    gemischt) und dem am haeufigsten getragenen Item. Beide Merkmale sind
    nominal, also ist der Chi-Quadrat-Test das Mittel der Wahl.

    Die Hypothese verbindet zwei Quellen: das Profil stammt aus den Basiswerten
    der PokeAPI, das Item aus den Champions-Bewegungsdaten. Bestaetigt sie
    sich, ist die Verknuepfung beider Quellen fachlich tragfaehig.

    Betrachtet werden nur Items mit mindestens zehn Traegern; seltene Items
    wuerden die erwarteten Haeufigkeiten unter die Belastbarkeitsgrenze der
    Approximation druecken.
    """
    items = _merkmalsanteile(conn, "held_item", STANDARD_KAMPFFORMAT)
    items = items[items["rang"] == 1][["anzeigename", "bezeichnung"]]
    profile = _rangliste(conn, STANDARD_KAMPFFORMAT)[["anzeigename", "offensiv_profil"]]
    gemeinsam = items.merge(profile, on="anzeigename")
    if gemeinsam.empty:
        raise DatenbasisFehlt("Keine Itemmerkmale geladen.")

    haeufig = gemeinsam["bezeichnung"].value_counts()
    haeufig = haeufig[haeufig >= 10].index
    gemeinsam = gemeinsam[gemeinsam["bezeichnung"].isin(haeufig)]

    kreuz = pd.crosstab(gemeinsam["offensiv_profil"], gemeinsam["bezeichnung"])
    if kreuz.empty:
        raise DatenbasisFehlt("Zu wenige Traeger je Item fuer eine belastbare Pruefung.")
    return chi_quadrat_unabhaengigkeit(kreuz.values.tolist())


def _pruefe_bizarroraum(conn: sqlite3.Connection) -> Pruefgroesse:
    """Sind Traeger von Bizarroraum langsamer als das uebrige Feld?

    *Bizarroraum* kehrt die Initiative fuer fuenf Runden um: die langsamsten
    Pokemon handeln zuerst. Ein Team, das die Attacke spielt, sollte deshalb
    aus langsamen Angreifern bestehen.

    Die Hypothese prueft eine Strategie, nicht eine Eigenschaft -- und sie
    prueft zugleich die im ETL angereicherte Taktik-Klasse der Attacke: nur
    wenn die Zuordnung stimmt, kann der Unterschied sichtbar werden.
    """
    attacken = _merkmalsanteile(conn, "move", STANDARD_KAMPFFORMAT)
    if attacken.empty:
        raise DatenbasisFehlt("Keine Attackenmerkmale geladen.")

    setzer = set(attacken.loc[attacken["taktik_klasse"] == "Bizarroraum", "anzeigename"])
    df = _rangliste(conn, STANDARD_KAMPFFORMAT)
    mit = df.loc[df["anzeigename"].isin(setzer), "stufe50_speed"].tolist()
    ohne = df.loc[~df["anzeigename"].isin(setzer), "stufe50_speed"].tolist()
    return mann_whitney(mit, ohne)


def _pruefe_wochenende(conn: sqlite3.Connection) -> Pruefgroesse:
    """Bewegt sich das Metagame am Wochenende staerker?

    Am Wochenende spielen mehr Gelegenheitsspieler; zugleich finden Turniere
    statt. Beides koennte die Rangfolge staerker durchruetteln als unter der
    Woche. Betrachtet wird je Pokemon und Tag der Betrag der Rangaenderung
    gegenueber dem Vortag, gruppiert nach Wochentag.

    Betriebliche Bedeutung: faellt der Unterschied deutlich aus, ist ein
    Wochenendstand keine geeignete Grundlage fuer die Turniervorbereitung
    unter der Woche.
    """
    df = _lese(conn, """
        SELECT anzeigename, datum_iso, wochentag, rang
        FROM V_Usage
        WHERE kampfformat = ? AND saison_aktuell = 1
        ORDER BY anzeigename, datum_iso
    """, (STANDARD_KAMPFFORMAT,))
    if df.empty:
        raise DatenbasisFehlt("Keine Bewegungsdaten geladen.")

    df["aenderung"] = df.groupby("anzeigename")["rang"].diff().abs()
    df = df.dropna(subset=["aenderung"])
    wochenende = df.loc[df["wochentag"].isin(["Samstag", "Sonntag"]), "aenderung"].tolist()
    woche = df.loc[~df["wochentag"].isin(["Samstag", "Sonntag"]), "aenderung"].tolist()
    return mann_whitney(wochenende, woche)


def _pruefe_laender(conn: sqlite3.Connection) -> Pruefgroesse:
    """Spielen die Regionen im Sammelkartenspiel verschiedene Decks?

    Kreuztabelle aus Region und Deck-Archetyp, gezaehlt in Spielern. Die
    Kennzahl ist kardinal -- die Quelle zaehlt Personen, keine Raenge -- und
    beide Merkmale sind nominal: der Chi-Quadrat-Unabhaengigkeitstest passt.

    Zwei Zuschnitte halten die Approximation belastbar: gruppiert wird nach
    **Region** statt nach Land (einzelne Laender sind zu duenn besetzt), und
    betrachtet werden nur die zehn meistgespielten Archetypen; alles Weitere
    faellt in eine Restklasse, statt verworfen zu werden.
    """
    df = pd.read_sql("""
        SELECT region, deck_name, SUM(spieler) AS spieler
        FROM V_TCG_Meta GROUP BY region, deck_name
    """, conn)
    if df.empty:
        raise DatenbasisFehlt("Keine TCG-Turnierdaten geladen. Die Strecke braucht "
                              "einen API-Schluessel (VGC_BI_TCG_SCHLUESSEL).")

    haeufigste = (df.groupby("deck_name")["spieler"].sum()
                  .nlargest(10).index)
    df["klasse"] = df["deck_name"].where(df["deck_name"].isin(haeufigste), "Uebrige Decks")
    kreuz = df.pivot_table(index="region", columns="klasse", values="spieler",
                           aggfunc="sum", fill_value=0)
    kreuz = kreuz.loc[kreuz.sum(axis=1) >= 30]
    if len(kreuz) < 2:
        raise DatenbasisFehlt("Weniger als zwei ausreichend besetzte Regionen.")
    return chi_quadrat_unabhaengigkeit(kreuz.values.tolist())


def _pruefe_go_ligen(conn: sqlite3.Connection) -> Pruefgroesse:
    """Ist die GO-Meta zwischen Super- und Meisterliga dieselbe?

    Dieselben Pokemon, andere Wettkampfpunkte-Grenze: die Superliga deckelt
    bei 1500, die Meisterliga ist offen. Verglichen werden die Scores der in
    beiden Ligen gefuehrten Pokemon per Rangkorrelation -- die Scores sind
    zwar kardinal, aber zwischen zwei verschieden kalibrierten Ranglisten ist
    nur die Reihenfolge vergleichbar, nicht die Zahl.
    """
    df = pd.read_sql("""
        SELECT g.quell_id, g.score AS score_great, m.score AS score_master
        FROM V_GO_Meta g
        JOIN V_GO_Meta m ON m.quell_id = g.quell_id AND m.zeit_sk = g.zeit_sk
        WHERE g.liga = 'great' AND m.liga = 'master'
          AND g.zeit_sk = (SELECT MAX(zeit_sk) FROM Fact_GO_Meta)
    """, conn)
    if len(df) < 20:
        raise DatenbasisFehlt(
            f"Nur {len(df)} Pokemon in beiden GO-Ligen gefuehrt (mindestens 20).")
    return spearman(df["score_great"].tolist(), df["score_master"].tolist())


def _pruefe_spieluebergreifend(conn: sqlite3.Connection) -> Pruefgroesse:
    """Ist ein starkes VGC-Pokemon auch in Pokemon GO stark?

    Die Bruecke ist die konforme Pokemon-Dimension: beide Fakten zeigen ueber
    den Slug auf dieselben Pokemon. Verglichen wird der Champions-Rang mit dem
    GO-Score der Meisterliga -- sie laesst als einzige Liga alle Pokemon ohne
    Wertedeckel zu und ist damit die fairste Gegenseite.

    Ein kleiner Rang ist der bessere, ein grosser Score der bessere: ein
    **negativer** Koeffizient bedeutet also, dass Staerke sich uebertraegt.
    """
    df = pd.read_sql(saison.anwenden("""
        SELECT u.rang, g.score
        FROM V_Usage_Aktuell u
        JOIN V_GO_Meta g ON g.slug = u.slug
        WHERE u.kampfformat = ? AND g.liga = 'master' AND g.ist_schatten = 0
          AND g.zeit_sk = (SELECT MAX(zeit_sk) FROM Fact_GO_Meta)
    """, conn), conn, params=(STANDARD_KAMPFFORMAT,))
    if len(df) < 20:
        raise DatenbasisFehlt(
            f"Nur {len(df)} Pokemon in beiden Spielen gefuehrt (mindestens 20).")
    return spearman(df["rang"].tolist(), df["score"].tolist())


# --------------------------------------------------------------------------
# Der Katalog
# --------------------------------------------------------------------------

KATALOG: list[Hypothese] = [
    Hypothese(
        schluessel="H1",
        titel="Wie schnell veraltet ein Tagesstand?",
        bereich=BEREICH_VGC,
        anwendungsfall="Wer sich heute auf ein Turnier am Wochenende vorbereitet, "
                       "muss wissen, ob die Auswertung von letzter Woche noch "
                       "traegt oder ob nur der juengste Stand zaehlt.",
        nullhypothese="Die Uebereinstimmung zweier Tagesranglisten haengt nicht "
                      "vom zeitlichen Abstand der beiden Tage ab.",
        alternativhypothese="Mit wachsendem Abstand nimmt die Uebereinstimmung ab.",
        begruendung="Entscheidet darueber, wie alt eine Auswertung sein darf. Schwankt "
                    "das Format nur, ist ein zwei Wochen alter Stand so gut wie der "
                    "heutige. Driftet es, ist er es nicht -- und das Archiv wird vom "
                    "Selbstzweck zur Voraussetzung.",
        verfahren="Spearman-Rangkorrelation zwischen dem Abstand zweier Tage und der "
                  "Rangkorrelation ihrer Ranglisten. Ein Verfahren fuer Rangdaten auf "
                  "einer Groesse, die selbst aus Raengen entsteht.",
        datenbasis="Pokemon Champions, alle geladenen Tage im Doppelkampf, "
                   "je Paar eine Rangkorrelation ueber rund 235 Pokemon.",
        berechnung=_pruefe_drift,
        bei_verwerfung="Das Format driftet: je weiter zwei Tage auseinanderliegen, "
                       "desto weniger stimmen ihre Ranglisten ueberein. Ein alter "
                       "Stand veraltet also nicht nur gefuehlt.",
        bei_beibehaltung="Kein Zusammenhang zwischen Abstand und Uebereinstimmung: "
                         "das Format schwankt um einen festen Zustand, statt sich "
                         "gerichtet zu bewegen.",
        einschraenkung="Die 120 Tagespaare stammen aus 16 Tagen und sind daher "
                       "nicht unabhaengig voneinander -- jeder Tag geht in 15 Paare "
                       "ein. Der p-Wert faellt dadurch zu klein aus. Die Aussage "
                       "stuetzt sich deshalb auf die Effektstaerke; sie ist von der "
                       "Abhaengigkeit nicht betroffen.",
    ),
    Hypothese(
        schluessel="H2",
        titel="Lohnt es, beim Teambau auf Initiative zu setzen?",
        bereich=BEREICH_VGC,
        anwendungsfall="Beim Teambau: ob Initiative ein eigenstaendiges "
                       "Auswahlkriterium ist -- und ob die Speed-Tiers-Seite zu "
                       "Recht eine eigene Seite bekommen hat.",
        nullhypothese="Zwischen der Initiative eines Pokemon und seinem Nutzungsrang "
                      "besteht kein Zusammenhang.",
        alternativhypothese="Schnellere Pokemon erreichen bessere Raenge.",
        begruendung="Wer zuerst handelt, entscheidet den Schlagabtausch -- so die "
                    "gaengige Lehrmeinung des Formats. Sie ist bisher nie an den "
                    "Daten geprueft worden.",
        verfahren="Spearman-Rangkorrelation zwischen Initiative auf Turnierstufe 50 "
                  "und Nutzungsrang. Der Rang ist ordinal, damit scheidet die "
                  "Pearson-Korrelation aus.",
        datenbasis="Nutzungsraenge des juengsten Tages (Doppelkampf) verknuepft mit "
                   "den Basiswerten der PokeAPI.",
        berechnung=_pruefe_initiative,
        bei_verwerfung="Initiative und Rang haengen zusammen; die Lehrmeinung des "
                       "Formats haelt der Pruefung stand.",
        bei_beibehaltung="Kein belastbarer Zusammenhang: Initiative allein erklaert "
                         "die Nutzung nicht.",
        einschraenkung="Betrachtet wird ein einzelner Tagesstand. Die Initiative "
                       "ohne Investition ist zudem nicht die gespielte: ein "
                       "Wahlschal verdoppelt sie, Statuspunkte heben sie an. Die "
                       "tatsaechlich gespielten Werte wertet die Seite Speed-Tiers "
                       "aus.",
    ),
    Hypothese(
        schluessel="H3",
        titel="Genuegt es, die Pokemon mit den hoechsten Werten zu spielen?",
        bereich=BEREICH_VGC,
        anwendungsfall="Beim Teambau: faellt die Antwort ja aus, ersetzt eine nach "
                       "Basiswertsumme sortierte Liste den Team-Builder. Faellt sie "
                       "nein aus, entscheiden Rollen und Typen -- und genau dafuer "
                       "gibt es die Analyse.",
        nullhypothese="Zwischen der Basiswertsumme und dem Nutzungsrang besteht "
                      "kein Zusammenhang.",
        alternativhypothese="Pokemon mit hoeherer Basiswertsumme erreichen bessere Raenge.",
        begruendung="Die Gegenprobe zu H2. Waere das Format allein eine Frage der "
                    "Rohwerte, braeuchte es keine Analyse -- eine nach Basiswertsumme "
                    "sortierte Liste genuegte. Die Effektstaerke sagt, wie viel "
                    "Spielraum daneben bleibt.",
        verfahren="Spearman-Rangkorrelation zwischen Basiswertsumme und Nutzungsrang.",
        datenbasis="Nutzungsraenge des juengsten Tages (Doppelkampf) verknuepft mit "
                   "den Basiswerten der PokeAPI.",
        berechnung=_pruefe_basiswerte,
        bei_verwerfung="Basiswertsumme und Rang haengen zusammen -- entscheidend ist "
                       "jedoch die Effektstaerke im Vergleich zu H2.",
        bei_beibehaltung="Die Rohstaerke erklaert den Rang nicht; das Format wird "
                         "ueber Rollen und Typen entschieden.",
    ),
    Hypothese(
        schluessel="H4",
        titel="Wie viel Doppelkampf-Wissen traegt im Einzelkampf?",
        bereich=BEREICH_VGC,
        anwendungsfall="Wer beide Formate spielt: ob die Vorbereitung uebertragbar "
                       "ist oder je Format neu ansetzt. Die Antwort steckt nicht im "
                       "Ob des Zusammenhangs, sondern im Wie-weit -- dem Abstand "
                       "des Koeffizienten zu eins.",
        nullhypothese="Zwischen den Rangfolgen im Einzel- und im Doppelkampf besteht "
                      "kein Zusammenhang.",
        alternativhypothese="Die Rangfolgen haengen zusammen, stimmen aber nicht ueberein.",
        begruendung="Dass beide Formate irgendwie zusammenhaengen, ist zu erwarten "
                    "-- interessant ist die Groesse des eigenstaendigen Anteils. "
                    "Er beziffert, wie viel Vorbereitung sich uebertragen laesst, "
                    "und rechtfertigt zugleich eine Grundentscheidung des "
                    "Datenmodells: das Kampfformat als eigene Dimension.",
        verfahren="Spearman-Rangkorrelation der paarweise zugeordneten Raenge. Die "
                  "Effektstaerke traegt hier die Aussage, nicht der p-Wert.",
        datenbasis="Juengster Tag, beide Kampfformate, rund 235 gemeinsame Pokemon.",
        berechnung=_pruefe_formatunterschied,
        bei_verwerfung="Die Formate haengen zusammen, ohne deckungsgleich zu sein. "
                       "Der Abstand zur vollstaendigen Uebereinstimmung ist der "
                       "eigenstaendige Anteil des jeweiligen Formats -- dieser Teil "
                       "der Vorbereitung ist je Format neu zu leisten.",
        bei_beibehaltung="Kein nachweisbarer Zusammenhang zwischen den Formaten.",
        einschraenkung="Ein Zusammenhang ist bei gemeinsamer Grundgesamtheit zu "
                       "erwarten; die Nullhypothese ist hier bewusst schwach. Die "
                       "Aussage liegt im Abstand des Koeffizienten zu eins.",
    ),
    Hypothese(
        schluessel="H5",
        titel="Kommen die Spielregeln in der Datenkette an?",
        bereich=BEREICH_VGC,
        art=ART_DATENPROBE,
        anwendungsfall="Vertrauensgrundlage fuer alle Attackenauswertungen: dass "
                       "Flaechenattacken in den Doppelkampf gehoeren, weiss jeder -- "
                       "gerade deshalb muss dieser zwingende Effekt in den eigenen "
                       "Daten messbar sein. Bleibt er aus, ist die Verknuepfung von "
                       "Champions-Merkmalen und PokeAPI-Stammdaten defekt, und kein "
                       "Scouting-Bericht waere mehr belastbar.",
        nullhypothese="Der Anteil von Attacken mit Flaechenwirkung unterscheidet sich "
                      "zwischen Einzel- und Doppelkampf nicht.",
        alternativhypothese="Im Doppelkampf werden Flaechenattacken haeufiger gespielt.",
        begruendung="Eine Attacke mit Zielbereich *all-opponents* trifft im Doppelkampf "
                    "beide Gegner und im Einzelkampf nur einen. Die Erwartung ist "
                    "fachlich eindeutig -- und genau deshalb taugt die Hypothese als "
                    "Probe auf die Datenkette: sie verbindet Champions-Merkmale mit "
                    "Attackenstammdaten der PokeAPI.",
        verfahren="Mann-Whitney-U ueber die je Pokemon summierten Anteile der "
                  "Flaechenattacken. Die Verteilung ist stark rechtsschief, ein "
                  "Mittelwertvergleich waere irrefuehrend.",
        datenbasis="Merkmalsfakt (Kategorie *move*) des juengsten Tages, verknuepft "
                   "mit dem Zielbereich aus der Attacken-Dimension.",
        berechnung=_pruefe_flaechenattacken,
        bei_verwerfung="Der Zielbereich der Attacke schlaegt sich messbar im "
                       "Kampfformat nieder -- die Verknuepfung beider Quellen "
                       "bildet die Spielrealitaet ab.",
        bei_beibehaltung="Kein Unterschied nachweisbar -- was angesichts der "
                         "Spielregeln auf ein Problem in der Datenkette hindeutet.",
    ),
    Hypothese(
        schluessel="H6",
        titel="Lohnt es, die Defensive an der Meta auszurichten?",
        bereich=BEREICH_VGC,
        anwendungsfall="Beim Teambau mit dem Team-Builder: haengen die Raenge am "
                       "Typ, muss die Defensivbewertung mit der Meta-Praesenz "
                       "gewichtet werden. Haengen sie nicht daran, genuegte eine "
                       "ungewichtete Deckung aller 18 Typen.",
        nullhypothese="Die Nutzungsraenge verteilen sich ueber alle Primaertypen gleich.",
        alternativhypothese="Mindestens ein Typ steht systematisch besser oder "
                            "schlechter als die uebrigen.",
        begruendung="Traegt unmittelbar in den Team-Builder: nur wenn Typen "
                    "systematisch unterschiedlich abschneiden, lohnt es, das eigene "
                    "Defensivprofil an der Meta auszurichten statt an allen Typen "
                    "gleichermassen.",
        verfahren="Kruskal-Wallis-H ueber die Rangverteilung je Primaertyp. Der "
                  "naheliegende Chi-Quadrat-Anpassungstest auf der Spitzengruppe "
                  "scheitert an seiner eigenen Voraussetzung -- bei 18 Typen und 50 "
                  "Plaetzen liegen 17 erwartete Haeufigkeiten unter fuenf.",
        datenbasis="Alle am juengsten Tag im Doppelkampf erfassten Pokemon, gruppiert "
                   "nach Primaertyp; Typen mit weniger als fuenf Vertretern bleiben "
                   "aussen vor.",
        berechnung=_pruefe_typenverteilung,
        bei_verwerfung="Die Raenge haengen vom Primaertyp ab. Eine an der Meta "
                       "gewichtete Defensivbewertung ist damit begruendet.",
        bei_beibehaltung="Kein Typunterschied nachweisbar -- die Raenge verteilen "
                         "sich ueber die Typen wie zufaellig.",
        einschraenkung="Der Test sagt, *dass* sich mindestens ein Typ abhebt, nicht "
                       "welcher. Welche Typen die Spitze tragen, zeigt der "
                       "OLAP-Explorer entlang der Typhierarchie.",
    ),
    Hypothese(
        schluessel="H7",
        titel="Ist absehbar, was ein Top-Pokemon im Set traegt?",
        bereich=BEREICH_VGC,
        anwendungsfall="Im Team-Preview mit 60 Sekunden auf der Uhr: wie viel "
                       "Vertrauen der Scouting-Bericht verdient, wenn der Gegner "
                       "weit oben steht -- und wie viel Vorsicht bei einem "
                       "Aussenseiter geboten ist, dessen Set offener ist.",
        nullhypothese="Zwischen dem Nutzungsrang und der Konzentration der "
                      "Attackenanteile besteht kein Zusammenhang.",
        alternativhypothese="Je besser der Rang, desto konzentrierter die Attackenwahl.",
        begruendung="Im Team-Preview bleiben rund 60 Sekunden. Traegt die Hypothese, "
                    "ist bei verbreiteten Pokemon eher absehbar, was sie fuehren -- "
                    "und der Scouting-Bericht wird belastbarer, je haeufiger der "
                    "Gegner gespielt wird.",
        verfahren="Spearman-Rangkorrelation zwischen Rang und Herfindahl-Index der "
                  "Attackenanteile. Der Index setzt Anteile voraus; auf der "
                  "Merkmalsebene liefert die Quelle sie, auf der Rangebene nicht.",
        datenbasis="Merkmalsfakt (Kategorie *move*) des juengsten Tages im Doppelkampf.",
        berechnung=_pruefe_vorhersagbarkeit,
        bei_verwerfung="Rang und Vorhersagbarkeit haengen zusammen; das Vorzeichen "
                       "sagt, in welche Richtung.",
        bei_beibehaltung="Die Vorhersagbarkeit eines Sets haengt nicht vom Rang ab.",
    ),
    Hypothese(
        schluessel="H8",
        titel="Trifft das abgeleitete Offensivprofil etwas Reales?",
        bereich=BEREICH_VGC,
        art=ART_DATENPROBE,
        anwendungsfall="Absicherung einer Anreicherung, auf der Scouting und "
                       "Schadensrechner aufbauen: das Offensivprofil ist im ETL "
                       "aus Basiswerten errechnet. Nur wenn Spieler ihre Items "
                       "erkennbar danach waehlen, trifft die Rechenvorschrift eine "
                       "reale Unterscheidung -- sonst waeren alle darauf "
                       "gestuetzten Aussagen Zahlenspielerei.",
        nullhypothese="Das meistgetragene Item ist unabhaengig vom Offensivprofil "
                      "des Pokemon.",
        alternativhypothese="Physische und spezielle Angreifer tragen unterschiedliche Items.",
        begruendung="Prueft die Anreicherung selbst. Das Offensivprofil ist im ETL aus "
                    "den Basiswerten abgeleitet, das Item kommt aus der Bewegungsdaten"
                    "quelle. Ein Zusammenhang belegt, dass die abgeleitete Groesse "
                    "etwas Reales trifft und nicht bloss eine Rechenvorschrift ist.",
        verfahren="Chi-Quadrat-Unabhaengigkeitstest ueber die Kreuztabelle aus "
                  "Offensivprofil und meistgetragenem Item; beide Merkmale nominal.",
        datenbasis="Merkmalsfakt (Kategorie *held_item*, Rang 1) des juengsten Tages, "
                   "beschraenkt auf Items mit mindestens zehn Traegern.",
        berechnung=_pruefe_itemwahl,
        bei_verwerfung="Itemwahl und Offensivprofil haengen zusammen -- die im ETL "
                       "abgeleitete Klassifikation trifft eine reale Unterscheidung.",
        bei_beibehaltung="Kein Zusammenhang nachweisbar; das Offensivprofil erklaert "
                         "die Itemwahl nicht.",
    ),
    Hypothese(
        schluessel="H9",
        titel="Trennt die Taktik-Klasse wirklich Spielweisen?",
        bereich=BEREICH_VGC,
        art=ART_DATENPROBE,
        anwendungsfall="Absicherung des Strategie-Radars im Gegner-Scouting: dass "
                       "Bizarroraum-Teams langsam sind, folgt aus der Spielmechanik. "
                       "Findet die im ETL vergebene Taktik-Klasse diesen bekannten "
                       "Unterschied nicht wieder, markiert der Radar die falschen "
                       "Pokemon -- und die Warnung vor dem Bizarroraum-Team kaeme "
                       "im Team-Preview nicht an.",
        nullhypothese="Pokemon, die Bizarroraum im Set fuehren, unterscheiden sich in "
                      "ihrer Initiative nicht vom uebrigen Feld.",
        alternativhypothese="Sie sind langsamer als das uebrige Feld.",
        begruendung="Bizarroraum kehrt die Initiative um; ein Team, das darauf setzt, "
                    "muss langsam sein. Bestaetigt sich das, ist die im ETL vergebene "
                    "Taktik-Klasse einer Attacke mehr als eine Beschriftung -- sie "
                    "trennt Spielweisen.",
        verfahren="Mann-Whitney-U auf der Initiative beider Gruppen. Die Gruppen sind "
                  "unterschiedlich gross und nicht normalverteilt.",
        datenbasis="Merkmalsfakt (Kategorie *move*) des juengsten Tages, Taktik-Klasse "
                   "*Bizarroraum* aus der Attacken-Anreicherung.",
        berechnung=_pruefe_bizarroraum,
        bei_verwerfung="Die Traeger sind messbar langsamer -- die Taktik-Klasse "
                       "trennt tatsaechlich Spielweisen.",
        bei_beibehaltung="Kein Initiativeunterschied nachweisbar.",
    ),
    Hypothese(
        schluessel="H10",
        titel="Taugt der Sonntagsstand fuer die Vorbereitung am Montag?",
        bereich=BEREICH_VGC,
        anwendungsfall="Fuer Betrieb und Vorbereitung: ruettelt das Wochenende die "
                       "Rangliste staerker durch, ist der Berichtstag bei jeder "
                       "Auswertung mitzudenken -- und ein Montagsturnier besser auf "
                       "dem Freitagsstand vorzubereiten als auf dem Sonntag.",
        nullhypothese="Die taegliche Rangbewegung unterscheidet sich zwischen "
                      "Wochenend- und Wochentagen nicht.",
        alternativhypothese="An Wochenenden faellt die Rangbewegung staerker aus.",
        begruendung="Betrieblich unmittelbar bedeutsam: faellt der Unterschied "
                    "deutlich aus, taugt ein Wochenendstand nicht als Grundlage fuer "
                    "die Vorbereitung unter der Woche -- und der taegliche Ladelauf "
                    "ist nicht nur wegen der Vorhaltezeit noetig.",
        verfahren="Mann-Whitney-U ueber die Betraege der taeglichen Rangaenderungen.",
        datenbasis="Alle geladenen Tage im Doppelkampf; je Pokemon und Tag eine "
                   "Rangaenderung gegenueber dem Vortag.",
        berechnung=_pruefe_wochenende,
        bei_verwerfung="Die Rangbewegung haengt vom Wochentag ab; der Berichtstag ist "
                       "bei jeder Auswertung mitzudenken.",
        bei_beibehaltung="Kein Wochentagseffekt nachweisbar -- Tagesstaende sind "
                         "untereinander vergleichbar.",
        einschraenkung="Je Pokemon gehen mehrere Tage ein; die Beobachtungen sind "
                        "damit nicht unabhaengig. Bei 16 Tagen und vier "
                        "Wochenendtagen ist die Datenbasis ausserdem duenn -- die "
                        "Pruefung ist bei laengerer Zeitreihe zu wiederholen.",
    ),
    Hypothese(
        schluessel="H11",
        titel="Treffe ich in Japan auf ein anderes Feld als in Europa?",
        bereich=BEREICH_MAERKTE,
        anwendungsfall="Turniervorbereitung im Sammelkartenspiel: ob die globale "
                       "Meta-Sicht genuegt oder die Vorbereitung auf die Region "
                       "des Turnierorts zugeschnitten werden muss.",
        nullhypothese="Die Verteilung der Deck-Archetypen ist unabhaengig von der "
                      "Region des Spielers.",
        alternativhypothese="Mindestens eine Region bevorzugt andere Archetypen.",
        begruendung="Die Laenderfrage laesst sich nur im Sammelkartenspiel stellen: "
                    "allein diese Quelle liefert den Ort des Spielers mit. Traegt "
                    "die Hypothese, ist eine globale Meta-Betrachtung fuer die "
                    "Turniervorbereitung vor Ort zu grob -- wer in Japan spielt, "
                    "bereitet sich auf ein anderes Feld vor als in Europa.",
        verfahren="Chi-Quadrat-Unabhaengigkeitstest ueber die Kreuztabelle aus "
                  "Region und Archetyp, gezaehlt in Spielern. Die Kennzahl ist "
                  "kardinal (Personenzaehlung), beide Merkmale sind nominal.",
        datenbasis="Limitless-Turnierstandings, verdichtet auf Regionen und die "
                   "zehn meistgespielten Archetypen plus Restklasse.",
        berechnung=_pruefe_laender,
        bei_verwerfung="Deckwahl und Region haengen zusammen: die Maerkte spielen "
                       "messbar verschieden.",
        bei_beibehaltung="Kein regionaler Unterschied nachweisbar -- die TCG-Meta "
                         "ist global einheitlich.",
        einschraenkung="Turnierspieler sind keine Zufallsstichprobe der jeweiligen "
                       "Region, und grosse Online-Turniere mischen die Maerkte. "
                       "Die Aussage gilt fuer die Turnierszene, nicht fuer alle "
                       "Spielenden.",
    ),
    Hypothese(
        schluessel="H12",
        titel="Muss ich meinen GO-Kader je Liga neu bewerten?",
        bereich=BEREICH_QUELLEN,
        anwendungsfall="Fuer GO-Spieler: ob ein in der Superliga bewaehrtes Pokemon "
                       "auch fuer die Meisterliga eine Empfehlung ist -- und fuers "
                       "Datenmodell, ob die Liga eine eigene Dimension verdient.",
        nullhypothese="Zwischen den Bewertungen der Pokemon in Super- und "
                      "Meisterliga besteht kein Zusammenhang.",
        alternativhypothese="Die Bewertungen haengen zusammen.",
        begruendung="Das GO-Gegenstueck zu H4: dieselben Pokemon unter anderer "
                    "Regel (Wertedeckel 1500 gegen offen). Faellt der Zusammenhang "
                    "schwach aus, rechtfertigt das die Liga als eigene Dimension -- "
                    "dieselbe Modellentscheidung wie beim Kampfformat.",
        verfahren="Spearman-Rangkorrelation der Scores. Die Scores sind kardinal, "
                  "aber zwischen zwei verschieden kalibrierten Ranglisten ist nur "
                  "die Reihenfolge vergleichbar, nicht die Zahl.",
        datenbasis="pvpoke-Ranglisten, juengster Stand, in beiden Ligen gefuehrte "
                   "Pokemon.",
        berechnung=_pruefe_go_ligen,
        bei_verwerfung="Die Ligen haengen zusammen -- entscheidend ist der Abstand "
                       "des Koeffizienten zu eins: er ist der eigene Anteil der "
                       "jeweiligen Liga.",
        bei_beibehaltung="Kein Zusammenhang zwischen den Ligen: der Wertedeckel "
                         "erzeugt eine vollstaendig eigene Meta.",
    ),
    Hypothese(
        schluessel="H13",
        titel="Ist ein starkes Pokemon in jedem Spiel stark?",
        bereich=BEREICH_QUELLEN,
        anwendungsfall="Wer von einem Spiel ins andere wechselt: ob sich das "
                       "Wissen ueber starke Pokemon mitnehmen laesst -- oder ob "
                       "jedes Regelwerk seine eigene Meta erzeugt und die "
                       "Vorbereitung von vorn beginnt.",
        nullhypothese="Zwischen dem VGC-Rang eines Pokemon und seinem GO-Score "
                      "besteht kein Zusammenhang.",
        alternativhypothese="Wer im VGC oben steht, steht auch in GO oben.",
        begruendung="Die spieluebergreifende Frage schlechthin -- und der Grund, "
                    "warum Dim_Pokemon als konforme Dimension ueber allen Quellen "
                    "steht. GO ersetzt Basiswerte durch eigene Werte, streicht "
                    "Faehigkeiten und rechnet Attacken um: bleibt trotzdem ein "
                    "Zusammenhang, ist die Staerke im Kern das Pokemon selbst; "
                    "verschwindet er, macht das Regelwerk die Meta.",
        verfahren="Spearman-Rangkorrelation zwischen Champions-Rang (Doppelkampf) "
                  "und pvpoke-Score der Meisterliga. Ein negativer Koeffizient "
                  "bedeutet Uebertragung: kleiner Rang ist besser, hoher Score ist "
                  "besser.",
        datenbasis="Juengster Stand beider Quellen, verknuepft ueber die konforme "
                   "Pokemon-Dimension; Schattenformen ausgenommen.",
        berechnung=_pruefe_spieluebergreifend,
        bei_verwerfung="Die Spiele haengen zusammen; das Vorzeichen sagt, ob "
                       "Staerke sich uebertraegt oder geradezu umkehrt.",
        bei_beibehaltung="Kein Zusammenhang: jedes Regelwerk erzeugt seine eigene "
                         "Meta, und die Staerke eines Pokemon ist keine Eigenschaft "
                         "des Pokemon, sondern des Spiels.",
        einschraenkung="Die Schnittmenge ist auf Pokemon beschraenkt, die in beiden "
                       "Spielen gewertet werden; GO-exklusive Groessen wie "
                       "Schattenformen bleiben aussen vor.",
    ),
]


# --------------------------------------------------------------------------
# Pruefung des gesamten Katalogs
# --------------------------------------------------------------------------

@dataclass
class Katalogergebnis:
    """Ergebnis der Pruefung des gesamten Katalogs."""

    ergebnisse: list[HypothesenErgebnis] = field(default_factory=list)
    alpha: float = ALPHA

    @property
    def geprueft(self) -> int:
        return sum(1 for e in self.ergebnisse if e.pruefbar)

    @property
    def verworfen(self) -> int:
        return sum(1 for e in self.ergebnisse if e.verworfen)

    @property
    def nicht_pruefbar(self) -> int:
        return sum(1 for e in self.ergebnisse if not e.pruefbar)

    def nach_bereich(self) -> dict[str, list[HypothesenErgebnis]]:
        gruppen: dict[str, list[HypothesenErgebnis]] = {}
        for ergebnis in self.ergebnisse:
            gruppen.setdefault(ergebnis.hypothese.bereich, []).append(ergebnis)
        return gruppen

    def als_tabelle(self) -> pd.DataFrame:
        """Verdichtete Uebersicht -- eine Zeile je Hypothese."""
        return pd.DataFrame([
            {
                "Nr": e.hypothese.schluessel,
                "Hypothese": e.hypothese.titel,
                "Bereich": e.hypothese.bereich,
                "Verfahren": e.pruefgroesse.verfahren if e.pruefbar else "-",
                "n": e.pruefgroesse.n if e.pruefbar else None,
                "Pruefgroesse": (f"{e.pruefgroesse.statistik_name} = {e.pruefgroesse.statistik}"
                                 if e.pruefbar else "-"),
                "p": round(e.pruefgroesse.p_wert, 6) if e.pruefbar else None,
                "Schranke (Holm)": round(e.schranke, 6) if e.pruefbar else None,
                "Effekt": (f"{e.pruefgroesse.effekt_name} = {e.pruefgroesse.effekt} "
                           f"({e.pruefgroesse.effekt_deutung})" if e.pruefbar else "-"),
                "Entscheidung": e.status,
            }
            for e in self.ergebnisse
        ])


def pruefe_alle(conn: sqlite3.Connection, alpha: float = ALPHA,
                katalog: Sequence[Hypothese] | None = None) -> Katalogergebnis:
    """Prueft den gesamten Katalog und korrigiert familienweise nach Holm.

    Ablauf in zwei Schritten: erst werden alle Pruefgroessen berechnet, dann
    wird ueber die tatsaechlich pruefbaren Hypothesen die Holm-Korrektur gelegt.
    Nicht pruefbare Hypothesen bleiben aussen vor -- sie wuerden die Familie
    vergroessern und damit die uebrigen unnoetig streng pruefen.

    Eine Hypothese, deren Berechnung mit einem unerwarteten Fehler abbricht,
    darf den Katalog nicht zum Stillstand bringen; sie wird als nicht pruefbar
    ausgewiesen.
    """
    hypothesen = list(katalog if katalog is not None else KATALOG)
    ergebnisse: list[HypothesenErgebnis] = []

    for hypothese in hypothesen:
        try:
            ergebnisse.append(HypothesenErgebnis(
                hypothese=hypothese, pruefgroesse=hypothese.berechnung(conn)))
        except DatenbasisFehlt as fehler:
            ergebnisse.append(HypothesenErgebnis(hypothese=hypothese, hinweis=str(fehler)))
        except Exception as fehler:  # noqa: BLE001 -- eine Hypothese darf den Katalog nicht stoppen
            ergebnisse.append(HypothesenErgebnis(
                hypothese=hypothese,
                hinweis=f"Die Berechnung ist fehlgeschlagen: {fehler}"))

    pruefbar = [e for e in ergebnisse if e.pruefbar]
    p_werte = [e.pruefgroesse.p_wert for e in pruefbar]  # type: ignore[union-attr]
    for ergebnis, verworfen, schranke in zip(
            pruefbar, holm_bonferroni(p_werte, alpha), holm_schranken(p_werte, alpha),
            strict=True):
        ergebnis.verworfen = verworfen
        ergebnis.schranke = schranke

    return Katalogergebnis(ergebnisse=ergebnisse, alpha=alpha)
