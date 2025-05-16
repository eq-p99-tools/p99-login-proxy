import time
import wx

# Define custom event IDs
EVT_STATS_UPDATED = wx.NewEventType()
EVT_USER_CONNECTED = wx.NewEventType()

# Create event binder objects
EVT_STATS_UPDATED_BINDER = wx.PyEventBinder(EVT_STATS_UPDATED, 1)
EVT_USER_CONNECTED_BINDER = wx.PyEventBinder(EVT_USER_CONNECTED, 1)

# Custom event classes
class StatsUpdatedEvent(wx.PyCommandEvent):
    def __init__(self, etype, eid):
        wx.PyCommandEvent.__init__(self, etype, eid)

class UserConnectedEvent(wx.PyCommandEvent):
    def __init__(self, etype, eid, username=""):
        wx.PyCommandEvent.__init__(self, etype, eid)
        self._username = username
        
    def GetUsername(self):
        return self._username

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
    
    def notify_user_connected(self, username):
        """Notify all listeners that a user has connected"""
        for listener in self.listeners:
            evt = UserConnectedEvent(EVT_USER_CONNECTED, listener.GetId(), username)
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

    def user_login(self, username):
        """Signal that a user has logged in"""
        self.notify_user_connected(username)
