"""Dashboard HTTP server — stdlib only, no Flask/Express needed.

Serves a single-page dashboard on http://localhost:3333 that can start a
pipeline run, stream its progress, and render the results.

Routes
------
  GET  /                      the dashboard page
  GET  /static/<file>         css / js
  POST /api/run               start a run (JSON body = pipeline options)
  GET  /api/progress          current job state + log lines (polled)
  GET  /api/results[?tag=]    analysis JSON for a finished run
  GET  /api/reports           past runs available in data/output
  GET  /api/config            what the server can offer (api key present? browser?)
  GET  /api/sources           source roadmap: cost, setup effort, live configured state
  GET  /api/download/<file>   download a generated report/csv/pdf
"""

from __future__ import annotations

import json
import mimetypes
import threading
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (  # noqa: E402
    OUTPUT_DIR,
    get_api_key,
    get_reddit_credentials,
    get_threads_token,
    load_sources_catalog,
)
from src.pipeline import Pipeline, PipelineConfig  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 3333

# Only these extensions may be downloaded from the output directory.
DOWNLOADABLE = {".md", ".json", ".csv", ".pdf", ".html"}


class Job:
    """State of the one run the server tracks at a time."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = "idle"          # idle | running | done | error
        self.percent = 0
        self.message = ""
        self.log: List[str] = []
        self.error: Optional[str] = None
        self.tag: Optional[str] = None
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.thread: Optional[threading.Thread] = None

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "state": self.state,
                "percent": self.percent,
                "message": self.message,
                "log": list(self.log),
                "error": self.error,
                "tag": self.tag,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def reset(self, tag: str) -> None:
        with self.lock:
            self.state = "running"
            self.percent = 0
            self.message = "Starting…"
            self.log = []
            self.error = None
            self.tag = tag
            self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.finished_at = None

    def progress(self, percent: int, message: str) -> None:
        with self.lock:
            self.percent = max(self.percent, min(99, percent))
            self.message = message.strip()
            self.log.append(message.rstrip())

    def append(self, message: str) -> None:
        with self.lock:
            self.log.append(message.rstrip())

    def finish(self, error: Optional[str] = None) -> None:
        with self.lock:
            self.state = "error" if error else "done"
            self.percent = self.percent if error else 100
            self.error = error
            self.message = error or "Complete"
            self.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")


JOB = Job()


def _run_pipeline(options: Dict[str, Any], tag: str) -> None:
    """Executed on a worker thread; never raises into the server."""
    try:
        requested = options.get("sources") or [options.get("source", "fixtures")]
        config = PipelineConfig(
            sources=[s for s in requested if s],
            max_queries=int(options.get("max_queries", 6)),
            videos_per_query=int(options.get("videos_per_query", 5)),
            comments_per_video=int(options.get("comments_per_video", 100)),
            relevance_threshold=float(options.get("threshold", 1.0)),
            analyzer=options.get("analyzer", "rules"),
            use_cache=bool(options.get("use_cache", True)),
            output_dir=OUTPUT_DIR,
            verbose=True,
            on_progress=JOB.progress,
        )
        result = Pipeline(config).run(tag=tag)

        if options.get("pdf"):
            JOB.progress(98, "      exporting PDF…")
            from src.pdf_export import export_pdf

            exported = export_pdf(result["paths"]["markdown"])
            JOB.append(
                f"      PDF -> {exported['pdf'].name}" if exported["pdf"]
                else "      ! PDF skipped (no Edge/Chrome found); HTML written instead"
            )

        stats = result["stats"]
        JOB.append(
            f"      DONE: {stats['analyzed_comments']} analyzed, "
            f"{stats['qualified_leads']} qualified, {len(result['profiles'])} segments"
        )
        JOB.finish()
    except Exception as exc:  # noqa: BLE001 - surface to the UI, don't crash the server
        JOB.append(f"ERROR: {exc}")
        traceback.print_exc()
        JOB.finish(error=str(exc))


def _latest_analysis() -> Optional[Path]:
    files = sorted(OUTPUT_DIR.glob("analysis_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _list_reports() -> List[Dict[str, Any]]:
    reports = []
    for path in sorted(OUTPUT_DIR.glob("analysis_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        tag = path.stem.replace("analysis_", "")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        run = data.get("run", {})
        overall = data.get("overall", {})
        sources = run.get("sources") or ([run["source"]] if run.get("source") else [])
        reports.append({
            "tag": tag,
            "generated_at": run.get("generated_at", ""),
            "source": "+".join(sources),
            "analyzer": run.get("analyzer", ""),
            "analyzed": overall.get("analyzed_comments", 0),
            "qualified": overall.get("qualified_leads", 0),
            "segments": len(data.get("segments", [])),
            "files": {
                ext.lstrip("."): f"{prefix}_{tag}{ext}"
                for prefix, ext in (("report", ".md"), ("report", ".pdf"),
                                    ("analysis", ".json"), ("comments", ".csv"))
                if (OUTPUT_DIR / f"{prefix}_{tag}{ext}").exists()
            },
        })
    return reports


class Handler(BaseHTTPRequestHandler):
    server_version = "SNSListening/0.1"

    # Quieter console: the pipeline's own logs are the interesting output.
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    # ------------------------------------------------------------- helpers

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser navigated away mid-response

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _file(self, path: Path, *, download: bool = False) -> None:
        if not path.exists() or not path.is_file():
            self._error(404, f"Not found: {path.name}")
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in (".md", ".csv"):
            content_type += "; charset=utf-8"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if route == "/":
            self._file(STATIC_DIR / "index.html")
            return

        if route.startswith("/static/"):
            name = unquote(route[len("/static/"):])
            # Resolve and confirm containment - no path traversal out of static/.
            candidate = (STATIC_DIR / name).resolve()
            if STATIC_DIR.resolve() not in candidate.parents:
                self._error(403, "Forbidden")
                return
            self._file(candidate)
            return

        if route == "/api/config":
            from src.config import get_anthropic_key
            from src.pdf_export import find_browser

            try:
                import anthropic  # noqa: F401

                has_sdk = True
            except ImportError:
                has_sdk = False

            reddit_id, reddit_secret = get_reddit_credentials()
            self._json({
                "has_youtube_key": bool(get_api_key()),
                "has_reddit": bool(reddit_id and reddit_secret),
                "has_threads": bool(get_threads_token()),
                "pdf_available": bool(find_browser()),
                "llm_available": has_sdk and bool(get_anthropic_key()),
                "llm_blocker": (
                    None if has_sdk and get_anthropic_key()
                    else "needs `pip install anthropic`" if not has_sdk
                    else "needs ANTHROPIC_API_KEY in .env"
                ),
                "output_dir": str(OUTPUT_DIR),
            })
            return

        if route == "/api/sources":
            catalog = load_sources_catalog()
            reddit_id, reddit_secret = get_reddit_credentials()
            configured = {
                "youtube": bool(get_api_key()),
                "reddit": bool(reddit_id and reddit_secret),
                "threads": bool(get_threads_token()),
            }
            # Merge the static roadmap with what is actually wired up right now,
            # so the panel can't drift from reality.
            for entry in catalog.get("sources", []):
                entry["configured"] = configured.get(entry["id"])
            self._json(catalog)
            return

        if route == "/api/progress":
            self._json(JOB.snapshot())
            return

        if route == "/api/reports":
            self._json({"reports": _list_reports()})
            return

        if route == "/api/results":
            params = parse_qs(parsed.query)
            tag = params.get("tag", [None])[0]
            path = (OUTPUT_DIR / f"analysis_{tag}.json") if tag else _latest_analysis()
            if not path or not path.exists():
                self._error(404, "No analysis available yet — run one first.")
                return
            self._send(200, path.read_bytes())
            return

        if route.startswith("/api/download/"):
            name = unquote(route[len("/api/download/"):])
            candidate = (OUTPUT_DIR / name).resolve()
            if OUTPUT_DIR.resolve() not in candidate.parents or candidate.suffix not in DOWNLOADABLE:
                self._error(403, "Forbidden")
                return
            self._file(candidate, download=True)
            return

        self._error(404, "Unknown route")

    # ----------------------------------------------------------------- POST

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route != "/api/run":
            self._error(404, "Unknown route")
            return

        if JOB.state == "running":
            self._error(409, "A run is already in progress.")
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            options = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(400, f"Bad request body: {exc}")
            return

        requested = options.get("sources") or [options.get("source", "fixtures")]
        if "youtube" in requested and not get_api_key():
            self._error(400, "No YOUTUBE_API_KEY configured — add one to .env.")
            return
        if not requested:
            self._error(400, "Pick at least one data source.")
            return

        tag = options.get("tag") or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        JOB.reset(tag)
        JOB.thread = threading.Thread(target=_run_pipeline, args=(options, tag), daemon=True)
        JOB.thread.start()
        self._json({"started": True, "tag": tag})


def local_ip_addresses() -> List[str]:
    """This machine's LAN IPv4 addresses, best-effort.

    The UDP 'connect' never sends a packet — it just asks the OS which local
    interface would be used to reach the internet, which is the address other
    machines on the network can actually reach.
    """
    import socket

    found: List[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127.") and address not in found:
                found.append(address)
    except OSError:
        pass
    return found


def serve(port: int = DEFAULT_PORT, *, open_browser: bool = True, host: str = "127.0.0.1") -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://localhost:{port}"
    exposed = host not in ("127.0.0.1", "localhost")

    print("=" * 62)
    print("  Zorvex SNS Listening — Dashboard")
    print("=" * 62)
    print(f"  Bound to     : {host}:{port}")
    print(f"  This machine : {url}")
    if exposed:
        for address in local_ip_addresses():
            print(f"  On your LAN  : http://{address}:{port}")
    print(f"  YouTube key  : {'configured' if get_api_key() else 'NOT SET (fixtures only)'}")
    print(f"  Output dir   : {OUTPUT_DIR}")
    print("  Stop with    : Ctrl+C")
    if exposed:
        print("-" * 62)
        print("  ! Reachable by anyone on this network. There is no login, so they")
        print("    can start runs (spending your YouTube quota) and download reports.")
        print("    Windows Firewall may still need to allow inbound Python — see")
        print("    the README's 'Opening it to other devices' section.")
    print("=" * 62)

    if open_browser:
        import webbrowser

        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
