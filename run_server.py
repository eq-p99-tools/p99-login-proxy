import asyncio
import sys
import wx
import threading

from eqemu_sso_login_proxy import server
from eqemu_sso_login_proxy.ui import start_ui
from eqemu_sso_login_proxy.updater import check_for_updates_on_startup

# Class to integrate wxPython with asyncio
class WxAsyncApp(wx.App):
    def __init__(self):
        super().__init__(False)
        self.loop = asyncio.get_event_loop()
        self.running = False
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
        # Start the proxy server
        proxy_task = asyncio.create_task(server.main())
        
        # Wait for the exit event to be set
        while not self.exit_event.is_set():
            await asyncio.sleep(0.1)
        
        # Cancel the proxy task
        proxy_task.cancel()
    
    def stop_event_loop(self):
        """Stop the event loop"""
        self.exit_event.set()
        self.ExitMainLoop()

if __name__ == '__main__':
    # Create the wxPython application with asyncio integration
    wx_app = WxAsyncApp()
    
    # Initialize the UI
    app, main_window = start_ui()
    
    # Check for updates on startup
    updater = check_for_updates_on_startup(main_window)
    
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
    
    try:
        # Start the event loop
        wx_app.start_event_loop()
    except KeyboardInterrupt:
        handle_exit()
    finally:
        print("Shutting down.")
        sys.exit(0)
