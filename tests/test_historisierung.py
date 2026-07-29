"""Tests der Historisierung, der Archivierung und der Saisonabgrenzung.

Diese Tests decken die zentralen Zusagen des Datenmodells ab:

* Aenderungen an Dimensionsattributen ueberschreiben nichts, sondern eroeffnen
  einen neuen Gueltigkeitszeitraum -- so bleiben Balance-Anpassungen zwischen
  Saisons nachvollziehbar.
* Das Rohdatenarchiv ueberlebt jedes Zuruecksetzen. Die Quelle haelt nur rund
  zwei Wochen vor; einmal verworfene Tage sind endgueltig verloren.
* Jeder Faktensatz traegt seine Saison, und genau eine Saison gilt als aktuell.
"""

from __future__ import annotations

import json

import pytest

from bi import quality, warehouse
from bi.etl import champions, load, pipeline
from bi.etl.transform import transformiere_pokemon, zeitdimension


@pytest.fixture
def conn():
    """Leeres Data Warehouse im Arbeitsspeicher."""
    verbindung = warehouse.verbindung(":memory:")
    yield verbindung
    verbindung.close()


def _pokemon(slug: str = "incineroar", attack: int = 115) -> dict:
    """Dimensionssatz ueber den regulaeren Transformationsweg."""
    nutzlast = {
        "id": 727, "name": slug, "species": {"name": slug},
        "types": [{"type": {"name": "fire"}}, {"type": {"name": "dark"}}],
        "stats": [
            {"stat": {"name": "hp"}, "base_stat": 95},
            {"stat": {"name": "attack"}, "base_stat": attack},
            {"stat": {"name": "defense"}, "base_stat": 90},
            {"stat": {"name": "special-attack"}, "base_stat": 80},
            {"stat": {"name": "special-defense"}, "base_stat": 90},
            {"stat": {"name": "speed"}, "base_stat": 60},
        ],
    }
    satz, _ = transformiere_pokemon(nutzlast, {slug: 7})
    return satz


# --------------------------------------------------------------------------
# Bi-temporale Historisierung
# --------------------------------------------------------------------------

def test_erstladung_legt_aktuellen_satz_an(conn) -> None:
    zaehler = load.lade_pokemon_dimension(conn, [_pokemon()], stichtag="2026-01-01")

    assert zaehler == {"neu": 1, "geaendert": 0, "unveraendert": 0}
    zeile = conn.execute("SELECT * FROM Dim_Pokemon").fetchone()
    assert zeile["ist_aktuell"] == 1
    assert zeile["gueltig_ab"] == "2026-01-01"
    assert zeile["gueltig_bis"] == warehouse.UNENDLICH


def test_unveraenderte_daten_erzeugen_keinen_neuen_satz(conn) -> None:
    """Ohne fachliche Aenderung darf kein zweiter Zeitraum entstehen."""
    load.lade_pokemon_dimension(conn, [_pokemon()], stichtag="2026-01-01")
    zaehler = load.lade_pokemon_dimension(conn, [_pokemon()], stichtag="2026-02-01")

    assert zaehler == {"neu": 0, "geaendert": 0, "unveraendert": 1}
    assert conn.execute("SELECT COUNT(*) FROM Dim_Pokemon").fetchone()[0] == 1


def test_balance_aenderung_eroeffnet_neuen_zeitraum(conn) -> None:
    """Der alte Zustand bleibt erhalten und wird sauber abgegrenzt."""
    load.lade_pokemon_dimension(conn, [_pokemon(attack=115)], stichtag="2026-01-01")
    zaehler = load.lade_pokemon_dimension(conn, [_pokemon(attack=125)], stichtag="2026-06-01")

    assert zaehler["geaendert"] == 1
    saetze = conn.execute(
        "SELECT attack, gueltig_ab, gueltig_bis, ist_aktuell FROM Dim_Pokemon "
        "ORDER BY gueltig_ab").fetchall()

    assert len(saetze) == 2, "Der historische Zustand muss erhalten bleiben."

    alt, neu = saetze
    assert alt["attack"] == 115
    assert alt["ist_aktuell"] == 0
    assert alt["gueltig_bis"] == "2026-05-31", "Abgrenzung auf den Vortag der Aenderung."

    assert neu["attack"] == 125
    assert neu["ist_aktuell"] == 1
    assert neu["gueltig_ab"] == "2026-06-01"


