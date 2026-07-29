"""Tests des Startaufbaus aus dem mitversionierten Archiv.

Ohne diesen Weg haette die Anwendung in der Cloud keine Daten: das
Datenverzeichnis ist nicht versioniert, und Streamlit Community Cloud setzt bei
jedem Deployment einen frischen Behaelter auf -- auch beim taeglichen
Archiv-Commit.

Die Tests pruefen deshalb vor allem zwei Zusagen:

* Der Aufbau kommt **ohne Netzzugriff** aus. Ein Kaltstart darf nicht davon
  abhaengen, dass die PokeAPI gerade erreichbar ist.
* Der Aufruf ist **gefahrlos wiederholbar**. Er steht in ``hole_verbindung`` und
  wird damit bei jedem neuen Behaelter ausgefuehrt.
"""

from __future__ import annotations

import gzip

import pytest

from bi import bootstrap, warehouse
from bi.etl import champions, load, stammarchiv
from bi.etl.transform import transformiere_pokemon


@pytest.fixture
def conn():
    verbindung = warehouse.verbindung(":memory:")
    yield verbindung
    verbindung.close()


def _pokemon(slug: str = "garchomp") -> dict:
    nutzlast = {
        "id": 445, "name": slug, "species": {"name": slug},
        "types": [{"type": {"name": "dragon"}}, {"type": {"name": "ground"}}],
        "stats": [
            {"stat": {"name": "hp"}, "base_stat": 108},
            {"stat": {"name": "attack"}, "base_stat": 130},
            {"stat": {"name": "defense"}, "base_stat": 95},
            {"stat": {"name": "special-attack"}, "base_stat": 80},
            {"stat": {"name": "special-defense"}, "base_stat": 85},
            {"stat": {"name": "speed"}, "base_stat": 102},
        ],
    }
    satz, _ = transformiere_pokemon(nutzlast, {slug: 4})
    return satz


def _abzug(datum: str = "2026-07-28", kampfformat: str = "Doubles") -> champions.Tagesabzug:
    return champions.Tagesabzug(
        quell_name="Garchomp", saison="M4", datum_iso=datum, kampfformat=kampfformat,
        zeilen=[
            {"pokemon": "Garchomp", "column_position": "1", "category": "move",
             "rank": "1", "name": "Dragon Claw", "percentage": "85.6%"},
            {"pokemon": "Garchomp", "column_position": "2", "category": "held_item",
             "rank": "1", "name": "Life Orb", "percentage": "42.0%"},
        ],
    )


@pytest.fixture
def archiv(tmp_path, conn):
    """Ein vollstaendiges Archiv auf der Platte -- Stammdaten und Rohdaten."""
    load.lade_pokemon_dimension(conn, [_pokemon()])
    champions.archiviere(
        conn, [_abzug("2026-07-27"), _abzug("2026-07-28")], lauf_id=1)

    verzeichnis = tmp_path / "archiv"
    champions.exportiere_archiv(conn, verzeichnis)
    stammarchiv.exportiere_stammdaten(conn, verzeichnis)
    return verzeichnis


# --------------------------------------------------------------------------
# Stammdatenauszug
# --------------------------------------------------------------------------

def test_stammdaten_kehren_vollstaendig_zurueck(archiv) -> None:
    """Der Auszug sichert tabellengetreu, samt Gueltigkeitszeitraeumen.

    Eine Neuladung ueber den regulaeren Weg wuerde die bi-temporale Historie
    von ``Dim_Pokemon`` verlieren -- der Auszug ist eine Wiederherstellung.
    """
    frisch = warehouse.verbindung(":memory:")
    try:
        zaehler = stammarchiv.importiere_stammdaten(frisch, archiv)
        assert zaehler["saetze"] == 1

        zeile = frisch.execute("SELECT * FROM Dim_Pokemon").fetchone()
        assert zeile["slug"] == "garchomp"
        assert zeile["attack"] == 130
        assert zeile["ist_aktuell"] == 1
        assert zeile["gueltig_bis"] == warehouse.UNENDLICH
    finally:
        frisch.close()


def test_vorhandene_stammdaten_werden_nicht_ueberschrieben(archiv, conn) -> None:
    """Der laufende Betrieb haelt ueber die PokeAPI den aktuelleren Stand."""
    conn.execute("UPDATE Dim_Pokemon SET attack = 999")
    stammarchiv.importiere_stammdaten(conn, archiv)

    assert conn.execute("SELECT attack FROM Dim_Pokemon").fetchone()[0] == 999


