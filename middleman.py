import threading
import time
import logging

from connection import Connection

LOGGER = logging.getLogger(__name__)


class LoginMiddlemand:
    def __init__(self, host="0.0.0.0", port=5998):
        self.connection = None
        self.thread = None
        self.running: bool = False
        self.connection_lock: threading.Lock = threading.Lock()
        self.host: str = host
        self.port: int = port

    def stop_listening(self):
        try:
            self.running = False
            if self.connection:
                self.stop_listening()
            if self.thread:
                self.thread.join()
            self.thread = None
            self.connection = None
        except Exception as ex:
            LOGGER.exception(str(ex), "LoginMiddleMand", None)

    def start_listening(self) -> None:
        try:
            with self.connection_lock:
                if self.running:
                    return
                self.running = True

            if self.connection:
                self.connection.dispose()
            if self.thread:
                self.thread.join()
            self.connection = Connection()
            self.thread = threading.Thread(target=self.listen_for_connections)
            self.thread.start()
        except Exception as ex:
            LOGGER.exception(ex)
            self.stop_listening()

    def listen(self):
        try:
            self.connection.open(self.port)
        except Exception as ex:
            LOGGER.exception(ex)
            return False
        return True

    def listen_for_connections(self) -> None:
        if not self.listen():
            return
        print("Starting ListenForConnections")
        try:
            inner_keep_running = True
            while inner_keep_running:
                try:
                    inner_keep_running = self.connection.connection_read()
                except Exception as e:
                    self.connection.dispose()
                    self.connection = Connection()
                    if not self.listen():
                        print("Exit ListenForConnections")
                        return
                    inner_keep_running = True
                    time.sleep(1)
                    LOGGER.exception(e)
                if not self.running:
                    print("Exit ListenForConnections")
                    return
                elif not inner_keep_running:
                    self.connection.dispose()
                    self.connection = Connection()
                    if not self.listen():
                        print("Exit ListenForConnections")
                        return
                    inner_keep_running = True
                    time.sleep(1)
        except Exception as ex:
            LOGGER.exception(ex)
        print("Exit ListenForConnections")


if __name__ == "__main__":
    middleman = LoginMiddlemand()
    middleman.start_listening()
    # time.sleep(60)
    # middleman.stop_listening()
