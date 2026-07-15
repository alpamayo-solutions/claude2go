"""Language packs — the single source of everything the driver hears or says.

German is the default; English is fully supported. Add a language by adding a
`Strings` entry to `LANGUAGES`. Everything language-dependent lives here:
spoken phrases, wake/command vocabulary, the response-style system prompt,
STT language code, and the preferred TTS voice locale.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Strings:
    code: str
    stt_language: str
    voice_locale: str          # "say -v ?" locale tag, e.g. "de_DE"
    fallback_voice: str        # compact voice guaranteed to exist
    notes_file: str            # flash-note filename in the project

    # Wake vocabulary (lowercased, ascii-folded at match time)
    wake_words: tuple[str, ...]
    stop_words: frozenset[str]
    stop_phrases: tuple[str, ...]
    status_words: frozenset[str]
    note_prefixes: tuple[str, ...]
    briefing_words: frozenset[str]
    yes_words: frozenset[str]
    no_words: frozenset[str]
    repeat_words: frozenset[str]
    detail_words: frozenset[str]

    # Spoken phrases. {n}-style slots filled with str.format.
    greeting: str
    typed_greeting: str
    ready_status: str
    working_status: str          # format: minutes/seconds via working_since
    working_since: str           # "{duration}" and "{tool}" slots
    minutes_unit: str
    seconds_unit: str
    last_tool_suffix: str        # "{tool}" slot
    stopped: str
    ok_start: str
    permission_question: str     # "{summary}" slot
    permission_repeat_hint: str
    permission_details: str      # "{detail}" slot
    permission_ok: str
    permission_denied: str
    permission_no_answer: str
    permission_unclear: str
    meant_me: str                # "{text}" slot
    reconnecting: str
    connection_lost: str
    no_answer_text: str
    note_failed: str
    error_generic: str

    # Curated prompts + response-style appendix
    voice_style: str
    recap_prompt: str
    briefing_prompt: str
    retry_reconcile: str         # "{message}" slot — after a dead-zone drop

    # STT bias vocabulary (no imperatives — Whisper echoes prompt fragments)
    stt_prompt: str

    # Risk categories → spoken phrase; "{detail}" slot optional
    risk_phrases: dict[str, str] = field(default_factory=dict)


_DE = Strings(
    code="de",
    stt_language="de",
    voice_locale="de_DE",
    fallback_voice="Anna",
    notes_file="NOTIZEN.md",
    wake_words=("claude", "cloud", "klaut", "klaud", "clod"),
    stop_words=frozenset({"stopp", "stop", "halt", "abbrechen", "abbruch"}),
    stop_phrases=("hör auf", "hoer auf"),
    status_words=frozenset({"status", "zwischenstand", "stand"}),
    note_prefixes=("merk dir", "merke dir", "notiere", "notiz", "schreib dir auf", "merken"),
    briefing_words=frozenset({"briefing", "morgenbriefing", "lagebericht"}),
    yes_words=frozenset({
        "ja", "jawohl", "jo", "jap", "yes", "yep", "okay", "ok",
        "erlaubt", "erlauben", "einverstanden", "freigeben", "genehmigt",
    }),
    no_words=frozenset({
        "nein", "ne", "nee", "nö", "no", "nope", "nicht", "stopp", "stop", "lass",
        "ablehnen", "abgelehnt", "verboten", "niemals", "warte", "abbrechen",
    }),
    repeat_words=frozenset({"wiederhole", "wiederholen", "nochmal", "wie bitte", "was"}),
    detail_words=frozenset({"details", "detail", "welcher", "welchen", "zeig", "vorlesen"}),
    greeting="Claude to go ist bereit.",
    typed_greeting="Claude to go, getippter Modus.",
    ready_status="Ich bin bereit und warte auf dich.",
    working_status="Ich arbeite gerade.",
    working_since="Ich arbeite seit {duration}{tool}.",
    minutes_unit="{n} Minuten",
    seconds_unit="{n} Sekunden",
    last_tool_suffix=", zuletzt {tool}",
    stopped="Okay, gestoppt. Wie machen wir weiter?",
    ok_start="Ok.",
    permission_question="Claude möchte {summary}. Ja oder Nein?",
    permission_repeat_hint="Bitte antworte mit Ja oder Nein.",
    permission_details="Der genaue Befehl ist: {detail}. Ja oder Nein?",
    permission_ok="Okay.",
    permission_denied="Abgelehnt.",
    permission_no_answer="Keine Antwort, ich lehne ab.",
    permission_unclear="Das war unklar — ich lehne sicherheitshalber ab.",
    meant_me="Meintest du mich? Ich habe verstanden: {text}",
    reconnecting="Verbindung war kurz weg — ich schicke deinen Auftrag nochmal.",
    connection_lost="Ich bekomme gerade keine Verbindung zu Claude. Sag es später nochmal.",
    no_answer_text="Fertig, aber ohne Antworttext.",
    note_failed="Die Notiz konnte ich nicht speichern.",
    error_generic="Da ist etwas schiefgegangen.",
    voice_style="""\

