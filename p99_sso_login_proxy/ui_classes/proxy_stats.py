import time

from PySide6.QtCore import QObject, Signal


class ProxyStats(QObject):
    """Track proxy connection statistics; emits Qt signals for UI updates (thread-safe)."""

    stats_updated = Signal()
    user_connected = Signal(str, str, str)  # alias, account, method
    login_auth_rejected = Signal(str, str)  # username, detail

    def __init__(self, parent=None):
        super().__init__(parent)
        self.total_connections = 0
        self.active_connections = 0
        self.completed_connections = 0
        self.proxy_status = "Initializing..."
        self.listening_address = "0.0.0.0"
        self.listening_port = 0
        self.start_time = time.time()

    def reset_uptime(self):
        """Reset the start time for uptime calculation"""
        self.start_time = time.time()

    def notify_stats_updated(self):
        """Notify that stats have been updated"""
        self.stats_updated.emit()

    def notify_user_connected(self, alias, account, method):
        """Notify that a user has connected"""
        self.user_connected.emit(alias, account, method)

    def update_status(self, status):
        """Update the proxy status"""
        self.proxy_status = status
        self.notify_stats_updated()

    def update_listening_info(self, address, port):
        """Update the listening address and port"""
        self.listening_address = address
        self.listening_port = port
        self.notify_stats_updated()

    def connection_started(self):
        """Increment connection counters when a new connection starts"""
        self.total_connections += 1
        self.active_connections += 1
        self.notify_stats_updated()

    def connection_completed(self):
        """Update counters when a connection completes"""
        self.active_connections = max(0, self.active_connections - 1)
        self.completed_connections += 1
        self.notify_stats_updated()

    def get_uptime(self):
        """Return uptime in human-readable format"""
        uptime_seconds = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def user_login(self, alias, account, method):
        """Signal that a user has logged in.

        alias:   what the user typed in the EQ login screen
        account: the effective account name sent to the login server
        method:  one of "sso", "local", "proxy_only", "skip_sso", "passthrough"
        """
        self.notify_user_connected(alias, account, method)

    def notify_auth_error(self, username, detail):
        """Notify all listeners of a server-rejected auth attempt."""
        self.login_auth_rejected.emit(username, detail)

    def auth_error(self, username, detail):
        """Signal that the server rejected a login attempt with a reason."""
        self.notify_auth_error(username, detail)
