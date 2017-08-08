from collections import deque

import datetime
import hashlib
import json
import logging
import os
import shelve
import threading

from flask import Flask, request

import aiml


log = logging.getLogger(__name__)


app = Flask(__name__)


"""
root {
    user {
        name
        message {
            id
            origin (client, server)
            content
            time
        }
    }
}
"""


class ItemLock:

    def __init__(self, lock_set: 'LockSet', item):
        self.lock_set = lock_set
        self.item = item

    def acquire(self):
        with self.lock_set.per_item_lock:
            while self.item in self.lock_set.locked_items:
                self.lock_set.item_unlocked.wait()
            self.lock_set.locked_items.add(self.item)

    def release(self):
        with self.lock_set.per_item_lock:
            self.lock_set.locked_items.remove(self.item)

    def __enter__(self):
        self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class LockSet:

    def __init__(self):
        self.list_lock = threading.Lock()  # For updating the list itself
        self.per_item_lock = threading.Lock()  # For updating the list of locked items
        self.item_unlocked = threading.Condition(self.per_item_lock)
        self.locked_items = set()  # The list of currently locked items

    def acquire(self):
        self.list_lock.acquire()
        while self.locked_items:
            self.item_unlocked.wait()

    def release(self):
        self.list_lock.release()

    def __getitem__(self, item):
        return ItemLock(self, item)

    def __enter__(self):
        self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class DataManager:

    def __init__(self, learn, base_folder=None):
        if isinstance(learn, str):
            learn = [learn]

        if base_folder is None:
            base_folder = os.path.expanduser('~/pyaiml_api')
        if not os.path.isdir(base_folder):
            os.makedirs(base_folder)

        self.base_folder = base_folder

        self.users = shelve.open(os.path.join(base_folder, 'users.db'))
        self.user_sessions = shelve.open(os.path.join(base_folder, 'user_sessions.db'))

        self.user_message_cache = {}
        self.user_message_lru = deque()
        self.max_cached_users = 1000

        self.user_locks = LockSet()
        self.message_locks = LockSet()
        self.sessions_lock = threading.Lock()
        self.kernel_lock = threading.Lock()

        self.kernel = aiml.Kernel()
        for item in learn:
            self.kernel.learn(item)
        self.kernel.respond('load aiml b')

    def close(self):
        self.user_locks.acquire()
        self.message_locks.acquire()
        self.sessions_lock.acquire()
        self.kernel_lock.acquire()

        self.users.close()
        self.user_sessions.close()
        for messages in self.user_message_cache.values():
            messages.close()

    def get_user_names(self):
        with self.user_locks:
            return list(self.users)

    def add_user(self, user_name, data, post=False):
        with self.user_locks:
            if post and user_name in self.users:
                raise KeyError(user_name)
            with self.user_locks[user_name]:
                self.users[user_name] = data

    def get_user_data(self, user_name):
        with self.user_locks[user_name]:
            return self.users[user_name]

    def _get_messages(self, user_name):
        if user_name in self.user_message_cache:
            messages = self.user_message_cache[user_name]
            self.user_message_lru.remove(user_name)
        else:
            if len(self.user_message_cache) >= self.max_cached_users:
                lru = self.user_message_lru.popleft()
                self.user_message_cache.pop(lru).close()
                with self.kernel_lock:
                    session_data = self.kernel.getSessionData(lru)
                with self.sessions_lock:
                    self.user_sessions[lru] = session_data
                with self.kernel_lock:
                    self.kernel.deleteSession(lru)
            messages = shelve.open(os.path.join(self.base_folder, 'users', user_name + '.db'))
            with self.sessions_lock:
                session_data = self.user_sessions.get(user_name, {})
            with self.kernel_lock:
                self.kernel.setSessionData(session_data, user_name)
            self.user_message_lru.append(user_name)
        return messages

    def get_message_ids(self, user_name):
        with self.user_locks[user_name]:
            if user_name not in self.users:
                raise KeyError(user_name)
            with self.message_locks[user_name]:
                return list(self._get_messages(user_name))

    def add_message(self, user_name, content):
        timestamp = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S.%f')
        message_id = 'c' + hashlib.sha256(timestamp.encode()).hexdigest()
        with self.user_locks[user_name]:
            if user_name not in self.users:
                raise KeyError(user_name)
            with self.message_locks[user_name]:
                messages = self._get_messages(user_name)
                messages[message_id] = {
                    'id': message_id,
                    'origin': 'client',
                    'content': content,
                    'timestamp': timestamp,
                }
            with self.kernel_lock:
                response = self.kernel.respond(content, user_name)
                session_data = self.kernel.getSessionData(user_name)
            with self.sessions_lock:
                self.user_sessions[user_name] = session_data
            if response:
                timestamp = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S.%f')
                message_id = 's' + hashlib.sha256(timestamp.encode()).hexdigest()
                message_data = {
                    'id': message_id,
                    'origin': 'server',
                    'content': response,
                    'time': timestamp,
                }
                with self.message_locks[user_name]:
                    messages[message_id] = message_data
                return message_id

    def get_message_data(self, user_name, message_id):
        with self.user_locks[user_name]:
            if user_name not in self.users:
                raise KeyError(user_name)
            with self.message_locks[user_name]:
                messages = self._get_messages(user_name)
                return messages[message_id]


