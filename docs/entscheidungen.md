# Entscheidungen und Gedankengaenge

Dieses Dokument haelt fest, **warum** das Projekt so gebaut ist, wie es gebaut
ist -- je Use-Case und Funktion der Gedankengang, die verworfenen Alternativen
und der Preis der getroffenen Entscheidung. Es ergaenzt das README, das den
Ist-Zustand beschreibt; hier steht der Weg dorthin.

---

## 1. Quellenwahl: warum diese vier

**Ausgangsfrage:** Woher kommen Pokemon, Items, Faehigkeiten -- und woher die
Meta?

Der Gedankengang trennt zwei Arten von Daten, die leicht zu verwechseln sind:

* **Stammdaten** beschreiben, was ein Pokemon, ein Item, eine Attacke *ist*:
  Typen, Basiswerte, Wirkungen. Sie stammen aus den **Hauptspielen** und
  aendern sich fast nie. Quelle: **PokeAPI** -- maschinenlesbar, vollstaendig,
  ohne Schluessel nutzbar. Die Alternative, diese Daten aus Champions selbst zu
  ziehen, scheitert daran, dass Champions sie schlicht nicht liefert: dort
  steht "Focus Sash" als Zeichenkette, sonst nichts.
* **Bewegungsdaten** beschreiben, was gespielt *wird*: Raenge, Anteile,
  Zaehlungen. Sie aendern sich taeglich und kommen je Spielform aus einer
  eigenen Quelle.

| Quelle | Spielform | Liefert | Messniveau | Warum diese |
|---|---|---|---|---|
| PokeAPI | Hauptspiele | Stammdaten | - | einzige vollstaendige, freie Strukturquelle |
| Pokemon Champions | VGC | Nutzungsrang, Sets | **ordinal** | offizielle Wettkampfplattform |
| pvpoke | Pokemon GO | Score 0-100 je Liga | kardinal | Referenz der GO-PvP-Szene; GO selbst veroeffentlicht nichts |
| Limitless | Sammelkartenspiel | Spieler je Deck **und Land** | kardinal | einzige Quelle mit Ortsangabe |

Die letzte Spalte der Ortsangabe war der Ausschlag fuer Limitless: die
Laenderhypothese (H11) ist mit keiner anderen Quelle formulierbar. Champions
kennt keinen Ort, pvpoke auch nicht.

**Preis:** Limitless verlangt einen (kostenlosen) API-Schluessel. Der Umgang
damit ist eine eigene Entscheidung: fehlt der Schluessel, wird die Strecke
**uebersprungen und protokolliert** -- nicht abgebrochen. Eine Zusatzquelle
darf den Gesamtlauf nicht scheitern lassen; ihr Fehlen darf aber auch nicht
unbemerkt bleiben.

---

## 2. Datenmodell: eine kleine Datenbank, zwei Lebenszyklen

**Ausgangsfrage:** Wohin mit den Daten?

Das Warehouse ist ein Star-Schema mit konformen Dimensionen. Die eigentliche
Modellentscheidung ist aber nicht das Schema, sondern die **Trennung nach
Lebenszyklus**:

* `vgc_dwh.db` -- das Warehouse. Eine **Ableitung** aus dem versionierten
  Rohdatenarchiv, bei jedem Kaltstart neu aufbaubar. Darf jederzeit geloescht
  werden.
* `vgc_nutzer.db` -- die eigene Datenhaltung (Konten, PC-System, Teams). Von
  Hand erfasst, nirgends sonst vorhanden, **nicht wiederbeschaffbar**. Wird von
  keinem Ladelauf beruehrt.

Beide haengen per `ATTACH DATABASE` an einer Verbindung, sodass eine Box sich
direkt mit `Dim_Pokemon` verknuepfen laesst. Der Verbund laeuft ueber den
**natuerlichen Schluessel** (`slug`), nicht ueber den Surrogatschluessel: der
Surrogatschluessel wechselt bei jedem Neuaufbau des Warehouse, und eine Box,
die darauf zeigte, waere danach still falsch verknuepft -- der schlimmste
Fehlertyp, weil ihn niemand bemerkt.

