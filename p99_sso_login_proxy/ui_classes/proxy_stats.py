import time

import wx

# Define custom event IDs
EVT_STATS_UPDATED = wx.NewEventType()
EVT_USER_CONNECTED = wx.NewEventType()
EVT_AUTH_ERROR = wx.NewEventType()

# Create event binder objects
EVT_STATS_UPDATED_BINDER = wx.PyEventBinder(EVT_STATS_UPDATED, 1)
EVT_USER_CONNECTED_BINDER = wx.PyEventBinder(EVT_USER_CONNECTED, 1)
EVT_AUTH_ERROR_BINDER = wx.PyEventBinder(EVT_AUTH_ERROR, 1)


# Custom event classes
class StatsUpdatedEvent(wx.PyCommandEvent):
    def __init__(self, etype, eid):
        wx.PyCommandEvent.__init__(self, etype, eid)


class UserConnectedEvent(wx.PyCommandEvent):
    def __init__(self, etype, eid, alias="", account="", method=""):
        wx.PyCommandEvent.__init__(self, etype, eid)
        self._alias = alias
        self._account = account
        self._method = method

    def GetAlias(self):
        return self._alias

    def GetAccount(self):
        return self._account

    def GetMethod(self):
        return self._method


class AuthErrorEvent(wx.PyCommandEvent):
    def __init__(self, etype, eid, username="", detail=""):
        wx.PyCommandEvent.__init__(self, etype, eid)
        self._username = username
        self._detail = detail

    def GetUsername(self):
        return self._username

    def GetDetail(self):
        return self._detail


# Global connection statistics
class ProxyStats:
    """Class to track and update proxy statistics"""

    def __init__(self):
        self.total_connections = 0
        self.active_connections = 0
        self.completed_connections = 0
        self.proxy_status = "Initializing..."
        self.listening_address = "0.0.0.0"
        self.listening_port = 0
        self.start_time = time.time()
        self.listeners = []

    def reset_uptime(self):
        """Reset the start time for uptime calculation"""
        self.start_time = time.time()

    def add_listener(self, listener):
        """Add a listener for events"""
        if listener not in self.listeners:
            self.listeners.append(listener)

    def remove_listener(self, listener):
        """Remove a listener"""
        if listener in self.listeners:
            self.listeners.remove(listener)

    def notify_stats_updated(self):
        """Notify all listeners that stats have been updated"""
        for listener in self.listeners:
            evt = StatsUpdatedEvent(EVT_STATS_UPDATED, listener.GetId())
            wx.PostEvent(listener, evt)

    def notify_user_connected(self, alias, account, method):
        """Notify all listeners that a user has connected"""
        for listener in self.listeners:
            evt = UserConnectedEvent(EVT_USER_CONNECTED, listener.GetId(), alias, account, method)
            wx.PostEvent(listener, evt)

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
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
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
        for listener in self.listeners:
            evt = AuthErrorEvent(EVT_AUTH_ERROR, listener.GetId(), username, detail)
            wx.PostEvent(listener, evt)

    def auth_error(self, username, detail):
        """Signal that the server rejected a login attempt with a reason."""
        self.notify_auth_error(username, detail)
