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


def test_quoted_mentions_do_not_ask():
    for cmd in ['git commit -m "fix rm bug"',
                "pytest -k kill_handler",
                'grep -rn "deploy" docs/',
                "git log --grep 'push'"]:
        assert not _bash(cmd).ask, cmd


def test_risky_has_spoken_summary():
    verdict = _bash("git push origin main")
    assert verdict.ask and "git push" in verdict.spoken_summary


def test_safe_builtin_tools():
    for tool in ["Read", "Edit", "Write", "Grep", "WebSearch", "TodoWrite"]:
        assert not classify(tool, {}).ask, tool


def test_mcp_read_allowed_write_asks():
    assert not classify("mcp__platform__search_projects", {}).ask
    assert classify("mcp__platform__send_message", {}).ask
    assert classify("mcp__odoo__create_invoice", {}).ask


def test_unknown_tool_asks():
    assert classify("SomeNewTool", {}).ask
