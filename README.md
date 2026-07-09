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
uv tool install --editable /Users/till/Projects/voice
```

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

- **„Claude, …"** — Auftrag oder Gedanke; auch „Hey Claude …".
- Nach jeder vorgelesenen Antwort ist das Mikro **20 Sekunden offen** — einfach
  antworten, ohne Wake-Word (Glas-Klang = Fenster offen).
- **„Claude, stopp"** — bricht Sprachausgabe und laufende Arbeit ab.
- **„Claude, Status"** — sagt dir, ob und wie lange er schon arbeitet.
- Riskante Aktionen (push, rm, deploy, Plattform-Schreibzugriffe …) fragt er
  laut an: mit **Ja** oder **Nein** antworten. Keine Antwort = abgelehnt,
  Claude arbeitet am Rest weiter.
- Während Claude arbeitet ist es still. Neue Aufträge werden gepuffert
  (Plopp-Klang) und nach dem Turn gesendet.
- Enter-Taste stoppt die Sprachausgabe, `q` + Enter beendet, Ctrl+C auch.

## Konfiguration

Defaults in `src/claude_to_go/config.py`; die wichtigsten per Flag:
`--mic` (Substring des Gerätenamens, Default „MacBook Pro Microphone" — bewusst
nicht das Standard-Input-Gerät, da dort BlackHole hängt), `--voice` (Default
Anna), `--whisper-model` (Default small), `--mute`.

## Grenzen (v1)

- Während der Sprachausgabe ist das Mikro stumm (Echo-Schutz) — unterbrechen
  per Enter-Taste, nicht per Stimme.
- Docker/Compose ist bewusst kein Setup-Weg: Container auf macOS haben keinen
  Mikrofon-/Lautsprecher-Zugriff.
