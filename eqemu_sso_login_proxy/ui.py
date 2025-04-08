import sys
import os
import time
from PyQt6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                             QHBoxLayout, QWidget, QPushButton, QSystemTrayIcon, 
                             QMenu, QFrame, QMessageBox, QProgressDialog)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QPixmap, QFont, QAction

# Global connection statistics
class ProxyStats(QObject):
    """Class to track and update proxy statistics"""
    stats_updated = pyqtSignal()
    user_connected = pyqtSignal(str)  # Signal for when a user connects
    
    def __init__(self):
        super().__init__()
        self.total_connections = 0
        self.active_connections = 0
        self.completed_connections = 0
        self.proxy_status = "Initializing..."
        self.listening_address = "0.0.0.0"
        self.listening_port = 0
        self.start_time = time.time()
    
    def update_status(self, status):
        """Update the proxy status"""
        self.proxy_status = status
        self.stats_updated.emit()
    
    def update_listening_info(self, address, port):
        """Update the listening address and port"""
        self.listening_address = address
        self.listening_port = port
        self.stats_updated.emit()
    
    def connection_started(self):
        """Increment connection counters when a new connection starts"""
        self.total_connections += 1
        self.active_connections += 1
        self.stats_updated.emit()
    
    def connection_completed(self):
        """Update counters when a connection completes"""
        self.active_connections = max(0, self.active_connections - 1)
        self.completed_connections += 1
        self.stats_updated.emit()
    
    def get_uptime(self):
        """Return uptime in human-readable format"""
        uptime_seconds = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def user_login(self, username):
        """Signal that a user has logged in"""
        self.user_connected.emit(username)

# Create a global stats instance
proxy_stats = ProxyStats()

class StatusLabel(QLabel):
    """Custom styled status label"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("font-weight: bold;")

class ValueLabel(QLabel):
    """Custom styled value label"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("color: #2c3e50;")

