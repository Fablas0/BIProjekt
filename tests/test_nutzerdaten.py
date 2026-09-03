"""Tests der eigenen Datenhaltung: Konten, PC-System und Teams.

Zwei Dinge stehen im Mittelpunkt:

* **Trennung der Lebenszyklen.** Das Warehouse darf jederzeit verworfen und
  aus dem Archiv neu aufgebaut werden; die eigenen Daten muessen das
  ueberleben. Der Test dazu ist der wichtigste der Datei.
* **Anmeldesicherheit.** Passwoerter liegen nie im Klartext, gleiche
  Passwoerter ergeben verschiedene Hashes, und eine angehobene Iterationszahl
  entwertet bestehende Konten nicht.
"""

from __future__ import annotations

import pytest

from bi import nutzerdaten, warehouse


@pytest.fixture
def conn(tmp_path):
    """Warehouse-Verbindung mit angehaengter Nutzerdatenbank."""
    verbindung = warehouse.verbindung(str(tmp_path / "dwh.db"))
    nutzerdaten.anhaengen(verbindung, tmp_path / "nutzer.db")
    yield verbindung
    verbindung.close()


# --------------------------------------------------------------------------
# Konten
# --------------------------------------------------------------------------

def test_erstes_konto_ist_verwaltung(conn) -> None:
    erster = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    zweiter = nutzerdaten.anlegen(conn, "gast", "noch-ein-passwort")
    assert erster.ist_verwaltung
    assert not zweiter.ist_verwaltung


def test_passwort_liegt_nie_im_klartext(conn) -> None:
    nutzerdaten.anlegen(conn, "fabian", "mein-geheimes-passwort")
    zeile = conn.execute("SELECT * FROM nutzer.Nutzer").fetchone()
    assert "mein-geheimes-passwort" not in (zeile["passwort_hash"] + zeile["salz"])
    assert int(zeile["iterationen"]) >= 100_000


def test_gleiches_passwort_ergibt_verschiedene_hashes(conn) -> None:
    """Je Konto ein eigenes Salz -- sonst verriete der Hash gleiche Passwoerter."""
    nutzerdaten.anlegen(conn, "a", "dasselbe-passwort")
    nutzerdaten.anlegen(conn, "b", "dasselbe-passwort")
    hashes = [z["passwort_hash"] for z in conn.execute("SELECT passwort_hash FROM nutzer.Nutzer")]
    assert hashes[0] != hashes[1]


def test_anmeldung_mit_richtigem_und_falschem_passwort(conn) -> None:
    nutzerdaten.anlegen(conn, "fabian", "richtiges-passwort")
    assert nutzerdaten.anmelden(conn, "fabian", "richtiges-passwort") is not None
    assert nutzerdaten.anmelden(conn, "fabian", "falsches-passwort") is None
    assert nutzerdaten.anmelden(conn, "unbekannt", "egal-was-hier-steht") is None


def test_benutzername_ist_unabhaengig_von_gross_und_kleinschreibung(conn) -> None:
    nutzerdaten.anlegen(conn, "Fabian", "richtiges-passwort")
    with pytest.raises(ValueError, match="vergeben"):
        nutzerdaten.anlegen(conn, "fabian", "anderes-passwort")
    assert nutzerdaten.anmelden(conn, "fabian", "richtiges-passwort") is not None


def test_zu_kurzes_passwort_wird_abgelehnt(conn) -> None:
    with pytest.raises(ValueError, match="10 Zeichen"):
        nutzerdaten.anlegen(conn, "fabian", "kurz")


def test_fehlversuche_werden_protokolliert(conn) -> None:
    nutzerdaten.anlegen(conn, "fabian", "richtiges-passwort")
    for _ in range(3):
        nutzerdaten.anmelden(conn, "fabian", "falsches-passwort")
    assert nutzerdaten.fehlversuche_seit(conn, "fabian", "2000-01-01") == 3


