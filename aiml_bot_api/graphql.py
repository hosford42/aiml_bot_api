"""
# Schema

    {
        users {
            id
            name
            messages {
                id
                origin (either "client" or "server")
                content
                time
            }
        }
    }

"""


# Security:
# https://www.slideshare.net/rnewton/best-practices-you-must-apply-to-secure-your-apis

# Mutations:
# https://dev-blog.apollodata.com/designing-graphql-mutations-e09de826ed97
# http://docs.graphene-python.org/en/latest/types/mutations/


import re

import flask_graphql
import graphene
from graphene import resolve_only_args

from .endpoints import app, data_manager


class User(graphene.ObjectType):
    """Model for the users. Each user has a name, a unique ID, and a list of
    messages sent to/from the user."""

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

    # noinspection PyShadowingBuiltins
    def __init__(self, id: str):
        self.id = id
        self.data = data_manager.get_user_data(id)
        super().__init__()

    @resolve_only_args
    def resolve_id(self):
        """Resolve the id field of the user."""
        return self.id

    @resolve_only_args
    def resolve_name(self):
        """Resolve the name field of the user."""
        return self.data['name']

    # noinspection PyShadowingBuiltins
    @resolve_only_args
    def resolve_messages(self, id=None, origin=None, content=None, time=None, after=None, before=None, pattern=None):
        """Resolve the list of messages nested under the user."""
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


class UserInput(graphene.InputObjectType):
    id = graphene.String()
    name = graphene.String()


class AddUser(graphene.Mutation):
    class Input:
        input = graphene.Argument(UserInput)

    user = graphene.Field(User)
    error = graphene.String()

    @staticmethod
    def mutate(root, args, context, info) -> 'AddUser':
        data = args.get('input')
        id = data.get('id')
        name = data.get('name')
        try:
            data_manager.add_user(id, name)
        except KeyError:
            user = None
            error = 'User already exists.'
        else:
            user = User(id)
            error = None
        return AddUser(user=user, error=error)


class SetUserName(graphene.Mutation):
    class Input:
        input = graphene.Argument(UserInput)

    user = graphene.Field(User)
    error = graphene.String()

    @staticmethod
    def mutate(root, args, context, info) -> 'SetUserName':
        data = args.get('input')
        id = data.get('id')
        name = data.get('name')
        try:
            data_manager.set_user_name(id, name)
        except KeyError:
            user = None
            error = 'User not found.'
        else:
            user = User(id)
            error = None
        return SetUserName(user=user, error=error)


class Message(graphene.ObjectType):
    """The model for messages. Each message has an associated ID, an origin, a
    time, a user, and the message content. Messages are always associated with
    exactly one user. A message will either originate from the user and be
    directed to the bot, or originate from the bot and be directed to the user;
    user-to-user messages are not supported. The value of the origin will be
    either "client" or "server" depending on whether it was sent by the user or
    the bot, respectively. The value of the time is a string in the format
    "YYYYMMDDHHMMSS.FFFFFF". Message IDs are unique among all messages
    belonging to the same user, but not necessarily among messages belonging to
    any user."""

    id = graphene.String()  # The unique (per user) ID of this message.
    origin = graphene.String()  # The origin of this message. (Either "server" or "client".)
    content = graphene.String()  # The content of this message.
    time = graphene.String()  # The date/time of this message, in the format YYYYMMDDHHMMSS.FFFFFF
    user = graphene.Field(User)  # The user who received or sent this message.

    # noinspection PyShadowingBuiltins
    def __init__(self, user_id, id):
        self.user_id = user_id
        self.id = id
        super().__init__()

    @resolve_only_args
    def resolve_id(self):
        """Resolve the id field of the message."""
        return self.id

    @resolve_only_args
    def resolve_origin(self):
        """Resolve the origin field of the message."""
        data = data_manager.get_message_data(self.user_id, self.id)
        return data['origin']

    @resolve_only_args
    def resolve_content(self):
        """Resolve the content field of the message."""
        data = data_manager.get_message_data(self.user_id, self.id)
        return data['content']

    @resolve_only_args
    def resolve_time(self):
        """Resolve the time field of the message."""
        data = data_manager.get_message_data(self.user_id, self.id)
        return data['time']

    @resolve_only_args
    def resolve_user(self):
        """Resolve the user field of the message."""
        return User(self.user_id)


class SendMessageInput(graphene.InputObjectType):
    user = graphene.InputField(UserInput)
    content = graphene.String()


class SendMessage(graphene.Mutation):
    class Input:
        input = graphene.Argument(SendMessageInput)

    user = graphene.Field(User)
    message = graphene.Field(Message)
    response = graphene.Field(Message)
    error = graphene.String()

    @staticmethod
    def mutate(root, args, context, info) -> 'SendMessage':
        data = args.get('input')
        if data is None:
            return SendMessage(user=None, message=None, response=None, error='No input specified.')

        user = data.get('user')  # type: UserInput
        content = data.get('content')  # type: str

        if user is None:
            return SendMessage(user=None, message=None, response=None, error='No user specified.')
        if not content:
            return SendMessage(user=None, message=None, response=None, error='No content specified.')

        user_id = user.get('id')
        if user_id is None:
            return SendMessage(user=None, message=None, response=None, error='No user ID specified.')

        try:
            message_id, response_id = data_manager.add_message(user_id, content)
        except KeyError:
            user = None
            message = None
            response = None
            error = 'User not found.'
        else:
            user = User(user_id)
            message = Message(user_id, message_id)
            if response_id is None:
                response = None
            else:
                response = Message(user_id, response_id)
            error = None
        return SendMessage(user=user, message=message, response=response, error=error)


class Query(graphene.ObjectType):
    """This is the schema entry point. Queries always start from this class
    and work their way through the other classes via the properties of each
    class. For example, to access Query.users[user_id].messages[message_id],
    the GraphQL query would be:

        {
            users(id: user_id) {
                messages(id: message_id) {
                    id,
                    origin,
                    content,
                    time
                }
            }
        }

    It is also possible to use other selection criteria besides the id, as
    determined by the corresponding resolve_*() method.
    """

    users = graphene.List(
        User,
        id=graphene.String(),
        name=graphene.String()
    )

    # noinspection PyShadowingBuiltins
    @resolve_only_args
    def resolve_users(self, id=None, name=None):
        """Resolve the selected users at the top level of the query."""
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


class Mutation(graphene.ObjectType):
    add_user = AddUser.Field()
    set_user_name = SetUserName.Field()
    send_message = SendMessage.Field()


# Register the schema and map it into an endpoint.
schema = graphene.Schema(query=Query, mutation=Mutation)
app.add_url_rule('/', view_func=flask_graphql.GraphQLView.as_view('graphql', schema=schema, graphiql=True))
