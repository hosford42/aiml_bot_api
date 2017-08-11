"""
AIML Bot API
============

This is a very basic [GraphQL](http://graphql.org/) API for
[AIML Bot](https://github.com/hosford42/aiml_bot).

**IMPORTANT:** No security measures are implemented. Use this module
as a public-facing API at your own risk. Anyone who has access to the
API has access to the entire data set.

Endpoints
---------

The following endpoints are provided:

`/`

The GraphQL endpoint is the preferred method for interacting with the system.

`/users`

A JSON endpoint for listing registered users or adding a new user.

`/users/<user_id>`

A JSON endpoint for retrieving information about a specific user.

`/users/<user_id>/messages`

A JSON endpoint for listing the messages to/from a user or sending
a new message to the bot.

`/users/<user_id>/messages/<message_id>`

A JSON endpoint for retrieving information about a specific message.
"""


from setuptools import setup

setup(
    name='AIML Bot API',
    version='0.0',
    author='Aaron Hosford',
    author_email='aaron.hosford@ericsson.com',
    license='MIT',
    description='Json API to AIML Bot',
    long_description=__doc__,
    url='https://github.com/hosford42/aiml_bot_api',

    platforms=["any"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "Topic :: Communications :: Chat",
        "Topic :: Scientific/Engineering :: Artificial Intelligence"
    ],

    packages=['aiml_bot_api'],
    install_requires=[
        'flask',
        'flask_graphql',
        'graphene',
        'aiml_bot',
    ],
)
