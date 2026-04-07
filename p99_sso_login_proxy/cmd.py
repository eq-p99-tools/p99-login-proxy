import asyncio
import logging
import platform
import sys
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from p99_sso_login_proxy import log_handler, server, theme, ui, updater, ws_client

logger = logging.getLogger("cmd")

logging.getLogger("websockets").setLevel(logging.INFO)
logging.getLogger("watchdog").setLevel(logging.INFO)


class QtAsyncApp(QApplication):
    """Integrate Qt GUI (main thread) with asyncio (daemon thread)."""

    def __init__(self, argv):
        super().__init__(argv)
        self.loop = asyncio.new_event_loop()
        self.running = False
        self.transport = None
        self.exit_event = threading.Event()
        self.loop_thread: threading.Thread | None = None

    def start_event_loop(self):
        """Start the asyncio loop in a background thread; block on Qt exec()."""
        log_handler.set_asyncio_loop(self.loop)
        self.running = True
        self.loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.loop_thread.start()
        self.exec()

    def _run_loop(self):
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
        self.proxy_task = asyncio.create_task(server.main())
        self.ws_task = asyncio.create_task(ws_client.start())

        while not self.exit_event.is_set():
            await asyncio.sleep(0.1)
            try:
                if self.transport is None and self.proxy_task.done():
                    self.transport = self.proxy_task.result()
            except Exception:
                logger.exception("Failed to start UDP proxy")

                def _fail_udp():
                    ui.error("Failed to start UDP proxy, check if another instance is running, and restart.")
                    self.stop_event_loop()

                QTimer.singleShot(0, _fail_udp)
                return

        self.proxy_task.cancel()
        self.ws_task.cancel()

    def restart_proxy_server(self):
        """Restart the proxy server (main thread)."""
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
                QTimer.singleShot(
                    0,
                    lambda: ui.error("Failed to restart proxy server. Please restart the application."),
                )

        future.add_done_callback(_on_restart_done)
        logger.info("Restart scheduled on asyncio loop.")

    def stop_event_loop(self):
        logger.info("Stopping event loop in QtAsyncApp")
        self.exit_event.set()
        self.quit()


_AUMID = "P99LoginProxy"


def _setup_win32_aumid():
    """Set the AUMID and register a Start Menu shortcut so toast
    notifications display our app name and icon."""
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_AUMID)

    try:
        import glob
        import os

        from PySide6.QtGui import QImage

        from p99_sso_login_proxy import config, utils

        png_path = utils.find_resource_path("tray_icon.png")
        if not png_path:
            return

        data_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "P99LoginProxy",
        )
        os.makedirs(data_dir, exist_ok=True)
        ico_path = os.path.join(data_dir, "icon.ico")

        img = QImage(png_path)
        if not img.isNull():
            img.save(ico_path, "ICO")

        start_menu = os.path.join(
            os.environ["APPDATA"],
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
        )
        lnk_name = f"{config.APP_NAME} v{config.APP_VERSION}.lnk"
        lnk_path = os.path.join(start_menu, lnk_name)

        for old in glob.glob(os.path.join(start_menu, "P99 Login Proxy*.lnk")):
            if old != lnk_path:
                os.remove(old)

        import pythoncom  # noqa: F401
        from win32com.client import Dispatch
        from win32com.propsys import propsys, pscon

        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(lnk_path)
        shortcut.TargetPath = sys.executable
        shortcut.IconLocation = ico_path
        shortcut.Description = f"{config.APP_NAME} v{config.APP_VERSION}"
        shortcut.save()

        store = propsys.SHGetPropertyStoreFromParsingName(lnk_path, None, 0x2, propsys.IID_IPropertyStore)
        store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(_AUMID))
        store.Commit()

        logger.info("Notification shortcut: %s", lnk_path)
    except Exception:
        logger.debug("Could not create notification shortcut", exc_info=True)


def main():
    qt_app = QtAsyncApp(sys.argv)
    theme.apply_dark_theme(qt_app)

    if platform.system() == "Windows":
        _setup_win32_aumid()

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
        import subprocess

        subprocess.Popen(["wine", "eqgame.exe", "patchme"], cwd=eq_dir, start_new_session=True)

    main_window = ui.start_ui()
    if platform.system() == "Windows":
        main_window.start_eq_func = start_eq_windows
    else:
        main_window.start_eq_func = start_eq_linux

    main_window.power_resume_requested.connect(qt_app.restart_proxy_server)

    try:
        updater.check_update()
    except Exception:
        logger.exception("Failed to check for updates")

    def handle_exit():
        qt_app.stop_event_loop()

    exit_timer = QTimer()
    exit_timer.setInterval(100)
    exit_timer.timeout.connect(lambda: _poll_exit(main_window, exit_timer, handle_exit))
    exit_timer.start()

    try:
        qt_app.start_event_loop()
    except KeyboardInterrupt:
        handle_exit()
    finally:
        logger.info("Shutting down.")
        sys.exit(0)


def _poll_exit(main_window, timer: QTimer, handle_exit):
    if main_window.exit_event.is_set():
        timer.stop()
        handle_exit()


if __name__ == "__main__":
    main()
