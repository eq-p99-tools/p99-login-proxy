import asyncio
import sys
import threading

import wx

from p99_sso_login_proxy import server, ui, updater, sso_api

# Class to integrate wxPython with asyncio
class WxAsyncApp(wx.App):
    def __init__(self):
        super().__init__(False)
        self.loop = asyncio.get_event_loop()
        self.running = False
        self.transport = None
        self.exit_event = threading.Event()
    
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
        # Start the proxy server\
        self.proxy_task = asyncio.create_task(server.main())

        # Wait for the exit event to be set
        while not self.exit_event.is_set():
            await asyncio.sleep(0.1)
            try:
                if self.transport is None and self.proxy_task.done():
                    self.transport = self.proxy_task.result()
            except Exception as e:
                print(f"Failed to start UDP proxy: {e}")
                ui.error("Failed to start UDP proxy, check if another instance is running, and restart.")
                self.stop_event_loop()
        
        # Cancel the proxy task
        self.proxy_task.cancel()
    
    def on_power_resume(self, event):
        """Handle power resume event"""
        wx.CallAfter(self.restart_proxy_server)

    def restart_proxy_server(self):
        """Restart the proxy server"""
        print("System resume event detected. Restarting proxy server...")

        if self.transport:
            self.transport.close()
        print("Existing transport shutdown.")

        self.proxy_task = self.loop.create_task(server.main())
        self.transport = None
        print("New transport started.")

    def stop_event_loop(self):
        """Stop the event loop"""
        print("[RUN SERVER] Stopping event loop in WxAsyncApp")
        self.exit_event.set()
        self.ExitMainLoop()

def main():
    # Create the wxPython application with asyncio integration
    wx_app = WxAsyncApp()

    def start_eq(eq_dir):
        print("Starting EverQuest...")
        import subprocess
        subprocess.Popen(
            ["powershell.exe", "-Command", "& { Start-Process eqgame.exe -ArgumentList @('patchme') -Verb RunAs }"],
            cwd=eq_dir, start_new_session=True, shell=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    
    # Initialize the UI
    main_window = ui.start_ui()
    main_window.start_eq_func = start_eq
    
    # Check for updates on startup
    try:
        updater.check_update()
    except Exception as e:
        print(f"[RUN SERVER] Failed to check for updates: {e}")
    
    # Fetch user accounts if API token is available
    try:
        sso_api.fetch_user_accounts()
    except Exception as e:
        print(f"[RUN SERVER] Failed to fetch user accounts: {e}")
    
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
        print("Shutting down.")
        sys.exit(0)

if __name__ == '__main__':
    main()