class ProxyUI(QMainWindow):
    """Main UI window for the proxy application"""
    # Signal to notify when application should exit
    exit_signal = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.setup_tray()
        
        # Update stats periodically
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)  # Update every second
        
        # Connect to user login signal
        proxy_stats.user_connected.connect(self.show_user_connected_notification)
        
        # Store updater reference
        self.updater = None
        self.update_progress_dialog = None
    
    def init_ui(self):
        self.setWindowTitle("EQEmu Login Proxy")
        self.setGeometry(100, 100, 400, 300)
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Add title
        title_label = QLabel("EQEmu Login Proxy")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #3498db; margin-bottom: 10px;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Add horizontal line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #bdc3c7; margin: 10px 0;")
        main_layout.addWidget(line)
        
        # Status
        status_layout = QHBoxLayout()
        status_label = StatusLabel("Status:")
        self.status_value = ValueLabel(proxy_stats.proxy_status)
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.status_value)
        status_layout.addStretch()
        main_layout.addLayout(status_layout)
        
        # Listening address
        address_layout = QHBoxLayout()
        address_label = StatusLabel("Listening on:")
        self.address_value = ValueLabel(f"{proxy_stats.listening_address}:{proxy_stats.listening_port}")
        address_layout.addWidget(address_label)
        address_layout.addWidget(self.address_value)
        address_layout.addStretch()
        main_layout.addLayout(address_layout)
        
        # Uptime
        uptime_layout = QHBoxLayout()
        uptime_label = StatusLabel("Uptime:")
        self.uptime_value = ValueLabel(proxy_stats.get_uptime())
        uptime_layout.addWidget(uptime_label)
        uptime_layout.addWidget(self.uptime_value)
        uptime_layout.addStretch()
        main_layout.addLayout(uptime_layout)
        
        # Add another horizontal line
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        line2.setStyleSheet("background-color: #bdc3c7; margin: 10px 0;")
        main_layout.addWidget(line2)
        
        # Connection statistics section title
        stats_title = QLabel("Connection Statistics")
        stats_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50; margin: 5px 0;")
        stats_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(stats_title)
        
        # Total connections
        total_layout = QHBoxLayout()
        total_label = StatusLabel("Total Connections:")
        self.total_value = ValueLabel(str(proxy_stats.total_connections))
        total_layout.addWidget(total_label)
        total_layout.addWidget(self.total_value)
        total_layout.addStretch()
        main_layout.addLayout(total_layout)
        
        # Active connections
        active_layout = QHBoxLayout()
        active_label = StatusLabel("Active Connections:")
        self.active_value = ValueLabel(str(proxy_stats.active_connections))
        active_layout.addWidget(active_label)
        active_layout.addWidget(self.active_value)
        active_layout.addStretch()
        main_layout.addLayout(active_layout)
        
        # Completed connections
        completed_layout = QHBoxLayout()
        completed_label = StatusLabel("Completed Connections:")
        self.completed_value = ValueLabel(str(proxy_stats.completed_connections))
        completed_layout.addWidget(completed_label)
        completed_layout.addWidget(self.completed_value)
        completed_layout.addStretch()
        main_layout.addLayout(completed_layout)
        
        # Add spacer
        main_layout.addStretch()
        
        # Minimize to tray button
        minimize_button = QPushButton("Minimize to Tray")
        minimize_button.clicked.connect(self.hide)
        main_layout.addWidget(minimize_button)
        
        # Connect stats update signal
        proxy_stats.stats_updated.connect(self.update_stats)
    
    def setup_tray(self):
        """Set up system tray icon and menu"""
        # Create a simple icon for the tray
        self.tray_icon = QSystemTrayIcon(self)
        
        # Try to use a custom icon if available, otherwise use a system icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon.png")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            # Use a system icon as fallback
            self.tray_icon.setIcon(QIcon.fromTheme("network-server"))
        
        # Create tray menu
        tray_menu = QMenu()
        
        # Add actions to the menu
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        
        check_update_action = QAction("Check for Updates", self)
        check_update_action.triggered.connect(self.check_for_updates)
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close_application)
        
        tray_menu.addAction(show_action)
        tray_menu.addAction(check_update_action)
        tray_menu.addSeparator()
        tray_menu.addAction(exit_action)
        
        # Set the menu for tray icon
        self.tray_icon.setContextMenu(tray_menu)
        
        # Show the tray icon
        self.tray_icon.show()
        
        # Connect activated signal (for double-click)
        self.tray_icon.activated.connect(self.tray_icon_activated)

    def tray_icon_activated(self, reason):
        """Handle tray icon activation (e.g., double-click)"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.activateWindow()
    
    def update_stats(self):
        """Update all statistics in the UI"""
        self.status_value.setText(proxy_stats.proxy_status)
        self.address_value.setText(f"{proxy_stats.listening_address}:{proxy_stats.listening_port}")
        self.uptime_value.setText(proxy_stats.get_uptime())
        self.total_value.setText(str(proxy_stats.total_connections))
        self.active_value.setText(str(proxy_stats.active_connections))
        self.completed_value.setText(str(proxy_stats.completed_connections))
        
        # Update tray tooltip with basic stats
        self.tray_icon.setToolTip(f"EQEmu Login Proxy\nStatus: {proxy_stats.proxy_status}\n"
                                 f"Connections: {proxy_stats.active_connections} active, "
                                 f"{proxy_stats.total_connections} total")
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Minimize to tray instead of closing
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "EQEmu Login Proxy",
            "Application is still running in the system tray.",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )
    
    def close_application(self):
        """Actually close the application"""
        # Hide the tray icon first to prevent it from lingering
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()
        
        # Emit signal to notify the main application to exit
        self.exit_signal.emit()
        
        # This will close the UI, but the main event loop needs to be stopped separately
        self.close()
    
    def show_user_connected_notification(self, username):
        """Show a tray notification when a user connects"""
        if hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "User Connected",
                f"User '{username}' has connected to the proxy.",
                QSystemTrayIcon.MessageIcon.Information,
                3000  # Show for 3 seconds
            )
    
    def check_for_updates(self):
        """Check for updates manually"""
        from eqemu_sso_login_proxy.updater import Updater
        
        # Create updater if not already created
        if not self.updater:
            self.updater = Updater()
            self.updater.update_available.connect(self.on_update_available)
            self.updater.update_progress.connect(self.on_update_progress)
            self.updater.update_complete.connect(self.on_update_complete)
        
        # Create progress dialog
        self.update_progress_dialog = QProgressDialog("Checking for updates...", "Cancel", 0, 100, self)
        self.update_progress_dialog.setWindowTitle("Update Check")
        self.update_progress_dialog.setAutoClose(False)
        self.update_progress_dialog.setAutoReset(False)
        self.update_progress_dialog.canceled.connect(self.cancel_update)
        self.update_progress_dialog.show()
        
        # Check for updates
        QApplication.processEvents()
        has_update = self.updater.check_for_updates()
        
        if not has_update and self.update_progress_dialog:
            self.update_progress_dialog.close()
            self.update_progress_dialog = None
            QMessageBox.information(self, "Update Check", "Your application is up to date.")
    
    def on_update_available(self, current_version, new_version):
        """Handle when an update is available"""
        if self.update_progress_dialog:
            self.update_progress_dialog.close()
            self.update_progress_dialog = None
        
        # Ask user if they want to update
        response = QMessageBox.question(
            self,
            "Update Available",
            f"A new version is available: {new_version}\n"
            f"Current version: {current_version}\n\n"
            "Would you like to update now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if response == QMessageBox.StandardButton.Yes:
            # Create progress dialog for update
            self.update_progress_dialog = QProgressDialog("Preparing to update...", "Cancel", 0, 100, self)
            self.update_progress_dialog.setWindowTitle("Updating")
            self.update_progress_dialog.setAutoClose(False)
            self.update_progress_dialog.setAutoReset(False)
            self.update_progress_dialog.canceled.connect(self.cancel_update)
            self.update_progress_dialog.show()
            
            # Start update in background
            QApplication.processEvents()
            self.updater.perform_update(new_version)
    
    def on_update_progress(self, message, progress):
        """Handle update progress updates"""
        if self.update_progress_dialog:
            self.update_progress_dialog.setLabelText(message)
            self.update_progress_dialog.setValue(progress)
            QApplication.processEvents()
    
    def on_update_complete(self, success, message):
        """Handle update completion"""
        if self.update_progress_dialog:
            self.update_progress_dialog.close()
            self.update_progress_dialog = None
        
        if success:
            # Ask user if they want to restart
            response = QMessageBox.question(
                self,
                "Update Complete",
                f"{message}\n\nRestart application now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if response == QMessageBox.StandardButton.Yes:
                self.updater.restart_application()
        else:
            # Show error message
            QMessageBox.critical(self, "Update Failed", message)
    
    def cancel_update(self):
        """Cancel the update process"""
        self.update_progress_dialog = None
        QMessageBox.information(self, "Update Cancelled", "The update process has been cancelled.")

def create_tray_icon():
    """Create a simple tray icon image"""
    from PIL import Image, ImageDraw
    
    # Create a new image with a transparent background
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Draw a simple network icon
    margin = 8
    draw.rectangle((margin, margin, size - margin, size - margin), outline=(52, 152, 219), width=2)
    draw.line((margin, margin, size - margin, size - margin), fill=(52, 152, 219), width=2)
    draw.line((size - margin, margin, margin, size - margin), fill=(52, 152, 219), width=2)
    
    # Save the image
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon.png")
    image.save(icon_path)
    return icon_path

def start_ui():
    """Initialize and start the UI"""
    # Create the tray icon if it doesn't exist
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_icon.png")
    if not os.path.exists(icon_path):
        create_tray_icon()
    
    # Create the Qt application
    app = QApplication(sys.argv)
    
    # Create and show the main window
    main_window = ProxyUI()
    main_window.show()
    
    return app, main_window
