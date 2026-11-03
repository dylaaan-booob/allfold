"""Electron-owned FastAPI host; raw runtime messages remain on stderr."""
from __future__ import annotations
import asyncio
import os
from pathlib import Path
import socket
import sys
import uvicorn
from allfold.config import load_config
from allfold.logging_setup import configure_logging
from allfold.web.app import create_app
from allfold.web.electron_bridge import ElectronBridge


def main():
    root = Path(__file__).resolve().parents[3]
    config_path = Path(sys.argv[1]).resolve()
    # Runtime configuration and data must remain inside this project root.
    config_path.relative_to(root)
    config = load_config(config_path)
    config.output_dir.resolve().relative_to(root)
    config.venue_whitelist.resolve().relative_to(root)
    listener = socket.socket()
    # Allow immediate restarts after TCP TIME_WAIT, but never SO_REUSEPORT:
    # a second live application must still fail to bind this origin.
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", 18767))
    except OSError as error:
        listener.close()
        raise RuntimeError("Electron UI port 18767 is unavailable; close the other instance before restarting") from error
    port = listener.getsockname()[1]
    token = os.environ.pop("ALLFOLD_ELECTRON_TOKEN")
    bridge = ElectronBridge(token, f"127.0.0.1:{port}",
        cdp_url=os.environ.pop("ALLFOLD_ELECTRON_CDP_URL", ""))
    application = create_app(config_path, electron_bridge=bridge)
    from allfold.logging_setup import effective_log_level
    log_level = effective_log_level(config.log_level.value).lower()
    if log_level not in {'debug', 'info', 'warn', 'warning', 'error'}:
        log_level = 'info'
    if log_level == 'warn':
        log_level = 'warning'
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port,
        access_log=False, log_level=log_level, ws_max_size=8 * 1024 * 1024))

    async def drain():
        application.state.kept_workflow.shutdown()
        application.state.batch_import.stop()
        for worker in (application.state.paper_enrichment, application.state.journal_cover_search, application.state.wos_coordinator):
            worker.shutdown()
        for worker in (application.state.batch_import, application.state.preparation_coordinator,
                       application.state.paper_enrichment, application.state.journal_cover_search, application.state.wos_coordinator):
            await asyncio.to_thread(worker.join)
        application.state.kept_workflow.advance()
        server.should_exit = True

    bridge.shutdown = drain
    configure_logging(log_level)
    # stdout has exactly one bootstrap message; it carries no credentials.
    print(f"ELECTRON_PORT={port}", flush=True)
    server.run(sockets=[listener])


if __name__ == "__main__":
    main()
