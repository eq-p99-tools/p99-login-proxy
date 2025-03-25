import asyncio
import sys
from PyQt5.QtWidgets import QApplication

from eqemu_sso_login_proxy import server
from eqemu_sso_login_proxy.ui import start_ui

if __name__ == '__main__':
    # Initialize the Qt application
    app, main_window = start_ui()
    
    # Set up the event loop
    loop = asyncio.get_event_loop()
    
    # Start the proxy server
    proxy_task = loop.create_task(server.main())
    
    # Set up a custom event loop integration for Qt
    def process_events():
        app.processEvents()
        loop.call_later(0.01, process_events)  # Schedule next processing
    
    # Start processing events
    process_events_task = loop.call_soon(process_events)
    
    # Connect the exit signal to stop the event loop
    def handle_exit():
        # Cancel all running tasks
        proxy_task.cancel()
        
        # Stop the event loop
        loop.stop()
        
        # Schedule the application to quit after event loop stops
        app.quit()
    
    # Connect the exit signal from the UI to our exit handler
    main_window.exit_signal.connect(handle_exit)
    
    try:
        # Run both the asyncio event loop and Qt event loop
        loop.run_forever()
    except KeyboardInterrupt:
        handle_exit()
    finally:
        print("Shutting down.")
        # Clean up the event loop
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        
        # Close the loop and exit
        loop.close()
        sys.exit(0)