def test_hoehere_iterationszahl_entwertet_konten_nicht(conn, monkeypatch) -> None:
    """Beim naechsten Anmelden wird der Hash mit dem neuen Aufwand neu gebildet."""
    nutzerdaten.anlegen(conn, "fabian", "richtiges-passwort")
    conn.execute("UPDATE nutzer.Nutzer SET iterationen = 100000, passwort_hash = ?",
                 (nutzerdaten._hash("richtiges-passwort",
                                    conn.execute("SELECT salz FROM nutzer.Nutzer").fetchone()[0],
                                    100000),))
    conn.commit()

    assert nutzerdaten.anmelden(conn, "fabian", "richtiges-passwort") is not None
    neu = conn.execute("SELECT iterationen FROM nutzer.Nutzer").fetchone()[0]
    assert int(neu) > 100000
    # Und die Anmeldung funktioniert mit dem neuen Hash weiterhin.
    assert nutzerdaten.anmelden(conn, "fabian", "richtiges-passwort") is not None


def test_passwort_aendern_prueft_das_bisherige(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "altes-passwort-1")
    with pytest.raises(ValueError, match="stimmt nicht"):
        nutzerdaten.passwort_aendern(conn, nutzer.nutzer_id, "falsch", "neues-passwort-1")
    nutzerdaten.passwort_aendern(conn, nutzer.nutzer_id, "altes-passwort-1", "neues-passwort-1")
    assert nutzerdaten.anmelden(conn, "fabian", "neues-passwort-1") is not None
    assert nutzerdaten.anmelden(conn, "fabian", "altes-passwort-1") is None


# --------------------------------------------------------------------------
# PC-System und Teams
# --------------------------------------------------------------------------

def _box_satz(**abweichungen) -> dict:
    satz = {
        "slug": "garchomp", "spitzname": "Knacki", "item_slug": "choicescarf",
        "faehigkeit_slug": "roughskin", "wesen": "Jolly",
        "punkte_hp": 2, "punkte_attack": 32, "punkte_speed": 32,
        "attacken": ["earthquake", "dragonclaw", "protect", "swordsdance"],
        "notiz": "Standard-Set",
    }
    satz.update(abweichungen)
    return satz


