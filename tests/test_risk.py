from claude_to_go.risk import classify


def _bash(cmd: str):
    return classify("Bash", {"command": cmd})


def test_safe_bash_commands():
    for cmd in ["ls -la", "git status", "git diff", "pytest -x", "uv run pytest",
                "grep -r foo src/", "git log --oneline", "cat README.md",
                "git commit -m 'fix'", "tail -f log.txt"]:
        assert not _bash(cmd).ask, cmd


def test_risky_bash_commands():
    for cmd in ["git push origin main", "rm -rf build", "sudo reboot",
                "git reset --hard HEAD~3", "npm publish", "docker system prune",
                "gh pr create --fill", "kill -9 1234",
                "alp task log-time ws card-1 --hours 2"]:
        assert _bash(cmd).ask, cmd


def test_risky_evasions_caught():
    for cmd in ['find . -name "*.log" | xargs rm',
                "git -C /tmp/repo push",
                "git --work-tree=/x push origin main",
                "ls && git push",
                "git restore .",
                "git stash drop",
                "find build -delete",
                "curl --request DELETE https://api.example.com/v1/thing"]:
        assert _bash(cmd).ask, cmd


def test_wrapper_and_env_prefix_evasions_caught():
    for cmd in ["GIT_SSH_COMMAND=ssh git push origin main",
                "env git push",
                "time git push origin main",
                "nohup rm -rf build",
                "FOO='a b' BAR=x git push",
                "bash -c 'git push origin main'",
                "sh -c \"rm -rf /tmp/x\""]:
        assert _bash(cmd).ask, cmd


def test_quoted_mentions_do_not_ask():
    for cmd in ['git commit -m "fix rm bug"',
                "pytest -k kill_handler",
                'grep -rn "deploy" docs/',
                "git log --grep 'push'"]:
        assert not _bash(cmd).ask, cmd


def test_git_push_summary_is_german_category_with_raw():
    # Spoken summaries are category-based German, not raw shell — the raw
    # command lives on the verdict for the "details" voice request.
    verdict = _bash("git push origin main")
    assert verdict.ask
    assert "pushen" in verdict.spoken_summary
    assert "origin main" in verdict.spoken_summary  # push target read aloud
    assert verdict.raw == "git push origin main"


def test_rm_summary_is_german_category_with_raw():
    verdict = _bash("rm -rf build/")
    assert verdict.ask
    assert "löschen" in verdict.spoken_summary
    assert "build/" in verdict.spoken_summary
    assert verdict.raw == "rm -rf build/"


def test_all_risky_summaries_are_nonempty_and_carry_raw():
    for cmd in ["sudo reboot", "git reset --hard", "npm publish",
                "docker system prune", "kill -9 42", "find build -delete"]:
        verdict = _bash(cmd)
        assert verdict.ask, cmd
        assert verdict.spoken_summary, cmd
        assert verdict.raw, cmd


def test_raw_is_shortened_for_very_long_commands():
    long_cmd = "git push origin " + "x" * 300
    verdict = _bash(long_cmd)
    assert verdict.ask
    assert len(verdict.raw) <= 160
    assert verdict.raw.endswith("…")


def test_safe_command_has_empty_summary_and_raw():
    verdict = _bash("git status")
    assert not verdict.ask
    assert verdict.spoken_summary == ""
    assert verdict.raw == ""


def test_safe_builtin_tools():
    for tool in ["Read", "Edit", "Write", "Grep", "WebSearch", "TodoWrite"]:
        assert not classify(tool, {}).ask, tool


def test_mcp_read_allowed_write_asks():
    assert not classify("mcp__platform__search_projects", {}).ask
    assert classify("mcp__platform__send_message", {}).ask
    assert classify("mcp__odoo__create_invoice", {}).ask


def test_unknown_tool_asks():
    assert classify("SomeNewTool", {}).ask
