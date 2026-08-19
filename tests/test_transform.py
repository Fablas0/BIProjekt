"""Tests des Transformationsschritts der Stammdaten.

Geprueft werden Filterung, Harmonisierung und Anreicherung -- jeweils mit
synthetischen Daten, damit die Tests ohne Zugriff auf die Quellsysteme laufen.
"""

from __future__ import annotations

import pytest

from bi.etl.mapping import loese_auf, normalisiere
from bi.etl.transform import (
    deutscher_formname,
    faehigkeit_klasse,
    offensiv_profil,
    rolle,
    speed_klasse,
    taktik_klasse,
    transformiere_attacke,
    transformiere_pokemon,
    zeilen_hash,
    zeitdimension,
)

# Slugs, wie sie die PokeAPI fuehrt.
BEKANNTE_SLUGS = {
    "incineroar", "garchomp", "iron-hands", "ho-oh",
    "ninetales-alola", "raichu-alola", "rotom-fan", "slowbro-galar",
    "arcanine-hisui", "tauros-paldea-aqua-breed", "aegislash-shield",
    "lycanroc-dusk", "gourgeist-super", "gourgeist-large", "florges",
    "vivillon", "palafin-zero", "furfrou", "landorus-incarnate",
    "urshifu-single-strike", "indeedee-female",
}


def _pokeapi_nutzlast(**abweichungen) -> dict:
    """Minimale, gueltige PokeAPI-Nutzlast fuer Tests."""
    basis = {
        "id": 727,
        "name": "incineroar",
        "species": {"name": "incineroar"},
        "types": [{"type": {"name": "fire"}}, {"type": {"name": "dark"}}],
        "stats": [
            {"stat": {"name": "hp"}, "base_stat": 95},
            {"stat": {"name": "attack"}, "base_stat": 115},
            {"stat": {"name": "defense"}, "base_stat": 90},
            {"stat": {"name": "special-attack"}, "base_stat": 80},
            {"stat": {"name": "special-defense"}, "base_stat": 90},
            {"stat": {"name": "speed"}, "base_stat": 60},
        ],
    }
    basis.update(abweichungen)
    return basis


# --------------------------------------------------------------------------
# Harmonisierung
# --------------------------------------------------------------------------

def test_normalisierung_von_sonderzeichen() -> None:
    assert normalisiere("Iron Hands") == "iron-hands"
    assert normalisiere("Ho-Oh") == "ho-oh"
    assert normalisiere("Farfetch'd") == "farfetchd"
    assert normalisiere("Mr. Mime") == "mr-mime"


@pytest.mark.parametrize(
    ("champions_name", "erwartet"),
    [
        # Vorangestellte Region -> angehaengtes Suffix
        ("Alolan Ninetales", "ninetales-alola"),
        ("Alolan Raichu", "raichu-alola"),
        ("Galarian Slowbro", "slowbro-galar"),
        ("Hisuian Arcanine", "arcanine-hisui"),
        # Region mitten im Namen, Zuchtform bleibt erhalten
        ("Paldean Tauros Aqua Breed", "tauros-paldea-aqua-breed"),
        # Rotom-Formen stehen voran
        ("Fan Rotom", "rotom-fan"),
        # Ausgeschriebene Formbezeichnungen
        ("Aegislash Shield Forme", "aegislash-shield"),
        ("Lycanroc Dusk Form", "lycanroc-dusk"),
        ("Palafin Zero Form", "palafin-zero"),
        ("Gourgeist Large Variety", "gourgeist-large"),
        # Sonderfall: 'Jumbo' heisst in der PokeAPI 'super'
        ("Gourgeist Jumbo Variety", "gourgeist-super"),
        # Rein kosmetische Formen fallen auf die Grundform zurueck
        ("Florges Red Flower", "florges"),
        ("Vivillon Fancy Pattern", "vivillon"),
        ("Furfrou Natural Form", "furfrou"),
        # Namen ohne Besonderheit
        ("Garchomp", "garchomp"),
        ("Iron Hands", "iron-hands"),
    ],
)
def test_champions_namen_werden_aufgeloest(champions_name: str, erwartet: str) -> None:
    """Champions schreibt Formen aus; die PokeAPI haengt sie als Suffix an."""
    assert loese_auf(champions_name, BEKANNTE_SLUGS) == erwartet


def test_unbekannter_bezeichner_wird_nicht_geraten() -> None:
    """Ohne eindeutige Zuordnung ist ``None`` das richtige Ergebnis.

    Ein falscher Treffer waere schaedlicher als ein protokollierter Fehltreffer:
    er wuerde Kennzahlen einem falschen Pokemon zuschreiben.
    """
    assert loese_auf("Voelligunbekannt", BEKANNTE_SLUGS) is None
    assert loese_auf("Erfundenian Ninetales", BEKANNTE_SLUGS) is None


