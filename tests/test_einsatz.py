"""Tests des Einsatzchecks: Box gegen die drei Spielformen.

Der Check darf keine stumme Luecke lassen: zu jedem Pokemon und jeder
Spielform gibt es genau einen Befund -- auch dann, wenn die Quelle nichts
fuehrt oder gar nicht geladen ist. Und er muss der Saisonauswahl folgen wie
jede andere Auswertung.
"""

from __future__ import annotations

import pytest

from bi import warehouse
from bi.analytics import einsatz
from bi.etl import go, load
from bi.etl.transform import transformiere_pokemon


@pytest.fixture
def conn():
    """Warehouse mit zwei Saisons: Garchomp fuehrt M4, Incineroar M5."""
    verbindung = warehouse.verbindung(":memory:")
    verbindung.executescript("""
        INSERT INTO Dim_Quelle (quelle_sk, schluessel, name, beschreibung,
                                ist_offiziell, granularitaet_zeit,
                                messniveau_nutzung, hat_partner_gewicht)
             VALUES (1, 'champions', 'Pokemon Champions', 'Testquelle',
                     1, 'Tag', 'ordinal', 1);
        INSERT INTO Dim_Kampfformat (kampfformat_sk, schluessel, bezeichnung,
                                     aktive_pokemon, mitnahme)
             VALUES (1, 'Doubles', 'Doppelkampf', 2, 4);
        INSERT INTO Dim_Saison (saison_sk, schluessel, bezeichnung, quelle_sk,
                                beginn, ende, ist_aktuell, erfasst_am)
             VALUES (1, 'M4', 'Season 4', 1, '2026-07-01', '2026-07-31', 0, '2026-08-01'),
                    (2, 'M5', 'Season 5', 1, '2026-08-01', '2026-08-31', 1, '2026-08-01');
    """)
    zeit = load.lade_zeit(verbindung, ["2026-07-20", "2026-08-10"])
    lauf_id = load.lauf_beginnen(verbindung, "Champions", "Test")

    for slug, pid in (("garchomp", 445), ("incineroar", 727), ("bidoof", 399)):
        nutzlast = {
            "id": pid, "name": slug, "species": {"name": slug},
            "types": [{"type": {"name": "dragon"}}],
            "stats": [{"stat": {"name": s}, "base_stat": 100} for s in
                      ("hp", "attack", "defense", "special-attack",
                       "special-defense", "speed")],
        }
        satz, _ = transformiere_pokemon(nutzlast, {slug: 4})
        load.lade_pokemon_dimension(verbindung, [satz])

    verbindung.executemany(
        f"""INSERT INTO Fact_Champions_Usage
               (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, quelle_sk,
                rang, rang_perzentil, erfasste_pokemon, etl_lauf_id)
           VALUES (?, ?, ?, ?, 1, ?, ?, 2, {lauf_id})""",
        [(1, zeit["2026-07-20"], 1, 1, 1, 100.0),
         (2, zeit["2026-07-20"], 1, 1, 80, 50.0),
         (2, zeit["2026-08-10"], 2, 1, 1, 100.0),
         (1, zeit["2026-08-10"], 2, 1, 80, 50.0)])
    verbindung.commit()
    yield verbindung
    verbindung.close()


def test_jede_spielform_liefert_genau_einen_befund(conn) -> None:
    ergebnis = einsatz.pruefen(conn, ["garchomp", "bidoof", "bidoof", ""])
    assert set(ergebnis) == {"garchomp", "bidoof"}
    for check in ergebnis.values():
        assert [b.spielform for b in check.befunde] == [
            "Champions Doubles", "Pokemon GO", "Sammelkartenspiel"]


def test_champions_urteil_folgt_der_ranggrenze(conn) -> None:
    ergebnis = einsatz.pruefen(conn, ["garchomp", "incineroar", "bidoof"])
    assert ergebnis["incineroar"].befund("Champions Doubles").urteil == "meta"
    assert ergebnis["garchomp"].befund("Champions Doubles").urteil == "spielbar"
    assert ergebnis["bidoof"].befund("Champions Doubles").urteil == "kein_einsatz"
    assert ergebnis["bidoof"].befund("Pokemon GO").urteil == "unbekannt"
    assert ergebnis["incineroar"].bestes_urteil == "meta"
    assert ergebnis["bidoof"].bestes_urteil == "kein_einsatz"


def test_einsatzcheck_folgt_der_saisonauswahl(conn) -> None:
    """In M4 fuehrte Garchomp -- der Check muss das nachvollziehen."""
    conn.saison_wahl = "M4"
    ergebnis = einsatz.pruefen(conn, ["garchomp", "incineroar"])
    assert ergebnis["garchomp"].befund("Champions Doubles").rang == 1
    assert ergebnis["incineroar"].befund("Champions Doubles").urteil == "spielbar"


def test_go_urteil_nimmt_die_beste_liga(conn) -> None:
    go.lade_stand(conn, "2026-08-18", "great",
                  [{"speciesId": "garchomp", "score": 70.0}], 1)
    go.lade_stand(conn, "2026-08-18", "master",
                  [{"speciesId": "garchomp", "score": 91.0},
                   {"speciesId": "garchomp_shadow", "score": 95.0}], 1)
    befund = einsatz.pruefen(conn, ["garchomp", "bidoof"])["garchomp"].befund("Pokemon GO")
    assert befund.urteil == "meta"
    assert befund.score == 91.0, "Schattenformen zaehlen nicht fuer die eigene Box."
    assert "Meisterliga" in befund.text
    assert einsatz.pruefen(conn, ["bidoof"])["bidoof"].befund("Pokemon GO").urteil == "kein_einsatz"


def test_bedeutung_bleibt_eine_aussage() -> None:
    """Jedes Urteil bildet auf eine der vier Bedeutungen des Designsystems ab."""
    from bi.ui import design

    for urteil in einsatz.URTEILE:
        assert einsatz.URTEIL_BEDEUTUNG[urteil] in design.BEDEUTUNGEN
        assert urteil in einsatz.URTEIL_TEXT
