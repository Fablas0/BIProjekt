"""Tests der Stammdaten aus den Hauptspielen: Items und Faehigkeiten.

Pokemon Champions nennt das getragene Item und die Faehigkeit nur beim Namen.
Was sie *tun*, steht ausschliesslich in den Hauptspielen und kommt ueber die
PokeAPI. Diese Tests sichern die Verknuepfung beider Quellen ab -- sie ist die
Stelle, an der die Namensschreibweisen auseinanderlaufen (``"Never-Melt Ice"``
gegen ``"never-melt-ice"``).

Alle Tests kommen ohne Netzzugriff aus; die Quellnutzlasten sind nachgebildet.
"""

from __future__ import annotations

import pytest

from bi import warehouse
from bi.etl import load
from bi.etl.champions import stammschluessel
from bi.etl.transform import item_klasse, transformiere_faehigkeit, transformiere_item


def _item(name: str, kategorie: str = "held-items", **abweichungen) -> dict:
    nutzlast = {
        "name": name,
        "category": {"name": kategorie},
        "fling_power": 30,
        "effect_entries": [
            {"language": {"name": "de"}, "short_effect": "Deutscher Text"},
            {"language": {"name": "en"}, "short_effect": "Holder's  Attack is raised."},
        ],
    }
    nutzlast.update(abweichungen)
    return nutzlast


# --------------------------------------------------------------------------
# Transformation
# --------------------------------------------------------------------------

def test_item_wird_auf_den_verknuepfungsschluessel_gebracht() -> None:
    """Der Schluessel muss zu dem passen, was aus dem Champions-Namen entsteht."""
    satz = transformiere_item(_item("never-melt-ice"))
    assert satz["slug"] == "nevermeltice"
    assert satz["slug"] == stammschluessel("Never-Melt Ice")
    assert satz["pokeapi_slug"] == "never-melt-ice"
    assert satz["anzeigename"] == "Never Melt Ice"


def test_item_kurztext_wird_englisch_und_normalisiert_uebernommen() -> None:
    """Deutsch ist bei Items nur lueckenhaft gepflegt; Mehrfachleerzeichen fallen weg."""
    satz = transformiere_item(_item("choice-band"))
    assert satz["effekt_kurz"] == "Holder's Attack is raised."


def test_item_ohne_kurztext_bleibt_leer() -> None:
    satz = transformiere_item(_item("mystery-item", effect_entries=[]))
    assert satz["effekt_kurz"] is None


@pytest.mark.parametrize(("slug", "kategorie", "klasse"), [
    ("choiceband", "choice", "Wahl-Item"),
    ("choicescarf", "choice", "Wahl-Item"),
    ("lifeorb", "held-items", "Schadensverstaerkung"),
    ("focussash", "held-items", "Ueberleben"),
    ("sitrusberry", "medicine", "Ueberleben"),
    ("oranberry", "medicine", "Beere"),
    ("splashplate", "plates", "Typverstaerkung"),
    ("charizarditex", "mega-stones", "Formwandel"),
    ("pokeball", "standard-balls", "Sonstige"),
])
def test_wirkungsklassen_der_items(slug: str, kategorie: str, klasse: str) -> None:
    """Die Klassifikation richtet sich nach der Wirkung im Kampf, nicht nach
    der am Verkaufsort orientierten Kategorie der PokeAPI."""
    assert item_klasse(slug, kategorie) == klasse


def test_nicht_kampfrelevante_items_werden_gekennzeichnet_nicht_verworfen() -> None:
    """Die Quelle soll vollstaendig abgebildet bleiben."""
    ball = transformiere_item(_item("poke-ball", "standard-balls"))
    assert ball["ist_kampfrelevant"] == 0
    assert ball["slug"] == "pokeball"


def test_faehigkeit_wird_klassifiziert_und_datiert() -> None:
    satz = transformiere_faehigkeit({
        "name": "drizzle",
        "generation": {"name": "generation-iii"},
        "effect_entries": [{"language": {"name": "en"}, "short_effect": "Summons rain."}],
    })
    assert satz["slug"] == "drizzle"
    assert satz["wirkung_klasse"] == "Wetter"
    assert satz["generation"] == 3
    assert satz["effekt_kurz"] == "Summons rain."


def test_faehigkeit_mit_bindestrich_im_namen() -> None:
    satz = transformiere_faehigkeit({"name": "flash-fire", "generation": {"name": "generation-iii"}})
    assert satz["slug"] == stammschluessel("Flash Fire")
    assert satz["anzeigename"] == "Flash Fire"


def test_unbekannte_generation_bleibt_leer() -> None:
    satz = transformiere_faehigkeit({"name": "irgendwas", "generation": {}})
    assert satz["generation"] is None


# --------------------------------------------------------------------------
# Laden und Verknuepfen
# --------------------------------------------------------------------------

@pytest.fixture
def conn():
    verbindung = warehouse.verbindung(":memory:")
    yield verbindung
    verbindung.close()