# --------------------------------------------------------------------------
# Filterung
# --------------------------------------------------------------------------

def test_gueltige_nutzlast_wird_uebernommen() -> None:
    satz, befund = transformiere_pokemon(_pokeapi_nutzlast(), {"incineroar": 7})
    assert befund is None
    assert satz["slug"] == "incineroar"
    assert satz["typ1"] == "Fire"
    assert satz["typ2"] == "Dark"
    assert satz["generation"] == 7
    assert satz["basiswert_summe"] == 530


def test_angezeigte_grundwerte_werden_angereichert() -> None:
    """Die Dimension traegt zusaetzlich die im Spiel angezeigten Werte."""
    satz, _ = transformiere_pokemon(_pokeapi_nutzlast(), {})
    assert satz["stufe50_hp"] == 170       # Basiswert 95
    assert satz["stufe50_attack"] == 135   # Basiswert 115
    assert satz["stufe50_speed"] == 80     # Basiswert 60


# --------------------------------------------------------------------------
# Deutsche Namen
# --------------------------------------------------------------------------

def test_deutscher_name_kommt_aus_der_speziesuebersetzung() -> None:
    satz, _ = transformiere_pokemon(_pokeapi_nutzlast(), {"incineroar": 7},
                                    {"incineroar": "Fuegro"})
    assert satz["name_de"] == "Fuegro"
    # Ohne Uebersetzung bleibt das Feld leer statt geraten.
    satz, _ = transformiere_pokemon(_pokeapi_nutzlast(), {"incineroar": 7}, {})
    assert satz["name_de"] is None


@pytest.mark.parametrize(("slug", "spezies", "spezies_de", "erwartet"), [
    ("ninetales-alola", "ninetales", "Vulnona", "Alola-Vulnona"),
    ("slowbro-galar", "slowbro", "Lahmus", "Galar-Lahmus"),
    ("arcanine-hisui", "arcanine", "Arkani", "Hisui-Arkani"),
    ("tauros-paldea-aqua-breed", "tauros", "Tauros", "Paldea-Tauros (Aqua Breed)"),
    ("landorus-therian", "landorus", "Demeteros", "Demeteros (Therian)"),
    ("urshifu-single-strike", "urshifu", "Wulaosu", "Wulaosu (Single Strike)"),
    ("garchomp", "garchomp", "Knakrack", "Knakrack"),
    ("ninetales-alola", "ninetales", None, None),
])
def test_deutscher_formname_folgt_der_regel(slug, spezies, spezies_de, erwartet) -> None:
    """Regionalformen tragen die Region als Praefix, alles andere Klammern.

    Regelbasiert statt Einzelliste -- die amtlichen Formnamen staenden nur in
    rund 1500 weiteren PokeAPI-Ressourcen.
    """
    assert deutscher_formname(slug, spezies, spezies_de) == erwartet


def test_satz_ohne_typ_wird_abgewiesen() -> None:
    satz, befund = transformiere_pokemon(_pokeapi_nutzlast(types=[]), {})
    assert satz is None
    assert befund is not None
    assert befund.klasse == "Mangel 1. Klasse"
    assert befund.dimension == "Vollstaendigkeit"


def test_satz_mit_fehlenden_basiswerten_wird_abgewiesen() -> None:
    unvollstaendig = _pokeapi_nutzlast()
    unvollstaendig["stats"] = unvollstaendig["stats"][:3]
    satz, befund = transformiere_pokemon(unvollstaendig, {})
    assert satz is None
    assert "speed" in befund.meldung


# --------------------------------------------------------------------------
# Anreicherung
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("attack", "sp_attack", "erwartet"),
    [(150, 60, "Physisch"), (60, 150, "Speziell"), (100, 105, "Gemischt"),
     (0, 0, "Kein Angriff")],
)
def test_offensivprofil(attack: int, sp_attack: int, erwartet: str) -> None:
    assert offensiv_profil(attack, sp_attack) == erwartet


@pytest.mark.parametrize(
    ("speed", "erwartet"),
    [(135, "Sehr schnell (120+)"), (100, "Schnell (100-119)"), (85, "Mittel (80-99)"),
     (60, "Langsam (60-79)"), (30, "Sehr langsam (<60)")],
)
def test_speed_klasse(speed: int, erwartet: str) -> None:
    assert speed_klasse(speed) == erwartet


def test_rollenableitung() -> None:
    assert rolle(70, 130, 70, 60, 70, 120) == "Schneller Sweeper"
    assert rolle(130, 140, 100, 50, 80, 50) == "Bizarroraum-Angreifer"
    assert rolle(120, 60, 120, 60, 120, 40) == "Defensive Wand"


