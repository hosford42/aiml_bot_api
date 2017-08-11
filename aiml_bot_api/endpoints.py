"""
## API Endpoints

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
        "id": "<user id>"
        "name": "<user's given name>"
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

#### Notes:

* The origin will be either "client" or "server".
* The timestamp will be a string formatted as "%Y%m%d%H%M%S.%f".


## Errors

For any request, an error may be returned rather than the expected result.
Errors will be formatted as:

    {
        "type": "error",
        "value": "<error description>"
    }

"""

import json
import logging
from functools import wraps

from flask import Flask, request, Response

from .data import DataManager


log = logging.getLogger(__name__)
app = Flask(__name__)

# TODO: Initialize this from a configuration file.
data_manager = DataManager()


def json_only(func):
    """Decorator for JSON-only API endpoints."""
    @wraps(func)
    def wrapped(*args, **kwargs):
        """The decorated function."""
        print(request.headers)
        if request.method in ('POST', 'PUT') and request.headers['Content-Type'] != 'application/json':
            return Response('Unsupported Media Type: %s' % request.headers['Content-Type'], status=415)
        else:
            raw_result = func(*args, **kwargs)  # type: dict
            if isinstance(raw_result.get('status'), int):
                status = raw_result.pop('status')
            else:
                status = None
            return Response(raw_result, status=status, content_type='application/json; charset=utf-8')
    return wrapped


@app.route('/users/', methods=['GET', 'POST'])
@json_only
def all_users():
    """The list of all users in the system.
    The client can get the list of users, or post a new user to the list."""
    if request.method == 'GET':
        # noinspection PyBroadException
        try:
            user_ids = data_manager.get_user_ids()
        except Exception:
            log.exception("Error in all_users() (GET):")
            return json.dumps({'type': 'error', 'value': 'Server-side error.', 'status': 500})
        else:
            return json.dumps({'type': 'user_list', 'value': user_ids})
    else:
        assert request.method == 'POST'
        user_data = request.get_json()
        if not isinstance(user_data, dict) or 'id' not in user_data or 'name' not in user_data or len(user_data) > 2:
            return json.dumps({'type': 'error', 'value': 'Malformed request.', 'status': 400})

        user_id = user_data['id']  # type: str
        if not isinstance(user_id, str) or not user_id.isidentifier():
            return json.dumps({'type': 'error', 'value': 'Invalid user ID.', 'status': 400})

        user_name = user_data['name']  # type: str
        if not isinstance(user_name, str) or not user_name:
            return json.dumps({'type': 'error', 'value': 'Invalid user name.', 'status': 400})

        # noinspection PyBroadException
        try:
            data_manager.add_user(user_id, user_name)
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User already exists.', 'status': 405})
        except Exception:
            log.exception("Error in all_users() (%s):" % request.method)
            return json.dumps({'type': 'error', 'value': 'Server-side error.', 'status': 500})
        else:
            return json.dumps({'type': 'user_created', 'id': user_id})


@app.route('/users/<user_id>/', methods=['GET', 'PUT'])
@json_only
def one_user(user_id):
    """A specific user. The client can get or set the associated properties for
    that user."""
    if request.method == 'GET':
        # noinspection PyBroadException
        try:
            user_data = data_manager.get_user_data(user_id)
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User not found.', 'status': 404})
        except Exception:
            log.exception("Error in one_user() (GET):")
            return json.dumps({'type': 'error', 'value': 'Server-side error.', 'status': 500})
        else:
            return json.dumps({'type': 'user', 'value': user_data})
    else:
        assert request.method == 'PUT'
        user_data = request.get_json()
        if (not isinstance(user_data, dict) or not user_data.keys() <= {'id', 'name'} or
                user_data.get('id', user_id) != user_id):
            return json.dumps({'type': 'error', 'value': 'Malformed request.', 'status': 400})

        if 'name' in user_data:
            user_name = user_data['name']  # type: str
            if not isinstance(user_name, str) or not user_name:
                return json.dumps({'type': 'error', 'value': 'Invalid user name.', 'status': 400})

            # noinspection PyBroadException
            try:
                data_manager.set_user_name(user_id, user_name)
            except KeyError:
                return json.dumps({'type': 'error', 'value': 'User not found.', 'status': 405})
            except Exception:
                log.exception("Error in all_users() (%s):" % request.method)
                return json.dumps({'type': 'error', 'value': 'Server-side error.', 'status': 500})

        return json.dumps({'type': 'user_updated', 'id': user_id})


@app.route('/users/<user_id>/messages/', methods=['GET', 'POST'])
@json_only
def all_messages(user_id):
    """The list of all messages associated with a given user.
    The client can get the list of messages, or post a new message to the list."""
    if request.method == 'GET':
        # noinspection PyBroadException
        try:
            message_ids = data_manager.get_message_ids(user_id)
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User not found.', 'status': 404})
        except Exception:
            log.exception("Error in all_messages(%r) (GET):" % user_id)
            return json.dumps({'type': 'error', 'value': 'Server-side error.', 'status': 500})
        else:
            return json.dumps({'type': 'message_list', 'value': message_ids})
    else:
        assert request.method == 'POST'
        message_data = request.get_json()
        if not (isinstance(message_data, dict) and message_data.get('origin', 'client') == 'client' and
                'content' in message_data and not message_data.keys() - {'origin', 'content'}):
            return json.dumps({'type': 'error', 'value': 'Malformed request.', 'status': 400})
        content = message_data['content']
        if not isinstance(content, str):
            return json.dumps({'type': 'error', 'value': 'Malformed request.', 'status': 400})
        content = content.strip()
        if not content:
            return json.dumps({'type': 'error', 'value': 'Empty message content.', 'status': 400})

        # noinspection PyBroadException
        try:
            message_id, response_id = data_manager.add_message(user_id, content)
        except KeyError:
            return json.dumps({'type': 'error', 'value': 'User not found.', 'status': 404})
        except Exception:
            log.exception("Error in all_messages(%r) (%s):" % (user_id, request.method))
            return json.dumps({'type': 'error', 'value': 'Server-side error.', 'status': 500})

        return json.dumps({'type': 'message_received', 'id': message_id, 'response_id': response_id})


@app.route('/users/<user_id>/messages/<message_id>/')
@json_only
def one_message(user_id, message_id):
    """A specific message for a specific user.
    The client can get the associated properties for that message."""
    # noinspection PyBroadException
    try:
        message_data = data_manager.get_message_data(user_id, message_id)
    except KeyError:
        return json.dumps({'type': 'error', 'value': 'Message not found.', 'status': 404})
    except Exception:
        log.exception("Error in one_message(%r, %r) (GET):" % (user_id, message_id))
        return json.dumps({'type': 'error', 'value': 'Server-side error.', 'status': 500})
    else:
        return json.dumps({'type': 'message', 'value': message_data})