def test_box_eintrag_anlegen_lesen_aendern_loeschen(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    box_id = nutzerdaten.box_speichern(conn, nutzer.nutzer_id, _box_satz())

    eintraege = nutzerdaten.box_lesen(conn, nutzer.nutzer_id)
    assert len(eintraege) == 1
    assert eintraege[0]["slug"] == "garchomp"
    assert eintraege[0]["attacken"] == ["earthquake", "dragonclaw", "protect", "swordsdance"]

    nutzerdaten.box_speichern(conn, nutzer.nutzer_id, _box_satz(spitzname="Neu"), box_id)
    assert nutzerdaten.box_lesen(conn, nutzer.nutzer_id)[0]["spitzname"] == "Neu"

    nutzerdaten.box_loeschen(conn, nutzer.nutzer_id, box_id)
    assert nutzerdaten.box_lesen(conn, nutzer.nutzer_id) == []


def test_box_ist_je_nutzer_getrennt(conn) -> None:
    """Die Kernzusage der Kontenbildung: niemand sieht fremde Daten."""
    a = nutzerdaten.anlegen(conn, "a", "sicheres-passwort")
    b = nutzerdaten.anlegen(conn, "b", "sicheres-passwort")
    nutzerdaten.box_speichern(conn, a.nutzer_id, _box_satz())
    assert nutzerdaten.box_lesen(conn, b.nutzer_id) == []
    # Auch ein Aenderungsversuch mit fremder Nutzerkennung laeuft ins Leere.
    fremde_id = nutzerdaten.box_lesen(conn, a.nutzer_id)[0]["box_id"]
    nutzerdaten.box_speichern(conn, b.nutzer_id, _box_satz(spitzname="Gekapert"), fremde_id)
    assert nutzerdaten.box_lesen(conn, a.nutzer_id)[0]["spitzname"] == "Knacki"


def test_mehr_als_vier_attacken_werden_beschnitten(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    nutzerdaten.box_speichern(conn, nutzer.nutzer_id,
                              _box_satz(attacken=["a", "b", "c", "d", "e"]))
    assert len(nutzerdaten.box_lesen(conn, nutzer.nutzer_id)[0]["attacken"]) == 4


def test_team_mit_hoechstens_sechs_mitgliedern(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    box_ids = [nutzerdaten.box_speichern(conn, nutzer.nutzer_id, _box_satz(spitzname=str(i)))
               for i in range(7)]
    with pytest.raises(ValueError, match="sechs"):
        nutzerdaten.team_speichern(conn, nutzer.nutzer_id, "Zu gross", box_ids)

    team_id = nutzerdaten.team_speichern(conn, nutzer.nutzer_id, "Turnier", box_ids[:6])
    teams = nutzerdaten.teams_lesen(conn, nutzer.nutzer_id)
    assert len(teams) == 1
    assert len(teams[0]["mitglieder"]) == 6
    assert [m["position"] for m in teams[0]["mitglieder"]] == [1, 2, 3, 4, 5, 6]

    nutzerdaten.team_loeschen(conn, nutzer.nutzer_id, team_id)
    assert nutzerdaten.teams_lesen(conn, nutzer.nutzer_id) == []


def test_box_loeschen_raeumt_teamzuordnung_auf(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    box_id = nutzerdaten.box_speichern(conn, nutzer.nutzer_id, _box_satz())
    nutzerdaten.team_speichern(conn, nutzer.nutzer_id, "Turnier", [box_id])
    nutzerdaten.box_loeschen(conn, nutzer.nutzer_id, box_id)
    assert nutzerdaten.teams_lesen(conn, nutzer.nutzer_id)[0]["mitglieder"] == []


# --------------------------------------------------------------------------
# Trennung der Lebenszyklen
# --------------------------------------------------------------------------

def test_eigene_daten_ueberleben_das_zuruecksetzen_des_warehouse(tmp_path) -> None:
    """Der wichtigste Test der Datei.

    Das Warehouse wird geleert und die Verbindung neu aufgebaut -- genau das
    geschieht bei jedem Kaltstart in der Cloud. Konten, Box und Teams muessen
    unveraendert vorhanden sein.
    """
    conn = warehouse.verbindung(str(tmp_path / "dwh.db"))
    nutzerdaten.anhaengen(conn, tmp_path / "nutzer.db")
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    box_id = nutzerdaten.box_speichern(conn, nutzer.nutzer_id, _box_satz())
    nutzerdaten.team_speichern(conn, nutzer.nutzer_id, "Turnier", [box_id])

    warehouse.zuruecksetzen(conn, archiv_verwerfen=True)
    conn.close()

    frisch = warehouse.verbindung(str(tmp_path / "dwh.db"))
    nutzerdaten.anhaengen(frisch, tmp_path / "nutzer.db")
    assert nutzerdaten.anmelden(frisch, "fabian", "sicheres-passwort") is not None
    assert len(nutzerdaten.box_lesen(frisch, nutzer.nutzer_id)) == 1
    assert len(nutzerdaten.teams_lesen(frisch, nutzer.nutzer_id)) == 1
    frisch.close()


def test_box_verknuepft_sich_mit_den_stammdaten(conn) -> None:
    """Ueber den natuerlichen Schluessel, ueber die Schemagrenze hinweg."""
    from bi.etl import load
    from bi.etl.transform import zeilen_hash

    load.lade_pokemon_dimension(conn, [{
        "pokedex_id": 445, "slug": "garchomp", "anzeigename": "Knackrack",
        "spezies": "garchomp", "generation": 4, "typ1": "Dragon", "typ2": "Ground",
        "typ_kombination": "Dragon / Ground",
        "hp": 108, "attack": 130, "defense": 95, "sp_attack": 80,
        "sp_defense": 85, "speed": 102,
        "stufe50_hp": 183, "stufe50_attack": 150, "stufe50_defense": 115,
        "stufe50_sp_attack": 100, "stufe50_sp_defense": 105, "stufe50_speed": 122,
        "basiswert_summe": 600, "offensiv_profil": "Physisch",
        "rolle": "Sweeper", "speed_klasse": "Schnell (100-119)",
        "resistenz_wert": 1.0, "row_hash": zeilen_hash({"slug": "garchomp"}),
    }], "2026-07-01")

    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    nutzerdaten.box_speichern(conn, nutzer.nutzer_id, _box_satz())
    eintrag = nutzerdaten.box_lesen(conn, nutzer.nutzer_id)[0]
    assert eintrag["anzeigename"] == "Knackrack"
    assert eintrag["typ1"] == "Dragon"
    assert eintrag["attack"] == 130


def test_bestand_zaehlt_die_eigene_datenhaltung(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    nutzerdaten.box_speichern(conn, nutzer.nutzer_id, _box_satz())
    zahlen = nutzerdaten.bestand(conn)
    assert zahlen["nutzer"] == 1
    assert zahlen["box_eintraege"] == 1
    assert zahlen["shiny_jagden"] == 0
    assert zahlen["spielstaende"] == 0
    assert zahlen["karten"] == 0


def test_box_kennt_shiny_und_herkunft(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    nutzerdaten.box_speichern(conn, nutzer.nutzer_id,
                              _box_satz(ist_shiny=True, herkunft="Platin"))
    nutzerdaten.box_speichern(conn, nutzer.nutzer_id, _box_satz())
    eintraege = nutzerdaten.box_lesen(conn, nutzer.nutzer_id)
    assert (eintraege[0]["ist_shiny"], eintraege[0]["herkunft"]) == (1, "Platin")
    assert (eintraege[1]["ist_shiny"], eintraege[1]["herkunft"]) == (0, None)


def test_bestehende_nutzerdatenbank_bekommt_neue_spalten(tmp_path) -> None:
    """Die Nutzerdatenbank ist nicht wiederbeschaffbar. Eine Datei aus der
    ersten Fassung -- ohne Shiny-Kennzeichen und Herkunft -- muss beim
    naechsten Anhaengen die Spalten bekommen, ohne einen Eintrag zu verlieren."""
    import sqlite3

    alt = sqlite3.connect(tmp_path / "nutzer.db")
    alt.executescript("""
        CREATE TABLE Nutzer (nutzer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            benutzername TEXT NOT NULL UNIQUE COLLATE NOCASE, anzeigename TEXT NOT NULL,
            passwort_hash TEXT NOT NULL, salz TEXT NOT NULL,
            verfahren TEXT NOT NULL DEFAULT 'pbkdf2_sha256', iterationen INTEGER NOT NULL,
            rolle TEXT NOT NULL DEFAULT 'spieler', angelegt_am TEXT NOT NULL,
            letzte_anmeldung TEXT, ist_aktiv INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE Box_Pokemon (box_id INTEGER PRIMARY KEY AUTOINCREMENT,
            nutzer_id INTEGER NOT NULL, slug TEXT NOT NULL, spitzname TEXT,
            item_slug TEXT, faehigkeit_slug TEXT, wesen TEXT NOT NULL DEFAULT 'Hardy',
            punkte_hp INTEGER NOT NULL DEFAULT 0, punkte_attack INTEGER NOT NULL DEFAULT 0,
            punkte_defense INTEGER NOT NULL DEFAULT 0,
            punkte_sp_attack INTEGER NOT NULL DEFAULT 0,
            punkte_sp_defense INTEGER NOT NULL DEFAULT 0,
            punkte_speed INTEGER NOT NULL DEFAULT 0,
            attacken TEXT NOT NULL DEFAULT '[]', notiz TEXT,
            angelegt_am TEXT NOT NULL, geaendert_am TEXT NOT NULL);
        INSERT INTO Nutzer (benutzername, anzeigename, passwort_hash, salz, iterationen,
                            angelegt_am) VALUES ('alt', 'alt', 'x', 'ab', 1, '2026-01-01');
        INSERT INTO Box_Pokemon (nutzer_id, slug, angelegt_am, geaendert_am)
             VALUES (1, 'garchomp', '2026-01-01', '2026-01-01');
    """)
    alt.commit()
    alt.close()

    conn = warehouse.verbindung(str(tmp_path / "dwh.db"))
    nutzerdaten.anhaengen(conn, tmp_path / "nutzer.db")
    eintrag = nutzerdaten.box_lesen(conn, 1)[0]
    assert eintrag["slug"] == "garchomp"
    assert eintrag["ist_shiny"] == 0
    assert eintrag["herkunft"] is None
    # Und die neuen Tabellen sind da.
    assert nutzerdaten.bestand(conn)["shiny_jagden"] == 0
    conn.close()