def test_stammdatenexport_schreibt_unveraendertes_nicht_neu(archiv, conn) -> None:
    zaehler = stammarchiv.exportiere_stammdaten(conn, archiv)
    assert zaehler["saetze"] == 1
    assert zaehler["geschrieben"] == 0, (
        "Unveraenderte Stammdaten wurden neu geschrieben -- das erzeugt einen "
        "taeglichen Commit ohne inhaltliche Aenderung.")


def test_stammdatenexport_ist_unabhaengig_von_der_kompression(archiv, conn) -> None:
    """Wie beim Rohdatenarchiv zaehlt die Nutzlast, nicht das Kompressat."""
    datei = archiv / "stammdaten" / "Dim_Pokemon.ndjson.gz"
    anders = gzip.compress(gzip.decompress(datei.read_bytes()), compresslevel=1, mtime=0)
    datei.write_bytes(anders)

    assert stammarchiv.exportiere_stammdaten(conn, archiv)["geschrieben"] == 0
    assert datei.read_bytes() == anders


# --------------------------------------------------------------------------
# Startaufbau
# --------------------------------------------------------------------------

def test_aufbau_erzeugt_ein_vollstaendiges_warehouse(archiv) -> None:
    frisch = warehouse.verbindung(":memory:")
    try:
        assert not warehouse.ist_befuellt(frisch)

        ergebnis = bootstrap.sicherstellen(frisch, archiv)

        assert ergebnis["aufgebaut"] is True
        assert ergebnis["erfolgreich"] is True
        assert ergebnis["tage"] == 2
        assert warehouse.ist_befuellt(frisch)
        assert frisch.execute(
            "SELECT COUNT(*) FROM Fact_Champions_Usage").fetchone()[0] == 2
        assert frisch.execute(
            "SELECT COUNT(*) FROM Fact_Champions_Merkmal").fetchone()[0] > 0
    finally:
        frisch.close()


def test_aufbau_kommt_ohne_netzzugriff_aus(archiv, monkeypatch) -> None:
    """Ein Kaltstart darf nicht von der Erreichbarkeit der PokeAPI abhaengen."""
    def _kein_netz(*_a, **_k):
        raise AssertionError("Der Startaufbau hat auf das Netz zugegriffen.")

    monkeypatch.setattr("bi.etl.extract.sitzung", _kein_netz)

    frisch = warehouse.verbindung(":memory:")
    try:
        assert bootstrap.sicherstellen(frisch, archiv)["aufgebaut"] is True
    finally:
        frisch.close()


def test_aufbau_laesst_ein_befuelltes_warehouse_unberuehrt(archiv, conn) -> None:
    """Der Aufruf steht im Startpfad und muss gefahrlos wiederholbar sein."""
    bootstrap.sicherstellen(conn, archiv)
    vorher = conn.execute("SELECT COUNT(*) FROM Fact_Champions_Merkmal").fetchone()[0]

    ergebnis = bootstrap.sicherstellen(conn, archiv)

    assert ergebnis["aufgebaut"] is False
    assert conn.execute(
        "SELECT COUNT(*) FROM Fact_Champions_Merkmal").fetchone()[0] == vorher


def test_ohne_archiv_geschieht_nichts(conn, tmp_path) -> None:
    """Ohne Archiv bleibt die Anwendung leer -- aber sie stuerzt nicht ab."""
    ergebnis = bootstrap.sicherstellen(conn, tmp_path / "gibtesnicht")

    assert ergebnis["aufgebaut"] is False
    assert "Kein Archiv" in str(ergebnis["grund"])
    assert not warehouse.ist_befuellt(conn)


def test_stammdaten_allein_gelten_nicht_als_archiv(conn, tmp_path) -> None:
    """Ohne Tagesstaende gibt es nichts aufzubauen."""
    load.lade_pokemon_dimension(conn, [_pokemon()])
    stammarchiv.exportiere_stammdaten(conn, tmp_path / "archiv")

    assert bootstrap.ist_aufbau_moeglich(tmp_path / "archiv") is False


def test_fortschritt_wird_von_null_bis_eins_gemeldet(archiv) -> None:
    """Die Anzeige waehrend des Aufbaus braucht einen brauchbaren Verlauf."""
    schritte: list[float] = []
    frisch = warehouse.verbindung(":memory:")
    try:
        bootstrap.sicherstellen(
            frisch, archiv, fortschritt=lambda anteil, _text: schritte.append(anteil))
    finally:
        frisch.close()

    assert schritte, "Es wurde kein Fortschritt gemeldet."
    assert schritte == sorted(schritte), f"Fortschritt springt zurueck: {schritte}"
    assert min(schritte) >= 0.0
    assert max(schritte) == pytest.approx(1.0)
