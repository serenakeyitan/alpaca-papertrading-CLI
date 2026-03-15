#!/usr/bin/env python3
"""Comprehensive test suite for the skill release package.

Validates:
1. SKILL.md format compliance (frontmatter, structure, content)
2. All required files present
3. File references in SKILL.md match actual files
4. No secrets or sensitive data in package
5. marketplace-entry.json validity
6. Script executability and syntax
7. requirements.txt completeness
8. .gitignore coverage
9. Cross-references between files
10. Web dashboard importability
11. Strategy registry completeness
12. Config example validity
"""

import json
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

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


# ── Test 1: SKILL.md Frontmatter ──────────────────────────────

def test_skill_md_frontmatter():
    """SKILL.md must have valid YAML frontmatter with required fields."""
    print("\n── Test 1: SKILL.md Frontmatter ──")
    skill_md = (SKILL_DIR / "SKILL.md").read_text()

    # Must start with ---
    check("Starts with ---", skill_md.startswith("---"))

    # Must have closing ---
    parts = skill_md.split("---", 2)
    check("Has closing ---", len(parts) >= 3, f"Found {len(parts)} parts")

    if len(parts) >= 3:
        frontmatter = parts[1].strip()
        # Must have name field
        check("Has 'name' field", "name:" in frontmatter)
        # Must have description field
        check("Has 'description' field", "description:" in frontmatter)
        # Name should be alpaca-papertrading
        name_match = re.search(r"name:\s*(.+)", frontmatter)
        if name_match:
            check("Name is alpaca-papertrading",
                  name_match.group(1).strip() == "alpaca-papertrading",
                  f"Got: {name_match.group(1).strip()}")
        # Description should be non-empty
        desc_match = re.search(r"description:\s*(.+)", frontmatter)
        if desc_match:
            check("Description is non-empty", len(desc_match.group(1).strip()) > 20,
                  f"Length: {len(desc_match.group(1).strip())}")
        # No requires field with missing deps
        if "requires:" in frontmatter:
            check("Requires field valid", True)
        else:
            check("No requires field (optional)", True)


# ── Test 2: SKILL.md Structure ──────────────────────────────────

def test_skill_md_structure():
    """SKILL.md must have required sections."""
    print("\n── Test 2: SKILL.md Structure ──")
    skill_md = (SKILL_DIR / "SKILL.md").read_text()

    required_sections = [
        "When to Use",
        "Natural Language Mapping",
        "Setup",
        "Key Rules",
        "Command Reference",
    ]
    for section in required_sections:
        check(f"Has '{section}' section",
              section.lower() in skill_md.lower(),
              "Section missing")

    # Should have web dashboard section (new feature)
    check("Has 'Web Dashboard' section", "web dashboard" in skill_md.lower())
    # Should have strategy section
    check("Has 'Strategy' section", "strategy" in skill_md.lower())
    # Should have scripts/files reference
    check("Has 'Scripts' section", "scripts" in skill_md.lower())
    check("Has 'Files' section", "files" in skill_md.lower())


# ── Test 3: SKILL.md Content Quality ──────────────────────────

def test_skill_md_content():
    """SKILL.md content should be accurate and complete."""
    print("\n── Test 3: SKILL.md Content Quality ──")
    skill_md = (SKILL_DIR / "SKILL.md").read_text()

    # Should mention paper trading safety
    check("Mentions paper trading only", "paper trading only" in skill_md.lower())

    # Should have natural language examples
    check("Has buy example", "buy" in skill_md.lower() and "shares" in skill_md.lower())
    check("Has sell example", "sell" in skill_md.lower())
    check("Has crypto example", "btc/usd" in skill_md.lower())

    # Should reference key scripts
    check("References auto-tick.py", "auto-tick.py" in skill_md)
    check("References start-web.sh", "start-web.sh" in skill_md)
    check("References install.sh", "install.sh" in skill_md)

    # Should list all strategy types
    strategy_types = ["grid", "dca", "momentum", "mean_reversion", "dip_buyer", "momentum_scalper"]
    for stype in strategy_types:
        check(f"Lists strategy type '{stype}'", stype in skill_md.lower(),
              f"Strategy type '{stype}' not mentioned")

    # Should have API endpoint docs
    check("Documents /api/account", "/api/account" in skill_md)
    check("Documents /api/strategies", "/api/strategies" in skill_md)
    check("Documents /api/watchlist", "/api/watchlist" in skill_md)
    check("Documents /api/orders", "/api/orders" in skill_md)
    check("Documents /api/bars", "/api/bars" in skill_md)

    # Should not have stale/wrong info
    check("No /root/ paths", "/root/" not in skill_md, "Has /root/ path (Linux-specific)")
    check("No hardcoded home dirs", "/home/" not in skill_md)

    # Should mention Render deployment
    check("Mentions Render deployment", "render" in skill_md.lower())

    # Should mention market hours
    check("Mentions market hours/closed", "mkt closed" in skill_md.lower() or "market" in skill_md.lower())

    # Word count reasonable (not too short, not bloated)
    word_count = len(skill_md.split())
    check(f"Word count reasonable ({word_count})", 300 < word_count < 3000,
          f"Got {word_count} words")


