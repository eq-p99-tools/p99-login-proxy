import asyncio
import logging
import platform
import sys
import threading

import wx

from p99_sso_login_proxy import server, ui, updater, ws_client

logger = logging.getLogger("cmd")


# Class to integrate wxPython with asyncio
class WxAsyncApp(wx.App):
    def __init__(self):
        super().__init__(False)
        self.loop = asyncio.new_event_loop()
        self.running = False
        self.transport = None
        self.exit_event = threading.Event()
        self.loop_thread: threading.Thread | None = None

    def start_event_loop(self):
        """Start the event loop"""
        self.running = True
        self.loop_thread = threading.Thread(target=self._run_loop)
        self.loop_thread.daemon = True
        self.loop_thread.start()
        self.MainLoop()

    def _run_loop(self):
        """Run the asyncio event loop in a separate thread"""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._check_exit())
        except asyncio.CancelledError:
            pass
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            self.loop.close()

    async def _check_exit(self):
        """Check if the exit event has been set"""
        # Start the proxy server
        self.proxy_task = asyncio.create_task(server.main())

        # Start the WebSocket client for real-time account data
        self.ws_task = asyncio.create_task(ws_client.start())

        # Wait for the exit event to be set
        while not self.exit_event.is_set():
            await asyncio.sleep(0.1)
            try:
                if self.transport is None and self.proxy_task.done():
                    self.transport = self.proxy_task.result()
            except Exception:
                logger.exception("Failed to start UDP proxy")
                wx.CallAfter(ui.error, "Failed to start UDP proxy, check if another instance is running, and restart.")
                self.stop_event_loop()

        # Cancel the proxy task and WS client
        self.proxy_task.cancel()
        self.ws_task.cancel()

    def on_power_resume(self, event):
        """Handle power resume event"""
        wx.CallAfter(self.restart_proxy_server)

    def restart_proxy_server(self):
        """Restart the proxy server (called from wx thread via CallAfter)."""
        logger.info("System resume event detected. Restarting proxy server...")

        if self.transport:
            self.transport.close()
        logger.info("Existing transport shutdown.")

        future = asyncio.run_coroutine_threadsafe(server.main(), self.loop)
        self.transport = None

        def _on_restart_done(fut):
            try:
                self.transport = fut.result()
                logger.info("New transport started.")
            except Exception:
                logger.exception("Failed to restart proxy server")
                wx.CallAfter(ui.error, "Failed to restart proxy server. Please restart the application.")

        future.add_done_callback(_on_restart_done)
        logger.info("Restart scheduled on asyncio loop.")

    def stop_event_loop(self):
        """Stop the event loop"""
        logger.info("Stopping event loop in WxAsyncApp")
        self.exit_event.set()
        self.ExitMainLoop()


def main():
    # Create the wxPython application with asyncio integration
    wx_app = WxAsyncApp()

    def start_eq_windows(eq_dir):
        logger.info("Starting EverQuest...")
        import subprocess

        subprocess.Popen(
            ["powershell.exe", "-Command", "& { Start-Process eqgame.exe -ArgumentList @('patchme') -Verb RunAs }"],
            cwd=eq_dir,
            start_new_session=True,
            shell=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        )

    def start_eq_linux(eq_dir):
        logger.info("Starting EverQuest...")
        # This is absolutely not accurate, need to get a real command from someone who knows...
        # or make it configurable because it likely is different on different distros
        import subprocess

        subprocess.Popen(["wine", "eqgame.exe", "patchme"], cwd=eq_dir, start_new_session=True)

    # Initialize the UI
    main_window = ui.start_ui()
    if platform.system() == "Windows":
        main_window.start_eq_func = start_eq_windows
    else:
        main_window.start_eq_func = start_eq_linux

    # Check for updates on startup
    try:
        updater.check_update()
    except Exception:
        logger.exception("Failed to check for updates")

    # Set up exit handler
    def handle_exit():
        wx_app.stop_event_loop()

    # Connect the exit event from the UI to our exit handler
    # In wxPython we need to check for the exit event being set
    def check_exit_event():
        if main_window.exit_event.is_set():
            handle_exit()
        else:
            wx.CallLater(100, check_exit_event)

    # Start checking for exit event
    check_exit_event()

    # Bind the power resume event
    main_window.Bind(wx.EVT_POWER_RESUME, wx_app.on_power_resume)

    try:
        # Start the event loop
        wx_app.start_event_loop()
    except KeyboardInterrupt:
        handle_exit()
    finally:
        logger.info("Shutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