**Verworfene Alternative:** alles in eine Datei. Haette beim ersten Kaltstart
in der Cloud die Konten geloescht.

Die **konforme Pokemon-Dimension** ist die zweite tragende Entscheidung: alle
Spielform-Fakten zeigen auf dieselben Pokemon. Erst dadurch ist die
spieluebergreifende Frage (H13: uebertraegt sich Staerke?) ueberhaupt
formulierbar. Das Sammelkartenspiel passt nicht direkt in dieses Raster --
seine Meta-Einheit ist das Deck, nicht das Pokemon. Statt das Deck kuenstlich
auf Pokemon herunterzubrechen, folgt das Modell der Quelle (`Dim_TCG_Deck`)
und schlaegt die Bruecke ueber das **Leit-Pokemon**, wo eine Aufloesung
gelingt.

---

## 3. Das Messniveau bestimmt Kennzahl und Verfahren

**Ausgangsfrage:** Welche Rechnungen sind erlaubt?

Champions liefert die Nutzung als **Rang**. Ein Rang traegt eine Reihenfolge,
keine Abstaende: Summen, Mittelwerte und Konzentrationsindizes darueber sind
fachlich nicht belastbar. Diese eine Beobachtung zieht sich durch das ganze
Projekt:

* Kennzahlen: Rangdifferenzen, Spearman-Korrelation, Top-N-Fluktuation,
  Verweildauer -- alles rangfest. Der Herfindahl-Index nur dort, wo echte
  Anteile vorliegen (Merkmalsebene).
* Statistik: ausschliesslich verteilungsfreie Verfahren (Spearman,
  Mann-Whitney, Wilcoxon, Kruskal-Wallis, Chi-Quadrat). Ein t-Test setzt
  Intervallskala voraus, die es hier nicht gibt.
* Trends: der Typenverlauf **zaehlt Vertreter** in der Spitzengruppe, statt
  Raenge zu mitteln.

Die neuen Quellen liefern dagegen kardinale Groessen (Score, Personenzaehlung)
-- dort sind Summen und Mittelwerte zulaessig. Damit die Auswertung das nicht
je Fall "weiss", steht das Messniveau als Merkmal **an der Quelle**
(`Dim_Quelle.messniveau_nutzung`), nicht im Code.

---

## 4. Hypothesen: warum ein Katalog und nicht nur ein Dashboard

**Ausgangsfrage:** Woher weiss man, dass ein Muster im Dashboard mehr ist als
Zufall?

Bei 235 Pokemon und zwei Formaten findet das Auge in jeder Grafik ein Muster.
Der Katalog macht daraus pruefbare Aussagen -- mit drei Regeln, die alle eine
konkrete Fehlerquelle abstellen:

1. **Formulierung vor dem Blick in die Daten** (samt beider Befundtexte und
   der Einschraenkung). Wer erst schaut und dann formuliert, prueft nichts
   mehr, sondern beschreibt.
2. **Kein p-Wert ohne Effektstaerke.** Bei n = 235 wird fast alles
   signifikant; erst die Effektstaerke sagt, ob es zaehlt.
3. **Holm-Bonferroni ueber die Familie.** Dreizehn Einzeltests zum Niveau
   5 % lieferten sonst mit rund 49 % Wahrscheinlichkeit mindestens einen
   Zufallstreffer -- ein Katalog ohne Korrektur waere fast garantiert
   "erfolgreich" und damit wertlos.

Dazu zwei Randentscheidungen: **nicht pruefbare** Hypothesen (Quelle nicht
geladen) gehen nicht in die Korrektur ein -- sonst hinge die Strenge der
uebrigen davon ab, was gerade fehlt. Und eine zu duenne Datenbasis wirft eine
Ausnahme, statt still "nicht verworfen" zu melden.

**Lehrstueck H6:** Der naheliegende Chi-Quadrat-Anpassungstest (Typen der
besten 50 gegen das Feld) scheitert an seiner eigenen Voraussetzung -- bei 18
Typen und 50 Plaetzen liegen 17 erwartete Haeufigkeiten unter fuenf. Statt
Klassen zusammenzulegen, bis die Faustregel erfuellt ist, wurde die Frage auf
dem Messniveau der Daten neu gestellt (Kruskal-Wallis ueber die
Rangverteilungen aller Typen). Der Weg steht absichtlich im Docstring der
Pruefung: der verworfene Ansatz ist Teil der Begruendung.