def test_zeitraeume_sind_lueckenlos_und_ueberschneidungsfrei(conn) -> None:
    """Die Gueltigkeitszeitraeume muessen direkt aneinander anschliessen."""
    for stichtag, wert in (("2026-01-01", 100), ("2026-03-01", 110), ("2026-05-01", 120)):
        load.lade_pokemon_dimension(conn, [_pokemon(attack=wert)], stichtag=stichtag)

    saetze = conn.execute(
        "SELECT gueltig_ab, gueltig_bis FROM Dim_Pokemon ORDER BY gueltig_ab").fetchall()
    assert len(saetze) == 3
    assert saetze[0]["gueltig_bis"] == "2026-02-28"
    assert saetze[1]["gueltig_ab"] == "2026-03-01"
    assert saetze[1]["gueltig_bis"] == "2026-04-30"
    assert saetze[2]["gueltig_ab"] == "2026-05-01"

    assert conn.execute(
        "SELECT COUNT(*) FROM Dim_Pokemon WHERE ist_aktuell = 1").fetchone()[0] == 1


def test_historischer_stichtag_ist_abfragbar(conn) -> None:
    """Der Zweck der Historisierung: Auswertung zu einem vergangenen Stand."""
    load.lade_pokemon_dimension(conn, [_pokemon(attack=100)], stichtag="2026-01-01")
    load.lade_pokemon_dimension(conn, [_pokemon(attack=140)], stichtag="2026-06-01")

    stand = conn.execute(
        "SELECT attack FROM Dim_Pokemon WHERE slug = ? AND ? BETWEEN gueltig_ab AND gueltig_bis",
        ("incineroar", "2026-03-15"),
    ).fetchone()
    assert stand["attack"] == 100, "Zum Stichtag im Maerz galt noch der alte Wert."


def test_qualitaetsregeln_nach_historisierung(conn) -> None:
    """Die Konsistenzregeln muessen nach mehreren Aenderungen bestehen."""
    for stichtag, wert in (("2026-01-01", 100), ("2026-03-01", 110), ("2026-05-01", 120)):
        load.lade_pokemon_dimension(conn, [_pokemon(attack=wert)], stichtag=stichtag)

    assert quality.regel_dimension_eindeutig(conn).bestanden
    assert quality.regel_historisierung_intervalle(conn).bestanden


# --------------------------------------------------------------------------
# Archivierung
# --------------------------------------------------------------------------

def _abzug(name: str = "Garchomp", datum: str = "2026-07-28",
           kampfformat: str = "Doubles") -> champions.Tagesabzug:
    return champions.Tagesabzug(
        quell_name=name, saison="M4", datum_iso=datum, kampfformat=kampfformat,
        zeilen=[
            {"pokemon": name, "column_position": "1", "category": "move", "rank": "1",
             "name": "Dragon Claw", "percentage": "85.6%"},
        ],
    )


def test_archiv_speichert_rohdaten_unveraendert(conn) -> None:
    champions.archiviere(conn, [_abzug()], lauf_id=1)
    zeile = conn.execute("SELECT * FROM Archiv_Champions").fetchone()

    assert zeile["saison"] == "M4"
    assert zeile["datum_iso"] == "2026-07-28"
    assert json.loads(zeile["nutzlast"])[0]["name"] == "Dragon Claw"


def test_archiv_ist_idempotent(conn) -> None:
    champions.archiviere(conn, [_abzug()], lauf_id=1)
    champions.archiviere(conn, [_abzug()], lauf_id=2)
    assert conn.execute("SELECT COUNT(*) FROM Archiv_Champions").fetchone()[0] == 1


def test_archivierte_staende_erkennt_bestand(conn) -> None:
    """Grundlage des inkrementellen Ladens."""
    champions.archiviere(conn, [_abzug(datum="2026-07-27"), _abzug()], lauf_id=1)
    staende = champions.archivierte_staende(conn)

    assert ("M4", "2026-07-28", "Doubles") in staende
    assert ("M4", "2026-07-26", "Doubles") not in staende


def test_archiv_kann_ohne_quellzugriff_zurueckgelesen_werden(conn) -> None:
    """Ermoeglicht das Neuverarbeiten nach geaenderten Ableitungsregeln."""
    champions.archiviere(conn, [_abzug()], lauf_id=1)
    zurueck = champions.lies_aus_archiv(conn)

    assert len(zurueck) == 1
    assert zurueck[0].zeilen[0]["name"] == "Dragon Claw"