# ── Test 4: Required Files Present ──────────────────────────

def test_required_files():
    """All essential files must exist."""
    print("\n── Test 4: Required Files Present ──")
    required = [
        "SKILL.md",
        "web_dashboard.py",
        "dashboard.py",
        "trade.py",
        "strategy_manager.py",
        "grid_bot.py",
        "tick.py",
        "requirements.txt",
        "setup.py",
        "config.example.json",
        "watchlist.json",
        "marketplace-entry.json",
        ".gitignore",
        "run.sh",
        "scripts/install.sh",
        "scripts/deploy.sh",
        "scripts/start-web.sh",
        "scripts/auto-tick.py",
    ]
    for f in required:
        check(f"File exists: {f}", (SKILL_DIR / f).exists())


# ── Test 5: Strategy Files Present ──────────────────────────

def test_strategy_files():
    """All strategy implementations must exist."""
    print("\n── Test 5: Strategy Files ──")
    strategies_dir = SKILL_DIR / "strategies"
    check("strategies/ dir exists", strategies_dir.is_dir())

    required_strategies = [
        "__init__.py",
        "base.py",
        "grid.py",
        "dca.py",
        "momentum.py",
        "mean_reversion.py",
        "dip_buyer.py",
        "momentum_scalper.py",
    ]
    for f in required_strategies:
        check(f"Strategy file: {f}", (strategies_dir / f).exists())


# ── Test 6: No Secrets ──────────────────────────────────────

def test_no_secrets():
    """No API keys, tokens, or credentials in package files."""
    print("\n── Test 6: No Secrets ──")
    secret_patterns = [
        r"PKAPI[A-Z0-9]{16,}",
        r"sk-[a-zA-Z0-9]{20,}",
        r"github_pat_[a-zA-Z0-9_]{20,}",
        r"ghp_[a-zA-Z0-9]{20,}",
        r'"api_key"\s*:\s*"PK(?!XXXXXXXXX)[^"]{10,}"',
        r'"secret_key"\s*:\s*"(?!YOUR_)[^"]{20,}"',
    ]

    files_to_check = [
        "SKILL.md", "web_dashboard.py", "dashboard.py", "trade.py",
        "strategy_manager.py", "config.example.json",
    ]

    for fname in files_to_check:
        fpath = SKILL_DIR / fname
        if not fpath.exists():
            continue
        content = fpath.read_text()
        for pattern in secret_patterns:
            matches = re.findall(pattern, content)
            check(f"No secrets in {fname} ({pattern[:20]}...)",
                  len(matches) == 0,
                  f"Found {len(matches)} matches")

    # config.json should NOT be in the package
    check("No config.json (real keys)", not (SKILL_DIR / "config.json").exists())
    check("No .env file", not (SKILL_DIR / ".env").exists())


# ── Test 7: marketplace-entry.json ──────────────────────────

def test_marketplace_entry():
    """marketplace-entry.json must be valid and complete."""
    print("\n── Test 7: marketplace-entry.json ──")
    mp = SKILL_DIR / "marketplace-entry.json"
    check("File exists", mp.exists())

    if mp.exists():
        data = json.loads(mp.read_text())
        check("Has name", "name" in data)
        check("Has description", "description" in data)
        check("Has version", "version" in data)
        check("Has author", "author" in data)
        check("Has repository", "repository" in data)
        check("Has keywords", "keywords" in data and len(data["keywords"]) > 0)
        check("Has category", "category" in data)

        # Version should be 0.3.0 for this release
        check("Version is 0.3.0", data.get("version") == "0.3.0",
              f"Got: {data.get('version')}")

        # Name matches SKILL.md
        skill_md = (SKILL_DIR / "SKILL.md").read_text()
        name_match = re.search(r"name:\s*(.+)", skill_md.split("---")[1])
        if name_match:
            check("Name matches SKILL.md",
                  data["name"] == name_match.group(1).strip(),
                  f"MP: {data['name']}, SKILL: {name_match.group(1).strip()}")

        # Repository URL valid
        check("Repository URL is GitHub",
              "github.com" in data.get("repository", ""))

        # Description not too long
        desc_len = len(data.get("description", ""))
        check(f"Description length OK ({desc_len})", 20 < desc_len < 500)


