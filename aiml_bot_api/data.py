"""
The backend data manager implementation. The DataManager class provides the
interface to the user and message data, ensuring consistency, persistence, and
thread safety.
"""

import datetime
import hashlib
import os
import shelve
import threading
from collections import deque

import aiml_bot


class ItemLock:
    """A lock for a single item in a lock set."""

    def __init__(self, lock_set: 'LockSet', item):
        self.lock_set = lock_set
        self.item = item

    def acquire(self):
        """Acquire the lock."""
        with self.lock_set.per_item_lock:
            while self.item in self.lock_set.locked_items:
                self.lock_set.item_unlocked.wait()
            self.lock_set.locked_items.add(self.item)

    def release(self):
        """Release the lock."""
        with self.lock_set.per_item_lock:
            self.lock_set.locked_items.remove(self.item)

    def __enter__(self):
        self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class LockSet:
    """A set of named resource locks."""

    def __init__(self):
        self.list_lock = threading.Lock()  # For updating the list itself
        self.per_item_lock = threading.Lock()  # For updating the list of locked items
        self.item_unlocked = threading.Condition(self.per_item_lock)
        self.locked_items = set()  # The list of currently locked items

    def acquire(self):
        """Acquire the entire set of locks."""
        self.list_lock.acquire()
        while self.locked_items:
            self.item_unlocked.wait()

    def release(self):
        """Release the entire set of locks."""
        self.list_lock.release()

    def __getitem__(self, item):
        return ItemLock(self, item)

    def __enter__(self):
        self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class DataManager:
    """The DataManager handles the storage of conversational data and
    triggering of the bot on behalf of the endpoints. It is designed to be
    thread-safe."""

    def __init__(self, bot: aiml_bot.Bot = None, data_folder: str = None):
        if data_folder is None:
            data_folder = os.path.expanduser('~/aiml_bot_api')
        if not os.path.isdir(data_folder):
            os.makedirs(data_folder)
        if not os.path.isdir(os.path.join(data_folder, 'messages')):
            os.makedirs(os.path.join(data_folder, 'messages'))

        self.data_folder = data_folder

        self.users = shelve.open(os.path.join(data_folder, 'users.db'))
        self.user_sessions = shelve.open(os.path.join(data_folder, 'user_sessions.db'))

        self.user_message_cache = {}
        self.user_message_lru = deque()
        self.max_cached_users = 1000

        self.user_locks = LockSet()
        self.message_locks = LockSet()
        self.sessions_lock = threading.Lock()
        self.bot_lock = threading.Lock()

        if bot is None:
            bot = aiml_bot.Bot(commands="load std aiml")
        self.bot = bot

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        """Close all resources held by the data manager in a clean and safe
        manner. Once this has been called, the data manager will no longer be
        in a usable state."""
        self.user_locks.acquire()
        self.message_locks.acquire()
        self.sessions_lock.acquire()
        self.bot_lock.acquire()

        self.users.close()
        self.user_sessions.close()
        for messages_db in self.user_message_cache.values():
            messages_db.close()

    def get_user_ids(self) -> list:
        """Return a list of user IDs."""
        with self.user_locks:
            return list(self.users)

    def add_user(self, user_id: str, user_name: str) -> None:
        """Add a new user. The user id must be new. Otherwise a KeyError is
        raised."""
        with self.user_locks, self.user_locks[user_id]:
            if user_id in self.users:
                raise KeyError(user_id)
            self.users[user_id] = {
                'id': user_id,
                'name': user_name,
            }

    def set_user_name(self, user_id: str, user_name: str) -> None:
        """Set the user's name to a new value. The user ID must already exist.
        If it does not, a KeyError is raised."""
        with self.user_locks[user_id]:
            # This has to be extracted, modified, and inserted as a unit; if
            # you operate directly on the user data without reassigning, e.g.
            # with `self.users[user_id]['name'] = user_name`, the changes
            # will not be written to disk and will be lost.
            user_data = self.users[user_id]
            user_data['name'] = user_name
            self.users[user_id] = user_data

    def get_user_data(self, user_id: str) -> dict:
        """Return the data associated with a given user ID. If no such user ID
        exists, raise a KeyError."""
        with self.user_locks[user_id]:
            return self.users[user_id]

    def _get_messages(self, user_id: str) -> dict:
        if user_id in self.user_message_cache:
            messages_db = self.user_message_cache[user_id]
            self.user_message_lru.remove(user_id)
        else:
            if len(self.user_message_cache) >= self.max_cached_users:
                lru = self.user_message_lru.popleft()
                self.user_message_cache.pop(lru).close()
                with self.bot_lock:
                    session_data = self.bot.get_session_data(lru)
                with self.sessions_lock:
                    self.user_sessions[lru] = session_data
                with self.bot_lock:
                    self.bot.delete_session(lru)
            messages_db = shelve.open(os.path.join(self.data_folder, 'messages', user_id + '.db'))
            with self.sessions_lock:
                session_data = self.user_sessions.get(user_id, {})
            with self.bot_lock:
                self.bot.set_session_data(session_data, user_id)
            self.user_message_lru.append(user_id)
        return messages_db

    def get_message_ids(self, user_id: str) -> list:
        """Return the list of message IDs for the given user."""
        with self.user_locks[user_id]:
            if user_id not in self.users:
                raise KeyError(user_id)
            with self.message_locks[user_id]:
                return list(self._get_messages(user_id))

    def add_message(self, user_id: str, content: str) -> (str, str):
        """Add a new incoming message from the user. The bot is given the
        immediate opportunity to respond, in which case the bot's response
        is also added. If the bot generates a response, a tuple (id1, id2)
        is returned, where id1 is the message ID of the user's message, and
        id2 is the message ID of the bot's reply. Otherwise, None is returned
        for the value of id2. If the user does not exist, a KeyError is raised.
        """
        timestamp = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S.%f')
        message_id = 'c' + hashlib.sha256(timestamp.encode()).hexdigest()
        with self.user_locks[user_id]:
            if user_id not in self.users:
                raise KeyError(user_id)
            with self.message_locks[user_id]:
                messages_db = self._get_messages(user_id)
                messages_db[message_id] = {
                    'id': message_id,
                    'origin': 'client',
                    'content': content,
                    'time': timestamp,
                }
            with self.bot_lock:
                response = self.bot.respond(content, user_id)
                session_data = self.bot.get_session_data(user_id)
            with self.sessions_lock:
                self.user_sessions[user_id] = session_data
            print("Response:", repr(response))
            if response:
                timestamp = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S.%f')
                response_id = 's' + hashlib.sha256(timestamp.encode()).hexdigest()
                response_data = {
                    'id': response_id,
                    'origin': 'server',
                    'content': response,
                    'time': timestamp,
                }
                with self.message_locks[user_id]:
                    messages_db[response_id] = response_data
            else:
                response_id = None
            return message_id, response_id

    def get_message_data(self, user_id: str, message_id: str) -> dict:
        """Return the data associated with a given message. If the user or
        message does not exist, a KeyError is raised."""
        with self.user_locks[user_id]:
            if user_id not in self.users:
                raise KeyError(user_id)
            with self.message_locks[user_id]:
                messages_db = self._get_messages(user_id)
                return messages_db[message_id]