def test_archiv_ueberlebt_zuruecksetzen(conn) -> None:
    """Die Quelle haelt nur zwei Wochen vor -- das Archiv darf nicht mitgeloescht werden."""
    champions.archiviere(conn, [_abzug()], lauf_id=1)

    warehouse.zuruecksetzen(conn, nur_fakten=False)
    assert conn.execute("SELECT COUNT(*) FROM Archiv_Champions").fetchone()[0] == 1, (
        "Das Archiv darf beim Zuruecksetzen nicht verloren gehen."
    )


def test_archiv_nur_auf_ausdrueckliche_anweisung_verwerfbar(conn) -> None:
    champions.archiviere(conn, [_abzug()], lauf_id=1)
    warehouse.zuruecksetzen(conn, archiv_verwerfen=True)
    assert conn.execute("SELECT COUNT(*) FROM Archiv_Champions").fetchone()[0] == 0


def test_archivumfang(conn) -> None:
    champions.archiviere(
        conn, [_abzug(datum="2026-07-26"), _abzug(datum="2026-07-27"), _abzug()],
        lauf_id=1)
    umfang = warehouse.archiv_umfang(conn)
    assert umfang["tage"] == 3
    assert umfang["erster_tag"] == "2026-07-26"


def test_archiv_ueberlebt_als_datei_und_kehrt_zurueck(conn, tmp_path) -> None:
    """Der Weg, auf dem die Zeitreihe die Vorhaltezeit der Quelle ueberdauert.

    Ohne diesen Export-Import-Weg begaenne jeder Lauf auf einem frischen Runner
    bei null, und das Archiv koennte nie mehr als die rund zwei Wochen umfassen,
    die die Quelle selbst vorhaelt.
    """
    champions.archiviere(
        conn, [_abzug(datum="2026-07-27"), _abzug(datum="2026-07-28"),
               _abzug(datum="2026-07-28", kampfformat="Singles")], lauf_id=1)

    export = champions.exportiere_archiv(conn, tmp_path / "archiv")
    assert export["saetze"] == 3
    assert export["dateien"] == 3

    # Frische Datenbank -- so sieht es auf einem leeren Runner aus.
    frisch = warehouse.verbindung(":memory:")
    try:
        assert warehouse.archiv_umfang(frisch).get("saetze") == 0

        eingelesen = champions.importiere_archiv(frisch, tmp_path / "archiv")
        assert eingelesen["saetze"] == 3

        umfang = warehouse.archiv_umfang(frisch)
        assert umfang["tage"] == 2
        assert umfang["erster_tag"] == "2026-07-27"

        # Die Nutzlast muss unveraendert zurueckkommen.
        zurueck = champions.lies_aus_archiv(frisch)
        assert {a.quell_name for a in zurueck} == {"Garchomp"}
        assert zurueck[0].zeilen[0]["name"] == "Dragon Claw"
    finally:
        frisch.close()


def test_export_ist_bytegleich_bei_unveraendertem_bestand(conn, tmp_path) -> None:
    """Ein unveraenderter Tag darf keinen neuen Commit erzeugen.

    Der Betriebslauf schreibt das Archiv taeglich ins Repository zurueck. Waeren
    die Dateien nicht deterministisch, entstuende jeden Tag ein Commit ohne
    inhaltliche Aenderung.
    """
    champions.archiviere(conn, [_abzug()], lauf_id=1)

    champions.exportiere_archiv(conn, tmp_path / "archiv")
    datei = next((tmp_path / "archiv").glob("*/*/*.ndjson.gz"))
    erster = datei.read_bytes()

    champions.exportiere_archiv(conn, tmp_path / "archiv")
    assert datei.read_bytes() == erster, (
        "Zweiter Export unterscheidet sich -- das erzeugte taeglich einen leeren Commit."
    )


def test_import_ist_idempotent(conn, tmp_path) -> None:
    champions.archiviere(conn, [_abzug()], lauf_id=1)
    champions.exportiere_archiv(conn, tmp_path / "archiv")

    frisch = warehouse.verbindung(":memory:")
    try:
        champions.importiere_archiv(frisch, tmp_path / "archiv")
        champions.importiere_archiv(frisch, tmp_path / "archiv")
        assert frisch.execute(
            "SELECT COUNT(*) FROM Archiv_Champions").fetchone()[0] == 1
    finally:
        frisch.close()


