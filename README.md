# VGC Business Intelligence

Business-Intelligence-Lösung für **Pokémon Champions**, die seit April 2026
offizielle Wettkampfplattform des Pokémon-Turnierbetriebs.

Das Projekt führt **vier Quellsysteme** in einem historisierten Data Warehouse
zusammen: die täglichen Ranked-Daten von Pokémon Champions, die Stammdaten der
Hauptspiele (PokeAPI), die PvP-Meta von Pokémon GO (pvpoke) und die
Turnier-Meta des Sammelkartenspiels samt Länderangabe (Limitless). Darauf
stehen ein Dashboard mit Kennzahlen, OLAP-Auswertung, Team-Analysen, einem
Team-Preview-Advisor und einem Schadensrechner — sowie ein **Hypothesenkatalog**,
der dreizehn vorab formulierte Aussagen statistisch prüft, statt sie zu
behaupten. Ein PC-System mit Nutzerkonten speichert eigene Pokémon, Sets und
Teams dauerhaft zwischen den Sitzungen.

Warum die Dinge so gebaut sind, wie sie gebaut sind — je Use-Case der
Gedankengang samt verworfener Alternativen — steht gesammelt in
[`docs/entscheidungen.md`](docs/entscheidungen.md).

**Live: <https://biprojekt-9uepcwtgxhxxmgkyv8furo.streamlit.app>**

Hochschulprojekt im Modul *Business Intelligence*, Duales Studium
Wirtschaftsinformatik, WiSe 2025/26.

---

## Fachliche Fragestellung

Wer ein Team für ein VGC-Turnier vorbereitet, trifft Entscheidungen unter
Unsicherheit: Welche Pokémon dominieren das Format? Wohin bewegt es sich? Wo ist
das eigene Team angreifbar? Und — die Frage, die unter Zeitdruck fällt — welche
vier der sechs Pokémon nehme ich im Team-Preview mit?

| Leitfrage | Umsetzung |
|---|---|
| Wie sieht das Format aktuell aus? | Meta-Cockpit mit Rangliste und Kennzahlen |
| Wie stabil ist es? | Rangkorrelation nach Spearman, Top-N-Fluktuation |
| Wer bewegt sich? | Rangveränderung gegenüber einem früheren Tag |
| Wer hält sich dauerhaft oben? | Verweildauer in der Spitzengruppe |
| Was spielt der Gegner? | Gegner-Scouting mit erwarteter Konfiguration |
| Wo ist mein Team verwundbar? | Defensivprofil, gewichtet mit der Meta-Präsenz |
| Wer handelt zuerst? | Speed-Tiers aus den real gespielten Statuspunkten |
| Überlebt mein Pokémon diesen Treffer? | Schadensrechner nach der Formel der Hauptspiele |
| Welche Typen und Items setzen sich durch? | Trendanalysen auf der Archiv-Zeitreihe |
| Spielen andere Länder anders? | Länderhypothese auf den TCG-Turnierdaten (H11) |
| Überträgt sich Stärke zwischen den Spielen? | Spielübergreifende Hypothesen (H12, H13) |
| **Welche 4 nehme ich mit?** | **Team-Preview-Advisor** |

Jede dieser Fragen ist entweder eine Kennzahl im Dashboard oder — wo eine
Behauptung im Raum steht — eine **Hypothese** mit Nullhypothese, Verfahren,
Effektstärke und Holm-Bonferroni-korrigierter Entscheidung.

---

## Architektur