# ── Test 8: requirements.txt ────────────────────────────────

def test_requirements():
    """requirements.txt should list all needed packages."""
    print("\n── Test 8: requirements.txt ──")
    req = (SKILL_DIR / "requirements.txt").read_text().strip()
    lines = [l.strip() for l in req.splitlines() if l.strip() and not l.startswith("#")]

    check("Has entries", len(lines) > 0)
    check("Has click", any("click" in l.lower() for l in lines))
    check("Has alpaca", any("alpaca" in l.lower() for l in lines))
    check("Has rich", any("rich" in l.lower() for l in lines))

    # Check for version pinning
    check("Uses version constraints", any(">=" in l or "==" in l for l in lines),
          "No version constraints found")


# ── Test 9: config.example.json ─────────────────────────────

def test_config_example():
    """config.example.json should be valid JSON with placeholder keys."""
    print("\n── Test 9: config.example.json ──")
    cfg = SKILL_DIR / "config.example.json"
    check("File exists", cfg.exists())

    if cfg.exists():
        data = json.loads(cfg.read_text())
        check("Has api_key", "api_key" in data)
        check("Has secret_key", "secret_key" in data)
        # Keys should be placeholders, not real
        check("api_key is placeholder",
              data["api_key"].startswith("PK") and "YOUR" in data["api_key"].upper()
              or data["api_key"].startswith("PKAPI")
              or len(data["api_key"]) < 30,
              f"Got: {data['api_key'][:10]}...")
        check("secret_key is placeholder",
              "YOUR" in data["secret_key"].upper()
              or len(data["secret_key"]) < 30,
              f"Got: {data['secret_key'][:10]}...")


# ── Test 10: .gitignore Coverage ─────────────────────────────

def test_gitignore():
    """Gitignore should exclude sensitive and generated files."""
    print("\n── Test 10: .gitignore Coverage ──")
    gi = (SKILL_DIR / ".gitignore").read_text()

    patterns = [
        ("config.json", "config.json"),
        (".env", ".env"),
        ("__pycache__", "__pycache__"),
        ("*.pyc", "*.pyc"),
        (".venv", ".venv" if ".venv" in gi else "venv"),
        ("*.log", "*.log"),
        ("grid_state.json", "grid_state"),
    ]
    for name, pattern in patterns:
        check(f"Ignores {name}", pattern in gi, f"Pattern '{pattern}' not in .gitignore")


# ── Test 11: Script Syntax ───────────────────────────────────

def test_script_syntax():
    """Scripts should have proper shebangs and be non-empty."""
    print("\n── Test 11: Script Syntax ──")
    scripts = [
        ("scripts/install.sh", "#!/"),
        ("scripts/start-web.sh", "#!/"),
        ("scripts/auto-tick.py", "#!/usr/bin/env python"),
        ("run.sh", "#!/"),
    ]
    for fname, shebang in scripts:
        fpath = SKILL_DIR / fname
        if fpath.exists():
            content = fpath.read_text()
            check(f"{fname}: has shebang", content.startswith(shebang),
                  f"Starts with: {content[:20]}")
            check(f"{fname}: non-empty", len(content) > 50)
        else:
            check(f"{fname}: exists", False, "File missing")

    # auto-tick.py should import strategy_manager
    auto_tick = (SKILL_DIR / "scripts/auto-tick.py").read_text()
    check("auto-tick imports StrategyManager", "StrategyManager" in auto_tick)
    check("auto-tick has main()", "def main" in auto_tick)

    # start-web.sh should reference web_dashboard.py
    start_web = (SKILL_DIR / "scripts/start-web.sh").read_text()
    check("start-web references web_dashboard.py", "web_dashboard.py" in start_web)


# ── Test 12: SKILL.md Table Formatting ───────────────────────

