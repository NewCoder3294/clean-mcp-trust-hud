"""Persistent scoring daemon.

Holds a warm ServiceContainer (embedding model loaded once) and scores files
on request over a unix socket, so the per-edit hook can run the embedding
indicators without paying model cold-start on every edit.

Protocol: newline-delimited JSON. Request ``{"file_path": str, "cwd": str?}``.
Response: the FileScore state dict (see ``state.file_score_to_dict``).
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from ..services.container import ServiceContainer
from ..util.logging import get_logger
from .service import _git_toplevel, _project_id_for
from .state import ScoringStateWriter, file_score_to_dict, write_repo_score

logger = get_logger(__name__)

DEFAULT_SOCKET_PATH = Path.home() / ".clean" / "scoring.sock"
_RECV_LIMIT = 1 << 16


def socket_path() -> Path:
    override = os.getenv("CLEAN_SCORING_SOCKET")
    return Path(override) if override else DEFAULT_SOCKET_PATH


def _handle_request(
    payload: dict, container: ServiceContainer, writer: ScoringStateWriter
) -> dict:
    file_path = payload.get("file_path")
    if not file_path:
        return {"error": "missing file_path"}

    # Refresh the index for the edited file FIRST (incremental — only changed
    # files re-embed) so the score is computed against current content and the
    # 'stale' flag clears. Only for already-indexed projects (avoids a surprise
    # full index on first touch).
    root = _git_toplevel(file_path) or os.path.dirname(os.path.abspath(file_path))
    try:
        if container.store.count(_project_id_for(root)) > 0:
            container.indexer.index(root)
    except Exception:
        logger.exception("daemon incremental reindex failed for %s", root)

    score = container.scoring.score_file(file_path, with_embeddings=True)
    writer.write(score)
    write_repo_score(score)
    return file_score_to_dict(score)


def serve(sock_path: Path | None = None) -> None:
    """Run the daemon (blocking). One request at a time."""
    sock_path = sock_path or socket_path()
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    container = ServiceContainer()
    logger.info("scoring daemon: warming embedding model...")
    container.warmup()
    writer = ScoringStateWriter()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(8)
    logger.info("scoring daemon ready on %s", sock_path)

    try:
        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    data = conn.recv(_RECV_LIMIT)
                    if not data:
                        continue
                    payload = json.loads(data.decode("utf-8"))
                    response = _handle_request(payload, container, writer)
                except Exception as exc:  # never let one bad request kill the daemon
                    logger.exception("scoring request failed")
                    response = {"error": str(exc)}
                try:
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                except OSError:
                    pass
    finally:
        server.close()
        if sock_path.exists():
            sock_path.unlink()


def request_score(
    file_path: str,
    cwd: str | None = None,
    sock_path: Path | None = None,
    timeout: float = 5.0,
) -> dict | None:
    """Ask a running daemon to score *file_path*. None if no daemon answers."""
    sock_path = sock_path or socket_path()
    if not sock_path.exists():
        return None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(str(sock_path))
        payload = {"file_path": file_path, "cwd": cwd or ""}
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        chunks = []
        while True:
            buf = client.recv(_RECV_LIMIT)
            if not buf:
                break
            chunks.append(buf)
            if buf.endswith(b"\n"):
                break
        client.close()
        if not chunks:
            return None
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