```
┌──────────────┐  ┌──────────────────┐  ┌──────────┐  ┌──────────────┐
│   PokeAPI    │  │ Pokemon Champions│  │  pvpoke  │  │  Limitless   │  Quellsysteme
│ (Hauptspiele:│  │ (VGC-Ranked,     │  │ (GO-PvP, │  │ (TCG-Turniere│
│  Stammdaten) │  │  täglich)        │  │  je Liga)│  │  mit Land)   │
└──────┬───────┘  └────────┬─────────┘  └────┬─────┘  └──────┬───────┘
       │       EXTRACT     │    parallelisiert, mit Retry    │
       └─────────┬─────────┴──────────┬──────────────────────┘
                 ▼                    ▼
      ┌─────────────────────────────────────────┐
      │  Stage_Pokeapi      Archiv_Champions    │   Schicht 1: Staging + Archiv
      │  Archiv_GO          Archiv_TCG          │   wird NIE geleert,
      └───────────────────┬─────────────────────┘   mitversioniert
                          │  TRANSFORM: Filterung · Harmonisierung · Anreicherung
                          ▼
      ┌─────────────────────────────────────────┐
      │  Core Data Warehouse (Star-Schema)      │   Schicht 2
      │  11 Dimensionen (Dim_Pokemon konform    │
      │  über alle Spielformen, bi-temporal)    │
      │  4 Faktentabellen                       │
      └───────┬─────────────────────────────────┘
              │                    ┌──────────────────────┐
              │                    │  Nutzerdatenbank     │  eigener Lebenszyklus:
              │      ATTACH ◄──────┤  Konten · PC-System  │  nicht ableitbar,
              │                    │  Teams               │  überlebt jeden Neuaufbau
              ▼                    └──────────────────────┘
   ┌──────────┴───────────┐
   ▼                      ▼
┌──────────────┐   ┌───────────────────────────┐
│  ETL_Lauf    │   │  Analytics                │   Schicht 3: Metadaten + Analyse
│  DQ_Befund   │   │  KPI · OLAP · Trends      │
└──────────────┘   │  Hypothesen · Schaden     │
                   └───────────┬───────────────┘
                               ▼
                        ┌─────────────┐
                        │  Streamlit  │   Präsentationsschicht
                        │  mit Konten │   (bi.fablas.org)
                        └─────────────┘
```

### Datenmodell

| Faktentabelle | Granularität | Kennzahlen |
|---|---|---|
| `Fact_Champions_Usage` | Pokémon × Kampfformat × Saison × **Tag** | Nutzungsrang, Rangperzentil |
| `Fact_Champions_Merkmal` | … × Merkmal | Anteil, Statuspunkte, berechnete Statuswerte |
| `Fact_GO_Meta` | Pokémon × Liga × Stand | Score 0–100 (kardinal), abgeleiteter Rang |
| `Fact_TCG_Meta` | Deck × Land × Turniertag | Spieler, Top-8 (kardinal, zählbar) |

Der Merkmalsfakt hält Attacken, Items, Fähigkeiten, Wesen, Punkteverteilungen und
Teampartner in einer Satzstruktur — genau so, wie die Quelle sie liefert. Eine
künstliche Aufteilung auf sechs Tabellen hätte die Struktur der Quelle verdeckt,
ohne etwas zu gewinnen.

**Konforme Dimensionen:** `Dim_Pokemon` (über alle Spielformen), `Dim_Zeit`,
`Dim_Saison`, `Dim_Kampfformat`, `Dim_Quelle`, `Dim_Attacke`, `Dim_Item`,
`Dim_Faehigkeit`, `Dim_Liga`, `Dim_Markt`, `Dim_TCG_Deck`.

Items und Fähigkeiten kommen aus den **Hauptspielen** (PokeAPI): Champions
nennt zum getragenen Item nur den Namen — Wirkung und Kategorie existieren nur
dort. Die Wirkungsklasse wird selbst vergeben, weil die PokeAPI-Kategorien am
Verkaufsort orientiert sind und nicht daran, was das Item im Kampf tut.

**Dimensionshierarchien** (Konsolidierungspfade für Drill-Down und Roll-Up):

- Zeit: `Jahr → Quartal → Monat → Tag`
- Pokémon: `Generation → Pokémon`
- Typ: `Primärtyp → Typ-Kombination`
- Rolle: `Offensivprofil → Teamrolle → Speed-Klasse`
- Format: `Saison → Kampfformat`
- Markt: `Region → Land` (Ländervergleich im Sammelkartenspiel)

---

## Das Messniveau bestimmt die Kennzahl

**Der zentrale Befund der Datenanalyse.** Champions gibt die Nutzung eines
Pokémon als **Rang** aus, nicht als Anteil. Das ist eine ordinale Größe: Rang 1
ist besser als Rang 2, aber *um wie viel* sagt die Zahl nicht.

Damit sind Summen und Mittelwerte über Ränge fachlich nicht belastbar. Ein
Herfindahl-Index etwa, der quadrierte Anteile aufsummiert, lässt sich darauf
**nicht** anwenden. Die Kennzahlen sind deshalb konsequent auf zulässige
Statistiken für Rangdaten ausgelegt:

| Fragestellung | Kennzahl | Warum zulässig |
|---|---|---|
| Wer steigt, wer fällt? | Rangdifferenz zum Vergleichstag | Differenzen von Rängen sind interpretierbar |
| Wie stabil ist das Format? | **Spearman-Rangkorrelation** | genau für ordinale Daten definiert |
| Wie fest ist die Spitze? | Top-N-Fluktuation | reine Mengenoperation |
| Wer hält sich oben? | Verweildauer in Tagen | Zählung, keine Verrechnung |

