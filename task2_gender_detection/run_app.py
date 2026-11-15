"""One command: set up (first run only) and start the dashboard.

    python run_app.py

On the first run it creates a local virtual environment (.venv) and installs requirements.txt; later runs start
immediately. Then it opens the dashboard (http://127.0.0.1:8502 by default). No API key is needed.
Options: --no-browser, --port N, --setup-only, --no-venv. Ctrl+C stops it.
"""
import sys

if sys.version_info < (3, 11):
    sys.exit(f"Python 3.11 or newer is required (this is {sys.version.split()[0]}).")

import argparse
import hashlib
import importlib.util
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def in_project_venv() -> bool:
    return Path(sys.prefix).resolve() == VENV.resolve()


def ensure_environment() -> Path:
    py = venv_python()
    if not py.exists():
        print("First run: creating the virtual environment (.venv) ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    stamp = VENV / ".requirements.sha256"
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if not stamp.exists() or stamp.read_text().strip() != digest:
        print("Installing dependencies (one-time, about a minute) ...", flush=True)
        try:
            subprocess.check_call([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                                   "-r", str(REQUIREMENTS)])
        except subprocess.CalledProcessError:
            sys.exit("Installing the dependencies failed (is there an internet connection?). Run again when fixed.")
        stamp.write_text(digest)
    return py


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=None, help="dashboard port (default from config.toml: 8502)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--setup-only", action="store_true", help="create .venv and install dependencies, then exit")
    ap.add_argument("--no-venv", action="store_true", help="use the current Python environment (skip .venv)")
    args = ap.parse_args()

    if not args.no_venv and not in_project_venv():
        py = ensure_environment()
        if args.setup_only:
            print("Setup finished.")
            return
        sys.exit(subprocess.call([str(py), str(Path(__file__).resolve()), *sys.argv[1:]]))
    if args.setup_only:
        print("Already running inside the project environment; nothing to set up.")
        return
    if importlib.util.find_spec("streamlit") is None:
        sys.exit("streamlit is not installed. Install it with:  pip install -r requirements.txt")

    sys.path.insert(0, str(ROOT / "src"))
    from config import load_config
    try:
        app_cfg = load_config()["app"]
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    port = args.port or app_cfg["port"]
    print(f"Starting the dashboard on http://{app_cfg['host']}:{port}  (Ctrl+C to stop)", flush=True)
    cmd = [sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py", "--server.port", str(port),
           "--server.address", app_cfg["host"], "--browser.gatherUsageStats", "false",
           "--server.headless", "true" if args.no_browser else "false"]
    try:
        sys.exit(subprocess.call(cmd, cwd=ROOT))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
