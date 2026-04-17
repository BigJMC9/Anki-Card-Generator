from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_npx() -> str:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx:
        return npx
    raise RuntimeError("npx not found on PATH. Install Node.js/npm first.")


def ensure_cargo_on_path(env: dict[str, str]) -> dict[str, str]:
    if shutil.which("cargo"):
        return env

    cargo_bin = Path.home() / ".cargo" / "bin"
    cargo_name = "cargo.exe" if os.name == "nt" else "cargo"
    cargo_exe = cargo_bin / cargo_name
    if cargo_exe.exists():
        env["PATH"] = f"{cargo_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


def main() -> int:
    args = sys.argv[1:]
    env = ensure_cargo_on_path(os.environ.copy())
    npx = resolve_npx()
    process = subprocess.run([npx, "tauri", *args], env=env)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
