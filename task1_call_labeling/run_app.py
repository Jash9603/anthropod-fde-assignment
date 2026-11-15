"""Start the backend (FastAPI) and the frontend (Streamlit) together.

    python run_app.py                # then open http://127.0.0.1:8501
    python run_app.py --backend-port 8001 --frontend-port 8502 --no-browser

Host, ports, models offered, upload limit and all LLM / retry / guardrail settings come from config.toml.

This only starts the web app. It does not run the unit tests or the 50-record batch pipeline
(use src/run.py for that). Press Ctrl+C to stop both processes.
"""
import argparse
import importlib.util
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from config import load_config   # noqa: E402  (standard library only)

REQUIRED_MODULES = {"fastapi": "fastapi", "uvicorn": "uvicorn", "streamlit": "streamlit",
                    "multipart": "python-multipart", "requests": "requests", "pydantic": "pydantic", "groq": "groq"}


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


def stop(proc: subprocess.Popen):
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
    args = ap.parse_args()

    missing = [pkg for mod, pkg in REQUIRED_MODULES.items() if importlib.util.find_spec(mod) is None]
    if missing:
        sys.exit("Missing packages: " + ", ".join(missing) + "\nInstall them with:  pip install -r requirements.txt")

    if args.config:                                   # the backend process reads the same file
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

    backend_url = f"http://{host}:{backend_port}"
    frontend_url = f"http://{host}:{frontend_port}"
    backend = frontend = None
    try:
        print(f"Starting backend (FastAPI) on {backend_url} ...")
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.backend.main:app", "--host", host,
             "--port", str(backend_port), "--log-level", "warning"], cwd=ROOT)
        if not wait_for(backend_url + "/health", 40):
            sys.exit("Backend did not become ready in time. Run it directly to see the error:\n"
                     f"  python -m uvicorn app.backend.main:app --port {backend_port}")
        health = urllib.request.urlopen(backend_url + "/health").read().decode()
        if '"api_key_configured":false' in health.replace(" ", ""):
            print("WARNING: GROQ_API_KEY is not set (export it or put it in .env). "
                  "The data views work, but predictions are disabled.")

        print(f"Starting frontend (Streamlit) on {frontend_url} ...")
        frontend = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app/frontend/streamlit_app.py",
             "--server.port", str(frontend_port), "--server.address", host,
             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
            cwd=ROOT, env={**os.environ, "BACKEND_URL": backend_url})
        if wait_for(frontend_url, 40) and not args.no_browser:
            webbrowser.open(frontend_url)
        print(f"\nReady:  frontend {frontend_url}   |   backend API docs {backend_url}/docs\nPress Ctrl+C to stop.")

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
