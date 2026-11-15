"""One command to run everything: backend (FastAPI) + dashboard (Streamlit).

    python run_app.py

On the first run it creates a local virtual environment (.venv) and installs the pinned dependencies from
requirements.txt (a minute or two); later runs start immediately. It also creates .env from .env.example if missing.
Then it starts the backend and the dashboard and opens http://127.0.0.1:8501. Upload your CSV from the dashboard.

Options:  --no-browser   --config FILE   --backend-port N   --frontend-port N
          --setup-only   create .venv and install dependencies, then exit
          --no-venv      use the current Python environment as is (skip .venv creation)
Host, ports, models offered, upload limit and all LLM / retry / guardrail settings come from config.toml.
This starts only the web app: it does not run the unit tests or the batch pipeline (src/run.py). Ctrl+C stops it.
"""
import sys

if sys.version_info < (3, 11):
    sys.exit(f"Python 3.11 or newer is required (this is {sys.version.split()[0]}).")

import argparse
import hashlib
import importlib.util
import os
import shutil
import socket
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
REQUIRED_MODULES = {"fastapi": "fastapi", "uvicorn": "uvicorn", "streamlit": "streamlit",
                    "multipart": "python-multipart", "requests": "requests", "pydantic": "pydantic", "groq": "groq"}


# ---- first-run setup ---------------------------------------------------------------------------
def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def in_project_venv() -> bool:
    return Path(sys.prefix).resolve() == VENV.resolve()


def ensure_environment() -> Path:
    """Create .venv and install requirements.txt when needed (re-installs only if requirements.txt changed)."""
    py = venv_python()
    if not py.exists():
        print("First run: creating the virtual environment (.venv) ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    stamp = VENV / ".requirements.sha256"
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if not stamp.exists() or stamp.read_text().strip() != digest:
        print("Installing dependencies (one-time, can take a minute or two) ...", flush=True)
        try:
            subprocess.check_call([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                                   "-r", str(REQUIREMENTS)])
        except subprocess.CalledProcessError:
            sys.exit("Installing the dependencies failed (is there an internet connection?). "
                     "Fix it and run `python run_app.py` again.")
        stamp.write_text(digest)
    return py


def ensure_env_file() -> bool:
    """Create .env from .env.example when missing. Returns True if it was just created."""
    env, example = ROOT / ".env", ROOT / ".env.example"
    if not env.exists() and example.exists():
        shutil.copyfile(example, env)
        return True
    return False


# ---- helpers ---------------------------------------------------------------------------------------
def port_free(host: str, port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host, port)) != 0


def wait_for(url: str, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None, help="config file (default: config.toml, or $LABELING_CONFIG)")
    ap.add_argument("--backend-port", type=int, default=None, help="[app] backend_port (default 8000)")
    ap.add_argument("--frontend-port", type=int, default=None, help="[app] frontend_port (default 8501)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    ap.add_argument("--setup-only", action="store_true", help="create .venv and install dependencies, then exit")
    ap.add_argument("--no-venv", action="store_true", help="use the current Python environment (skip .venv)")
    args = ap.parse_args()

    # 1. environment: run inside the project's .venv (created and filled on the first run)
    if not args.no_venv and not in_project_venv():
        py = ensure_environment()
        if args.setup_only:
            print("Setup finished.")
            return
        sys.exit(subprocess.call([str(py), str(Path(__file__).resolve()), *sys.argv[1:]]))
    if args.setup_only:
        print("Already running inside the project environment; nothing to set up.")
        return

    missing = [pkg for mod, pkg in REQUIRED_MODULES.items() if importlib.util.find_spec(mod) is None]
    if missing:
        sys.exit("Missing packages: " + ", ".join(missing) + "\nInstall them with:  pip install -r requirements.txt")

    sys.path.insert(0, str(ROOT / "src"))
    from config import load_config                       # standard library only

    # 2. .env (API key)
    created_env = ensure_env_file()
    if created_env:
        print("Created .env from .env.example. Put your GROQ_API_KEY in it (predictions stay disabled until then).")

    # 3. settings and ports
    if args.config:                                      # the backend process reads the same file
        os.environ["LABELING_CONFIG"] = str(Path(args.config).resolve())
    try:
        app_cfg = load_config(args.config)["app"]
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    host = app_cfg["host"]
    backend_port = args.backend_port or app_cfg["backend_port"]
    frontend_port = args.frontend_port or app_cfg["frontend_port"]
    for port in (backend_port, frontend_port):
        if not port_free(host, port):
            sys.exit(f"Port {port} is already in use. Pick another with --backend-port / --frontend-port "
                     "(or set it in config.toml).")

    # 4. start backend and dashboard
    backend_url = f"http://{host}:{backend_port}"
    frontend_url = f"http://{host}:{frontend_port}"
    backend = frontend = None
    try:
        print(f"Starting backend (FastAPI) on {backend_url} ...", flush=True)
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.backend.main:app", "--host", host,
             "--port", str(backend_port), "--log-level", "warning"], cwd=ROOT)
        if not wait_for(backend_url + "/health", 40):
            sys.exit("Backend did not become ready in time. Run it directly to see the error:\n"
                     f"  python -m uvicorn app.backend.main:app --port {backend_port}")
        health = urllib.request.urlopen(backend_url + "/health").read().decode()
        if '"api_key_configured":false' in health.replace(" ", "") and not created_env:
            print("WARNING: GROQ_API_KEY is not set in .env. The dashboard works, but predictions are disabled.")

        print(f"Starting dashboard (Streamlit) on {frontend_url} ...", flush=True)
        frontend = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app/frontend/streamlit_app.py",
             "--server.port", str(frontend_port), "--server.address", host,
             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
            cwd=ROOT, env={**os.environ, "BACKEND_URL": backend_url})
        if wait_for(frontend_url, 40) and not args.no_browser:
            webbrowser.open(frontend_url)
        print(f"\nReady:  dashboard {frontend_url}   |   backend API docs {backend_url}/docs\nPress Ctrl+C to stop.")

        while backend.poll() is None and frontend.poll() is None:
            time.sleep(1)
        print("A process exited; shutting down.")
    except KeyboardInterrupt:
        print("\nStopping ...")
    finally:
        stop(frontend)
        stop(backend)


if __name__ == "__main__":
    main()
