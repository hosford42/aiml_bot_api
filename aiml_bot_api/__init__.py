"""
# AIML Bot API

A GraphQL/JSON API for the AIML Bot.


## Endpoints

### /

The GraphQL endpoint.

Schema:
    query {
        users {
            id,
            name,
            messages {
                id,
                content,
                time,
                origin
            }
        }
    }

### /users

A JSON endpoint for listing users and posting new users.

### /users/<user_id>

A JSON endpoint for getting or updating a particular user's associated data.

### /users/<user_id>/messages

A JSON endpoint for listing messages for a particular user and posting new
messages for that user.

### /users/<user_id>/messages/<message_id>

A JSON endpoint for getting a particular message's associated data.
"""

# http://blog.luisrei.com/articles/flaskrest.html
# https://www.digitalocean.com/community/tutorials/how-to-structure-large-flask-applications
# https://realpython.com/blog/python/api-integration-in-python/
# https://yacine.org/2016/10/17/10-minutes-to-a-custom-graphql-backend/

# Also, consider converting the AIML to something a little more palatable, or at least using a simpler XML parsing
# library like those described here: http://docs.python-guide.org/en/latest/scenarios/xml/. It should be really easy
# to convert to JSON or YAML.


from .data import DataManager
from .endpoints import app
from .graphql import schema
