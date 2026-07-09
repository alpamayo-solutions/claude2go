# Claude-to-go (c2g) — Design

**Datum:** 2026-07-09 · **Status:** vom Nutzer freigegeben (Ansatz A), Bau autorisiert

## Ziel

Freihändiges Arbeiten mit Claude Code beim Autofahren. Der Nutzer spricht, Claude
arbeitet autonom im Projektverzeichnis, gesprochen wird nur das Nötigste — kurz,
auf Deutsch, mit klaren Entscheidungsfragen.

## Entscheidungen (aus dem Brainstorming)

| Frage | Entscheidung |
|---|---|
| Kopplung an Claude | **Claude Agent SDK (Python)** — startet das lokale `claude`-Binary mit Abo-Login; verifiziert funktionsfähig ohne API-Key |
| Mic-Trigger | **Wake-Word "Claude"** + offenes Antwortfenster direkt nach jeder vorgelesenen Frage/Antwort |
| Sprachausgabe | **Nur Fragen, Freigaben, Endergebnisse.** Stille während der Arbeit |
| Autonomie | **Voll autonom, riskante Aktionen per Sprache freigeben** (git push, rm, deploy, …) |
| Setup | Laptop im Auto am Hotspot; STT/TTS lokal (funklochfest), nur Claude braucht Netz |
| Stil | Deutsch, max. 2 kurze Sätze, endet mit Entscheidungsfrage oder „Wie machen wir weiter?" |
| Später | Handy als entferntes Audio-Ende (Variante 3) — Audio-Schicht daher austauschbar gekapselt |
| Docker | Verworfen: Docker Desktop auf macOS hat keinen Mic-/Speaker-Zugriff. Stattdessen `uv tool install` |

## Architektur

```
Mikro (sounddevice, echtes Gerät — NICHT BlackHole)
  → VAD-Segmentierung (webrtcvad, Fallback: RMS)
  → STT lokal (faster-whisper, small, Deutsch)
  → Router: Wake-Word? Antwortfenster offen? Kommando (stopp/status)?
  → ClaudeSession (Agent SDK, persistent, setting_sources user+project)
      ↳ can_use_tool-Callback → Risk-Klassifikator → riskant? per Stimme fragen
  → Endergebnis → Sanitizer (Markdown raus) → TTS (macOS `say`, Anna)
  → Antwortfenster öffnet sich (ohne Wake-Word antworten)
```

Komponenten (je eine Datei, klar geschnitten):

- `audio.py` — Mikro-Stream + VAD-Segmentierung in eigenem Thread, liefert fertige Äußerungen als Audio-Arrays in eine asyncio-Queue. Gerät per Namens-Substring wählbar (Default: „MacBook Pro Microphone", da BlackHole Standard-Input ist).
- `stt.py` — faster-whisper-Wrapper (CPU int8, `language=de`, `initial_prompt` biased auf „Claude", Git-Vokabular).
- `tts.py` — `say`-Wrapper (unterbrechbar), Earcons via `afplay` (Fenster auf/zu, Fehler), Text-Sanitizer.
- `wake.py` — Wake-Varianten-Matching (claude/cloud/klaut/…), Kommandos: stopp, status.
- `risk.py` — Klassifikator: Bash-Regex-Liste + MCP-Namens-Heuristik → `allow` oder `ask`.
- `session.py` — Agent-SDK-Client: query/stream/interrupt, `can_use_tool`, Turn-Ergebnis extrahieren.
- `app.py` — Orchestrierung/Zustandsmaschine, Antwortfenster, Freigabe-Dialog.
- `cli.py` — `c2g` Entry Point: voice (default), `--typed`, `--send`, `--continue`, `doctor`.
- `prompts.py` — Sprachmodus-Systemprompt (append), deutsch.
- `config.py` — Defaults + CLI-Overrides.

## Verhalten im Detail

- **Mikro immer an**, aber weitergeleitet wird nur: Äußerung beginnt mit Wake-Variante,
  ODER Antwortfenster ist offen (20 s nach jeder gesprochenen Frage/Antwort).
- **Während TTS spricht ist das Mikro stumm** (Echo-Schutz: Anna sagt „Claude" → Feedback-Schleife).
- **„Claude stopp"** → TTS abbrechen + `client.interrupt()`. **„Claude Status"** → lokale Ansage
  (arbeitet seit X, zuletzt Tool Y) ohne Claude zu stören.
- **Freigabe-Dialog:** riskante Aktion → Earcon + „Claude möchte: <Kurzform>. Ja oder Nein?"
  → Ja/Nein-Parsing; unklar → einmal nachfragen; Timeout 30 s → Deny mit Hinweis, später erneut zu fragen.
- **AskUserQuestion-Tool ist deaktiviert**; Claude stellt Fragen als Text am Turn-Ende (wird vorgelesen).
- **Neue Nachricht während Claude arbeitet:** wird gepuffert und nach Turn-Ende gesendet (Earcon als Quittung).
- **Session-Fortsetzung:** `--continue` nutzt `continue_conversation` (letzte Session im cwd).

## Fehlerbehandlung

- Kein Netz/SDK-Fehler → Basso-Earcon + kurze Ansage („Verbindung weg, ich versuche es weiter").
- STT-Leerergebnis/zu kurz → verwerfen, kein Feedback (sonst nervt jedes Radio-Geräusch).
- `doctor` prüft: echtes Mikro gefunden, macOS-Mikrofonberechtigung, Anna-Stimme, Whisper-Modell (lädt herunter), SDK-Roundtrip mit Abo-Login.

## Tests

- Unit: Wake-Matching, Risk-Klassifikator, TTS-Sanitizer, Ja/Nein-Parser.
- E2E ohne Auto: `c2g --send "…"` (eine Nachricht, Antwort auf stdout+TTS) und `--typed`-Modus.
- Vor der Fahrt: einmal `c2g doctor` am Schreibtisch (löst macOS-Mikrofon-Prompt aus, lädt Modell).

## Offen / bewusst v1-Grenzen

- Barge-in während TTS nur per Enter-Taste, nicht per Stimme (Echo-Problem).
- Anthropic-Policy-Verdikt zur Abo-Nutzung im SDK: Recherche läuft parallel; technisch verifiziert.
- Handy-Frontend (Variante 3): späterer Ausbau, Audio-Schicht ist dafür gekapselt.
