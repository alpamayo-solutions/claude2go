# Roadmap-Vorschlag claude2go (v2)

## 1. Top-Verbesserungen (Impact beim Fahren / Aufwand)

1. **STT-Confidence-Gate** (S) — `stt.py` verwirft `_info` und jede Segment-Konfidenz; Whisper halluziniert auf Fahrgeräusch bekanntermaßen Text, der im offenen 20s-Antwortfenster oder als „Ja" im Freigabedialog durchgeht. Segmente mit hoher `no_speech_prob` / schlechtem `avg_logprob` filtern, im Freigabe-Kontext strenger — schließt die einzige unbewachte Tür, durch die Rauschen eine Aktion freigeben kann (~20 Zeilen).
2. **Funkloch-Auto-Retry** (S) — `_recover_session` bittet nach Netzabbruch den Fahrer, den Auftrag neu zu diktieren, obwohl `message` im `_turn_worker` noch im Scope liegt. Nachricht nach Reconnect einmal automatisch re-queuen („Verbindung war weg, ich schicke es nochmal"); auf der Pendelstrecke mit Tunneln ist das der häufigste Fehlerfall.
3. **Sofort-Earcon bei Äußerungsende** (S) — zwischen Segment-Ende und Whisper-Ergebnis vergehen mehrere Sekunden ohne jedes Feedback; der Fahrer weiß nicht, ob das Mikro ihn erfasst hat, und wiederholt sich. Ein leiser Tick direkt beim Dequeue vor `transcriber.transcribe` macht 3s STT-Latenz wahrgenommen irrelevant.
4. **Verständliche, kontextreiche Freigabe-Ansagen + „Wiederhole"** (M) — `risk.py` liest den Roh-Shellbefehl vor („git push origin … --force-with-lease" ist bei Fahrgeräusch nicht parsebar) und eine überhörte Frage endet nach 30s stumm im Deny. Pro Risiko-Kategorie eine deutsche Kurzform mit billigem Kontext („3 Commits auf main pushen"), Rohbefehl nur auf Nachfrage, „wiederhole" wiederholt die Frage — betrifft die gefährlichste Interaktion des Systems.
5. **Fenster-zu-Signal + Kulanz bei knapp verpassten Antworten** (S) — das 20s-Fenster schließt lautlos; eine Äußerung 2s danach wird still verworfen und der Fahrer wartet minutenlang auf einen Auftrag, der nie ankam. Earcon beim Ablauf plus Nachfrage („Meintest du mich?") bei substanziellen Äußerungen kurz nach Fensterschluss — `captured_at` macht den Zeitvergleich trivial.

*Knapp dahinter:* Mikrofon-Watchdog (Stream-Status/`finished_callback` in `audio.py`, M) und Lebenszeichen-Ping bei langen Turns (S) — beide sinnvoll, aber erst nach den fünf oben.

## 2. Top-Features

1. **Blitznotiz „Claude, merk dir …"** (S) — neues lokales Kommando in `wake.parse_command`, schreibt in eine TODO-Datei im cwd, quittiert nur mit Ack-Earcon. Gedanken-Capture in <1s statt vollem Turn; beim Fahren sind Ideen in 10 Sekunden weg.
2. **Voice-Barge-in per Stopp-Keyword-Gate** (M) — heute läuft eine 700-Zeichen-Antwort bis zu ~40s unaufhaltbar, Abbruch nur per Enter-Taste. Mikro während TTS aktiv lassen, aber Utterances ausschließlich gegen die STOP-Wörter matchen — die eigene TTS-Stimme sagt nie isoliert „Stopp", das Feedback-Risiko ist minimal. Ersetzt das L-teure Satz-Lücken-Konzept. *(Deduped aus 2 Agenten.)*
3. **Auto-Recap bei `--continue`** (S) — nach dem Einsteigen automatisch eine synthetische Nachricht senden („Fasse in 2 Sätzen zusammen, wo wir standen") und vorlesen; Orientierung ist der erste Bedarf am Anfang der Fahrt, und der VOICE_STYLE-Prompt erzwingt bereits Kürze.
4. **Morgen-Briefing „Claude, Briefing"** (M) — kuratierter Prompt-Turn über git status, `gh`-CI-Stand und offene `alp`-Karten (via `setting_sources` bereits im Session-Kontext). Verwandelt die ersten 2 Pendel-Minuten in Tagesplanung ohne drei Einzelfragen.
5. **JSONL-Fahrtenprotokoll** (M) — heute ist alle Observability `print()` nach stdout und nach der Fahrt weg. Append-only Log (Utterance + STT-Konfidenz, Routing, Freigaben, Fehler, Turn-Dauer) macht jede Fahrt am Schreibtisch debugbar und ist die Datenbasis fürs Tuning von Wake/VAD/Timeouts — ohne Log keine Iteration als Solo-Entwickler.

*Verworfen/vertagt:* Handy als Audio-Frontend (stärkste physische Verbesserung, aber L und eigenes Projekt), Projektwechsel per Stimme (real eher M-L, nach Config-Datei sinnvoller), CI-Wache (nice-to-have nach Briefing).

## 3. TTS-Empfehlung

**Ehrliches Fazit: `say` + Anna Premium bleibt der Default.** Für kurze deutsche Ansagen auf M-Series gewinnt `say` die Achse, die im Auto zählt: Time-to-first-audio ≈ 0. Die beiden Researcher widersprechen sich beim einzigen echten Kandidaten sogar in der Qualitätsbewertung („klar wärmer" vs. „etwa gleichauf").

Maximal zwei Kandidaten, falls du es wissen willst:

| Kandidat | Lizenz | Erwartete Latenz (M-Series) | Einschätzung |
|---|---|---|---|
| **Piper + de_DE-thorsten-high** | Engine GPL-3.0 (aktiver Fork; altes MIT-Repo archiviert), Voices frei | ~0,1–0,3s pro Satz, CPU, offline | Einziger Kandidat, der `say`-Latenz hält. `pip install piper-tts`, ~100 MB Voice, ~5 Zeilen Code. |
| **Kartoffelbox_Turbo / Chatterbox** | CC-BY-4.0 / MIT | realistisch 1–5s pro Äußerung (die 75–200ms-Angaben sind CUDA-Zahlen) | Deutlich natürlicher, aber bricht den Hands-free-Flow; Turbo-Finetune explizit experimentell. Nur als Spike mit Satz-Streaming denkbar. |

**Empfehlung:** Ein zeitboxter A/B-Test (1h) mit Piper/Thorsten. Klingt er dir nicht *deutlich* besser als Anna Premium, bleib bei `say` — nichts anderes schlägt es auf der Latenz-Achse. Kokoro (kein offizielles Deutsch), XTTS-v2/F5/Fish (Non-Commercial-Lizenzen + Mac-Latenz) und Orpheus (CUDA-Stack) fallen alle durch harte Gates. Qwen3-TTS (Apache 2.0, MLX) in 6 Monaten neu prüfen. Falls du später Barge-in mit Streaming willst, ist RealtimeTTS (MIT) der passende Wrapper — Architektur-, kein Qualitätsargument.

## 4. Mein Vorschlag

1. **STT-Confidence-Gate zuerst** — kleinster Aufwand, größtes Sicherheitsloch: aktuell kann Reifenrauschen ein „Ja" im Freigabedialog werden.
2. **Funkloch-Auto-Retry** — der häufigste reale Fehlerfall der Pendelstrecke, und der Fix sind wenige Zeilen, weil die Nachricht schon im Scope liegt.
3. **Voice-Barge-in per Stopp-Gate** — beseitigt den letzten zwingenden Griff zur Tastatur; danach ist das System erstmals vollständig hands-free bedienbar.

Kein TTS-Wechsel jetzt (höchstens der 1h-Piper-Test nebenbei); direkt danach das JSONL-Log, damit jede weitere Iteration auf Fahrtdaten statt Bauchgefühl basiert.

---

*Ergänzung (vom Nutzer gesetzt): das iPhone-Audio-Frontend (siehe docs/superpowers/specs/2026-07-10-phone-frontend-design.md) ist unabhängig von obiger Priorisierung als Feature geplant — Hotspot-LAN zuerst, Headscale-Tailnet danach.*
