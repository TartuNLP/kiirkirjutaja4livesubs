# Modified from https://stackoverflow.com/a/70603488
from threading import Lock


class Stream:
    def __init__(self, starting_data):
        self.starting_data = starting_data
        self.buffer = starting_data
        self.lock = Lock()

    def read(self, n=None):
        with self.lock:
            chunk = self.buffer[:n]
            if n is None:
                self.buffer = self.starting_data
            else:
                self.buffer = self.buffer[n:]
        return chunk

    def write(self, data):
        with self.lock:
            self.buffer += data