def test_import_aus_leerem_verzeichnis_bleibt_stabil(conn, tmp_path) -> None:
    """Der erste Lauf ueberhaupt findet noch kein Archiv vor."""
    assert champions.importiere_archiv(conn, tmp_path / "gibtesnicht") == {
        "dateien": 0, "saetze": 0}


def test_archivluecke_wird_erkannt(conn) -> None:
    """Ein ausgelassener Ladelauf hinterlaesst eine nicht schliessbare Luecke."""
    champions.archiviere(
        conn, [_abzug(datum="2026-07-20"), _abzug(datum="2026-07-23")], lauf_id=1)

    ergebnis = quality.regel_archiv_lueckenlos(conn)
    assert not ergebnis.bestanden
    assert "2026-07-21" in ergebnis.befund
    assert ergebnis.betroffen == 2


# --------------------------------------------------------------------------
# Saisonabgrenzung
# --------------------------------------------------------------------------

def test_saison_wird_mit_zeitraum_gefuehrt(conn) -> None:
    quelle_sk = load.lade_quelle(conn, "champions")
    load.lade_saison(conn, "M4", "Season 4", quelle_sk, ["2026-07-16", "2026-07-28"])

    zeile = conn.execute("SELECT * FROM Dim_Saison WHERE schluessel = 'M4'").fetchone()
    assert zeile["beginn"] == "2026-07-16"
    assert zeile["ende"] == "2026-07-28"
    assert zeile["ist_aktuell"] == 1


def test_saisonzeitraum_waechst_mit_dem_archiv(conn) -> None:
    """Frueher archivierte Tage bleiben Teil der Saison.

    Auch wenn die Quelle sie inzwischen nicht mehr fuehrt -- genau dafuer ist das
    Archiv da.
    """
    quelle_sk = load.lade_quelle(conn, "champions")
    load.lade_saison(conn, "M4", "Season 4", quelle_sk, ["2026-07-20", "2026-07-25"])
    load.lade_saison(conn, "M4", "Season 4", quelle_sk, ["2026-07-24", "2026-08-02"])

    zeile = conn.execute(
        "SELECT beginn, ende FROM Dim_Saison WHERE schluessel='M4'").fetchone()
    assert zeile["beginn"] == "2026-07-20", "Der fruehere Beginn darf nicht verloren gehen."
    assert zeile["ende"] == "2026-08-02"


def test_nur_eine_saison_je_quelle_ist_aktuell(conn) -> None:
    """Verhindert, dass Pokemon aus abgelaufenen Saisons die Auswertung verfaelschen."""
    quelle_sk = load.lade_quelle(conn, "champions")
    load.lade_saison(conn, "M3", "Season 3", quelle_sk, ["2026-05-01"])
    load.lade_saison(conn, "M4", "Season 4", quelle_sk, ["2026-07-16"])

    aktuell = [z["schluessel"] for z in conn.execute(
        "SELECT schluessel FROM Dim_Saison WHERE ist_aktuell = 1")]
    assert aktuell == ["M4"]
    assert quality.regel_saison_zuordnung(conn).bestanden


def test_quelle_traegt_ihr_messniveau(conn) -> None:
    """Die Auswertung soll pruefen koennen, was die Quelle liefert."""
    load.lade_quelle(conn, "champions")
    zeile = conn.execute("SELECT * FROM Dim_Quelle WHERE schluessel='champions'").fetchone()

    assert zeile["messniveau_nutzung"] == "ordinal"
    assert zeile["hat_partner_gewicht"] == 0
    assert zeile["granularitaet_zeit"] == "Tag"
    assert zeile["ist_offiziell"] == 1
    assert zeile["vorhaltung_tage"] == 14


# --------------------------------------------------------------------------
# Faktenladung
# --------------------------------------------------------------------------

def _vorbereiten(conn) -> tuple[dict[str, int], int, dict[str, int], int]:
    load.lade_pokemon_dimension(conn, [_pokemon()], stichtag="2026-01-01")
    zeit = load.lade_zeit(conn, ["2026-07-27", "2026-07-28"])
    quelle_sk = load.lade_quelle(conn, "champions")
    formate = load.lade_alle_kampfformate(conn)
    saison_sk = load.lade_saison(conn, "M4", "Season 4", quelle_sk, ["2026-07-28"])
    return zeit, saison_sk, formate, quelle_sk


