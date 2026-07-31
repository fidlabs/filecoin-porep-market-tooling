"""Test package generation: sptool CARs + manifest + HTTP server + ngrok."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

DUMMY_ACTOR = "f01000"  # sptool requires --actor even for local commands

MINIMUM_DAG_PIECE_SIZE = 1_048_576  # 1 MiB — enforced by porep-market validation

NGROK_API_URL = "http://localhost:4040/api/tunnels"


# ---------------------------------------------------------------------------
# sptool wrappers
# ---------------------------------------------------------------------------

def find_sptool(override: str | None) -> str:
    if override:
        path = Path(override)
        if not path.is_file():
            raise RuntimeError(f"sptool not found at {override} (check SPTOOL_PATH in .env.e2e)")
        return str(path)

    if shutil.which("sptool"):
        return "sptool"

    raise RuntimeError("sptool binary not found. Set SPTOOL_PATH in .env.e2e or add sptool to PATH.")


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result.stdout


def generate_rand_car(sptool: str, output_dir: Path, size: int) -> tuple[str, Path]:
    stdout = _run([
        sptool, "--actor", DUMMY_ACTOR,
        "toolbox", "mk12-client", "generate-rand-car",
        str(output_dir), "--size", str(size),
    ])

    # expected line: "Payload CID: <cid>, written to: <path>"
    match = re.search(r"Payload CID:\s+(\S+),\s+written to:\s+(.+\.car)", stdout)
    if not match:
        raise RuntimeError(f"generate-rand-car output not recognised:\n{stdout}")

    return match.group(1).strip(), Path(match.group(2).strip())


def compute_commp(sptool: str, car_path: Path) -> tuple[str, int, int]:
    stdout = _run([
        sptool, "--actor", DUMMY_ACTOR,
        "toolbox", "mk12-client", "commp",
        str(car_path),
    ])

    cid_m = re.search(r"CommP CID:\s+(\S+)", stdout)
    size_m = re.search(r"Piece size:\s+(\d+)", stdout)
    file_m = re.search(r"Car file size:\s+(\d+)", stdout)

    if not cid_m or not size_m or not file_m:
        raise RuntimeError(f"commp output not recognised:\n{stdout}")

    return cid_m.group(1), int(size_m.group(1)), int(file_m.group(1))


def process_piece(
    sptool: str,
    output_dir: Path,
    size: int,
    piece_type: str,
    idx: int,
    preparation_id: int,
    attachment_id: int,
    storage_id: int,
) -> dict[str, Any]:
    payload_cid, car_path = generate_rand_car(sptool, output_dir, size)
    commp_cid, padded_size, file_size = compute_commp(sptool, car_path)

    # rename {payloadCid}.car → {commPCid}.car so the HTTP server can map
    # GET /piece/{commPCid} → {commPCid}.car (as expected by onboard_data)
    car_path.rename(output_dir / f"{commp_cid}.car")

    return {
        "id": idx,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "pieceType": piece_type,
        "pieceCid": commp_cid,
        "pieceSize": padded_size,
        "rootCid": payload_cid,
        "fileSize": file_size,
        "minPieceSizePadding": 0,
        "storageId": storage_id,
        "storagePath": f"{commp_cid}.car",
        "numOfFiles": 0,
        "preparationId": preparation_id,
        "attachmentId": attachment_id,
        "jobId": idx,
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def build_manifest(pieces: list[dict[str, Any]], storage_id: int, output_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "attachmentId": pieces[0]["attachmentId"],
            "storageId": storage_id,
            "source": {
                "id": storage_id,
                "name": "local-test",
                "type": "local",
                "path": str(output_dir),
            },
            "pieces": pieces,
        }
    ]


def validate_manifest(manifest: list[dict[str, Any]]) -> None:
    """Mirror the porep-market validation so we catch problems early."""
    pieces = manifest[0]["pieces"]
    data_pcs = [p for p in pieces if p["pieceType"] == "data"]
    dag_pcs = [p for p in pieces if p["pieceType"] == "dag"]

    assert len(dag_pcs) == 1, "exactly one dag piece required"
    assert len(data_pcs) >= 1, "at least one data piece required"

    assert len({p["preparationId"] for p in pieces}) == 1, "all pieces must share the same preparationId"
    assert len({p["attachmentId"] for p in pieces}) == 1, "all pieces must share the same attachmentId"

    dag_size = dag_pcs[0]["pieceSize"]
    assert dag_size >= MINIMUM_DAG_PIECE_SIZE, (
        f"dag pieceSize {dag_size} < {MINIMUM_DAG_PIECE_SIZE} (1 MiB), increase dag size"
    )


def get_manifest_piece_bytes(manifest: list[dict[str, Any]]) -> int:
    return sum(int(piece["pieceSize"]) for piece in manifest[0]["pieces"])


def get_min_price_per_sector_per_month(
    *,
    manifest: list[dict[str, Any]],
    sector_size_bytes: int = 32 * 1024 * 1024 * 1024,
    epochs_in_month: int = 86_400,
) -> int:
    deal_size_bytes = get_manifest_piece_bytes(manifest)
    min_sectors = max(1, -(-deal_size_bytes // sector_size_bytes))
    return max(1, -(-epochs_in_month // min_sectors))


# ---------------------------------------------------------------------------
# HTTP server + ngrok
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    """Serves manifest at / and CAR files at /piece/<commPCid>."""

    manifest_bytes: bytes
    cars_dir: Path

    def do_GET(self):
        if self.path in ("/", "/manifest.json"):
            self._respond(200, "application/json", self.manifest_bytes)

        elif self.path.startswith("/piece/"):
            name = self.path[len("/piece/"):]
            car = self.cars_dir / f"{name}.car"
            if car.exists():
                self._respond(200, "application/octet-stream", car.read_bytes())
            else:
                self.send_error(404, f"not found: {name}.car")

        else:
            self.send_error(404)

    def _respond(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # noqa: N802
        pass  # keep test output clean


def start_server(port: int, manifest_bytes: bytes, cars_dir: Path) -> HTTPServer:
    class Handler(_Handler):
        pass

    Handler.manifest_bytes = manifest_bytes
    Handler.cars_dir = cars_dir

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def get_ngrok_tunnels() -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(NGROK_API_URL, timeout=3) as response:
            payload = json.loads(response.read())
    except Exception:
        return []

    tunnels = payload.get("tunnels")
    return tunnels if isinstance(tunnels, list) else []


def get_active_ngrok_url(port: int) -> str | None:
    tunnels = get_ngrok_tunnels()
    if not tunnels:
        return None

    port_markers = {
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
        f"localhost:{port}",
        f"127.0.0.1:{port}",
    }

    https_tunnels = [t for t in tunnels if t.get("proto") == "https" and t.get("public_url")]
    for tunnel in https_tunnels:
        addr = str(tunnel.get("config", {}).get("addr", ""))
        if addr in port_markers or any(marker in addr for marker in port_markers):
            return str(tunnel["public_url"])

    if len(https_tunnels) == 1:
        return str(https_tunnels[0]["public_url"])

    return None


def start_ngrok(port: int) -> tuple[str | None, subprocess.Popen | None]:
    if not shutil.which("ngrok"):
        return None, None

    proc = subprocess.Popen(
        ["ngrok", "http", str(port), "--log=stdout"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)  # give ngrok time to establish the tunnel

    url = get_active_ngrok_url(port)
    return url, proc


def stop_ngrok(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def ensure_ngrok_url(port: int) -> tuple[str, subprocess.Popen | None]:
    active_url = get_active_ngrok_url(port)
    if active_url:
        return active_url, None  # reuse existing tunnel, don't own the process

    url, proc = start_ngrok(port)
    if not url:
        stop_ngrok(proc)
        raise RuntimeError("Failed to start ngrok tunnel or obtain public HTTPS URL")

    return url, proc


# ---------------------------------------------------------------------------
# Generated package (pieces + manifest served over HTTP)
# ---------------------------------------------------------------------------

@dataclass
class GeneratedPackage:
    manifest_url: str
    output_dir: Path
    port: int
    manifest: list[dict[str, Any]]
    server: HTTPServer
    ngrok_proc: subprocess.Popen | None = None

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        stop_ngrok(self.ngrok_proc)


def create_generated_package(
    *,
    sptool_path: str | None,
    output_dir: Path,
    port: int,
    num_data_pieces: int = 1,
    data_size: int = 1_000_000,
    dag_size: int = 1_100_000,
    preparation_id: int = 1,
    attachment_id: int = 1,
    storage_id: int = 1,
    use_ngrok: bool = True,
) -> GeneratedPackage:
    sptool = find_sptool(sptool_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    pieces: list[dict[str, Any]] = []
    for idx in range(1, num_data_pieces + 1):
        pieces.append(process_piece(
            sptool, output_dir, data_size, "data", idx,
            preparation_id, attachment_id, storage_id,
        ))
    pieces.append(process_piece(
        sptool, output_dir, dag_size, "dag", num_data_pieces + 1,
        preparation_id, attachment_id, storage_id,
    ))

    manifest = build_manifest(pieces, storage_id, output_dir)
    validate_manifest(manifest)

    manifest_json = json.dumps(manifest, indent=2)
    (output_dir / "manifest.json").write_text(manifest_json, encoding="utf-8")

    server = start_server(port, manifest_json.encode("utf-8"), output_dir)

    ngrok_url = None
    ngrok_proc = None
    if use_ngrok:
        try:
            ngrok_url, ngrok_proc = ensure_ngrok_url(port)
        except RuntimeError:
            server.shutdown()
            server.server_close()
            raise

    return GeneratedPackage(
        manifest_url=ngrok_url or f"http://127.0.0.1:{port}",
        output_dir=output_dir,
        port=port,
        manifest=manifest,
        server=server,
        ngrok_proc=ngrok_proc,
    )