Auf der **Merkmalsebene** — welche Attacke in wie viel Prozent der Sets vorkommt —
liefert die Quelle dagegen echte Anteile. Dort ist der Herfindahl-Index zulässig
und wird eingesetzt: als Maß für die Vorhersagbarkeit eines Sets.

Die neuen Quellen messen anders: pvpoke bewertet mit einem **Score von 0 bis
100** (kardinal), Limitless **zählt Spieler** (kardinal). Damit die Auswertung
das nicht je Fall „weiß", steht das Messniveau als Merkmal an der Quelle
(`Dim_Quelle.messniveau_nutzung`) — und dieselbe Regel bestimmt auch das
statistische Verfahren im Hypothesenkatalog: Rangdaten bekommen Rangverfahren,
Zählungen bekommen Chi-Quadrat.

Zwei Tests sichern das strukturell ab: der Kennzahlenkatalog des OLAP-Explorers
darf keine Summenaggregation über einen Rang anbieten, und ein Anteil in Prozent
entsteht nur bei additiven Kennzahlen.

Die zweite Regel ist teuer erkauft. Der Explorer wies den Anteil zuvor für jede
Kennzahl aus — ein Rang wurde durch die Summe aller Ränge geteilt, und daraus
entstand die Aussage „120 von 235 Ausprägungen decken 80 Prozent ab". Sie war
ohne Gehalt, und sie widersprach genau dem Grundsatz, den dieser Abschnitt
aufstellt. Jede Kennzahl trägt jetzt selbst, ob ein Anteil über ihr zulässig ist
und ob ein kleinerer Wert der bessere ist.

---

## Hypothesenkatalog: prüfen statt behaupten

Ein Dashboard zeigt, *was* der Fall ist — nicht, ob das Gezeigte mehr ist als
Rauschen. Bei 235 Pokémon und zwei Formaten findet das Auge in jeder Grafik ein
Muster. Der Katalog (`bi/analytics/hypothesen.py`, Seite *Hypothesen*,
kopflos: `python -m scripts.hypothesen_pruefen`) macht daraus **dreizehn
prüfbare Aussagen** in vier Bereichen: Wettkampf-Metagame, Stammdaten,
Quellenvergleich über die Spielformen, Länder- und Marktvergleich.

Jede Hypothese ist **vor** dem Blick in die Daten formuliert und trägt
Nullhypothese, Alternativhypothese, fachliche Begründung, Verfahren,
Datenbasis, beide Befundtexte — und ihre **Einschränkung**, denn eine
Einschränkung, die erst nach dem Ergebnis formuliert wird, ist eine Ausrede.

Drei Regeln gegen Scheinergebnisse:

1. **Das Messniveau bestimmt das Verfahren.** Ausschließlich verteilungsfreie
   Tests (Spearman, Mann-Whitney-U, Wilcoxon, Kruskal-Wallis, Chi-Quadrat) —
   ein t-Test setzt Intervallskala voraus, die Ränge nicht haben.
2. **Kein p-Wert ohne Effektstärke.** Bei n = 235 wird fast jeder Unterschied
   signifikant; erst Cliffs Delta, Cramérs V oder ρ sagen, ob er zählt.
3. **Holm-Bonferroni über die Familie.** Dreizehn Einzeltests zum Niveau 5 %
   lieferten sonst mit rund 49 % Wahrscheinlichkeit mindestens einen reinen
   Zufallstreffer. Nicht prüfbare Hypothesen (Quelle nicht geladen) gehen
   nicht in die Korrektur ein und werden als *nicht prüfbar* ausgewiesen —
   nie stillschweigend als „nicht verworfen".

Befunde auf dem aktuellen Bestand (16 Tage): Das Format **driftet** nachweislich
(H1, ρ = −0,65 — ein alter Stand veraltet wirklich, das Archiv ist damit
Voraussetzung, nicht Kür). Die Lehrmeinung „Initiative entscheidet" hält der
Prüfung **nicht** stand (H2, p = 0,13), die Basiswertsumme dagegen schon (H3,
mittlerer Effekt). Flächenattacken sind messbar ein Doppelkampf-Merkmal (H5)
und Bizarroraum-Träger messbar langsamer (H9) — beides bestätigt zugleich, dass
die Verknüpfung von Champions-Merkmalen und Hauptspiel-Stammdaten die
Spielregeln korrekt abbildet.

Die Verteilungsfunktionen (Normal, t, Chi-Quadrat) sind selbst umgesetzt und
gegen Tabellenwerte getestet — es gibt keine SciPy-Version, die Python 3.10
bis 3.14 gleichzeitig bedient, und das Projekt hat SciPy dafür schon einmal
ausgebaut.

