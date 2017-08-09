# http://blog.luisrei.com/articles/flaskrest.html
# https://www.digitalocean.com/community/tutorials/how-to-structure-large-flask-applications
# https://realpython.com/blog/python/api-integration-in-python/
# https://yacine.org/2016/10/17/10-minutes-to-a-custom-graphql-backend/

# Also, consider converting the AIML to something a little more palatable, or at least using a simpler XML parsing
# library like those described here: http://docs.python-guide.org/en/latest/scenarios/xml/. It should be really easy
# to convert to JSON or YAML.


from collections import deque
from functools import wraps

import datetime
import hashlib
import json
import logging
import os
import re
import shelve
import threading

from flask import Flask, request, Response
import graphene
from graphene import resolve_only_args
import flask_graphql


import aiml


log = logging.getLogger(__name__)


app = Flask(__name__)


"""
root {
    user {
        id
        name
        message {
            id
            origin (client, server)
            content
            time
        }
    }
}


For any request, an error may be returned rather than the expected result.
Errors will be formatted as:

    {
        "type": "error",
        "value": "<error description>"
    } 


### GET /user/

Return a list of user IDs.

Output:

    {
        "type": "user_list",
        "value": [
            "<user id>",
            "<user id>",
            ...
        ]
    }

### POST /user/

Create a new user.

Input:

    {
        "name": "<user name>"
    }

Output:

    {
        "type": "user_created",
        "value": "<user id>" 
    }


### GET /user/<user id>/

Get a specific user's information.

Output:

    {
        "type": "user",
        "value": {
            "name": "<user name>",
            "id": "<user id>"
        }
    }


### GET /user/<user id>/message/

Get a list of the messages to/from a user.

Output:

    {
        "type": "message_list",
        "value": [
            "<message id>",
            "<message id>",
            ...
        ]
    }
    
    
### POST /user/<user id>/message/

Create a new message.

Input:

    {
        "content": "<message content>"
    }
    
Output:
    
    {
        "type": "message_received",
        "id": "<message id>",
        "response_id": "<response id>" 
    }
    
Note that the response ID may be null if the system did not generate a reply.


### GET /user/<user id>/message/<message id>/

Get a specific message's information.

Output:

    {
        "type": "message",
        "value": {
            "id": "<message id>",
            "origin": "<origin>",
            "time": "<timestamp>",
            "content": "<message content>"
        }
    }

Notes:

* The origin will be either "client" or "server".
* The timestamp will be a string formatted as "%Y%m%d%H%M%S.%f".
"""


