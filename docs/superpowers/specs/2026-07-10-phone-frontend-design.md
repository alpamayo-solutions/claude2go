# Feature-Spec: iPhone als Audio-Frontend (CarPlay-nah, ohne App)

**Datum:** 2026-07-10 · **Status:** geplant, vom Nutzer angefordert · **Aufwand:** M

## Ziel

Mikrofon und Sprachausgabe wandern vom MacBook aufs iPhone. CarPlay routet das
iPhone-Audio automatisch auf die Autoboxen; das iPhone-Mikro in der Halterung
ist näher am Fahrer als das Laptop-Mikro. Keine CarPlay-App nötig (Entitlement
für Dev-Tools nicht erreichbar) — nur „iPhone spielt Ton".

## Architektur

- **Phone-Seite: PWA statt App.** Eine einzelne HTML-Seite (Vanilla JS, kein
  Build-Step), ausgeliefert vom Mac. `getUserMedia` streamt Mikro-PCM über
  WebSocket; empfangenes TTS-Audio spielt ein `<audio>`/WebAudio-Element.
  Als Home-Bildschirm-PWA installierbar; aktive Audio-Session hält Safari wach.
- **Mac-Seite: `c2g --audio remote`.** Neuer `AudioServer` (aiohttp, WS + TLS)
  ersetzt `MicListener` als Äußerungsquelle (gleiche VAD-Segmentierung auf den
  empfangenen PCM-Frames) und `RemoteSpeaker` ersetzt `Speaker` (rendert mit
  `say -o` in WAV und streamt ans Phone; Earcons als JSON-Event, Sounds liegen
  im Frontend). Router, Whisper, Claude-Session, Freigabe-Gate: unverändert.

## Protokoll (eine WS-Verbindung, duplex)

Phone → Mac: binäre PCM-Chunks (16 kHz mono int16, ~100 ms) ·
`{"type":"hello","client":"iphone"}`

Mac → Phone: binäre WAV-Chunks (TTS) ·
`{"type":"earcon","name":"listen|ack|start|error|attention"}` ·
`{"type":"transcript","text":…}` / `{"type":"status",…}` (On-Screen-Anzeige)

## Netz & Sicherheit

- Im Auto: Mac hängt am iPhone-Hotspot → direkte LAN-Verbindung.
- Remote-Szenario (Mac bleibt zuhause): Tailnet über den bestehenden
  **Headscale**-Server (iPhone mit normalem Tailscale-Client). Damit ist der
  Mac von überall erreichbar — das ist Variante 3 aus dem ursprünglichen
  Brainstorming. TLS-Caveat: `tailscale serve`-Zertifikate brauchen
  ACME/DNS-Unterstützung im Headscale-Setup; Fallback ist ein selbstsigniertes
  Zertifikat, dem das iPhone einmalig vertraut (getUserMedia braucht Secure
  Context).
- Ohne Tailscale: selbstsigniertes Zertifikat, einmalig auf dem iPhone
  vertrauen. Token-Query-Param gegen fremde Verbindungen.

## Gewinn nebenbei

Safari wendet auf `getUserMedia` **Echo-Cancellation** an (Annas Stimme wird
aus dem Mikrosignal herausgerechnet) → **Voice-Barge-in wird möglich**, das
bisherige v1-Limit (Mikro stumm während TTS) entfällt auf dem Phone-Pfad.

## Offene Punkte

- iOS-Autolock: Phone muss im Cradle geladen + Bildschirm an bleiben
  (PWA kann Wake Lock anfordern; verifizieren).
- Latenz TTS-Datei-Rendering (~0,5–1 s) vs. lokales `say` — akzeptabel,
  ggf. Chunk-Streaming während `say` noch rendert.
- Reconnect-Logik bei Funkloch (WS-Backoff, Audio-Puffer verwerfen).