**Warum kein SciPy:** Es gibt keine SciPy-Version, die Python 3.10 bis 3.14
gleichzeitig bedient -- das Projekt hat SciPy dafuer schon einmal ausgebaut.
Die drei benoetigten Verteilungen sind deshalb selbst umgesetzt und gegen
Tabellenwerte getestet; der Verzicht ist nur so nicht mit einer ungeprueften
Eigenentwicklung erkauft.

---

## 5. Use-Case PC-System: warum eine eigene Erfassung

**Ausgangsfrage:** Die Meta-Auswertung sagt, was *andere* spielen. Wo bleiben
die eigenen Pokemon?

Der Gedankengang: alle Analysewerkzeuge (Schadensrechner, Team-Analysen)
brauchen als Eingabe ein konkretes Set -- Pokemon, Item, Faehigkeit, Wesen,
Statuspunkte, Attacken. Ohne eigene Erfassung muesste man dieses Set bei jedem
Aufruf neu zusammenklicken. Das PC-System (benannt nach dem PC der Spiele)
speichert es **dauerhaft und je Nutzer**.

Drei Entscheidungen darin:

* **Auswahl statt Freitext.** Die Erfassungsmaske bietet nur an, was die
  Dimensionen fuehren. Damit ist jeder Box-Eintrag verknuepfbar -- der
  Schadensrechner findet zum Item die Wirkung, zur Attacke den Typ. Freitext
  haette die Erfassung bequemer und jede Auswertung unmoeglich gemacht.
* **Attacken als JSON-Liste statt eigener Tabelle.** Die Spielregeln deckeln
  bei vier; ausgewertet wird die Liste stets als Ganzes. Eine Beziehungstabelle
  waere normalisierter, brachte aber keinen einzigen zusaetzlichen Zugriffsweg.
* **Champions-Regeln, nicht Hauptreihen-Regeln.** Statuspunkte 0-32 je Wert,
  66 gesamt, ein Punkt = +1 Endwert. Die Pruefung sitzt in der Erfassung, mit
  denselben Funktionen (`bi.stats`), die auch der ETL verwendet.

## 6. Use-Case Nutzerkonten: warum selbst gebaut

**Ausgangsfrage:** Die Anwendung steht unter `bi.fablas.org` im offenen Netz;
eigene Teams sind genau die Information, die ein Turniergegner gerne haette.

Streamlit bringt keine Kontenverwaltung mit; externe Dienste (OAuth-Anbieter)
haetten eine Abhaengigkeit und ein Datenschutzthema in ein Hochschulprojekt
geholt. Die Eigenloesung beschraenkt sich auf das seit Jahrzehnten
Standardisierte:

* PBKDF2-HMAC-SHA256 (Standardbibliothek), eigenes Salz je Konto,
  Iterationszahl **im Datensatz** -- sie laesst sich anheben, ohne bestehende
  Konten zu entwerten: beim naechsten erfolgreichen Anmelden wird der Hash
  nachgezogen.
* Vergleich in konstanter Zeit; bei unbekanntem Namen wird trotzdem gehasht,
  damit die Antwortzeit keine Konten verraet. Dieselbe Fehlermeldung fuer
  falschen Namen und falsches Passwort.
* Sperre nach Fehlversuchen ueber das Anmeldeprotokoll -- sie uebersteht damit
  einen Neustart des Dienstes.
* Passwortregel: Laenge schlaegt Zeichenklassen (BSI/NIST-Linie).
  Erzwungene Sonderzeichen erzeugen kuerzere, schlechter merkbare Passwoerter.

Das erste Konto erhaelt die Verwaltungsrolle -- irgendjemand muss einrichten
koennen, und ein fest verdrahtetes Startpasswort waere die schlechtere Loesung.
Danach schuetzt ein Zugangscode die Selbstregistrierung.

## 7. Use-Case Schadensrechner: warum exakt statt ungefaehr

**Ausgangsfrage:** Der Preview-Advisor liefert eine Rangfolge -- reicht das
nicht?