def test_dimensionen_werden_geladen_und_sind_idempotent(conn) -> None:
    saetze = [transformiere_item(_item("focus-sash")), transformiere_item(_item("life-orb"))]
    load.lade_item_dimension(conn, saetze)
    load.lade_item_dimension(conn, saetze)
    assert conn.execute("SELECT COUNT(*) FROM Dim_Item").fetchone()[0] == 2

    faehigkeiten = [transformiere_faehigkeit({"name": "intimidate", "generation": {}})]
    load.lade_faehigkeit_dimension(conn, faehigkeiten)
    load.lade_faehigkeit_dimension(conn, faehigkeiten)
    assert conn.execute("SELECT COUNT(*) FROM Dim_Faehigkeit").fetchone()[0] == 1


def test_geaenderte_stammdaten_werden_uebernommen(conn) -> None:
    """Ein spaeterer Lauf mit besseren Daten muss den Satz aktualisieren."""
    load.lade_item_dimension(conn, [transformiere_item(_item("focus-sash", effect_entries=[]))])
    load.lade_item_dimension(conn, [transformiere_item(_item("focus-sash"))])
    zeile = conn.execute("SELECT effekt_kurz FROM Dim_Item WHERE slug = 'focussash'").fetchone()
    assert zeile["effekt_kurz"] == "Holder's Attack is raised."


def test_deutscher_name_wird_uebernommen_und_nicht_getilgt(conn) -> None:
    """Der Name kommt aus dem names-Block; ein Lauf ohne ihn tilgt nichts."""
    mit_namen = transformiere_item(_item(
        "focus-sash", names=[{"language": {"name": "de"}, "name": "Fokusband"}]))
    assert mit_namen["name_de"] == "Fokusband"
    load.lade_item_dimension(conn, [mit_namen])

    ohne_namen = transformiere_item(_item("focus-sash"))
    assert ohne_namen["name_de"] is None
    load.lade_item_dimension(conn, [ohne_namen])

    zeile = conn.execute("SELECT name_de FROM Dim_Item WHERE slug = 'focussash'").fetchone()
    assert zeile["name_de"] == "Fokusband"


def test_merkmalsfakt_traegt_die_neuen_fremdschluessel(conn) -> None:
    """Die Sicht muss Itemwirkung und Faehigkeitswirkung mitliefern."""
    spalten = {z[1] for z in conn.execute("PRAGMA table_info(Fact_Champions_Merkmal)")}
    assert {"item_sk", "faehigkeit_sk"} <= spalten

    sichtspalten = {z[1] for z in conn.execute("PRAGMA table_info(V_Merkmal)")}
    assert {"item_klasse", "item_effekt", "faehigkeit_klasse"} <= sichtspalten


def test_bestehende_datenbank_wird_nachgezogen(tmp_path) -> None:
    """Eine Datenbank aus der Zeit vor den neuen Spalten muss weiterlaufen.

    ``CREATE TABLE IF NOT EXISTS`` ruehrt eine vorhandene Tabelle nicht an --
    ohne das Nachziehen fehlten die Spalten dauerhaft. Neu aufbauen scheidet
    aus: das Rohdatenarchiv haelt Tagesstaende, die die Quelle laengst
    vergessen hat.
    """
    import sqlite3

    pfad = tmp_path / "alt.db"
    alt = sqlite3.connect(pfad)
    alt.executescript("""
        CREATE TABLE Fact_Champions_Merkmal (
            pokemon_sk INTEGER NOT NULL, zeit_sk INTEGER NOT NULL,
            saison_sk INTEGER NOT NULL, kampfformat_sk INTEGER NOT NULL,
            kategorie TEXT NOT NULL, rang INTEGER NOT NULL,
            bezeichnung TEXT NOT NULL, anteil REAL, attacke_sk INTEGER,
            PRIMARY KEY (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, kategorie, rang));
        INSERT INTO Fact_Champions_Merkmal VALUES (1, 20260728, 1, 1, 'move', 1, 'Blizzard', 96.6, NULL);
    """)
    alt.commit()
    alt.close()

    conn = warehouse.verbindung(str(pfad))
    spalten = {z[1] for z in conn.execute("PRAGMA table_info(Fact_Champions_Merkmal)")}
    assert {"item_sk", "faehigkeit_sk"} <= spalten
    # Der Bestand bleibt erhalten.
    assert conn.execute("SELECT COUNT(*) FROM Fact_Champions_Merkmal").fetchone()[0] == 1
    conn.close()


def test_stammarchiv_sichert_die_neuen_dimensionen(conn, tmp_path) -> None:
    """Ohne Sicherung muesste ein Kaltstart sie erneut ueber das Netz holen."""
    from bi.etl import stammarchiv

    assert "Dim_Item" in stammarchiv.STAMMTABELLEN
    assert "Dim_Faehigkeit" in stammarchiv.STAMMTABELLEN

    load.lade_item_dimension(conn, [transformiere_item(_item("focus-sash"))])
    load.lade_faehigkeit_dimension(conn, [transformiere_faehigkeit(
        {"name": "intimidate", "generation": {"name": "generation-iii"}})])
    stammarchiv.exportiere_stammdaten(conn, tmp_path)

    frisch = warehouse.verbindung(":memory:")
    stammarchiv.importiere_stammdaten(frisch, tmp_path)
    assert frisch.execute("SELECT slug FROM Dim_Item").fetchone()["slug"] == "focussash"
    assert frisch.execute(
        "SELECT wirkung_klasse FROM Dim_Faehigkeit").fetchone()["wirkung_klasse"] == "Stoerung"
    frisch.close()
