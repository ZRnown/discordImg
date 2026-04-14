#!/usr/bin/env python3
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
BIN_DIR = ROOT / "src-tauri" / "binaries"


def detect_target_triple() -> str:
    explicit = os.getenv("TAURI_TARGET_TRIPLE")
    if explicit:
        return explicit

    machine = platform.machine().lower()
    system = platform.system().lower()
    is_arm = machine in {"arm64", "aarch64"}

    if system == "windows":
        return "aarch64-pc-windows-msvc" if is_arm else "x86_64-pc-windows-msvc"
    if system == "darwin":
        return "aarch64-apple-darwin" if is_arm else "x86_64-apple-darwin"
    return "aarch64-unknown-linux-gnu" if is_arm else "x86_64-unknown-linux-gnu"


def build() -> None:
    model_path = ROOT / "yolov8s-world.pt"
    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "backend-api",
    ]
    if model_path.exists():
        pyinstaller_cmd.extend(["--add-data", f"{model_path}{os.pathsep}."])
    else:
        print(f"[build-sidecar] warning: model file not found, skipping bundle: {model_path}")

    pyinstaller_cmd.append(str(ROOT / "backend" / "app.py"))

    subprocess.run(pyinstaller_cmd, cwd=ROOT, check=True)

    target = detect_target_triple()
    is_windows_target = "windows" in target
    source_bin = DIST_DIR / ("backend-api.exe" if is_windows_target else "backend-api")
    if not source_bin.exists():
        raise FileNotFoundError(f"sidecar binary not found: {source_bin}")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target_name = f"backend-api-{target}"
    if is_windows_target:
        target_name += ".exe"
    target_bin = BIN_DIR / target_name
    shutil.copy2(source_bin, target_bin)
    print(f"built sidecar: {target_bin}")


if __name__ == "__main__":
    build()