def _satz(datum: str, rang: int) -> champions.ChampionsSatz:
    return champions.ChampionsSatz("incineroar", "M4", datum, "Doubles", rang, [])


def test_rangperzentil_normiert_auf_null_bis_hundert(conn) -> None:
    """Raenge aus Tagen mit unterschiedlich vielen Pokemon werden vergleichbar."""
    zeit, saison_sk, formate, quelle_sk = _vorbereiten(conn)
    pokemon = {z["slug"]: z["pokemon_sk"] for z in
               conn.execute("SELECT slug, pokemon_sk FROM Dim_Pokemon")}
    lauf = load.lauf_beginnen(conn, "Test", "perzentil")

    anzahl, _ = champions.lade_fakten(
        conn, [_satz("2026-07-28", 1)], zeit, saison_sk, formate, quelle_sk,
        pokemon, {}, lauf)

    assert anzahl == 1
    zeile = conn.execute(
        "SELECT rang, rang_perzentil FROM Fact_Champions_Usage").fetchone()
    assert zeile["rang"] == 1
    assert zeile["rang_perzentil"] == 100.0


def test_wiederholter_lauf_erzeugt_keine_dubletten(conn) -> None:
    """Derselbe Tag zweimal geladen ergibt genau einen Faktensatz."""
    zeit, saison_sk, formate, quelle_sk = _vorbereiten(conn)
    pokemon = {z["slug"]: z["pokemon_sk"] for z in
               conn.execute("SELECT slug, pokemon_sk FROM Dim_Pokemon")}
    lauf = load.lauf_beginnen(conn, "Test", "idempotenz")

    champions.lade_fakten(conn, [_satz("2026-07-28", 5)], zeit, saison_sk, formate,
                          quelle_sk, pokemon, {}, lauf)
    champions.lade_fakten(conn, [_satz("2026-07-28", 3)], zeit, saison_sk, formate,
                          quelle_sk, pokemon, {}, lauf)

    zeilen = conn.execute("SELECT rang FROM Fact_Champions_Usage").fetchall()
    assert len(zeilen) == 1, "Der fachliche Schluessel muss die Dublette verhindern."
    assert zeilen[0]["rang"] == 3, "Der erneute Lauf aktualisiert die Kennzahl."


def test_neuer_tag_loescht_vorhandene_historie_nicht(conn) -> None:
    """Nicht-Volatilitaet: bereits geladene Tage bleiben unberuehrt.

    Das ist die Voraussetzung dafuer, dass die Zeitreihe ueber die Vorhaltezeit
    der Quelle hinaus waechst.
    """
    zeit, saison_sk, formate, quelle_sk = _vorbereiten(conn)
    pokemon = {z["slug"]: z["pokemon_sk"] for z in
               conn.execute("SELECT slug, pokemon_sk FROM Dim_Pokemon")}
    lauf = load.lauf_beginnen(conn, "Test", "zeitreihe")

    champions.lade_fakten(conn, [_satz("2026-07-27", 8)], zeit, saison_sk, formate,
                          quelle_sk, pokemon, {}, lauf)
    champions.lade_fakten(conn, [_satz("2026-07-28", 4)], zeit, saison_sk, formate,
                          quelle_sk, pokemon, {}, lauf)

    tage = conn.execute("""
        SELECT z.datum_iso, f.rang FROM Fact_Champions_Usage f
        JOIN Dim_Zeit z ON z.zeit_sk = f.zeit_sk ORDER BY z.datum_iso
    """).fetchall()

    assert len(tage) == 2
    assert tage[0]["rang"] == 8
    assert tage[1]["rang"] == 4


def test_fakt_ohne_dimensionssatz_wird_abgewiesen(conn) -> None:
    """Referenzielle Integritaet: ohne Dimensionssatz kein Fakt."""
    zeit, saison_sk, formate, quelle_sk = _vorbereiten(conn)
    lauf = load.lauf_beginnen(conn, "Test", "integritaet")

    unbekannt = champions.ChampionsSatz("gibtesnicht", "M4", "2026-07-28", "Doubles", 1, [])
    anzahl, befunde = champions.lade_fakten(
        conn, [unbekannt], zeit, saison_sk, formate, quelle_sk, {}, {}, lauf)

    assert anzahl == 0
    assert any(b.dimension == "Referenzielle Integritaet" for b in befunde)


