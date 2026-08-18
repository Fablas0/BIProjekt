"""Tests des Hypothesenkatalogs.

Geprueft wird gegen ein **kuenstliches Warehouse mit bekannter Wahrheit**: die
Testdaten sind so gebaut, dass das Ergebnis jeder Hypothese vorab feststeht.
Ein Katalog, der auf echten Daten "irgendetwas" ausgibt, waere nicht pruefbar --
hier ist er es.

Zusaetzlich wird das Verhalten an den Raendern abgesichert: eine Hypothese ohne
Datenbasis muss als *nicht pruefbar* ausgewiesen werden und darf weder als
bestaetigt noch als widerlegt gelten, und sie darf die Holm-Korrektur der
uebrigen nicht verschaerfen.
"""

from __future__ import annotations

import pytest

from bi.analytics import hypothesen
from bi.analytics.pruefverfahren import DatenbasisFehlt, Pruefgroesse
from bi.etl import load
from bi.etl.transform import zeilen_hash

TAGE = ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
        "2026-07-24", "2026-07-25", "2026-07-26", "2026-07-27"]

TYPEN = ["Fire", "Water", "Grass", "Electric", "Dragon"]


def _pokemon_satz(nummer: int) -> dict:
    """Ein Dimensionssatz mit systematisch variierten Merkmalen.

    Initiative und Basiswertsumme steigen mit der Nummer -- und die Nummer
    bestimmt spaeter den Rang. Damit ist der Zusammenhang, den H2 und H3
    suchen, in den Daten mit bekannter Staerke angelegt.
    """
    speed = 40 + nummer * 3
    return {
        "pokedex_id": 1000 + nummer,
        "slug": f"testmon-{nummer:03d}",
        "anzeigename": f"Testmon {nummer:03d}",
        "spezies": f"testmon-{nummer:03d}",
        "generation": 9,
        "typ1": TYPEN[nummer % len(TYPEN)],
        "typ2": None,
        "typ_kombination": TYPEN[nummer % len(TYPEN)],
        "hp": 80, "attack": 100, "defense": 80,
        "sp_attack": 90, "sp_defense": 80, "speed": speed,
        "stufe50_hp": 160, "stufe50_attack": 120, "stufe50_defense": 100,
        "stufe50_sp_attack": 110, "stufe50_sp_defense": 100,
        "stufe50_speed": speed,
        "basiswert_summe": 430 + nummer * 3,
        "offensiv_profil": ["Physisch", "Speziell", "Gemischt"][nummer % 3],
        "rolle": "Sweeper", "speed_klasse": "Schnell", "resistenz_wert": 1.0,
        "row_hash": zeilen_hash({"slug": f"testmon-{nummer:03d}", "nr": nummer}),
    }