def json_only(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        print(request.headers)
        if request.method in ('POST', 'PUT') and request.headers['Content-Type'] != 'application/json':
            return Response('Unsupported Media Type: %s' % request.headers['Content-Type'], status=415)
        else:
            raw_result = func(*args, **kwargs)
            return Response(raw_result, content_type='application/json; charset=utf-8')
    return wrapped


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
        if not os.path.isdir(os.path.join(base_folder, 'messages')):
            os.makedirs(os.path.join(base_folder, 'messages'))

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

        load_folder = os.path.dirname(learn[0])
        for item in learn:
            self.kernel.learn(item)

        cwd = os.getcwd()
        try:
            os.chdir(load_folder)
            self.kernel.respond('load aiml b')
        finally:
            os.chdir(cwd)

    def __del__(self):
        self.close()

    def close(self):
        self.user_locks.acquire()
        self.message_locks.acquire()
        self.sessions_lock.acquire()
        self.kernel_lock.acquire()

        self.users.close()
        self.user_sessions.close()
        for messages_db in self.user_message_cache.values():
            messages_db.close()

    def get_user_ids(self):
        with self.user_locks:
            return list(self.users)

    def add_user(self, user_name, post=False):
        user_id = hashlib.sha256(user_name.encode()).hexdigest()
        with self.user_locks:
            if post and user_id in self.users:
                raise KeyError(user_id)
            with self.user_locks[user_id]:
                self.users[user_id] = {
                    'name': user_name,
                    'id': user_id
                }
        return user_id

    def get_user_data(self, user_id):
        with self.user_locks[user_id]:
            return self.users[user_id]

    def _get_messages(self, user_id):
        if user_id in self.user_message_cache:
            messages_db = self.user_message_cache[user_id]
            self.user_message_lru.remove(user_id)
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
            messages_db = shelve.open(os.path.join(self.base_folder, 'messages', user_id + '.db'))
            with self.sessions_lock:
                session_data = self.user_sessions.get(user_id, {})
            with self.kernel_lock:
                self.kernel.setSessionData(session_data, user_id)
            self.user_message_lru.append(user_id)
        return messages_db

    def get_message_ids(self, user_id):
        with self.user_locks[user_id]:
            if user_id not in self.users:
                raise KeyError(user_id)
            with self.message_locks[user_id]:
                return list(self._get_messages(user_id))

    def add_message(self, user_id, content):
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
            with self.kernel_lock:
                response = self.kernel.respond(content, user_id)
                session_data = self.kernel.getSessionData(user_id)
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

    def get_message_data(self, user_id, message_id):
        with self.user_locks[user_id]:
            if user_id not in self.users:
                raise KeyError(user_id)
            with self.message_locks[user_id]:
                messages_db = self._get_messages(user_id)
                return messages_db[message_id]


# TODO: Make the std-startup.xml path dynamic.
xml_path = '../pyaiml/std-startup.xml'
data_manager = DataManager(xml_path)
print(len(data_manager.get_user_ids()))
for user_id in data_manager.get_user_ids():
    print(user_id, data_manager.get_user_data(user_id)['name'])


@app.route('/user/', methods=['GET', 'POST'])
@json_only
def users():
    if request.method == 'GET':
        try:
            user_ids = data_manager.get_user_ids()
        except Exception:
            log.error("Error in users() (GET):")
            return json.dumps({'type': 'error', 'value': 'Server-side error.'})
        else:
            return json.dumps({'type': 'user_list', 'value': user_ids})
    else:
        assert request.method == 'POST'
        user_data = request.get_json()
        if not isinstance(user_data, dict) or 'name' not in user_data or len(user_data) > 1:
            return json.dumps({'type': 'error', 'value': 'Malformed request.'})
        user_name = user_data['name']
        try:
            user_id = data_manager.add_user(user_name, post=True)
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User name already exists.'})
        except Exception:
            log.exception("Error in users() (%s):" % request.method)
            return json.dumps({'type': 'error', 'value': 'Server-side error.'})
        else:
            return json.dumps({'type': 'user_created', 'id': user_id})


@app.route('/user/<user_id>/')
@json_only
def user(user_id):
    try:
        user_data = data_manager.get_user_data(user_id)
    except KeyError:
        return json.dumps({'type': 'error', 'value': 'User not found.'})
    except Exception:
        log.exception("Error in user() (GET):")
        return json.dumps({'type': 'error', 'value': 'Server-side error.'})
    else:
        return json.dumps({'type': 'user', 'value': user_data})


@app.route('/user/<user_id>/message/', methods=['GET', 'POST'])
@json_only
def messages(user_id):
    if request.method == 'GET':
        try:
            message_ids = data_manager.get_message_ids(user_id)
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User not found.'})
        except Exception:
            log.exception("Error in messages(%r) (GET):" % user_id)
            return json.dumps({'type': 'error', 'value': 'Server-side error.'})
        else:
            return json.dumps({'type': 'message_list', 'value': message_ids})
    else:
        assert request.method == 'POST'
        message_data = request.get_json()
        if not (isinstance(message_data, dict) and message_data.get('origin', 'client') == 'client' and
                'content' in message_data and not message_data.keys() - {'origin', 'content'}):
            return json.dumps({'type': 'error', 'value': 'Malformed request.'})
        content = message_data['content']
        if not isinstance(content, str):
            return json.dumps({'type': 'error', 'value': 'Malformed request.'})
        content = content.strip()
        if not content:
            return json.dumps({'type': 'error', 'value': 'Empty message content.'})

        try:
            message_id, response_id = data_manager.add_message(user_id, content)
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User not found.'})
        except Exception:
            log.exception("Error in messages(%r) (%s):" % (user_id, request.method))
            return json.dumps({'type': 'error', 'value': 'Server-side error.'})

        return json.dumps({'type': 'message_received', 'id': message_id, 'response_id': response_id})


@app.route('/user/<user_id>/message/<message_id>/')
@json_only
def message(user_id, message_id):
    try:
        message_data = data_manager.get_message_data(user_id, message_id)
    except KeyError:
        return json.dumps({'type': 'error', 'value': 'Message not found.'})
    except Exception:
        log.exception("Error in message(%r, %r) (GET):" % (user_id, message_id))
        return json.dumps({'type': 'error', 'value': 'Server-side error.'})
    else:
        return json.dumps({'type': 'message', 'value': message_data})


class User(graphene.ObjectType):
    id = graphene.String()  # The unique ID of the user.
    name = graphene.String()  # The name of the user.
    messages = graphene.List(  # The messages to/from this user.
        lambda: Message,
        id=graphene.String(),
        origin=graphene.String(),
        content=graphene.String(),
        time=graphene.String(),
        after=graphene.String(),
        before=graphene.String(),
        pattern=graphene.String()
    )

    def __init__(self, id: str):
        self.id = id
        self.data = data_manager.get_user_data(id)
        super().__init__()

    @resolve_only_args
    def resolve_id(self):
        return self.id

    @resolve_only_args
    def resolve_name(self):
        return self.data['name']

    @resolve_only_args
    def resolve_messages(self, id=None, origin=None, content=None, time=None, after=None, before=None, pattern=None):
        if id is None:
            message_data = [data_manager.get_message_data(self.id, id) for id in data_manager.get_message_ids(self.id)]
        else:
            try:
                message_data = [data_manager.get_message_data(self.id, id)]
            except KeyError:
                message_data = []
        if origin is not None:
            message_data = [data for data in message_data if data['origin'] == origin]
        if content is not None:
            message_data = [data for data in message_data if data['content'] == content]
        if time is not None:
            message_data = [data for data in message_data if data['time'] == time]
        if after is not None:
            after = float(after)
            message_data = [data for data in message_data if float(data['time']) >= after]
        if before is not None:
            before = float(before)
            message_data = [data for data in message_data if float(data['time']) <= before]
        if pattern is not None:
            pattern = re.compile(pattern)
            message_data = [data for data in message_data if pattern.match(data['content'])]
        return [Message(self.id, data['id']) for data in message_data]


class Message(graphene.ObjectType):
    id = graphene.String()  # The unique (per user) ID of this message.
    origin = graphene.String()  # The origin of this message. (Either "server" or "client".)
    content = graphene.String()  # The content of this message.
    time = graphene.String()  # The date/time of this message, in the format YYYYMMDDHHMMSS.FFFFFF
    user = graphene.Field(User)  # The user who received or sent this message.

    def __init__(self, user_id, id):
        self.user_id = user_id
        self.id = id
        super().__init__()

    @resolve_only_args
    def resolve_id(self):
        return self.id

    @resolve_only_args
    def resolve_origin(self):
        data = data_manager.get_message_data(self.user_id, self.id)
        return data['origin']

    @resolve_only_args
    def resolve_content(self):
        data = data_manager.get_message_data(self.user_id, self.id)
        return data['content']

    @resolve_only_args
    def resolve_time(self):
        data = data_manager.get_message_data(self.user_id, self.id)
        return data['time']

    @resolve_only_args
    def resolve_user(self):
        return User(self.user_id)


class Query(graphene.ObjectType):
    users = graphene.List(
        User,
        id=graphene.String(),
        name=graphene.String()
    )
    # messages = graphene.List(
    #     Message,
    #     user_id=graphene.String(),
    #     id=graphene.String(),
    #
    # )

    @resolve_only_args
    def resolve_users(self, id=None, name=None):
        if id is None:
            if name is None:
                return [User(id) for id in data_manager.get_user_ids()]
            else:
                return [User(id) for id in data_manager.get_user_ids()
                        if data_manager.get_user_data(id)['name'] == name]
        else:
            try:
                data = data_manager.get_user_data(id)
            except KeyError:
                return []
            if name is None or data['name'] == name:
                return [User(id)]
            else:
                return []

    # @resolve_only_args
    # def resolve_messages(self, user_id=None, id=None, origin=None, content=None, time=None, after=None, before=None,
    #                      pattern=None):
    #     if user_id is None:
    #         user_ids = data_manager.get_user_ids()
    #     else:
    #         user_ids = [user_id]
    #     results = []
    #     for user_id in user_ids:
    #         user = User(user_id)
    #         results.extend(user.resolve_messages(id, origin, content, time, after, before, pattern))
    #     return results


schema = graphene.Schema(query=Query)
app.add_url_rule('/graphql', view_func=flask_graphql.GraphQLView.as_view('graphql', schema=schema, graphiql=True))