def test_etl_protokoll_wird_gefuehrt(conn) -> None:
    """Jeder Lauf muss mit Kennzahlen und Laufzeit protokolliert werden."""
    lauf = load.lauf_beginnen(conn, "Test", "protokoll")
    load.lauf_abschliessen(conn, lauf, "erfolgreich", gelesen=100, geladen=95,
                           abgewiesen=5, meldung="Testlauf")

    zeile = conn.execute("SELECT * FROM ETL_Lauf WHERE lauf_id = ?", (lauf,)).fetchone()
    assert zeile["status"] == "erfolgreich"
    assert zeile["zeilen_gelesen"] == 100
    assert zeile["zeilen_abgewiesen"] == 5
    assert zeile["dauer_sekunden"] is not None


def test_zeitdimension_wird_mit_letztem_tag_markiert(conn) -> None:
    load.lade_zeit(conn, ["2026-07-26", "2026-07-28", "2026-07-27"])
    letzter = conn.execute(
        "SELECT datum_iso FROM Dim_Zeit WHERE ist_letzter_tag = 1").fetchall()
    assert len(letzter) == 1
    assert letzter[0]["datum_iso"] == "2026-07-28"
    # Der Schluessel folgt dem Datum.
    assert conn.execute("SELECT zeit_sk FROM Dim_Zeit WHERE datum_iso='2026-07-28'"
                        ).fetchone()[0] == zeitdimension("2026-07-28")["zeit_sk"]


def test_attacken_werden_auch_beim_archivneuaufbau_geladen(conn, monkeypatch) -> None:
    """``--aus-archiv`` darf die Attacken-Stammdaten nicht ueberspringen.

    Der Schalter bedeutet "die Tagesstaende nicht erneut bei Champions abrufen",
    nicht "keine Stammdaten laden" -- die Pokemon-Stammdaten kommen im selben Lauf
    ebenfalls ueber das Netz. Ein Ueberspringen liess ``Dim_Attacke`` auf einem
    frischen Rechner leer; die Qualitaetsregel zur Attackenverknuepfung fiel dann
    auf 0 Prozent und jede Matchup-Bewertung ins Leere.
    """
    load.lade_pokemon_dimension(conn, [_pokemon("garchomp")])
    champions.archiviere(conn, [_abzug()], lauf_id=1)

    gerufen: list[set[str]] = []
    monkeypatch.setattr(pipeline, "attacken_ergaenzen",
                        lambda _conn, namen, *a, **k: gerufen.append(namen) or 0)

    ergebnis = champions.laden(conn, aus_archiv=True)

    assert ergebnis["erfolgreich"], ergebnis.get("meldung")
    assert gerufen, "attacken_ergaenzen wurde beim Archivneuaufbau nicht aufgerufen."
    # Uebergeben wird die Kompaktform, mit der das PokeAPI-Verzeichnis indiziert
    # ist -- ohne Bindestriche und Kleinschreibung.
    assert "dragonclaw" in gerufen[0], (
        f"Der benoetigte Attackenschluessel fehlt in {gerufen[0]}.")


def test_ausfall_der_attackenquelle_verwirft_den_lauf_nicht(conn, monkeypatch) -> None:
    """Ohne Attacken bleiben die Nutzungsfakten gueltig -- nur die Bewertung leidet."""
    load.lade_pokemon_dimension(conn, [_pokemon("garchomp")])
    champions.archiviere(conn, [_abzug()], lauf_id=1)

    def _faellt_aus(*_a, **_k):
        raise ConnectionError("PokeAPI nicht erreichbar")

    monkeypatch.setattr(pipeline, "attacken_ergaenzen", _faellt_aus)

    ergebnis = champions.laden(conn, aus_archiv=True)

    assert ergebnis["erfolgreich"], "Ein Ausfall der Stammdatenquelle darf den Lauf nicht verwerfen."
    assert conn.execute("SELECT COUNT(*) FROM Fact_Champions_Usage").fetchone()[0] > 0
    befunde = [z[0] for z in conn.execute("SELECT meldung FROM DQ_Befund")]
    assert any("nicht nachgeladen" in b for b in befunde), (
        f"Der Ausfall wurde nicht protokolliert: {befunde}")
