#!/usr/bin/env python3
"""
Vibesbot Desktop App - Aplicación de escritorio nativa.

Abre el dashboard en una ventana nativa sin necesidad de navegador externo.
"""
import asyncio
import sys
import os
import threading
import signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import webview
import uvicorn

from src.web_server import create_app
from src.utils.logger import setup_logger


class VibesbotApp:
    """Aplicación de escritorio para Vibesbot."""
    
    def __init__(self, port: int = 8765):
        self.port = port
        self.server_thread = None
        self.window = None
        
    def start_server(self):
        """Inicia el servidor FastAPI en un hilo separado."""
        app = create_app()
        
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning"
        )
        server = uvicorn.Server(config)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())
    
    def run(self):
        """Ejecuta la aplicación."""
        self.server_thread = threading.Thread(target=self.start_server, daemon=True)
        self.server_thread.start()
        
        import time
        time.sleep(2)
        
        self.window = webview.create_window(
            title="VIBESBOT — Trading Radar",
            url=f"http://127.0.0.1:{self.port}",
            width=1400,
            height=900,
            min_size=(1200, 700),
            resizable=True,
            frameless=False,
            easy_drag=True,
            text_select=False,
            background_color="#0a0a0f"
        )
        
        webview.start(
            debug=False,
            http_server=False
        )


def main():
    """Punto de entrada principal."""
    setup_logger("vibesbot", console_output=False, file_output=True)
    
    app = VibesbotApp()
    app.run()


if __name__ == "__main__":
    main()