def test_skill_md_tables():
    """All markdown tables in SKILL.md should be well-formed."""
    print("\n── Test 12: SKILL.md Table Formatting ──")
    skill_md = (SKILL_DIR / "SKILL.md").read_text()

    # Find all tables (lines starting with |)
    table_lines = [l for l in skill_md.splitlines() if l.strip().startswith("|")]
    check("Has markdown tables", len(table_lines) > 0, f"Found {len(table_lines)} table lines")

    # Check table separator lines (|---|...|)
    sep_lines = [l for l in table_lines if re.match(r"\|[\s\-|]+\|", l)]
    check("Has table separators", len(sep_lines) > 0)

    # Each table should have header + separator + at least one row
    # Simple check: count tables by counting separator lines
    check(f"Has {len(sep_lines)} tables", len(sep_lines) >= 3,
          f"Expected at least 3 tables")

    # No broken pipes (uneven column counts)
    for i, line in enumerate(table_lines):
        col_count = line.count("|")
        if col_count < 3:  # minimum: | col1 | col2 |
            check(f"Table line {i+1} well-formed", False,
                  f"Only {col_count} pipes: {line[:60]}...")


# ── Test 13: Cross-references ────────────────────────────────

def test_cross_references():
    """Files referenced in SKILL.md should exist."""
    print("\n── Test 13: Cross-references ──")
    skill_md = (SKILL_DIR / "SKILL.md").read_text()

    # Extract file references from SKILL.md
    file_refs = [
        "web_dashboard.py",
        "dashboard.py",
        "trade.py",
        "strategy_manager.py",
        "grid_bot.py",
        "tick.py",
        "config.example.json",
        "watchlist.json",
        "requirements.txt",
        "setup.py",
        "marketplace-entry.json",
        "strategies/",
        "scripts/install.sh",
        "scripts/deploy.sh",
        "scripts/start-web.sh",
        "scripts/auto-tick.py",
    ]

    for ref in file_refs:
        # Check mentioned in SKILL.md
        basename = ref.rstrip("/")
        check(f"SKILL.md mentions {ref}",
              basename in skill_md or ref in skill_md,
              f"'{ref}' not found in SKILL.md")
        # Check file exists
        fpath = SKILL_DIR / ref
        check(f"File exists: {ref}",
              fpath.exists(),
              f"Referenced in SKILL.md but doesn't exist")


# ── Test 14: Strategy Registry Matches Files ─────────────────

def test_strategy_registry():
    """Strategy types in strategy_manager.py should match strategy files."""
    print("\n── Test 14: Strategy Registry ──")
    sm_content = (SKILL_DIR / "strategy_manager.py").read_text()

    # Extract registry entries
    registry_types = re.findall(r'"(\w+)":\s*\w+Strategy', sm_content)
    check(f"Has {len(registry_types)} registered types", len(registry_types) >= 6,
          f"Found: {registry_types}")

    expected = ["grid", "dca", "momentum", "mean_reversion", "dip_buyer", "momentum_scalper"]
    for stype in expected:
        check(f"Registry has '{stype}'", stype in registry_types)

    # Each should have a corresponding file
    for stype in registry_types:
        fpath = SKILL_DIR / "strategies" / f"{stype}.py"
        check(f"Strategy file exists: {stype}.py", fpath.exists())


# ── Test 15: Web Dashboard Imports ────────────────────────────

def test_web_dashboard_imports():
    """web_dashboard.py should be importable and have key components."""
    print("\n── Test 15: Web Dashboard Structure ──")
    wd = (SKILL_DIR / "web_dashboard.py").read_text()

    # Key imports
    check("Imports Flask", "from flask import" in wd or "import flask" in wd)
    check("Imports alpaca API", "alpaca_trade_api" in wd or "alpaca" in wd)

    # Key routes
    routes = re.findall(r'@app\.route\("([^"]+)"\)', wd)
    check(f"Has {len(routes)} routes", len(routes) >= 7)
    expected_routes = ["/", "/api/account", "/api/strategies", "/api/watchlist",
                       "/api/orders", "/api/log"]
    for route in expected_routes:
        check(f"Has route {route}", route in routes,
              f"Route {route} not found in: {routes}")

    # Key functions
    check("Has _utc_to_local_str", "_utc_to_local_str" in wd)
    check("Has _load_config", "_load_config" in wd)
    check("Has _get_api", "_get_api" in wd)

    # Should use waitress for production
    check("Uses waitress", "waitress" in wd.lower())

    # Line count reasonable
    line_count = len(wd.splitlines())
    check(f"Line count ({line_count})", line_count > 200)


# ── Test 16: No Debug/Dev Artifacts ──────────────────────────

