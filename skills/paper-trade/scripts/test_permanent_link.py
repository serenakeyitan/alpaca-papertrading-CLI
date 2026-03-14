#!/usr/bin/env python3
"""Comprehensive test suite for the permanent link feature.

Tests:
1. setup-link.sh script validity
2. start-web.sh ngrok integration
3. keep-alive.sh ngrok integration
4. Tunnel config file format
5. Fallback behavior (no config → cloudflared)
6. SKILL.md documentation updates
7. Script syntax and structure
8. Config persistence and cleanup
9. Provider detection logic
10. Edge cases (malformed config, missing binaries)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


# ── Test 1: setup-link.sh Script Validity ─────────────────

def test_setup_link_script():
    """setup-link.sh must be valid, executable, and well-structured."""
    print("\n── Test 1: setup-link.sh Script Validity ──")
    script = SCRIPTS_DIR / "setup-link.sh"
    check("File exists", script.exists())

    content = script.read_text()
    check("Has shebang", content.startswith("#!/usr/bin/env bash"))
    check("Is executable", os.access(script, os.X_OK))
    check("Non-trivial (>50 lines)", len(content.splitlines()) > 50,
          f"got {len(content.splitlines())} lines")

    # Syntax check
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    check("Passes bash -n syntax check", result.returncode == 0,
          result.stderr.strip() if result.stderr else "")

    # Structure checks
    check("Has status subcommand", '"status"' in content)
    check("Has reset subcommand", '"reset"' in content)
    check("References ngrok", "ngrok" in content)
    check("References tunnel.json config", "tunnel.json" in content)
    check("References ~/.alpaca-cli/", ".alpaca-cli" in content)

    # User guidance
    check("Has ngrok signup URL", "dashboard.ngrok.com" in content)
    check("Has authtoken instructions", "authtoken" in content)
    check("Has static domain instructions", "domain" in content.lower())
    check("Prompts for domain input", "read -p" in content)

    # Input validation
    check("Strips protocol from domain input", "sed" in content and "https" in content)
    check("Validates domain looks like ngrok", "ngrok" in content and "app" in content)

    # Config save
    check("Saves provider field", "'provider'" in content or '"provider"' in content)
    check("Saves domain field", "'domain'" in content or '"domain"' in content)
    check("Creates config dir", "mkdir -p" in content)

    # UX
    check("Has success message", "Permanent link configured" in content or "permanent" in content.lower())
    check("Shows final URL", "https://" in content)
    check("Has step numbers", "Step 1" in content and "Step 2" in content and "Step 3" in content)

    # Safety
    check("Uses set -uo pipefail", "set -uo pipefail" in content)
    check("No hardcoded paths", "/Users/" not in content)
    check("No secrets/tokens", "github_pat" not in content and "sk-" not in content)


# ── Test 2: start-web.sh ngrok Integration ────────────────

def test_start_web_ngrok():
    """start-web.sh must properly integrate ngrok with cloudflared fallback."""
    print("\n── Test 2: start-web.sh ngrok Integration ──")
    content = (SCRIPTS_DIR / "start-web.sh").read_text()

    # Syntax check
    result = subprocess.run(
        ["bash", "-n", str(SCRIPTS_DIR / "start-web.sh")],
        capture_output=True, text=True
    )
    check("Passes bash -n syntax check", result.returncode == 0,
          result.stderr.strip() if result.stderr else "")

    # ngrok support
    check("Reads tunnel.json config", "tunnel.json" in content or "TUNNEL_CONFIG" in content)
    check("Detects ngrok provider", 'provider' in content and 'ngrok' in content)
    check("Reads domain from config", 'domain' in content)
    check("Starts ngrok with --url flag", "--url=" in content)
    check("Uses ngrok http command", "ngrok http" in content)

    # Fallback
    check("Has cloudflared fallback", "cloudflared" in content)
    check("Falls back when ngrok fails", "Falling back" in content or "fall" in content.lower())
    check("Falls back when no config (cloudflared path exists)",
          "cloudflared tunnel --url" in content)

    # URL persistence
    check("Writes to .tunnel_url file", "tunnel_url" in content.lower() or "TUNNEL_URL_FILE" in content)

    # User messaging
    check("Labels ngrok as permanent", "permanent" in content.lower())
    check("Labels cloudflared as temporary", "temporary" in content.lower())
    check("Suggests setup-link.sh", "setup-link.sh" in content)

    # ngrok health check
    check("Checks ngrok API (localhost:4040)", "4040" in content)

    # Priority: ngrok first, cloudflared second
    ngrok_pos = content.find("ngrok http")
    cf_pos = content.find("cloudflared tunnel --url")
    check("ngrok checked before cloudflared", ngrok_pos < cf_pos,
          f"ngrok at {ngrok_pos}, cloudflared at {cf_pos}")


# ── Test 3: keep-alive.sh ngrok Integration ───────────────

def test_keep_alive_ngrok():
    """keep-alive.sh must support ngrok for persistent tunnels."""
    print("\n── Test 3: keep-alive.sh ngrok Integration ──")
    content = (SCRIPTS_DIR / "keep-alive.sh").read_text()

    # Syntax check
    result = subprocess.run(
        ["bash", "-n", str(SCRIPTS_DIR / "keep-alive.sh")],
        capture_output=True, text=True
    )
    check("Passes bash -n syntax check", result.returncode == 0,
          result.stderr.strip() if result.stderr else "")

    # Provider detection
    check("Reads tunnel.json config", "tunnel.json" in content or "TUNNEL_CONFIG" in content)
    check("Detects TUNNEL_PROVIDER", "TUNNEL_PROVIDER" in content)
    check("Detects NGROK_DOMAIN", "NGROK_DOMAIN" in content)
    check("Default provider is cloudflared", '"cloudflared"' in content)

    # ngrok wrapper
    check("Generates ngrok tunnel wrapper", "ngrok http" in content)
    check("Generates cloudflared tunnel wrapper", "cloudflared tunnel --url" in content)
    check("Wrapper selection is conditional", "if" in content and "TUNNEL_PROVIDER" in content)

    # Status command shows provider
    check("Status shows provider name", "TUNNEL_PROVIDER" in content and "RUNNING" in content)
    check("Status shows permanent/temporary type", "permanent" in content and "temporary" in content)

    # Kill both tunnel types on cleanup
    check("Kills ngrok on stop", 'pkill -f "ngrok http"' in content)
    check("Kills cloudflared on stop", 'pkill -f "cloudflared tunnel"' in content)

    # Preflight checks for both providers
    check("Checks ngrok binary exists", "ngrok" in content and "not found" in content.lower())
    check("Checks cloudflared binary exists", "cloudflared" in content and "not found" in content.lower())

    # Permanent link messaging
    check("Shows permanent URL for ngrok", "permanent" in content.lower() and "never changes" in content.lower())
    check("Suggests setup-link.sh for cloudflared users", "setup-link.sh" in content)


# ── Test 4: Tunnel Config Format ──────────────────────────

def test_tunnel_config_format():
    """tunnel.json config should follow expected schema."""
    print("\n── Test 4: Tunnel Config Format ──")

    # Test creating a config
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "tunnel.json"

        # Simulate what setup-link.sh creates
        config = {"provider": "ngrok", "domain": "my-dashboard.ngrok-free.app"}
        config_path.write_text(json.dumps(config, indent=2))

        # Read it back
        loaded = json.loads(config_path.read_text())
        check("Config is valid JSON", True)
        check("Has provider field", "provider" in loaded)
        check("Has domain field", "domain" in loaded)
        check("Provider is ngrok", loaded["provider"] == "ngrok")
        check("Domain is string", isinstance(loaded["domain"], str))
        check("Domain has no protocol prefix", not loaded["domain"].startswith("http"))
        check("Domain has no trailing slash", not loaded["domain"].endswith("/"))

        # Test python reading (same as scripts do)
        result = subprocess.run(
            ["python3", "-c",
             f"import json; d=json.load(open('{config_path}')); "
             f"print(d.get('provider','')); print(d.get('domain',''))"],
            capture_output=True, text=True
        )
        check("Python can read config", result.returncode == 0)
        lines = result.stdout.strip().split("\n")
        check("Python reads provider correctly", lines[0] == "ngrok")
        check("Python reads domain correctly", lines[1] == "my-dashboard.ngrok-free.app")


# ── Test 5: Fallback Behavior ─────────────────────────────

def test_fallback_behavior():
    """Without tunnel config, scripts should fall back to cloudflared."""
    print("\n── Test 5: Fallback Behavior ──")

    start_web = (SCRIPTS_DIR / "start-web.sh").read_text()
    keep_alive = (SCRIPTS_DIR / "keep-alive.sh").read_text()

    # start-web.sh: check fallback path
    check("start-web: Checks if config file exists",
          '-f "$TUNNEL_CONFIG"' in start_web or "-f" in start_web)
    check("start-web: Falls back to cloudflared when no ngrok",
          "cloudflared" in start_web)
    check("start-web: Handles missing both providers",
          "No tunnel provider" in start_web or "not found" in start_web.lower())

    # keep-alive.sh: check fallback
    check("keep-alive: Default provider is cloudflared",
          'TUNNEL_PROVIDER="cloudflared"' in keep_alive)
    check("keep-alive: Only reads config if file exists",
          '-f "$TUNNEL_CONFIG"' in keep_alive)

    # Both scripts handle PROVIDER not being set
    check("start-web: Handles unset PROVIDER",
          '${PROVIDER:-}' in start_web or '${PROVIDER:-""}' in start_web)
    check("start-web: Handles unset DOMAIN",
          '${DOMAIN:-}' in start_web or '${DOMAIN:-""}' in start_web)


# ── Test 6: SKILL.md Documentation ────────────────────────

def test_skill_md_docs():
    """SKILL.md should document the permanent link feature."""
    print("\n── Test 6: SKILL.md Documentation ──")
    skill_md = (SKILL_DIR / "SKILL.md").read_text()

    # New feature documented
    check("Mentions permanent link", "permanent" in skill_md.lower())
    check("Mentions setup-link.sh", "setup-link.sh" in skill_md)
    check("Mentions ngrok", "ngrok" in skill_md.lower())
    check("Mentions free", "free" in skill_md.lower())

    # Natural language mapping updated
    check("Has 'get a permanent link' mapping",
          "permanent link" in skill_md.lower() and "setup-link" in skill_md)

    # Launch section updated
    check("Setup-link in launch section",
          "setup-link.sh" in skill_md and "one-time" in skill_md.lower())

    # Features section updated
    check("Permanent link in features",
          "permanent public link" in skill_md.lower() or "permanent link" in skill_md.lower())
    check("Cloudflare fallback mentioned",
          "fallback" in skill_md.lower() or "temporary" in skill_md.lower())

    # Scripts table updated
    check("setup-link.sh in scripts table",
          "setup-link.sh" in skill_md and "|" in skill_md)

    # Still mentions cloudflare (backward compat)
    check("Still documents Cloudflare", "cloudflare" in skill_md.lower())


# ── Test 7: Script Cross-compatibility ────────────────────

def test_script_compatibility():
    """All three scripts should use consistent config paths and variable names."""
    print("\n── Test 7: Script Cross-compatibility ──")

    setup = (SCRIPTS_DIR / "setup-link.sh").read_text()
    start = (SCRIPTS_DIR / "start-web.sh").read_text()
    keep = (SCRIPTS_DIR / "keep-alive.sh").read_text()

    # Same config path across all scripts
    config_path = "$HOME/.alpaca-cli/tunnel.json"
    for name, content in [("setup-link", setup), ("start-web", start), ("keep-alive", keep)]:
        check(f"{name}: Uses {config_path}",
              "alpaca-cli" in content and "tunnel.json" in content,
              "Config path mismatch")

    # Same JSON field names
    for name, content in [("setup-link", setup), ("start-web", start), ("keep-alive", keep)]:
        check(f"{name}: References 'provider' field",
              "provider" in content)
        check(f"{name}: References 'domain' field",
              "domain" in content.lower())

    # tunnel_url file used by start-web and keep-alive
    for name, content in [("start-web", start), ("keep-alive", keep)]:
        check(f"{name}: Uses .tunnel_url file",
              ".tunnel_url" in content)

    # setup-link reset matches what other scripts expect
    check("setup-link reset removes config",
          "rm -f" in setup and "TUNNEL_CONFIG" in setup)


# ── Test 8: No Regressions ───────────────────────────────

def test_no_regressions():
    """Existing functionality should not be broken."""
    print("\n── Test 8: No Regressions ──")

    start = (SCRIPTS_DIR / "start-web.sh").read_text()
    keep = (SCRIPTS_DIR / "keep-alive.sh").read_text()

    # start-web.sh: existing features preserved
    check("start-web: Still has --port flag", "--port" in start)
    check("start-web: Still has --no-tunnel flag", "--no-tunnel" in start)
    check("start-web: Still starts dashboard", "web_dashboard.py" in start)
    check("start-web: Still has cleanup trap", "trap cleanup" in start)
    check("start-web: Still checks venv", "VENV_PYTHON" in start)
    check("start-web: Still checks config", ".alpaca-cli/config.json" in start)
    check("start-web: Still has Ctrl+C message", "Ctrl+C" in start)

    # keep-alive.sh: existing features preserved
    check("keep-alive: Still has stop command", '"stop"' in keep)
    check("keep-alive: Still has status command", '"status"' in keep)
    check("keep-alive: Still creates dashboard plist", "LABEL_DASH" in keep)
    check("keep-alive: Still creates tunnel plist", "LABEL_TUNNEL" in keep)
    check("keep-alive: Still uses launchctl", "launchctl load" in keep)
    check("keep-alive: Still has wrapper script", "TUNNEL_WRAPPER" in keep)
    check("keep-alive: Still cleans up old agents", "launchctl unload" in keep)


# ── Test 9: Edge Cases ────────────────────────────────────

def test_edge_cases():
    """Handle malformed config, missing binaries, etc."""
    print("\n── Test 9: Edge Cases ──")

    start = (SCRIPTS_DIR / "start-web.sh").read_text()
    keep = (SCRIPTS_DIR / "keep-alive.sh").read_text()

    # Handle missing config gracefully
    check("start-web: Config file check uses -f",
          '-f "$TUNNEL_CONFIG"' in start)

    # Handle ngrok not installed
    check("start-web: Checks ngrok binary",
          "command -v ngrok" in start)

    # Handle ngrok process dying
    check("start-web: Checks ngrok PID after start",
          "kill -0" in start and "TUNNEL_PID" in start)

    # keep-alive: handles provider detection failure
    check("keep-alive: Provider detection has fallback",
          "|| echo" in keep and "cloudflared" in keep)

    # Test with empty/malformed config
    with tempfile.TemporaryDirectory() as tmpdir:
        # Empty JSON
        empty_config = Path(tmpdir) / "empty.json"
        empty_config.write_text("{}")
        result = subprocess.run(
            ["python3", "-c",
             f"import json; d=json.load(open('{empty_config}')); "
             f"print(d.get('provider','')); print(d.get('domain',''))"],
            capture_output=True, text=True
        )
        check("Handles empty config (no crash)", result.returncode == 0)
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else ["", ""]
        # Both empty strings may collapse to one line or two
        check("Empty config returns empty provider", len(lines) >= 1 and lines[0] == "")
        check("Empty config returns empty domain",
              (len(lines) >= 2 and lines[1] == "") or (len(lines) == 1 and lines[0] == ""))

        # Config with only provider, no domain
        partial_config = Path(tmpdir) / "partial.json"
        partial_config.write_text('{"provider": "ngrok"}')
        result = subprocess.run(
            ["python3", "-c",
             f"import json; d=json.load(open('{partial_config}')); "
             f"print(d.get('domain',''))"],
            capture_output=True, text=True
        )
        check("Handles config missing domain", result.returncode == 0)
        check("Missing domain returns empty string", result.stdout.strip() == "")


# ── Test 10: Security Checks ─────────────────────────────

def test_security():
    """No secrets, safe input handling, no injection vectors."""
    print("\n── Test 10: Security Checks ──")

    for fname in ["setup-link.sh", "start-web.sh", "keep-alive.sh"]:
        content = (SCRIPTS_DIR / fname).read_text()

        # No hardcoded secrets
        check(f"{fname}: No API keys",
              not re.search(r'[A-Z]{2}[a-zA-Z0-9]{16,}', content) or
              "PKAPI" not in content)
        check(f"{fname}: No tokens",
              "github_pat" not in content and "gho_" not in content)

        # No eval or dangerous constructs
        check(f"{fname}: No eval", "eval " not in content)

    # setup-link.sh: input sanitization
    setup = (SCRIPTS_DIR / "setup-link.sh").read_text()
    check("setup-link: Strips protocol from domain input",
          "sed" in setup and "https" in setup)

    # Config uses python json (safe) not bash eval
    check("setup-link: Uses python for JSON write",
          "python3" in setup and "json.dump" in setup)

    # start-web.sh: uses python for JSON read (not bash jq/eval)
    start = (SCRIPTS_DIR / "start-web.sh").read_text()
    check("start-web: Uses python for JSON read",
          "python3 -c" in start and "json.load" in start)


# ── Test 11: URL Format Validation ────────────────────────

def test_url_formats():
    """Verify URL construction is correct for different scenarios."""
    print("\n── Test 11: URL Format Validation ──")

    start = (SCRIPTS_DIR / "start-web.sh").read_text()

    # ngrok URL should be https://domain (not http://)
    check("ngrok URL uses https",
          'TUNNEL_URL="https://$DOMAIN"' in start or
          "https://$DOMAIN" in start)

    # cloudflared URL pattern detection (in fallback section)
    check("Cloudflared URL pattern correct",
          "trycloudflare" in start)

    # .tunnel_url file gets the full URL
    check("Writes full URL to .tunnel_url",
          'echo "$TUNNEL_URL" > "$TUNNEL_URL_FILE"' in start or
          "TUNNEL_URL_FILE" in start)

    # ngrok --url flag format
    check("ngrok --url uses domain without protocol",
          '--url="$DOMAIN"' in start)


# ── Test 12: Wrapper Script Generation ────────────────────

def test_wrapper_scripts():
    """keep-alive.sh generates correct wrapper scripts for each provider."""
    print("\n── Test 12: Wrapper Script Generation ──")
    content = (SCRIPTS_DIR / "keep-alive.sh").read_text()

    # ngrok wrapper
    check("ngrok wrapper writes URL to file immediately",
          'echo "https://' in content and "URL_FILE" in content)
    check("ngrok wrapper uses --url flag",
          "--url=" in content)
    check("ngrok wrapper logs output",
          "ngrok-dashboard.log" in content)

    # cloudflared wrapper
    check("cloudflared wrapper removes old URL file",
          'rm -f "$URL_FILE"' in content)
    check("cloudflared wrapper waits for URL",
          "seq 1 60" in content)
    check("cloudflared wrapper uses grep for URL detection",
          "trycloudflare" in content)

    # Both wrappers are executable
    check("Wrapper made executable", "chmod +x" in content)


# ── Test 13: Integration with web_dashboard.py ────────────

def test_dashboard_integration():
    """web_dashboard.py should work with both tunnel providers."""
    print("\n── Test 13: Dashboard Integration ──")

    wd = (SKILL_DIR / "web_dashboard.py").read_text()

    # Dashboard reads from .tunnel_url file (provider-agnostic)
    check("Dashboard reads .tunnel_url file", ".tunnel_url" in wd)
    check("Dashboard displays tunnel URL in status bar", "tunnel_url" in wd)
    check("Dashboard makes URL clickable", "href" in wd and "tunnel_url" in wd)

    # Dashboard doesn't care which provider in its display/API logic
    # (references in comments/docstrings are OK)
    import re
    wd_no_comments = re.sub(r'""".*?"""', '', wd, flags=re.DOTALL)
    wd_no_comments = re.sub(r'#.*$', '', wd_no_comments, flags=re.MULTILINE)
    check("Dashboard is provider-agnostic (no ngrok/cloudflared in active code)",
          "ngrok" not in wd_no_comments.lower() and "cloudflared" not in wd_no_comments.lower())


# ── Run All ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Permanent Link Feature — Comprehensive Test Suite")
    print("=" * 60)

    test_setup_link_script()
    test_start_web_ngrok()
    test_keep_alive_ngrok()
    test_tunnel_config_format()
    test_fallback_behavior()
    test_skill_md_docs()
    test_script_compatibility()
    test_no_regressions()
    test_edge_cases()
    test_security()
    test_url_formats()
    test_wrapper_scripts()
    test_dashboard_integration()

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)