---

## Eigener Bestand: PC-System, Konten, Schadensrechner

Die Meta-Auswertung sagt, was *andere* spielen. Das **PC-System** (benannt nach
dem PC der Spiele) erfasst die eigenen Pokémon — Item, Fähigkeit, Wesen,
Statuspunkte nach Champions-Regeln, bis zu vier Attacken — und stellt Teams
aus bis zu sechs Einträgen zusammen. Erfasst wird über Auswahlfelder aus den
Dimensionen, nie als Freitext: nur so bleibt jeder Eintrag verknüpfbar.

Eigene Daten liegen in einer **eigenen Datenbank** (`vgc_nutzer.db`), die per
`ATTACH` an der Warehouse-Verbindung hängt. Der Grund ist der Lebenszyklus:
das Warehouse ist eine Ableitung und entsteht bei jedem Kaltstart aus dem
Archiv neu — eigene Einträge darin wären danach fort. Der Bezug zur
Pokémon-Dimension läuft über den natürlichen Schlüssel (`slug`), weil der
Surrogatschlüssel bei jedem Neuaufbau wechselt.

**Nutzerkonten** sichern den Bestand im offenen Netz: PBKDF2-HMAC-SHA256 mit
eigenem Salz je Konto und der Iterationszahl im Datensatz (anhebbar, ohne
Konten zu entwerten), Vergleich in konstanter Zeit, Sperre nach Fehlversuchen,
Selbstregistrierung nur mit Zugangscode. Die Anmeldemaske folgt dem
Designsystem der Seite. Das erste Konto erhält die Verwaltungsrolle.

Der **Schadensrechner** beantwortet die Frage, an der eine
Einwechselentscheidung hängt: überlebt mein Pokémon diesen Treffer? Umgesetzt
ist die Schadensformel der Hauptspiele (ab Generation V) mit der
Rundungsreihenfolge des Spiels — zwischen den Multiplikatoren wird abgerundet,
und genau an diesen Einzelpunkten entscheiden sich K.-o.-Grenzen. Items und
Fähigkeiten wirken über `Dim_Item` und `Dim_Faehigkeit` mit; beide Seiten des
Vergleichs kommen wahlweise aus der eigenen Box oder aus dem meistgespielten
Set der Meta. Variable Stärken und Feldeffekte jenseits von Wetter und
Schirmen bildet der Rechner bewusst nicht ab und sagt das auch.

---

## Das Trainingssystem von Pokémon Champions

Champions hat die Fleißpunkte und Determinationswerte der Hauptreihe ersetzt:

| | Hauptreihe | Pokémon Champions |
|---|---|---|
| Investition | Fleißpunkte, 0–252 je Wert, 510 gesamt | **Statuspunkte**, 0–32 je Wert, **66 gesamt** |
| Wirkung | 4 Fleißpunkte = +1 Statuspunkt | **1 Statuspunkt = +1 Endwert** (Stufe 50) |
| Determinationswerte | 0–31, züchtbar | **fest 31**, nicht veränderbar |
| Wesen | Natur | *Stat Alignment*, gleiche Wirkung |

Die im Spiel als „Base stats" angezeigten Werte sind bereits die Werte auf Stufe
50 ohne Investition. Für Knackrack zeigt das Spiel 183/150/115/100/105/122 —
`bi.stats.stufe50_grundwerte` reproduziert genau diese Zahlen, was als Test
hinterlegt ist.

In der Praxis werden meist zwei Werte auf 32 gesetzt und die verbleibenden zwei
Punkte auf einen dritten verteilt. Knackrack mit `Jolly 2/32/0/0/0/32` erreicht
damit 169 Initiative und 182 Angriff.

**Folge für Bizarroraum-Sets:** In der Hauptreihe macht man ein Pokémon über null
Determinationswerte bewusst langsam. In Champions ist das **unmöglich** — die
Werte liegen fest bei 31. Dort bleibt allein das Wesen.

---

## Team-Preview-Advisor

Im Turnier bringt jede Seite sechs Pokémon mit, sieht im Team-Preview die sechs
des Gegners und wählt daraus die Kämpfer: **vier** im Doppelkampf, **drei** im
Einzelkampf.

Die Quelle veröffentlicht nicht, welche Pokémon tatsächlich mitgenommen wurden —
diese Kennzahl existiert öffentlich nicht. Sie wird auch nicht gebraucht: eine
Durchschnittsquote sagte nur, was Spieler *im Mittel* bringen, nicht was gegen
*dieses eine* Team richtig ist.

