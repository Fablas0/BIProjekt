"""Prueft, dass die Gestaltung an einer Stelle liegt und Gelb reserviert bleibt.

Beide Regeln stehen im Docstring von :mod:`bi.ui.design`,
waren aber bislang nur Absprache. Eine Absprache haelt genau so lange, bis
jemand unter Zeitdruck ein ``style='color:#e74c3c'`` in ein Seitenmodul
schreibt -- danach faellt es niemandem mehr auf, weil es ja schon einmal jemand
getan hat.
"""

from __future__ import annotations

import colorsys
import re
import tokenize
from pathlib import Path

import pytest

from bi.ui import design

UI_VERZEICHNIS = Path(design.__file__).parent
SEITENMODULE = sorted(p for p in UI_VERZEICHNIS.glob("*.py") if p.name != "design.py")

# Farbwerte in einer Zeichenkette: Hexwerte und rgb()/rgba().
FARBWERT = re.compile(r"#[0-9A-Fa-f]{3,8}\b|rgba?\(")

# Eine der benannten Farbskalen von Plotly ("Sunset", "Reds", "RdYlGn" ...).
# Sie kommen ohne Farbwert aus und waeren dem Muster oben entgangen, umgehen
# das Designsystem aber genauso -- "Sunset" und "RdYlGn" fuehren beide durch
# Gelb.
BENANNTE_SKALA = re.compile(
    r"color_(?:continuous_scale|discrete_sequence|discrete_map)\s*=\s*[\"']")


def _farbangaben(modul: Path) -> list[str]:
    """Alle Farbangaben eines Moduls.

    Gesucht wird in den Zeichenketten des Quelltextes, nicht im Rohtext: ein
    Hexwert in einem Kommentar erlaeutert eine Entscheidung und ist keine.
    """
    treffer: list[str] = []
    with tokenize.open(modul) as datei:
        for marke in tokenize.generate_tokens(datei.readline):
            if marke.type == tokenize.STRING:
                treffer.extend(FARBWERT.findall(marke.string))
            elif marke.type == tokenize.COMMENT:
                continue
    treffer.extend(BENANNTE_SKALA.findall(
        "\n".join(zeile.split("#", 1)[0] for zeile in
                  modul.read_text(encoding="utf-8").splitlines())))
    return treffer


@pytest.mark.parametrize("modul", SEITENMODULE, ids=lambda p: p.name)
def test_kein_farbwert_ausserhalb_des_designsystems(modul: Path) -> None:
    """Nur ``design.py`` legt Farben fest -- jedes andere Modul verweist darauf.

    Ohne diese Grenze wandert die Gestaltung in die Seitenmodule zurueck. Genau
    so entstanden die dreizehn abweichenden ``style``-Angaben in
    ``seite_scouting``, von denen der Docstring des Designsystems berichtet.
    """
    gefunden = _farbangaben(modul)
    assert not gefunden, (
        f"{modul.name} legt eigene Farben fest: {', '.join(sorted(set(gefunden)))}. "
        "Farben gehoeren nach bi/ui/design.py."
    )


def _ist_gelb(farbwert: str) -> bool:
    """Ob ein Farbwert im gelben Bereich des Farbkreises liegt.

    Geprueft wird der Farbton, nicht die Zeichenkette: ein Verlauf kann auch
    ueber ein blasses ``#FFE27A`` ins Gelbe laufen, ohne dass ihm das anzusehen
    waere. Als gelb gilt ein Ton zwischen 40 und 70 Grad -- Orange bei rund 25
    Grad bleibt damit erlaubt --, sofern die Farbe ueberhaupt kraeftig genug
    ist, um als Gelb wahrgenommen zu werden.
    """
    rot, gruen, blau = (int(farbwert[i:i + 2], 16) / 255 for i in (1, 3, 5))
    farbton, saettigung, helligkeit = colorsys.rgb_to_hsv(rot, gruen, blau)
    return 40 <= farbton * 360 <= 70 and saettigung > 0.25 and helligkeit > 0.4


def _stufen(verlauf: list) -> list[str]:
    """Die Farbwerte eines Verlaufs, mit oder ohne vorangestellte Position."""
    return [stufe[1] if isinstance(stufe, (list, tuple)) else stufe for stufe in verlauf]


# Alles, worin Gelb nicht vorkommen darf. Die Empfehlung fehlt hier bewusst --
# ihr gehoert die Farbe.
NEUTRALE_SKALEN = {
    "DIAGRAMM_FOLGE": design.DIAGRAMM_FOLGE,
    "ABSTUFUNG_GUETE": design.ABSTUFUNG_GUETE,
    "VERLAUF_BILANZ": design.VERLAUF_BILANZ,
    "VERLAUF_ANFAELLIGKEIT": design.VERLAUF_ANFAELLIGKEIT,
    "VERLAUF_RANG": design.VERLAUF_RANG,
    "VERLAUF_NEUTRAL": design.VERLAUF_NEUTRAL,
    "VERLAUF_GEFAHR": design.VERLAUF_GEFAHR,
    "STUFEN_FARBEN": list(design.STUFEN_FARBEN.values()),
}


@pytest.mark.parametrize("name", sorted(NEUTRALE_SKALEN))
def test_gelb_bleibt_der_empfehlung_vorbehalten(name: str) -> None:
    """Keine Diagrammfarbe und keine Abstufung darf ins Gelbe laufen.

    Im Team-Preview bleiben rund 60 Sekunden. Gelb bedeutet dort *das hier ist
    die Antwort*; taucht derselbe Ton nebenan als vierte Balkenfarbe oder als
    mittlere Stufe einer Ampel auf, bedeutet er gar nichts mehr.
    """
    gelbe = [farbe for farbe in _stufen(NEUTRALE_SKALEN[name]) if _ist_gelb(farbe)]
    assert not gelbe, (
        f"{name} enthaelt Gelb: {', '.join(gelbe)}. Gelb ist der Empfehlung "
        "vorbehalten (bi/ui/design.py)."
    )


def test_empfehlung_ist_gelb() -> None:
    """Gegenprobe: die Empfehlungsfarbe selbst muss gelb sein.

    Ohne sie liesse sich der Test oben auch dadurch erfuellen, dass es
    ueberhaupt kein Gelb mehr gibt.
    """
    assert _ist_gelb(design.POKEMON_GELB)


def test_jede_bedeutung_hat_eine_darstellung() -> None:
    """Zu jeder Bedeutung ausser ``neutral`` gehoert eine eigene CSS-Klasse."""
    stilblatt = design._stilblatt()
    for bedeutung in design.BEDEUTUNGEN:
        if bedeutung == "neutral":
            continue
        assert f".kachel--{bedeutung}" in stilblatt, (
            f"Fuer die Bedeutung '{bedeutung}' fehlt die Klasse .kachel--{bedeutung}."
        )
