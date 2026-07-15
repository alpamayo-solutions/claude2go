# Claude-to-go (`c2g`)

[🇬🇧 English](README.md) · **🇩🇪 Deutsch**

> Freihändig mit Claude Code arbeiten — beim Autofahren, Spazieren, Training
> oder Pendeln. Immer dann, wenn die Hände nicht frei sind.

Du sagst „Claude, fix die failenden Tests", Claude arbeitet im Projekt und
liest dir eine kurze Antwort vor. Immer-an-Mikrofon mit Wake-Word, lokale
Spracherkennung (offline, funklochfest), riskante Aktionen wie `git push`
werden per Stimme freigegeben. Optional steuerst du alles vom iPhone — die
Antworten laufen dann über CarPlay aus den Autoboxen.

<p align="center">
  <img src="docs/screenshots/ready.png" width="30%" alt="Bereit, mit Transkript">
  <img src="docs/screenshots/working.png" width="30%" alt="Claude arbeitet">
  <img src="docs/screenshots/permission.png" width="30%" alt="Freigabe-Dialog">
</p>
<p align="center"><sub>iPhone-Frontend: bereit · arbeitet · Freigabe per Ja/Nein</sub></p>

## Wie es funktioniert

c2g ist eine dünne Sprachschicht **auf deiner normalen Claude-Code-Session** —
kein API-Zugang, kein zweites Modell. Es startet dein lokal installiertes
`claude`-Binary über das offizielle Claude Agent SDK mit **deinem Abo-Login**:
gleiche Engine, gleiche `CLAUDE.md`-Regeln und Skills wie im Terminal.

> **Nur persönlicher Einzelbetrieb.** Dein Account und dein Token bleiben bei
> dir — nicht teilen, nicht für Dritte betreiben. Jeder Nutzer meldet sich mit
> seinem eigenen Claude-Abo an.

## Installation

```bash
uv tool install "git+https://github.com/alpamayo-solutions/claude2go"
```

**Voraussetzungen:** macOS · [Claude Code](https://claude.com/claude-code) mit
eigenem Abo (`claude login`) · [`uv`](https://docs.astral.sh/uv/).

Danach **einmal am Schreibtisch** ausführen — das löst den macOS-Mikrofon-
Dialog aus, lädt das Spracherkennungs-Modell herunter und prüft die ganze
Kette:

```bash
c2g doctor
```

## Loslegen

```bash
cd ~/projekte/mein-projekt
c2g
```

Claude begrüßt dich, danach sagst du **„Claude, …"** gefolgt von deinem
Auftrag. Beenden mit `q` + Enter oder Ctrl+C.

| Befehl | Zweck |
|---|---|
| `c2g` | Voice-Modus im aktuellen Projekt |
| `c2g --continue` | letzte Unterhaltung fortsetzen (mit gesprochenem Recap) |
| `c2g --resume [ID]` | bestimmte Session fortsetzen (ohne ID: letzte im Verzeichnis) |
| `c2g --phone` | iPhone als Mikro & Lautsprecher (siehe unten) |
| `c2g --typed` | tippen statt sprechen, Ausgabe trotzdem per Stimme (zum Testen) |
| `c2g --send "..."` | eine Nachricht, Antwort, Ende (für Skripte) |
| `c2g --lang de\|en` | Sprache der Bedienung für diesen Lauf |
| `c2g --model opus` | anderes Modell verwenden |
| `c2g doctor` | Setup einmalig prüfen |

## Sprache

Deutsch ist der Default; Englisch wird vollständig unterstützt — Wake-
Vokabular, gesprochene Sätze, Spracherkennung und Stimme wechseln gemeinsam.

Pro Lauf mit `--lang en` setzen oder dauerhaft in `~/.c2g/config.toml`
festlegen:

```toml
language = "en"
```

Die Rangfolge ist immer **CLI-Flag > Einstellungsdatei > eingebauter
Default**. Auch andere Vorlieben lassen sich dort festpinnen, z.B. `voice`,
`speech_rate`, `whisper_model`, `mic_device`, `model`.

## Freihändige Sprachbedienung

**Reden:**

- **„Claude, …"** — Auftrag oder Gedanke (auch „Hey Claude …"). Ein leiser
  **Tick** bestätigt „gehört", der **Hero-Klang** heißt „ich lege los".
- Nach jeder Antwort ist das Mikro **20 Sekunden offen** — du antwortest
  direkt, ohne Wake-Word (Glas-Klang = offen, Flaschen-Klang = zu). Sprichst
  du kurz nach dem Schließen, fragt er nach: *„Meintest du mich?"*
- **Während Claude arbeitet einfach reinreden** — Zwischenfragen fließen in
  den laufenden Auftrag ein und werden sofort beantwortet.

**Kommandos** (deutsche / englische Trigger-Wörter, wo sie sich
unterscheiden):

- **„Claude, stopp"** / *„Claude, stop"* — bricht Sprachausgabe und Arbeit
  ab, auch mitten in seine Stimme hinein (Voice-Barge-in).
- **„Claude, Status"** — ob und wie lange er schon arbeitet.
- **„Claude, merk dir …"** / *„Claude, note …"* — Blitznotiz in die
  Notizdatei im Projekt (`NOTIZEN.md` / `NOTES.md`), quittiert nur mit einem
  Ton, kein Auftrag. Ideen sind unterwegs sonst in 10 Sekunden weg.
- **„Claude, Briefing"** — Branch, Git-Status, CI und offene Aufgaben in vier
  kurzen Sätzen.

**Freigaben:** Riskante Aktionen fragt Claude in Klartext an —
*„Claude möchte auf Git pushen: origin main. Ja oder Nein?"* Du antwortest
**Ja** / **Nein**; **„wiederhole"** (*"repeat"*) wiederholt die Frage,
**„details"** liest den genauen Befehl vor. Unsichere Antworten (Radio,
Fahrgeräusch) werden ignoriert — nur klar verstandene zählen. Keine Antwort =
abgelehnt, Claude macht mit dem Rest weiter.

