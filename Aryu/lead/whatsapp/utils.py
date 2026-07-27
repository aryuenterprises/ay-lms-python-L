# whatsapp/utils.py
from collections import OrderedDict
import threading

class BoundedLRUCache:
    """
    Thread-safe LRU cache for O(1) lookup and insertion.
    Prevents processing duplicate Meta webhook message IDs.
    """
    def __init__(self, capacity: int = 10000):
        self.cache = OrderedDict()
        self.capacity = capacity
        self.lock = threading.Lock()

    def contains_and_add(self, key: str) -> bool:
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return True
            self.cache[key] = True
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
            return False

# Instantiate it here so it acts as a singleton for the worker process
message_deduplicator = BoundedLRUCache(capacity=50000)

