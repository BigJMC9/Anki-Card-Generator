from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def find_rustc() -> str:
    rustc = shutil.which("rustc")
    if rustc:
        return rustc

    fallback = Path.home() / ".cargo" / "bin" / ("rustc.exe" if sys.platform == "win32" else "rustc")
    if fallback.exists():
        return str(fallback)

    raise RuntimeError("rustc was not found. Install Rust and ensure rustc is available on PATH.")


def get_host_triple(rustc_path: str) -> str:
    output = subprocess.check_output([rustc_path, "-vV"], text=True)
    for line in output.splitlines():
        if line.startswith("host: "):
            return line.replace("host: ", "").strip()
    raise RuntimeError("Unable to determine rust host target triple from rustc -vV output.")


def get_venv_python(venv_root: Path) -> Path:
    if sys.platform == "win32":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    sidecar_root = project_root / "python_sidecar"
    binaries_root = project_root / "src-tauri" / "binaries"
    entry_script = sidecar_root / "main.py"
    venv_root = sidecar_root / ".venv"

    binaries_root.mkdir(parents=True, exist_ok=True)

    rustc_path = find_rustc()
    host_triple = get_host_triple(rustc_path)

    if venv_root.exists():
        shutil.rmtree(venv_root)
    run([sys.executable, "-m", "venv", "--system-site-packages", str(venv_root)])

    venv_python = get_venv_python(venv_root)
    if not venv_python.exists():
        raise RuntimeError(f"Virtualenv python not found at: {venv_python}")

    run([str(venv_python), "-m", "pip", "install", "--no-cache-dir", "--upgrade", "pip", "pyinstaller"])

    requirements = sidecar_root / "requirements.txt"
    if requirements.exists():
        run([str(venv_python), "-m", "pip", "install", "--no-cache-dir", "-r", str(requirements)])

    dist_root = sidecar_root / "dist"
    build_root = sidecar_root / "build"
    spec_file = sidecar_root / "anki-sidecar.spec"

    if dist_root.exists():
        shutil.rmtree(dist_root)
    if build_root.exists():
        shutil.rmtree(build_root)
    if spec_file.exists():
        spec_file.unlink()

    run(
        [
            str(venv_python),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "anki-sidecar",
            "--paths",
            str(project_root.parent),
            str(entry_script),
        ],
        cwd=sidecar_root,
    )

    sidecar_name = "anki-sidecar.exe" if sys.platform == "win32" else "anki-sidecar"
    built_binary = dist_root / sidecar_name
    if not built_binary.exists():
        raise RuntimeError(f"Expected sidecar binary was not produced: {built_binary}")

    suffix = ".exe" if sys.platform == "win32" else ""
    target_binary = binaries_root / f"anki-sidecar-{host_triple}{suffix}"
    shutil.copy2(built_binary, target_binary)

    print(f"Sidecar built: {target_binary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
