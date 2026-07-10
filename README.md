# Claude-to-go (`c2g`)

Freihändig mit Claude Code arbeiten — gebaut fürs Auto. Immer-an-Mikrofon mit
Wake-Word, lokale Spracherkennung (offline, funklochfest), kurze deutsche
Antworten per Sprachausgabe, riskante Aktionen werden per Stimme freigegeben.

Nutzt das offizielle Claude Agent SDK, das dein lokal installiertes
`claude`-Binary mit deinem Abo-Login startet — gleiche Engine, gleiche
CLAUDE.md-Regeln und Skills wie deine normale Session. Einziger persönlicher
Single-User-Betrieb; Account/Token nicht teilen, nicht für Dritte betreiben.

## Installation

```bash
uv tool install "git+https://github.com/alpamayo-solutions/claude2go"
# oder für lokale Entwicklung:
uv tool install --editable /Users/till/Projects/voice
```

Voraussetzungen: macOS, installiertes Claude Code (`claude login` mit eigenem
Abo — Accounts/Tokens niemals teilen), `uv`.

Danach **einmal am Schreibtisch** (löst den macOS-Mikrofon-Prompt aus und lädt
das Whisper-Modell herunter):

```bash
c2g doctor
```

## Benutzung

```bash
cd ~/projects/mein-projekt
c2g                  # Voice-Modus
c2g --continue       # letzte Unterhaltung im Verzeichnis fortsetzen
c2g --typed          # tippen statt sprechen (Ausgabe trotzdem per Stimme)
c2g --send "Wie viele offenen TODOs gibt es?"   # Einzelnachricht, dann Ende
c2g --model opus     # Modell-Override
```

### Im Auto

- **„Claude, …"** — Auftrag oder Gedanke; auch „Hey Claude …". Ein leiser
  Tick bestätigt: gehört, wird verarbeitet. Der Hero-Klang: er legt los.
- Nach jeder vorgelesenen Antwort ist das Mikro **20 Sekunden offen** — einfach
  antworten, ohne Wake-Word (Glas-Klang = offen, Flaschen-Klang = zu). Sprichst
  du kurz nach dem Schließen, fragt er nach: „Meintest du mich?"
- **„Claude, stopp"** — bricht Sprachausgabe und Arbeit ab; funktioniert auch
  **mitten in seine Stimme hinein** (Voice-Barge-in).
- **„Claude, Status"** — sagt dir, ob und wie lange er schon arbeitet.
- **„Claude, merk dir …"** — Blitznotiz in `NOTIZEN.md`, quittiert nur per
  Plopp; kein Claude-Turn, unter einer Sekunde.
- **„Claude, Briefing"** — Branch, Git-Status, CI, offene Aufgaben in vier Sätzen.
- Während Claude arbeitet: **einfach reinreden** — Zwischenfragen werden in den
  laufenden Turn injiziert und sofort beantwortet.
- Riskante Aktionen fragt er in Klartext an („Claude möchte auf Git pushen:
  origin main. Ja oder Nein?"). **Ja/Nein** entscheiden, **„wiederhole"**
  wiederholt, **„details"** liest den Rohbefehl vor. Whisper-unsichere Antworten
  (Radio, Rauschen) werden ignoriert — nur klare Antworten zählen.
- Bricht die Verbindung ab (Funkloch), verbindet er sich neu und **schickt
  deinen Auftrag automatisch nochmal**.
- `c2g --continue` liest beim Start ein kurzes Recap vor: wo wart ihr stehen
  geblieben.
- Jede Fahrt wird als JSONL-Protokoll unter `~/.c2g/logs/` mitgeschrieben
  (`--no-log` schaltet ab).
- Enter-Taste stoppt die Sprachausgabe, `q` + Enter beendet, Ctrl+C auch.

### iPhone als Mikro & Lautsprecher (CarPlay-nah)

```bash
c2g --phone
```

Startet einen Server samt QR-Code; iPhone scannen, Safari öffnet die PWA
(einmal dem selbstsignierten Zertifikat vertrauen, „Start" tippen). Ab dann:
iPhone-Mikro nimmt auf, Antworten spielen über das iPhone — und CarPlay/
Bluetooth routet sie auf die Autoboxen. Große Ja/Nein/Stopp-Buttons als
Touch-Fallback, Live-Transkript auf dem Display. Mit Tailscale/Headscale
funktioniert das auch, wenn der Mac zuhause bleibt.

## Konfiguration

Defaults in `src/claude_to_go/config.py`; die wichtigsten per Flag:
`--mic` (Substring des Gerätenamens, Default „MacBook Pro Microphone" — bewusst
nicht das Standard-Input-Gerät, da dort BlackHole hängt), `--voice` (Default
Anna), `--whisper-model` (Default small), `--mute`.

## Grenzen

- Während der Sprachausgabe reagiert das Mikro nur auf Stopp-Wörter
  (Echo-Schutz); alles andere sagst du danach.
- Docker/Compose ist bewusst kein Setup-Weg: Container auf macOS haben keinen
  Mikrofon-/Lautsprecher-Zugriff.