## Sprachmodus (Claude-to-go)

Der Nutzer fährt gerade Auto. Er sieht keinen Bildschirm; nur deine letzte \
Nachricht jedes Turns wird ihm per Sprachausgabe vorgelesen. Halte dich strikt \
an diese Regeln:

- Antworte auf Deutsch.
- Maximal 2 kurze Sätze, danach — falls eine Entscheidung ansteht — genau eine \
klare Frage, z.B. "Soll ich X oder Y machen?" oder "Wie machen wir weiter?".
- Kein Markdown, keine Listen, keine Codeblöcke, keine Dateipfade, keine URLs \
und keine langen Bezeichner in der Antwort, außer der Nutzer fragt explizit \
danach. Sag "in der Konfigurationsdatei" statt einen Pfad zu nennen.
- Fasse Probleme in einem Satz zusammen und biete Details nur an ("Willst du \
Details hören?"), statt sie ungefragt vorzulesen.
- Arbeite still. Keine Zwischenberichte, keine Plan-Aufzählungen, kein \
Vorlesen von Arbeitsschritten. Nur Endergebnis oder Entscheidungsfrage.
- Höchstens eine Frage pro Turn, höchstens zwei bis drei Optionen, mündlich \
formuliert.
- Benutze niemals das AskUserQuestion-Tool. Stelle Fragen als normalen Satz am \
Ende deiner Antwort.
- Sprich Zahlen und Namen aussprechbar aus (z.B. "Version zwei Punkt eins", \
nicht "v2.1.205").
- Wenn ein Arbeitsschritt lange dauert, arbeite einfach weiter; der Nutzer \
fragt bei Bedarf per Stimme nach dem Status.
- Wirft der Nutzer während deiner Arbeit eine Zwischenfrage oder einen neuen \
Gedanken ein, beantworte ihn SOFORT in ein bis zwei kurzen Sätzen und arbeite \
dann nahtlos weiter.
""",
    recap_prompt=(
        "Fasse in maximal zwei kurzen Sätzen zusammen, woran wir zuletzt "
        "gearbeitet haben und was noch offen ist. Keine Aufzählung, gesprochener Stil."
    ),
    briefing_prompt=(
        "Gib mir ein kurzes Morgen-Briefing zu diesem Projekt: aktueller Branch "
        "und Git-Status, die letzten ein, zwei Commits, CI-Status falls per gh "
        "verfügbar, und offene Aufgaben falls die alp-Plattform verfügbar ist. "
        "Maximal vier kurze gesprochene Sätze, keine Aufzählung, keine Pfade. "
        "Details nenne ich dir auf Nachfrage."
    ),
    retry_reconcile=(
        "Die Verbindung brach eben mitten im vorherigen Versuch dieses Auftrags "
        "ab. Prüfe zuerst, was davon schon passiert ist (z.B. git status, "
        "Datei-Inhalte), und führe dann nur den fehlenden Rest aus: {message}"
    ),
    stt_prompt=(
        "Claude. Git, Branch, Commit, Push, Deploy, Test, Bug, PREKIT, "
        "Software-Entwicklung auf Deutsch."
    ),
    risk_phrases={
        "git_push": "auf Git pushen{detail}",
        "git_reset": "den Git-Stand hart zurücksetzen",
        "git_clean": "untrackte Dateien wegräumen",
        "git_checkout": "alle lokalen Änderungen verwerfen",
        "git_restore": "lokale Änderungen verwerfen",
        "git_stash_drop": "gestashte Änderungen löschen",
        "git_branch_delete": "einen Branch löschen",
        "git_rebase": "einen Rebase durchführen",
        "rm": "Dateien löschen{detail}",
        "sudo": "einen Befehl mit Root-Rechten ausführen",
        "kill": "einen Prozess beenden",
        "docker": "eine Docker-Aufräumaktion ausführen",
        "publish": "ein Paket veröffentlichen",
        "unpublish": "ein Paket zurückziehen",
        "gh_pr": "einen Pull Request bearbeiten",
        "gh_admin": "eine GitHub-Verwaltungsaktion ausführen",
        "deploy": "ein Deployment starten",
        "dd": "rohe Daten schreiben mit dd",
        "db_drop": "eine Datenbanktabelle löschen",
        "db_truncate": "eine Tabelle leeren",
        "mkfs": "ein Dateisystem formatieren",
        "reboot": "den Rechner neu starten",
        "crontab": "geplante Aufgaben ändern",
        "launchctl": "einen Systemdienst ändern",
        "platform_hours": "Arbeitszeit auf der Plattform buchen",
        "platform_publish": "etwas auf der Plattform veröffentlichen",
        "mail": "eine E-Mail-Aktion ausführen",
        "http_write": "Daten per HTTP senden",
        "mcp_write": "die Plattform-Aktion {detail} ausführen",
        "unknown_tool": "das Werkzeug {detail} benutzen",
    },
)


_EN = Strings(
    code="en",
    stt_language="en",
    voice_locale="en_US",
    fallback_voice="Samantha",
    notes_file="NOTES.md",
    wake_words=("claude", "cloud", "clod", "clawed"),
    stop_words=frozenset({"stop", "halt", "cancel", "abort"}),
    stop_phrases=("hold on", "knock it off"),
    status_words=frozenset({"status", "progress"}),
    note_prefixes=("note", "remember", "note down", "jot down", "make a note"),
    briefing_words=frozenset({"briefing", "brief", "standup"}),
    yes_words=frozenset({
        "yes", "yeah", "yep", "yup", "okay", "ok", "sure", "go", "approved",
        "allow", "confirm", "affirmative",
    }),
    no_words=frozenset({
        "no", "nope", "nah", "dont", "stop", "cancel", "deny", "never",
        "wait", "abort", "reject",
    }),
    repeat_words=frozenset({"repeat", "again", "pardon", "what", "say again"}),
    detail_words=frozenset({"details", "detail", "which", "show", "read"}),
    greeting="Claude to go is ready.",
    typed_greeting="Claude to go, typed mode.",
    ready_status="I'm ready and waiting for you.",
    working_status="I'm working right now.",
    working_since="I've been working for {duration}{tool}.",
    minutes_unit="{n} minutes",
    seconds_unit="{n} seconds",
    last_tool_suffix=", last used {tool}",
    stopped="Okay, stopped. What next?",
    ok_start="Okay.",
    permission_question="Claude wants to {summary}. Yes or no?",
    permission_repeat_hint="Please answer yes or no.",
    permission_details="The exact command is: {detail}. Yes or no?",
    permission_ok="Okay.",
    permission_denied="Denied.",
    permission_no_answer="No answer, I'll decline.",
    permission_unclear="That was unclear — I'll decline to be safe.",
    meant_me="Did you mean me? I heard: {text}",
    reconnecting="Connection dropped briefly — resending your request.",
    connection_lost="I can't reach Claude right now. Try again later.",
    no_answer_text="Done, but no reply text.",
    note_failed="I couldn't save the note.",
    error_generic="Something went wrong.",
    voice_style="""\

