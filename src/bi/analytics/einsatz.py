"""Einsatzcheck: Kann ein eigenes Pokemon gerade kompetitiv gespielt werden?

Die Box sagt, was jemand besitzt; das Warehouse sagt, was gespielt wird. Der
Einsatzcheck legt beides uebereinander -- je Spielform, denn dieselbe Frage
hat drei verschiedene Antworten:

* **Champions (VGC):** Wird das Pokemon im Ranked gefuehrt, und auf welchem
  Rang? Ein Pokemon ohne Eintrag ist entweder nicht zugelassen oder wird
  nicht gespielt -- beides heisst: derzeit kein Einsatz. Die Grenze zur
  Meta-Relevanz ist ``META_RANGGRENZE`` aus der Konfiguration, dieselbe, die
  auch das Cockpit verwendet.
* **Pokemon GO:** In welcher Liga erreicht es den besten Score? Der Score ist
  kardinal; ein Wert ab ``GO_EINSATZ_SCORE`` gilt als spielbar.
* **Sammelkartenspiel:** Fuehrt es als Leit-Pokemon ein Turnierdeck an?

Das Urteil ist eine **Aussage** im Sinne des Designsystems -- ``guenstig``,
``neutral`` oder ``gefahr`` -- und keine Farbe. Was daraus wird, entscheidet
:mod:`bi.ui.design`.

Alle Champions-Abfragen laufen ueber ``saison_aktuell = 1`` und werden mit
:func:`bi.analytics.saison.anwenden` umhuellt; der Einsatzcheck folgt damit
der in der Seitenleiste gewaehlten Saison wie jede andere Auswertung.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..config import META_RANGGRENZE
from . import saison

# Ab diesem pvpoke-Score gilt ein Pokemon in einer GO-Liga als spielbar. Die
# Rangliste reicht bis weit unter 50; die Szene spielt in der Praxis, was
# ueber etwa 80 liegt.
GO_EINSATZ_SCORE = 80.0

URTEILE = ("meta", "spielbar", "kein_einsatz", "unbekannt")
URTEIL_TEXT = {
    "meta": "Meta-relevant",
    "spielbar": "Spielbar",
    "kein_einsatz": "Derzeit kein Einsatz",
    "unbekannt": "Keine Daten",
}
URTEIL_BEDEUTUNG = {
    "meta": "guenstig", "spielbar": "neutral", "kein_einsatz": "gefahr",
    "unbekannt": "neutral",
}


@dataclass(frozen=True)
class Befund:
    """Der Einsatzcheck fuer ein Pokemon in einer Spielform."""

    spielform: str
    urteil: str
    text: str
    rang: int | None = None
    score: float | None = None

    @property
    def bedeutung(self) -> str:
        return URTEIL_BEDEUTUNG[self.urteil]


@dataclass
class Einsatz:
    """Alle Befunde zu einem Pokemon."""

    slug: str
    befunde: list[Befund] = field(default_factory=list)

    @property
    def bestes_urteil(self) -> str:
        """Das guenstigste Urteil ueber alle Spielformen -- fuer die Kurzanzeige."""
        for urteil in URTEILE:
            if any(b.urteil == urteil for b in self.befunde):
                return urteil
        return "unbekannt"

    def befund(self, spielform: str) -> Befund | None:
        return next((b for b in self.befunde if b.spielform == spielform), None)


def _champions(conn: sqlite3.Connection, slugs: list[str]) -> dict[str, list[Befund]]:
    # Nicht V_Usage_Aktuell: die Sicht ist auf die laufende Saison festgelegt
    # und wuerde eine in der Seitenleiste gewaehlte aeltere Saison leer
    # lassen. Der juengste Tag je Saison und Format wird deshalb hier bestimmt.
    platzhalter = ", ".join("?" * len(slugs))
    zeilen = conn.execute(saison.anwenden(f"""
        SELECT u.slug, u.kampfformat, u.rang, u.erfasste_pokemon
          FROM V_Usage u
          JOIN (SELECT saison_sk, kampfformat_sk, MAX(zeit_sk) AS zeit_sk
                  FROM Fact_Champions_Usage GROUP BY saison_sk, kampfformat_sk) neueste
            ON neueste.saison_sk = u.saison_sk
           AND neueste.kampfformat_sk = u.kampfformat_sk
           AND neueste.zeit_sk = u.zeit_sk
         WHERE u.saison_aktuell = 1 AND u.slug IN ({platzhalter})
         ORDER BY u.slug, u.kampfformat
    """, conn), slugs).fetchall()  # noqa: S608 -- nur Platzhalter, keine Werte

    gefunden: dict[str, list[Befund]] = {}
    for z in zeilen:
        rang = int(z["rang"])
        urteil = "meta" if rang <= META_RANGGRENZE else "spielbar"
        gefunden.setdefault(z["slug"], []).append(Befund(
            f"Champions {z['kampfformat']}", urteil,
            f"Rang {rang} von {int(z['erfasste_pokemon'])} im Ranked", rang=rang))
    return gefunden


def _go(conn: sqlite3.Connection, slugs: list[str]) -> dict[str, Befund]:
    platzhalter = ", ".join("?" * len(slugs))
    zeilen = conn.execute(f"""
        SELECT slug, liga_name, score, rang
          FROM V_GO_Meta
         WHERE slug IN ({platzhalter}) AND ist_schatten = 0
           AND zeit_sk = (SELECT MAX(zeit_sk) FROM Fact_GO_Meta)
         ORDER BY slug, score DESC
    """, slugs).fetchall()  # noqa: S608 -- nur Platzhalter, keine Werte

    beste: dict[str, Befund] = {}
    for z in zeilen:
        if z["slug"] in beste:
            continue  # nach Score absteigend sortiert: der erste ist der beste
        score = float(z["score"])
        urteil = "meta" if score >= GO_EINSATZ_SCORE else "spielbar"
        beste[z["slug"]] = Befund(
            "Pokemon GO", urteil,
            f"{z['liga_name']}: Score {score:.1f}, Rang {int(z['rang'])}",
            rang=int(z["rang"]), score=score)
    return beste


def _tcg(conn: sqlite3.Connection, slugs: list[str]) -> dict[str, Befund]:
    platzhalter = ", ".join("?" * len(slugs))
    zeilen = conn.execute(f"""
        SELECT d.leit_slug AS slug, d.anzeigename, SUM(f.spieler) AS spieler
          FROM Dim_TCG_Deck d
          JOIN Fact_TCG_Meta f ON f.deck_sk = d.deck_sk
         WHERE d.leit_slug IN ({platzhalter})
         GROUP BY d.leit_slug, d.anzeigename
         ORDER BY d.leit_slug, spieler DESC
    """, slugs).fetchall()  # noqa: S608 -- nur Platzhalter, keine Werte

    beste: dict[str, Befund] = {}
    for z in zeilen:
        if z["slug"] in beste:
            continue
        beste[z["slug"]] = Befund(
            "Sammelkartenspiel", "meta",
            f"Leit-Pokemon des Decks '{z['anzeigename']}' ({int(z['spieler'])} Spieler)")
    return beste


def pruefen(conn: sqlite3.Connection, slugs: list[str]) -> dict[str, Einsatz]:
    """Der Einsatzcheck fuer eine Liste von Pokemon-Schluesseln.

    Je Spielform gibt es genau einen Befund je Pokemon -- auch dann, wenn die
    Quelle nichts fuehrt: dann lautet er "kein Einsatz" bzw. "keine Daten",
    falls die Spielform ueberhaupt nicht geladen ist. Eine stumme Luecke
    saehe aus wie ein vergessener Fall.
    """
    eindeutig = sorted({s for s in slugs if s})
    ergebnis = {slug: Einsatz(slug) for slug in eindeutig}
    if not eindeutig:
        return ergebnis

    champions_geladen = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM Fact_Champions_Usage)").fetchone()[0]
    go_geladen = conn.execute("SELECT EXISTS(SELECT 1 FROM Fact_GO_Meta)").fetchone()[0]
    tcg_geladen = conn.execute("SELECT EXISTS(SELECT 1 FROM Fact_TCG_Meta)").fetchone()[0]

    champions = _champions(conn, eindeutig) if champions_geladen else {}
    go = _go(conn, eindeutig) if go_geladen else {}
    tcg = _tcg(conn, eindeutig) if tcg_geladen else {}

    formate = [z[0] for z in conn.execute(
        "SELECT schluessel FROM Dim_Kampfformat ORDER BY schluessel")]

    for slug, einsatz in ergebnis.items():
        if champions_geladen:
            vorhanden = {b.spielform: b for b in champions.get(slug, [])}
            for kampfformat in formate:
                name = f"Champions {kampfformat}"
                einsatz.befunde.append(vorhanden.get(name) or Befund(
                    name, "kein_einsatz", "Im Ranked derzeit nicht gefuehrt"))
        else:
            einsatz.befunde.append(Befund("Champions", "unbekannt", "Ranked nicht geladen"))

        if go_geladen:
            einsatz.befunde.append(go.get(slug) or Befund(
                "Pokemon GO", "kein_einsatz", "In keiner Liga-Rangliste"))
        else:
            einsatz.befunde.append(Befund("Pokemon GO", "unbekannt", "GO-Meta nicht geladen"))

        if tcg_geladen:
            einsatz.befunde.append(tcg.get(slug) or Befund(
                "Sammelkartenspiel", "kein_einsatz", "Fuehrt kein Turnierdeck an"))
        else:
            einsatz.befunde.append(Befund(
                "Sammelkartenspiel", "unbekannt", "Turnierdaten nicht geladen"))

    return ergebnis