**Unterwegs robust:** Bricht die Verbindung ab (Funkloch), verbindet Claude
sich neu und schickt deinen Auftrag automatisch nochmal — ohne blind schon
Erledigtes zu wiederholen. Jede Fahrt landet als JSONL-Protokoll unter
`~/.c2g/logs/` (`--no-log` schaltet es ab).

## iPhone als Mikro & Lautsprecher

```bash
c2g --phone
```

Es erscheint ein QR-Code im Terminal. iPhone scannen → Safari öffnet die App →
**„Start"** tippen. Ab dann nimmt das iPhone-Mikro auf und die Antworten
laufen über das iPhone — **CarPlay oder Bluetooth routet sie automatisch auf
die Autoboxen**. Auf dem Display: Live-Transkript und große
**Ja / Nein / Stopp**-Knöpfe als Touch-Alternative zur Stimme.

- Das iPhone-Mikro in der Halterung sitzt näher an dir als das Laptop-Mikro —
  bessere Erkennung. Zusätzlich erlaubt Safaris Echo-Unterdrückung echtes
  Voice-Barge-in.
- Beim ersten Öffnen einmal dem selbstsignierten Zertifikat vertrauen (Safari:
  „Details" → „Webseite öffnen").
- Jede Sitzung erzeugt ein **Zufalls-Token**, das in der QR-Code-URL steckt —
  ohne gültiges Token wird jede Verbindung abgewiesen. Der Server ist nur in
  deinem lokalen Netz erreichbar (im Auto: dein iPhone-Hotspot).
- Mit **Tailscale/Headscale** funktioniert das auch, wenn der Mac zuhause
  bleibt und nur das iPhone mitfährt.

## Konfiguration

Sinnvolle Defaults sind gesetzt; das Wichtigste per Flag:

| Flag | Bedeutung |
|---|---|
| `--mic "..."` | Mikrofon per Namensteil wählen (Default „MacBook Pro Microphone") |
| `--voice "..."` | TTS-Stimme (Default: beste installierte Stimme der aktiven Sprache) |
| `--whisper-model` | Erkennungsmodell (Default `small`) |
| `--mute` | keine Sprachausgabe, nur Konsole |
| `--no-log` | kein Fahrtenprotokoll |

Für eine natürlichere Stimme in den *Systemeinstellungen → Bedienungshilfen →
Gesprochene Inhalte* eine Premium-Stimme laden (z.B. „Anna (Premium)" für
Deutsch) — c2g wählt automatisch die beste installierte Stimme für die aktive
Sprache.

## Grenzen

- Während der Sprachausgabe reagiert das Mikro nur auf Stopp-Wörter
  (Echo-Schutz); alles andere sagst du danach.
- Docker/Compose ist bewusst kein Setup-Weg: Container haben auf macOS keinen
  Mikrofon-/Lautsprecher-Zugriff.

## Lizenz

[MIT](LICENSE) © 2026 Alpamayo Solutions