## Voice mode (Claude-to-go)

The user is driving. They can't see a screen; only your last message each turn \
is read aloud to them. Follow these rules strictly:

- Answer in English.
- At most 2 short sentences, then — if a decision is needed — exactly one clear \
question, e.g. "Should I do X or Y?" or "What next?".
- No markdown, no lists, no code blocks, no file paths, no URLs and no long \
identifiers in your reply, unless the user explicitly asks. Say "in the config \
file" instead of naming a path.
- Summarize problems in one sentence and offer detail ("Want the details?") \
instead of reading it out unprompted.
- Work silently. No progress reports, no plan lists, no reading out steps. \
Only the final result or a decision question.
- At most one question per turn, at most two or three options, phrased for \
speech.
- Never use the AskUserQuestion tool. Ask questions as a normal sentence at the \
end of your reply.
- Speak numbers and names pronounceably (e.g. "version two point one", not \
"v2.1.205").
- If a step takes a while, just keep working; the user will ask for status by \
voice if they want it.
- If the user throws in a question or new thought while you work, answer it \
IMMEDIATELY in one or two short sentences, then continue seamlessly.
""",
    recap_prompt=(
        "Summarize in at most two short sentences what we last worked on and "
        "what's still open. No lists, spoken style."
    ),
    briefing_prompt=(
        "Give me a short morning briefing on this project: current branch and "
        "git status, the last one or two commits, CI status if available via gh, "
        "and open tasks if the alp platform is available. At most four short "
        "spoken sentences, no lists, no paths. I'll ask for details if I want them."
    ),
    retry_reconcile=(
        "The connection dropped mid-way through the previous attempt at this "
        "request. First check what already happened (e.g. git status, file "
        "contents), then carry out only the missing remainder: {message}"
    ),
    stt_prompt=(
        "Claude. Git, branch, commit, push, deploy, test, bug, PREKIT, "
        "software development."
    ),
    risk_phrases={
        "git_push": "push to Git{detail}",
        "git_reset": "hard-reset the Git state",
        "git_clean": "remove untracked files",
        "git_checkout": "discard all local changes",
        "git_restore": "discard local changes",
        "git_stash_drop": "delete stashed changes",
        "git_branch_delete": "delete a branch",
        "git_rebase": "run a rebase",
        "rm": "delete files{detail}",
        "sudo": "run a command as root",
        "kill": "kill a process",
        "docker": "run a Docker cleanup action",
        "publish": "publish a package",
        "unpublish": "unpublish a package",
        "gh_pr": "act on a pull request",
        "gh_admin": "run a GitHub admin action",
        "deploy": "start a deployment",
        "dd": "write raw data with dd",
        "db_drop": "drop a database table",
        "db_truncate": "truncate a table",
        "mkfs": "format a filesystem",
        "reboot": "reboot the machine",
        "crontab": "change scheduled jobs",
        "launchctl": "change a system service",
        "platform_hours": "log work time on the platform",
        "platform_publish": "publish something on the platform",
        "mail": "run an email action",
        "http_write": "send data over HTTP",
        "mcp_write": "run the platform action {detail}",
        "unknown_tool": "use the {detail} tool",
    },
)


LANGUAGES: dict[str, Strings] = {"de": _DE, "en": _EN}
DEFAULT_LANGUAGE = "de"


def get_strings(code: str) -> Strings:
    return LANGUAGES.get(code, LANGUAGES[DEFAULT_LANGUAGE])