def test_taktik_klasse_aus_namensliste() -> None:
    assert taktik_klasse("trickroom", "status", 0, "user") == "Bizarroraum"
    assert taktik_klasse("followme", "status", 2, "user") == "Umleitung"
    assert taktik_klasse("swordsdance", "status", 0, "user") == "Setup"


def test_taktik_klasse_aus_strukturmerkmalen() -> None:
    """Nicht namentlich hinterlegte Attacken werden ueber ihre Merkmale erkannt."""
    assert taktik_klasse("aquajet", "physical", 1, "selected-pokemon") == "Prioritaet"
    assert taktik_klasse("dazzlinggleam", "special", 0, "all-opponents") == "Flaechenschaden"
    assert taktik_klasse("flamethrower", "special", 0, "selected-pokemon") == "Offensiv"


def test_faehigkeitsklasse() -> None:
    """Champions liefert Faehigkeiten als Anzeigenamen mit Leerzeichen."""
    assert faehigkeit_klasse("Drizzle") == "Wetter"
    assert faehigkeit_klasse("Grassy Surge") == "Terrain"
    assert faehigkeit_klasse("Hadron Engine") == "Terrain"
    assert faehigkeit_klasse("Intimidate") == "Stoerung"
    assert faehigkeit_klasse("Rough Skin") == "Sonstige"


def test_attacke_wird_mit_kompaktem_schluessel_gefuehrt() -> None:
    """Champions liefert Anzeigenamen; der Schluessel ist die kompakte Form."""
    satz = transformiere_attacke({
        "name": "dragon-claw", "type": {"name": "dragon"},
        "damage_class": {"name": "physical"}, "power": 80, "accuracy": 100,
        "priority": 0, "target": {"name": "selected-pokemon"},
        "names": [
            {"language": {"name": "ja"}, "name": "ドラゴンクロー"},
            {"language": {"name": "de"}, "name": "Drachenklaue"},
        ],
    })
    assert satz["slug"] == "dragonclaw"
    assert satz["anzeigename"] == "Dragon Claw"
    assert satz["name_de"] == "Drachenklaue"
    assert satz["typ"] == "Dragon"
    assert satz["taktik_klasse"] == "Offensiv"


def test_attacke_ohne_uebersetzung_bleibt_englisch() -> None:
    """Die Nutzlast traegt die Namen mit -- fehlt Deutsch, bleibt das Feld leer."""
    satz = transformiere_attacke({
        "name": "hyper-beam", "type": {"name": "normal"},
        "damage_class": {"name": "special"}, "power": 150, "accuracy": 90,
        "priority": 0, "target": {"name": "selected-pokemon"},
    })
    assert satz["name_de"] is None


def test_zeilen_hash_reagiert_auf_aenderungen() -> None:
    """Der Hash muss sich genau dann aendern, wenn sich ein Attribut aendert.

    Damit werden Balance-Anpassungen zwischen zwei Saisons erkannt und loesen
    einen neuen Gueltigkeitszeitraum aus.
    """
    a = zeilen_hash((727, "Fire", "Dark", 95, 115, 90, 80, 90, 60))
    b = zeilen_hash((727, "Fire", "Dark", 95, 115, 90, 80, 90, 60))
    c = zeilen_hash((727, "Fire", "Dark", 95, 120, 90, 80, 90, 60))
    assert a == b
    assert a != c


# --------------------------------------------------------------------------
# Zeitdimension
# --------------------------------------------------------------------------

def test_zeitdimension_konsolidierungspfad() -> None:
    satz = zeitdimension("2026-07-28")
    assert satz["zeit_sk"] == 20260728
    assert satz["datum_iso"] == "2026-07-28"
    assert satz["jahr"] == 2026
    assert satz["monat"] == 7
    assert satz["tag"] == 28
    assert satz["quartal"] == 3
    # Konsolidierungspfad nach oben: Tag -> Monat -> Quartal -> Jahr
    assert satz["monat_iso"] == "2026-07"
    assert satz["quartal_label"] == "Q3 2026"
    assert satz["tag_label"] == "28.07.2026"
    assert satz["wochentag"] == "Dienstag"


def test_zeitschluessel_sind_chronologisch_sortierbar() -> None:
    """Der Schluessel JJJJMMTT ordnet die Tage ohne zusaetzliche Umwandlung."""
    schluessel = [zeitdimension(t)["zeit_sk"]
                  for t in ("2026-07-09", "2026-07-28", "2026-08-01")]
    assert schluessel == sorted(schluessel)