@pytest.fixture
def warehouse_mit_bekannter_wahrheit(tmp_path):
    """Ein kleines, vollstaendiges Warehouse mit vorab bekannten Zusammenhaengen.

    Angelegt sind 40 Pokemon an acht Tagen in beiden Kampfformaten:

    * Der Rang folgt im Doppelkampf umgekehrt der Initiative -- H2 muss
      anschlagen.
    * Im Einzelkampf ist die Reihenfolge dieselbe, nur leicht verschoben --
      H4 muss einen starken, aber nicht vollstaendigen Zusammenhang finden.
    * Flaechenattacken kommen ausschliesslich im Doppelkampf vor -- H5 muss
      anschlagen.
    """
    from bi import warehouse

    conn = warehouse.verbindung(str(tmp_path / "test.db"))
    quelle_sk = load.lade_quelle(conn, "champions")
    formate = load.lade_alle_kampfformate(conn)
    zeit = load.lade_zeit(conn, TAGE)
    saison_sk = load.lade_saison(conn, "T1", "Testsaison", quelle_sk, TAGE)
    load.lade_pokemon_dimension(conn, [_pokemon_satz(i) for i in range(40)], TAGE[0])
    load.lade_attacken_dimension(conn, [
        {"slug": "flaechenschlag", "anzeigename": "Flaechenschlag", "typ": "Fire",
         "kategorie": "physical", "basisschaden": 90, "genauigkeit": 100,
         "prioritaet": 0, "zielbereich": "all-opponents", "taktik_klasse": "Offensiv"},
        {"slug": "einzelschlag", "anzeigename": "Einzelschlag", "typ": "Water",
         "kategorie": "physical", "basisschaden": 90, "genauigkeit": 100,
         "prioritaet": 0, "zielbereich": "selected-pokemon", "taktik_klasse": "Offensiv"},
        {"slug": "bizarroraum", "anzeigename": "Bizarroraum", "typ": "Psychic",
         "kategorie": "status", "basisschaden": None, "genauigkeit": None,
         "prioritaet": -7, "zielbereich": "entire-field", "taktik_klasse": "Bizarroraum"},
    ])

    pokemon = {z["slug"]: z["pokemon_sk"] for z in
               conn.execute("SELECT slug, pokemon_sk FROM Dim_Pokemon")}
    attacken = {z["slug"]: z["attacke_sk"] for z in
                conn.execute("SELECT slug, attacke_sk FROM Dim_Attacke")}

    for tag in TAGE:
        for kampfformat, versatz in (("Doubles", 0), ("Singles", 3)):
            for nummer in range(40):
                slug = f"testmon-{nummer:03d}"
                # Schnellere Pokemon (hohe Nummer) erhalten den besseren Rang.
                rang = 40 - nummer + (versatz if nummer % 4 == 0 else 0)
                conn.execute(
                    """INSERT INTO Fact_Champions_Usage
                       (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, quelle_sk,
                        rang, rang_perzentil, erfasste_pokemon, etl_lauf_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 40, 0)""",
                    (pokemon[slug], zeit[tag], saison_sk, formate[kampfformat],
                     quelle_sk, rang, round(100 * (40 - rang) / 39, 2)))

                merkmale = [
                    ("move", 1, "Einzelschlag", 90.0, attacken["einzelschlag"]),
                    ("held_item", 1, "Fokusgurt" if nummer % 3 else "Leben-Orb", 70.0, None),
                ]
                if kampfformat == "Doubles":
                    merkmale.append(
                        ("move", 2, "Flaechenschlag", 60.0, attacken["flaechenschlag"]))
                # Die zehn langsamsten Pokemon fuehren Bizarroraum -- H9.
                if nummer < 10:
                    merkmale.append(("move", 3, "Bizarroraum", 55.0, attacken["bizarroraum"]))

                for kategorie, rang_merkmal, bezeichnung, anteil, attacke_sk in merkmale:
                    conn.execute(
                        """INSERT INTO Fact_Champions_Merkmal
                           (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, kategorie,
                            rang, bezeichnung, anteil, attacke_sk)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (pokemon[slug], zeit[tag], saison_sk, formate[kampfformat],
                         kategorie, rang_merkmal, bezeichnung, anteil, attacke_sk))
    conn.commit()
    yield conn
    conn.close()


# --------------------------------------------------------------------------
# Aufbau des Katalogs
# --------------------------------------------------------------------------

def test_katalog_ist_vollstaendig_beschrieben() -> None:
    """Jede Hypothese muss vor der Auswertung vollstaendig formuliert sein."""
    assert hypothesen.KATALOG, "Der Katalog ist leer."
    for hypothese in hypothesen.KATALOG:
        for feld in ("titel", "nullhypothese", "alternativhypothese", "begruendung",
                     "verfahren", "datenbasis", "bei_verwerfung", "bei_beibehaltung"):
            wert = getattr(hypothese, feld)
            assert wert and len(wert) > 20, f"{hypothese.schluessel}: {feld} fehlt"


def test_schluessel_sind_eindeutig() -> None:
    schluessel = [h.schluessel for h in hypothesen.KATALOG]
    assert len(schluessel) == len(set(schluessel))


def test_nullhypothese_ist_als_verneinung_formuliert() -> None:
    """Die Nullhypothese muss die Aussage sein, die widerlegt werden soll."""
    for hypothese in hypothesen.KATALOG:
        text = hypothese.nullhypothese.lower()
        assert any(wort in text for wort in
                   ("kein", "nicht", "unabhaengig", "gleich", "entspricht")), \
            f"{hypothese.schluessel}: H0 ist nicht als Verneinung formuliert."


# --------------------------------------------------------------------------
# Pruefung gegen bekannte Wahrheit
# --------------------------------------------------------------------------

def test_initiative_wird_erkannt(warehouse_mit_bekannter_wahrheit) -> None:
    """Rang und Initiative sind gegenlaeufig angelegt -- das muss anschlagen."""
    ergebnis = hypothesen._pruefe_initiative(warehouse_mit_bekannter_wahrheit)
    assert ergebnis.effekt == pytest.approx(-1.0)
    assert ergebnis.p_wert < 0.001


def test_formatunterschied_wird_erkannt(warehouse_mit_bekannter_wahrheit) -> None:
    """Die Formate sind aehnlich, aber nicht deckungsgleich sortiert."""
    ergebnis = hypothesen._pruefe_formatunterschied(warehouse_mit_bekannter_wahrheit)
    assert 0.8 < ergebnis.effekt < 1.0


def test_flaechenattacken_werden_erkannt(warehouse_mit_bekannter_wahrheit) -> None:
    """Flaechenattacken kommen nur im Doppelkampf vor."""
    ergebnis = hypothesen._pruefe_flaechenattacken(warehouse_mit_bekannter_wahrheit)
    assert ergebnis.p_wert < 0.001
    assert ergebnis.effekt == pytest.approx(1.0)


def test_bizarroraum_traeger_sind_langsamer(warehouse_mit_bekannter_wahrheit) -> None:
    ergebnis = hypothesen._pruefe_bizarroraum(warehouse_mit_bekannter_wahrheit)
    assert ergebnis.p_wert < 0.001
    assert ergebnis.effekt < -0.9


def test_katalog_laeuft_vollstaendig_durch(warehouse_mit_bekannter_wahrheit) -> None:
    """Kein Katalogeintrag darf mit einem unerwarteten Fehler abbrechen."""
    ergebnis = hypothesen.pruefe_alle(warehouse_mit_bekannter_wahrheit)
    assert len(ergebnis.ergebnisse) == len(hypothesen.KATALOG)
    for einzeln in ergebnis.ergebnisse:
        assert einzeln.pruefbar or "Berechnung ist fehlgeschlagen" not in einzeln.hinweis


# --------------------------------------------------------------------------
# Verhalten ohne Datenbasis
# --------------------------------------------------------------------------

def test_leeres_warehouse_ergibt_nicht_pruefbar(tmp_path) -> None:
    """Ohne Daten darf keine Hypothese als bestaetigt oder widerlegt gelten."""
    from bi import warehouse

    conn = warehouse.verbindung(str(tmp_path / "leer.db"))
    ergebnis = hypothesen.pruefe_alle(conn)
    assert ergebnis.geprueft == 0
    assert ergebnis.verworfen == 0
    assert ergebnis.nicht_pruefbar == len(hypothesen.KATALOG)
    assert all(e.status == "nicht pruefbar" for e in ergebnis.ergebnisse)
    conn.close()


def _kunsthypothese(schluessel: str, p_wert: float | None) -> hypothesen.Hypothese:
    """Hypothese mit fest vorgegebenem Ergebnis -- fuer die Korrekturlogik."""
    def berechne(_conn):
        if p_wert is None:
            raise DatenbasisFehlt("Quelle nicht geladen.")
        return Pruefgroesse("Testverfahren", "T", 1.0, p_wert, 100, "Spearman rho", 0.5)

    return hypothesen.Hypothese(
        schluessel=schluessel, titel=f"Kunsthypothese {schluessel}",
        bereich="Test", nullhypothese="Es besteht kein Zusammenhang.",
        alternativhypothese="Es besteht ein Zusammenhang.",
        begruendung="-", verfahren="-", datenbasis="-", berechnung=berechne)


def test_nicht_pruefbare_hypothesen_verschaerfen_die_korrektur_nicht(tmp_path) -> None:
    """Sie duerfen die Familie nicht vergroessern.

    Sonst wuerde eine nicht geladene Quelle die uebrigen Hypothesen strenger
    pruefen -- ein Ergebnis haenge damit davon ab, was *nicht* vorliegt.
    """
    from bi import warehouse

    conn = warehouse.verbindung(":memory:")
    mit_luecke = hypothesen.pruefe_alle(conn, katalog=[
        _kunsthypothese("A", 0.02), _kunsthypothese("B", 0.04),
        _kunsthypothese("C", None), _kunsthypothese("D", None)])
    ohne_luecke = hypothesen.pruefe_alle(conn, katalog=[
        _kunsthypothese("A", 0.02), _kunsthypothese("B", 0.04)])

    schranken_mit = [e.schranke for e in mit_luecke.ergebnisse if e.pruefbar]
    schranken_ohne = [e.schranke for e in ohne_luecke.ergebnisse if e.pruefbar]
    assert schranken_mit == schranken_ohne
    assert mit_luecke.nicht_pruefbar == 2
    conn.close()


def test_holm_korrektur_wirkt_im_katalog(tmp_path) -> None:
    """Ein p-Wert unter 5 Prozent genuegt in einer grossen Familie nicht mehr."""
    from bi import warehouse

    conn = warehouse.verbindung(":memory:")
    ergebnis = hypothesen.pruefe_alle(
        conn, katalog=[_kunsthypothese(str(i), 0.04) for i in range(10)])
    assert ergebnis.verworfen == 0
    assert all(e.pruefbar for e in ergebnis.ergebnisse)
    conn.close()


def test_befund_folgt_der_entscheidung(warehouse_mit_bekannter_wahrheit) -> None:
    """Der ausgegebene Satz stammt aus dem Katalog, nicht aus dem Ergebnis."""
    ergebnis = hypothesen.pruefe_alle(warehouse_mit_bekannter_wahrheit)
    for einzeln in ergebnis.ergebnisse:
        if not einzeln.pruefbar:
            assert einzeln.befund.startswith("Nicht pruefbar")
        elif einzeln.verworfen:
            assert einzeln.befund == einzeln.hypothese.bei_verwerfung
        else:
            assert einzeln.befund == einzeln.hypothese.bei_beibehaltung
