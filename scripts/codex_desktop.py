"""Find the ChatGPT desktop app's runnable Codex CLI on Windows."""

import os
import re
import subprocess
from pathlib import Path

import processes


def installed_package_roots():
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        return []
    powershell = Path(system_root) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    query = """
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    Get-AppxPackage -Name 'OpenAI.Codex' -ErrorAction SilentlyContinue |
      Where-Object { $_.PackageFamilyName -eq 'OpenAI.Codex_2p2nqsd0c76g0' } |
      Sort-Object Version -Descending |
      ForEach-Object { $_.InstallLocation }
    """
    try:
        result = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", query],
            stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8-sig", errors="replace",
            timeout=8, **processes.launch_options(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode:
        return []
    roots = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    return [root for root in roots if root.is_absolute()]


def relocated_candidates():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    root = Path(local) / "OpenAI/Codex/bin"
    candidates = []
    for path in root.glob("*/codex.exe"):
        if re.fullmatch(r"[0-9a-f]{16,64}", path.parent.name, re.IGNORECASE):
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
    return [path for _, path in sorted(candidates, reverse=True)]


def find_cli():
    for path in [
        *(root / "app/resources/codex.exe" for root in installed_package_roots()),
        *relocated_candidates(),
    ]:
        try:
            if not path.is_file():
                continue
            result = subprocess.run(
                [str(path), "exec", "--help"], stdin=subprocess.DEVNULL, capture_output=True,
                encoding="utf-8", errors="replace", timeout=5, **processes.launch_options(),
            )
            if result.returncode == 0 and all(flag in result.stdout for flag in ("--json", "--output-schema", "resume")):
                return path
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None