Stattdessen wird die Entscheidung durchgerechnet: 15 × 15 = 225 Paarungen im
Doppelkampf, 20 × 20 = 400 im Einzelkampf — in unter 0,1 Sekunden. Je Paarung
werden drei Größen verrechnet:

| Anteil | Größe | Grundlage |
|---|---|---|
| 45 % | Offensive | tatsächlich gespielte Attacken gegen die Typen des Gegners |
| 35 % | Defensive | dieselbe Rechnung in der Gegenrichtung |
| 20 % | Initiative | reale Werte aus den Statuspunkten |

Die Gesamtwertung verrechnet den Mittelwert mit dem ungünstigsten Fall (30 %
Risikoabschlag), damit keine Auswahl gewinnt, die im Mittel gut dasteht, aber
gegen eine bestimmte Aufstellung einbricht. Ausgegeben werden die empfohlene
Auswahl, der Beitrag je Pokémon, die riskanteste gegnerische Auswahl und eine
Begründung im Klartext.

---

## Archivierung: die Quelle vergisst, das Warehouse nicht

Champions hält nur rund **14 Tage** Tagesstände vor. Fällt ein Tag heraus, ist er
nicht nachladbar. Jeder Lauf schreibt die Rohnutzlast deshalb nach
`Archiv_Champions` — eine Tabelle, die auch beim vollständigen Zurücksetzen des
Warehouse **erhalten bleibt** und nur auf ausdrückliche Anweisung geleert wird.

Damit wächst eine Zeitreihe, die an der Quelle selbst nicht existiert. Das Archiv
erlaubt außerdem, geänderte Ableitungsregeln auf alle je gesicherten Tage
anzuwenden, ohne die Quelle erneut anzufragen — 2 Sekunden statt 30.

### Zwei Stufen, weil eine nicht reicht

Eine Tabelle allein genügt nicht: `data/` ist nicht versioniert, und ein
CI-Läufer beginnt jedes Mal mit leerer Platte. Die Datenbanktabelle überlebt
zwar jedes Zurücksetzen des Warehouse, aber keinen neuen Rechner. Deshalb wird
das Archiv zusätzlich als Datei abgelegt und **mitversioniert**:

```
archiv/M4/Doubles/2026-07-28.ndjson.gz        ~0,3 MB je Tag
archiv/stammdaten/Dim_Pokemon.ndjson.gz        0,11 MB, einmalig
archiv/stammdaten/Dim_Attacke.ndjson.gz        0,01 MB, einmalig
```

Eine Zeile je Rohdatensatz, gzip-komprimiert, deterministisch sortiert und ohne
Zeitstempel im gzip-Kopf. Ob eine Datei neu geschrieben wird, entscheidet ein
Vergleich der **entpackten Nutzlast** — nicht der komprimierten Bytes: zlib
liefert je nach Fassung und Betriebssystem unterschiedliche Kompressate für
denselben Eingang. Ein Byte-Vergleich schrieb im Betrieb das gesamte Archiv neu,
sobald der Lauf vom Entwicklungsrechner auf den Linux-Runner wanderte.

Der Stammdatenauszug liegt daneben, weil Champions nur Namen und Ränge liefert:
Typ, Basiswerte und Attackeneigenschaften stammen aus der PokeAPI. Er wird
**tabellengetreu** gesichert, samt Gültigkeitszeiträumen — eine Neuladung über
den regulären Weg würde die bi-temporale Historie von `Dim_Pokemon` verlieren.

Der ETL-Lauf liest dieses Verzeichnis vor jedem Zugriff auf die Quelle ein; der
tägliche Workflow schreibt es danach zurück. Erst dieser Kreislauf lässt die
Zeitreihe die 14-Tage-Grenze überschreiten.

```bash
python -m scripts.archiv_export        # Datenbank  → Dateien
python -m scripts.etl_lauf             # Dateien    → Datenbank, dann Quelle
python -m scripts.etl_lauf --ohne-archiv   # Dateiarchiv übergehen
```

### Das Warehouse entsteht beim Start neu

Die Anwendung baut das Data Warehouse beim ersten Aufruf aus dem Archiv auf.
Der Grund steht in den Größenverhältnissen — gemessen an 6 gegenüber 13 Tagen:

| Bestand | je Tag | je Jahr | wiederbeschaffbar? |
|---|---|---|---|
| Rohdatenarchiv | 0,3 MB | ~110 MB | **nein** — die Quelle vergisst nach 14 Tagen |
| Data Warehouse | 6,0 MB | ~2,2 GB | ja — in Sekunden aus dem Archiv |