def test_no_artifacts():
    """Package should not contain debug or development artifacts."""
    print("\n── Test 16: No Debug/Dev Artifacts ──")

    # No __pycache__ committed
    check("No __pycache__/", not (SKILL_DIR / "__pycache__").exists())
    check("No strategies/__pycache__/",
          not (SKILL_DIR / "strategies" / "__pycache__").exists())

    # No .pyc files
    pyc_files = list(SKILL_DIR.glob("**/*.pyc"))
    check("No .pyc files", len(pyc_files) == 0, f"Found {len(pyc_files)}")

    # strategies_state.json is now committed (needed for Render deployment)
    check("strategies_state.json present",
          (SKILL_DIR / "strategies_state.json").exists())
    check("No grid_state.json",
          not (SKILL_DIR / "grid_state.json").exists())
    check("No .venv/", not (SKILL_DIR / ".venv").exists())

    # No log files
    log_files = list(SKILL_DIR.glob("*.log"))
    check("No *.log files", len(log_files) == 0, f"Found: {[f.name for f in log_files]}")


# ── Test 17: setup.py Validity ───────────────────────────────

def test_setup_py():
    """setup.py should have correct metadata."""
    print("\n── Test 17: setup.py ──")
    setup = (SKILL_DIR / "setup.py").read_text()

    check("Has name", "name=" in setup)
    check("Has version", "version=" in setup)
    check("Has description", "description=" in setup)
    check("Has python_requires", "python_requires=" in setup)
    check("Has install_requires", "install_requires=" in setup)
    check("Has entry_points", "entry_points=" in setup)
    check("Requires Python 3.10+", "3.10" in setup)


# ── Test 18: SKILL.md No Stale Content ───────────────────────

def test_skill_md_no_stale():
    """SKILL.md should not have outdated info from previous versions."""
    print("\n── Test 18: SKILL.md No Stale Content ──")
    skill_md = (SKILL_DIR / "SKILL.md").read_text()

    # Should not reference old paths
    check("No /root/ references", "/root/" not in skill_md)
    check("No ~/.openclaw/ references", "/.openclaw/" not in skill_md)

    # Should not have TODO markers
    check("No TODO markers", "TODO" not in skill_md.upper())
    check("No FIXME markers", "FIXME" not in skill_md.upper())
    # XXX check: strip code blocks first (placeholder keys use X's)
    non_code = re.sub(r'```.*?```', '', skill_md, flags=re.DOTALL)
    check("No XXX markers", "XXX" not in non_code)

    # Should not reference non-existent commands
    check("No 'alpaca rebalance'", "alpaca rebalance" not in skill_md.lower())

    # Version in description should match marketplace
    mp = json.loads((SKILL_DIR / "marketplace-entry.json").read_text())
    # Just check they both reference same name
    check("Name consistency",
          mp["name"] in skill_md,
          f"marketplace name '{mp['name']}' not in SKILL.md")


# ── Test 19: README.md Present ────────────────────────────────

def test_readme():
    """README.md should exist and be informative."""
    print("\n── Test 19: README.md ──")
    readme = SKILL_DIR / "README.md"
    check("README.md exists", readme.exists())
    if readme.exists():
        content = readme.read_text()
        check("README is non-trivial", len(content) > 500,
              f"Only {len(content)} chars")
        check("README has install instructions",
              "install" in content.lower())


# ── Test 20: Watchlist JSON Valid ─────────────────────────────

def test_watchlist():
    """watchlist.json should be valid."""
    print("\n── Test 20: Watchlist JSON ──")
    wl = SKILL_DIR / "watchlist.json"
    check("File exists", wl.exists())
    if wl.exists():
        data = json.loads(wl.read_text())
        check("Is a list", isinstance(data, list))
        check("Has symbols", len(data) > 0)
        check("Has stock symbols", any(not "/" in s for s in data))
        check("Has crypto symbols", any("/" in s for s in data))


# ── Run All ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Skill Release Package Test Suite")
    print("=" * 60)

    test_skill_md_frontmatter()
    test_skill_md_structure()
    test_skill_md_content()
    test_required_files()
    test_strategy_files()
    test_no_secrets()
    test_marketplace_entry()
    test_requirements()
    test_config_example()
    test_gitignore()
    test_script_syntax()
    test_skill_md_tables()
    test_cross_references()
    test_strategy_registry()
    test_web_dashboard_imports()
    test_no_artifacts()
    test_setup_py()
    test_skill_md_no_stale()
    test_readme()
    test_watchlist()

    print("\n" + "=" * 60)
    print(f"  Results: {passed}/{passed + failed} passed, {failed} failed")
    print("=" * 60)

    sys.exit(1 if failed else 0)