# TODO: Make the std-startup.xml path dynamic.
data_manager = DataManager('../pyaiml/std-startup.xml')


@app.route('/user/', methods=['GET', 'POST', 'PUT'])
def users():
    if request.method == 'GET':
        try:
            user_names = data_manager.get_user_names()
        except Exception:
            log.error("Error in users() (GET):")
            return json.dumps({'type': 'error', 'value': 'Server-side error.'})
        else:
            return json.dumps({'type': 'user_list', 'value': user_names})
    else:
        assert request.method in ('POST', 'PUT')
        user_data = request.get_json()
        if 'name' not in user_data or len(user_data) > 1:
            return json.dumps({'type': 'error', 'value': 'Malformed request.'})
        user_name = user_data['name']
        try:
            data_manager.add_user(user_name, user_data, post=(request.method == 'POST'))
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User name already exists.'})
        except Exception:
            log.error("Error in users() (%s):" % request.method)
            return json.dumps({'type': 'error', 'value': 'Server-side error.'})
        else:
            return json.dumps({'type': 'created', 'value': 'user'})


@app.route('/user/<user_name>')
def user(user_name):
    try:
        user_data = data_manager.get_user_data(user_name)
    except KeyError:
        return json.dumps({'type': 'error', 'value': 'User not found.'})
    except Exception:
        log.error("Error in user(%r) (GET):" % user_name)
        return json.dumps({'type': 'error', 'value': 'Server-side error.'})
    else:
        return json.dumps({'type': 'user', 'value': user_data})


@app.route('/user/<user_name>/message/', methods=['GET', 'POST'])
def messages(user_name):
    if request.method == 'GET':
        try:
            message_ids = data_manager.get_message_ids(user_name)
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User not found.'})
        except Exception:
            log.error("Error in messages(%r) (GET):" % user_name)
            return json.dumps({'type': 'error', 'value': 'Server-side error.'})
        else:
            return json.dumps({'type': 'message_list', 'value': message_ids})
    else:
        assert request.method == 'POST'
        message_data = request.get_json()
        if not (isinstance(message_data, dict) and message_data.get('origin', 'client') == 'client' and
                'content' in message_data and message_data - {'origin', 'content'}):
            return json.dumps({'type': 'error', 'value': 'Malformed request.'})
        content = message_data['content']
        if not isinstance(content, str):
            return json.dumps({'type': 'error', 'value': 'Malformed request.'})
        content = content.strip()
        if not content:
            return json.dumps({'type': 'error', 'value': 'Empty message content.'})

        try:
            response_id = data_manager.add_message(user_name, content)
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User not found.'})
        except Exception:
            log.error("Error in messages(%r) (%s):" % (user_name, request.method))
            return json.dumps({'type': 'error', 'value': 'Server-side error.'})

        if response_id is None:
            return json.dumps({'type': 'message', 'value': None})
        else:
            try:
                message_data = data_manager.get_message_data(user_name, response_id)
            except Exception:
                log.error("Error in messages(%r) (%s):" % (user_name, request.method))
                return json.dumps({'type': 'error', 'value': 'Server-side error.'})
            else:
                return json.dumps({'type': 'message', 'value': message_data})


@app.route('/user/<user_name>/message/<message_id>')
def message(user_name, message_id):
    try:
        message_data = data_manager.get_message_data(user_name, message_id)
    except KeyError:
        return json.dumps({'type': 'error', 'value': 'Message not found.'})
    except Exception:
        log.error("Error in message(%r, %r) (GET):" % (user_name, message_id))
        return json.dumps({'type': 'error', 'value': 'Server-side error.'})
    else:
        return json.dumps({'type': 'message', 'value': message_data})