Nein, weil die Einwechselentscheidung an einer Schwelle haengt: *ueberlebt
mein Pokemon diesen Treffer?* Eine Rangfolge kennt keine Schwellen. Der
Rechner setzt deshalb die Schadensformel der Hauptspiele um -- **mit der
Rundungsreihenfolge des Spiels**, denn zwischen den Multiplikatoren wird
abgerundet, und genau an diesen Einzelpunkten entscheiden sich K.-o.-Grenzen.
Halbrundung erfolgt ab 0,5 abwaerts (pokeRound), Brueche in
1/4096-Festkommaschritten wie im Spiel.

Ebenso bewusst die **Grenzen**: Attacken mit variabler Staerke und Feldeffekte
jenseits von Wetter und Schirmen bildet der Rechner nicht ab -- zusammen unter
fuenf Prozent der gespielten Attacken. Ein Rechner, der neun Zehntel der
Faelle exakt trifft und den Rest ausweist, ist ehrlicher als einer, der alles
verspricht. Die Grenzen stehen im Modul-Docstring und in der Oberflaeche.

Items und Faehigkeiten wirken ueber die Dimensionen der Hauptspiele mit --
das ist der Punkt, an dem sich die Investition in `Dim_Item` und
`Dim_Faehigkeit` auszahlt: ein Wahlband ist fuer den Rechner keine
Zeichenkette, sondern ein Multiplikator 6144/4096 auf physische Angriffe.

## 8. Use-Case Trends: vier Fragen, vier rangfeste Antworten

**Ausgangsfrage:** Was macht die Zeitreihe sichtbar, die das Archiv aufbaut?

Die vier Trendauswertungen (starke Typen, Item-Nutzung, Neuzugaenge,
Dauerbrenner) sind bewusst schlicht gehalten -- jede ist eine Zaehlung oder
ein Minimum, nie ein Mittelwert ueber Raenge. Der interessanteste Fall ist der
Typenverlauf: "mittlerer Rang je Typ" waere die naheliegende und falsche
Kennzahl; gezaehlt werden stattdessen Vertreter in der Spitzengruppe.
"Dauerhaft stark" delegiert an die bestehende Verweildauer, statt sie zu
duplizieren -- eine Kennzahl, zwei Verwendungen, eine Wahrheit.

---

## 9. Betrieb: GitHub Actions sammelt, der Jetson serviert

**Ausgangsfrage:** Wo laeuft was -- und warum nicht alles an einem Ort?

* **Sammeln** muss taeglich und zuverlaessig geschehen, weil Champions nach
  14 Tagen vergisst. GitHub Actions ist dafuer der robustere Ort: laeuft auch,
  wenn der Jetson aus ist, und schreibt das Archiv versioniert ins Repository.
* **Servieren** braucht Rechenzeit und einen dauerhaften Speicher fuer die
  Nutzerdaten -- das ist der Jetson. Er zieht den Datenstand per `git pull`
  und verarbeitet ihn **ohne Netzzugriff** aus dem Archiv; die Reihenfolge
  "erst sichern, dann pruefen" bleibt gewahrt.
* **Veroeffentlichen** uebernimmt ein Cloudflare Tunnel (`bi.fablas.org`):
  kein offener Port, Streamlit lauscht nur auf 127.0.0.1. Die Zugangskontrolle
  liegt in der Anwendung -- sie muss auch gelten, wenn jemand im Heimnetz
  steht.

Ein Ausfall des Jetson kostet damit nichts Unwiederbringliches ausser der
Nutzerdatenbank -- und genau die wird taeglich per `VACUUM INTO` gesichert
(kein Dateikopieren waehrend eines Schreibvorgangs).

---

## 10. Die Feedback-Runde: fünf Befunde, fünf Entscheidungen

Eine Nutzerrückmeldung (August 2026) hat fünf Schwächen benannt; die
Antworten darauf sind jeweils eine Entscheidung, kein Pflaster:

* **„Manche Hypothesen sind banal."** Der Befund traf die Titel, nicht die
  Prüfungen: H5, H8 und H9 haben ein durch die Spielregeln festgelegtes
  Soll-Ergebnis — genau das macht sie zum Known-Answer-Test der eigenen
  Datenkette. Diese Rolle war unsichtbar. Jetzt trägt jede Hypothese eine
  **Art** (Erkenntnisfrage oder Datenprobe) und einen **Anwendungsfall**
  („welche Entscheidung hängt am Ergebnis?"), die Titel sind Fragen, und ein
  Test erzwingt beides dauerhaft. Verworfen: die banalen Prüfungen streichen —
  dann stünde jede andere Auswertung ohne Beleg da, dass die Verarbeitung die
  Spielrealität überhaupt abbildet.
* **„Die Generationsstatistik zeigt nur 2026."** Stimmt zwingend: die
  Zeitdimension beginnt mit dem ersten Champions-Tag. Die Frage „wie wuchs der
  Pokédex?" spielt auf der Zeitachse der Hauptspiele (1996–2022), und die
  steht in keiner Quelle. Sie liegt jetzt als eigene Regelbasis
  (`bi.generationen`) neben der Typen-Matrix — Stammdaten ohne Quellsystem,
  durch Tests gesichert. Verworfen: Erscheinungsdaten in die Zeitdimension
  mischen; ein Faktentag 1999 ohne Fakten wäre Modellverschmutzung.
* **„Namen bitte auf Deutsch."** Der englische Anzeigename bleibt der
  Schlüssel zwischen den Quellsystemen; die deutsche Übersetzung (`name_de`
  in vier Dimensionen, aus den PokeAPI-Übersetzungen) ist reine Beschriftung:
  nicht im `row_hash`, wird fortgeschrieben statt getilgt, fällt bei fehlender
  Übersetzung auf Englisch zurück statt zu raten. Auswahlfelder zeigen und
  finden beide Namen. Verworfen: die Anwendung komplett umzustellen — dann
  wäre jeder Abgleich mit der Quelle (die englisch liefert) ein Ratespiel.
* **„Wo bekomme ich ein Pokémon in welcher Generation?"** Fundorte je
  Spielstand pflegen Bisafans und PokéWiki seit Jahren in einer Tiefe, die
  sich nicht sinnvoll ins Warehouse duplizieren lässt — und die dortigen
  Artikel sind über den deutschen Namen präzise adressierbar. Der Pokédex
  verlinkt deshalb, statt zu kopieren. Verworfen: die Encounter-Endpunkte der
  PokeAPI als fünfte Quelle; hunderte Ressourcen je Spielversion für eine
  Auskunft, die als Link besser altert.
* **„Was ist mit Casuals?"** Der Pokédex ist die Antwort in Seitenform: voller
  Bestand statt Ranked-Ausschnitt, Typen-Berater aus der Regelbasis (hilft
  gegen jeden Arenaleiter, ganz ohne Meta), Steckbrief mit beiden
  Wertesystemen. Die Turnierseiten bleiben unangetastet — eine Seite, die
  beides gleichzeitig sein will, wäre keins von beidem.

---

## 11. Was bewusst nicht gebaut wurde

* **Keine Nutzungsquote fuer Champions.** Die Quelle liefert keine; ein
  Platzhalter waere eine Erfindung. Stattdessen ordinale Kennzahlen und ein
  ausdruecklich als Ableitung gekennzeichnetes Rangperzentil.
* **Keine Team-Preview-Mitnahmequote.** Existiert oeffentlich nicht -- und
  eine Durchschnittsquote sagte ohnehin nicht, was gegen *dieses eine* Team
  richtig ist. Der Advisor rechnet stattdessen die konkrete Paarung durch.
* **Kein SciPy, kein OAuth, kein ORM.** Jede Abhaengigkeit muss ihre
  Festlegbarkeit ueber Python 3.10-3.14 nachweisen; drei
  Verteilungsfunktionen, eine Anmeldemaske und ein Dutzend SQL-Abfragen
  rechtfertigen keine.
* **Kein Live-Zugriff der Auswertung auf die Quellen.** Alles laeuft gegen
  das Warehouse; die Quellen werden genau einmal am Tag angefasst. Eine
  Auswertung, die bei jedem Seitenaufruf eine fremde API fragt, waere so
  schnell wie das langsamste fremde System.
