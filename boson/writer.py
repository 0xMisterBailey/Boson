"""The writer: one isolated headless `claude -p` run over a throwaway copy of the studio (T12's isolation).

The writer never sees the studio repo itself. It works in a temp copy of the snapshot; the caller copies
back only the files that call is allowed to write, so "edit nothing else" holds by construction, and no
`.claude/` or log ever lands in the studio. Top rung = Opus (SPEC v3 §3); every result names its writer.
"""
import json, os, pathlib, re, shutil, subprocess, tempfile

HOME = pathlib.Path(os.environ.get("BOSON_HOME") or pathlib.Path.home() / ".cache" / "boson")   # $BOSON_HOME moves every cache (the tests point it at a tmp dir)

HERE = pathlib.Path(__file__).parent
MODEL = os.environ.get("BOSON_WRITER", "claude-opus-5-5")
# A local writer: the same isolated `claude -p` pointed at an open model behind the box's model gateway
# (e.g. http://127.0.0.1:8088/slot/primary, as ~/dotfiles/launchpad/claude-local does; never a raw llama-server
# port). Set BOSON_WRITER to the model name the slot serves. Nothing then leaves the box.
BASE_URL = os.environ.get("BOSON_WRITER_BASE_URL", "").strip()
CACHE = HOME


def label():
    return f"writer {MODEL} (claude -p{', local gateway' if BASE_URL else ''}, isolated)"


def task(name, **kw):
    t = (HERE / "tasks" / f"{name}.md").read_text()
    for k, v in kw.items():
        t = t.replace("{" + k + "}", str(v))
    return t


def run(snapshot_dir, prompt, log_name):
    """Run the writer in a fresh copy of snapshot_dir. -> (work dir, result dict). Caller deletes work."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="boson-writer-"))
    shutil.copytree(snapshot_dir, work, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", ".claude", ".boson-snapshot", "renders", "cache"))
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)  # own repo: own (empty) memory slug
    cmd = ["claude", "-p", "--model", MODEL, "--setting-sources", "project", "--strict-mcp-config",
           "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
           "--append-system-prompt", (HERE / "tasks" / "studio-author.md").read_text(),
           "--permission-mode", "acceptEdits", "--allowedTools", "Read Write Edit Glob Grep",
           "--disallowedTools", "Bash", "--output-format", "stream-json", "--verbose", prompt]
    # Clean config dir (credentials only) + no inherited CLAUDE* env: otherwise the operator's own
    # CLAUDE.md, mods, hooks and memory reach the writer (T12 forge run 1). ComfyUI may carry them too.
    cfg = CACHE / ("cc-config-local" if BASE_URL else "cc-config")
    cfg.mkdir(parents=True, exist_ok=True)
    creds = pathlib.Path.home() / ".claude" / ".credentials.json"
    if BASE_URL:              # a local writer carries no Claude login: with one, claude -p still called Anthropic
        (cfg / ".credentials.json").unlink(missing_ok=True)   # (first local round, 2026-10-27, strace)
    elif not creds.exists():
        raise RuntimeError("the writer is Claude (claude -p) and this machine has no Claude login: run `claude` once "
                           "to sign in (stored rounds need no writer)")
    else:
        shutil.copy(creds, cfg / ".credentials.json")
        os.chmod(cfg / ".credentials.json", 0o600)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE") and k != "AI_AGENT"}
    env["CLAUDE_CONFIG_DIR"] = str(cfg)
    if BASE_URL:              # nothing leaves the box: no login, no telemetry, error reports or update checks
        env.pop("ANTHROPIC_API_KEY", None)
        env.update(ANTHROPIC_BASE_URL=BASE_URL, ANTHROPIC_AUTH_TOKEN="local", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
                   DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1", DISABLE_AUTOUPDATER="1")
    # ~/.claude/CLAUDE.md is also read as an ancestor dir's project file (T12 forge run 2): exclude it.
    (work / ".claude").mkdir(exist_ok=True)
    home = pathlib.Path.home()
    (work / ".claude" / "settings.json").write_text(json.dumps(
        {"claudeMdExcludes": [str(home / ".claude" / "CLAUDE.md"), str(home / ".claude" / "**")]}))
    log = CACHE / "logs" / f"{log_name}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as f:
        rc = subprocess.run(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=f,
                            stderr=subprocess.STDOUT).returncode
    text = log.read_text()
    evs = [json.loads(x) for x in text.splitlines() if x.startswith("{")]
    init = next((e for e in evs if e.get("subtype") == "init"), {})
    stray = [p["name"] for p in init.get("plugins", []) if p.get("path") != "builtin"]
    if stray:
        raise RuntimeError(f"writer not isolated, plugins loaded: {stray} (log {log})")
    if re.search(r"```dbox|DONE_WITH_CONCERNS|operator CLAUDE\.md", text):
        raise RuntimeError(f"writer saw the operator's CLAUDE.md (signature in {log}); run discarded")
    last = next((e for e in reversed(evs) if e.get("type") == "result"), {})
    if rc or last.get("is_error"):
        raise RuntimeError(f"writer failed rc={rc}: {(last.get('result') or text[-400:])} (log {log})")
    return work, {"writer": label(), "cost_usd": 0 if BASE_URL else round(last.get("total_cost_usd", 0), 2),
                  "minutes": round(last.get("duration_ms", 0) / 60000, 1), "summary": last.get("result", ""),
                  "log": f"~/.cache/boson/logs/{log.name}"}  # no home path: this meta is committed to the studio