Gesichert wird deshalb das Kleine und Unersetzliche, aufgebaut wird das Große
und Ableitbare. Das ist zugleich die Kernidee der Staging-Schicht: die Rohdaten
sind die Wahrheit, das Warehouse ist eine Ableitung.

Praktisch löst das ein reales Betriebsproblem: `data/` ist nicht versioniert,
und Streamlit Community Cloud setzt bei jedem Deployment einen frischen Behälter
auf — auch beim täglichen Archiv-Commit. Ohne diesen Schritt stünde die
Anwendung dort jeden Tag wieder ohne Daten da.

Der Aufbau läuft in `bi.bootstrap`, hängt in `hole_verbindung()` und geschieht
über `st.cache_resource` genau einmal je Behälter. Er kommt **ohne jeden
Netzzugriff** aus — ein Test schaltet die Verbindung dafür ab. Gemessen dauert
er 7 Sekunden für 13 Tage; für Mitte September sind rund 30 Sekunden zu
erwarten, einmalig nach jedem Deployment.

Drei Qualitätsregeln sichern das ab: *Lückenlosigkeit des Archivs* meldet
ausgelassene Ladeläufe, solange sich noch etwas retten lässt,
*Archivdeckung der Fakten* stellt sicher, dass jeder geladene Tag gesichert ist,
und der Export-Import-Weg selbst ist durch Tests abgedeckt — einschließlich der
Byte-Gleichheit unveränderter Tage.

### Saisonabgrenzung

Jeder Faktensatz trägt seine Saison. Genau eine Saison je Quelle gilt als
aktuell; alle Auswertungen filtern darauf. Damit verfälschen Pokémon aus
abgelaufenen Regulationen die laufende Saison nicht.

Der Saisonzeitraum wächst mit dem Archiv: früher gesicherte Tage bleiben Teil der
Saison, auch wenn die Quelle sie nicht mehr führt. Balance-Anpassungen an den
Pokémon selbst deckt die bi-temporale Historisierung von `Dim_Pokemon` ab.

---

## Historisierung

`Dim_Pokemon` ist **bi-temporal** ausgeführt — Delta-Verfahren kombiniert mit
Gültigkeitszeiträumen:

| Feld | Zweck |
|---|---|
| `gueltig_ab` / `gueltig_bis` | fachlicher Gültigkeitszeitraum |
| `ist_aktuell` | schneller Zugriff auf den Ist-Stand |
| `dwh_geladen_am` | technischer Ladezeitpunkt |
| `row_hash` | Änderungserkennung über die fachlich relevanten Attribute |

Ändert sich ein Attribut — etwa durch eine Balance-Anpassung zwischen zwei
Saisons — wird der bisherige Satz zum Vortag abgegrenzt und ein neuer eröffnet.
Auswertungen zu einem historischen Stichtag bleiben möglich.

Die Faktentabellen sind **nicht-volatil** (Inmon): es wird ausschließlich
eingefügt oder auf dem fachlichen Schlüssel aktualisiert. Ein wiederholter Lauf
desselben Tages ist idempotent und lässt die übrige Zeitreihe unberührt.

---

## OLAP-Operationen

Der Würfel wird relational gehalten (ROLAP). Alle Operationen sind im
OLAP-Explorer bedienbar:

| Operation | Bedienung |
|---|---|
| Slice | Filter auf einer Dimension |
| Dice | Filter auf mehreren Dimensionen |
| Drill-Down / Roll-Up | Schaltflächen am Konsolidierungspfad |
| Pivot (Rotation) | Achsen vertauschen |
| Split / Merge | Spaltenachse hinzunehmen bzw. entfernen |

Jede Kennzahl trägt ihre Aggregationsregel — und für Ränge sind nur Minimum,
Maximum, Median und Anzahl zugelassen.

---

## Datenqualität

Zweistufig geprüft:

**Während des Ladens** — Vollständigkeit von Pflichtfeldern, Auflösbarkeit der
Bezeichner, Regelkonformität der Statuspunkte. Befunde werden nach **Mangel
1. Klasse** (automatisch erkennbar und korrigierbar) und **Mangel 2. Klasse**
(erkennbar, erfordert fachliche Entscheidung) unterschieden und in `DQ_Befund`
protokolliert.

**Nach dem Laden** (`bi.quality`) — 20 Regeln auf dem Gesamtbestand entlang der
Dimensionen Vollständigkeit, Konsistenz, Eindeutigkeit, Wertebereich und
Aktualität. Der verdichtete **Qualitätsindex** dient als Qualitätstor in der CI.

### Befunde aus der Quellanalyse

1. **Keine Nutzungsquote, nur ein Rang.** Geprüft über alle 236 Pokémon und alle
   geladenen Tage. Das Datenmodell bildet das ehrlich ab und erfindet keinen
   Platzhalter; die Kennzahlen sind entsprechend ordinal ausgelegt.

2. **Teampartner ohne Gewicht.** 2330 Zeilen, davon 0 mit Prozentwert. Die
   Partnervorschläge zählen deshalb Nennungen aus und mitteln keine Anteile.

3. **121 von 48.740 Punkteverteilungen verletzen die Spielregeln** — bis zu 200
   Punkte in einem Einzelwert (Maximum 32) und Summen bis 130 (Budget 66). Im
   Spiel unmöglich. Die Sätze werden geladen, aber ausgewiesen.

4. **26 von 236 Bezeichnern sind nicht direkt auflösbar.** Champions schreibt
   Formen aus und stellt die Region voran (`Alolan Ninetales`), die PokeAPI hängt
   sie an (`ninetales-alola`). Regelbasiert gelöst statt über eine Einzelliste;
   verbleibende Nicht-Treffer werden protokolliert statt geraten. Aktuelle
   Trefferquote: **100 %**.

---

## Installation und Betrieb

```bash
git clone https://github.com/Fablas0/BIProjekt.git
cd BIProjekt
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Beim ersten Start ist das Data Warehouse leer. Unter *ETL & Datenqualität*
nacheinander **Stammdaten laden** und **Champions-Daten laden** ausführen — der
vollständige Aufbau dauert rund 30 Sekunden.

### Kopfloser Betrieb

```bash
python -m scripts.etl_lauf
```

Nur die tägliche Strecke (so sollte der geplante Lauf aussehen):

```bash
python -m scripts.etl_lauf --nur-champions
```

Qualitätstor:

```bash
python -m scripts.qualitaet_pruefen --mindestindex 90
```

### Tests

```bash
pip install -r requirements-dev.txt && pytest -q && ruff check .
```

Die Oberflächentests überspringen sich selbst, solange kein befülltes Data
Warehouse vorliegt.

---

## CI/CD

**`ci.yml`** — bei jedem Push und Pull Request: Ruff-Linting, Tests auf Python
3.10 und 3.12, und auf dem Hauptzweig zusätzlich ein Integrationslauf gegen die
echte Quelle mit anschließendem Qualitätstor. Der Lauf protokolliert die
installierten Versionen; die meisten Befunde, die lokal nicht auftreten, sind
Versionsunterschiede. Ist die Quelle nicht erreichbar (Rückgabewert 75), wird der
Integrationsteil übersprungen statt rot gemeldet — ein fremder Ausfall ist kein
Codefehler.

**`etl_taeglich.yml`** — Operationalisierung: **täglich** um 05:00 Uhr. Der
tägliche Rhythmus ist keine Kür, sondern Pflicht: die Quelle hält nur 14 Tage
vor. Der Lauf liest das versionierte Dateiarchiv ein, holt den neuen Tag, schreibt
das Archiv zurück ins Repository und prüft **erst danach** die Qualität — sonst
könnte ein Qualitätsmangel einen unwiederbringlichen Tagesstand kosten. Hier
führt ein Quellausfall bewusst zu einem roten Lauf: ein nicht abgeholter Tag ist
nach der Vorhaltezeit endgültig verloren, das muss auffallen.

### Deployment

Zwei Zielumgebungen, eine Codebasis:

**Streamlit Community Cloud** (öffentliche Demo): Repository verbinden,
`app.py` als Einstiegspunkt, `requirements.txt` wird automatisch installiert.
Das Verzeichnis `data/` ist bewusst nicht versioniert, `archiv/` dagegen schon —
die Cloud baut das Warehouse beim ersten Aufruf daraus auf. Es ist also nichts
einzurichten: Repository verbinden, fertig.

**Jetson unter `bi.fablas.org`** (eigener Betrieb mit Nutzerdaten): systemd-
Dienst hinter einem Cloudflare Tunnel — kein offener Port, Streamlit lauscht
nur auf 127.0.0.1, `bi.fablas.org` hängt als Unterseite an der bestehenden
Domain. Die Nutzerdatenbank liegt außerhalb des Repositories und wird täglich
per `VACUUM INTO` gesichert. Der Jetson ruft keine Quelle selbst an: GitHub
Actions sammelt, der Jetson übernimmt per `git pull` und verarbeitet ohne
Netzzugriff aus dem Archiv. Einrichtung und Betrieb: [`deploy/jetson/`](deploy/jetson/README.md).

Die Abhängigkeiten sind exakt festgelegt und auf **Python 3.10 bis 3.14** geprüft:
für jede dieser Versionen existiert von jedem Paket ein fertiges Wheel. Ohne diese
Prüfung übersetzt die Cloud pandas aus dem Quelltext — der Aufbau dauert dann
45 Minuten statt einer.

---

## Projektstruktur

```
├── app.py                        Einstiegspunkt (Streamlit)
├── src/bi/
│   ├── config.py                 zentrale Konfiguration
│   ├── typechart.py              Typen-Regelbasis
│   ├── stats.py                  Statuspunkte, Wesen, Initiative-Szenarien
│   ├── warehouse.py              Schema-DDL, Sichten, Verbindung, Migration
│   ├── nutzerdaten.py            Konten, PC-System, Teams (eigene Datenbank)
│   ├── quality.py                20 Qualitätsregeln
│   ├── etl/
│   │   ├── extract.py            PokeAPI: Pokémon, Attacken, Items, Fähigkeiten
│   │   ├── champions.py          Champions-Strecke inkl. Archivierung
│   │   ├── go.py                 Pokémon-GO-Strecke (pvpoke)
│   │   ├── tcg.py                Sammelkartenspiel-Strecke (Limitless)
│   │   ├── archivdatei.py        Determinismus-Zusage der Archivdateien
│   │   ├── stammarchiv.py        Versionierter Auszug der Stammdaten
│   │   ├── spielformarchiv.py    Versionierte Ablage der TCG-/GO-Rohdaten
│   │   ├── mapping.py            Harmonisierung der Bezeichner
│   │   ├── transform.py          Filterung · Anreicherung · Zeitdimension
│   │   ├── load.py               Historisierung, Dimensionen, Protokoll
│   │   └── pipeline.py           Orchestrierung
│   ├── analytics/
│   │   ├── kpi.py                ordinale Kennzahlen, Rangkorrelation
│   │   ├── olap.py               Würfeloperationen
│   │   ├── trends.py             Typen, Items, Neuzugänge, Dauerbrenner
│   │   ├── verteilungen.py       Normal-, t-, Chi-Quadrat-Verteilung (ohne SciPy)
│   │   ├── pruefverfahren.py     verteilungsfreie Tests, Holm-Bonferroni
│   │   ├── hypothesen.py         der Katalog: 13 Hypothesen in 4 Bereichen
│   │   ├── schaden.py            Schadensformel der Hauptspiele
│   │   ├── speed.py              Speed-Tiers, Szenarien, Benchmark
│   │   ├── threat.py             Bedrohungs- und Abdeckungsanalyse
│   │   └── preview.py            Team-Preview-Advisor
│   └── ui/                       vierzehn Seitenmodule, Anmeldung, Design
├── scripts/                      kopflose ETL-, Prüf- und Hypothesenläufe
├── deploy/jetson/                Betrieb unter bi.fablas.org (systemd, Tunnel)
├── docs/entscheidungen.md        Warum so? Gedankengang je Use-Case
├── tests/                        373 Tests
└── .github/workflows/            CI und täglicher Ladelauf
```

---

## Zuordnung zum Projektbericht

| Kapitel | Fundstelle |
|---|---|
| Problem- und Datenbeschreibung | dieses README, `docs/entscheidungen.md` |
| Quellenwahl und Begründung | `docs/entscheidungen.md` §1, `bi/etl/{champions,go,tcg}.py` |
| ETL | `bi/etl/` — je ein Modul pro Prozessschritt und Quelle |
| Datenmodellierung | `bi/warehouse.py` (DDL mit Begründungen), `bi/nutzerdaten.py` |
| Datenanalyse | `bi/analytics/` |
| Hypothesen und Statistik | `bi/analytics/{hypothesen,pruefverfahren,verteilungen}.py` |
| Datenvisualisierung / Dashboard | `bi/ui/` |
| Datenqualität | `bi/quality.py` (20 Regeln) |
| Operationalisierung | `scripts/`, `.github/workflows/`, `deploy/jetson/` |

---

## Quellen und Rechtliches

- [Pokémon Champions Battle Data](https://championsbattledata.com/) — VGC-Bewegungsdaten
- [PokeAPI](https://pokeapi.co) — Stammdaten der Hauptspiele
- [pvpoke](https://pvpoke.com) — PvP-Ranglisten für Pokémon GO
- [Limitless](https://limitlesstcg.com) — Turnierdaten des Sammelkartenspiels

Rein akademisches Projekt ohne kommerzielle Nutzung. Es besteht keine Verbindung
zu Nintendo, Game Freak oder The Pokémon Company.
