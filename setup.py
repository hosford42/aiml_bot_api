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
import os
import warnings


def get_long_description():
    """Load the long description from the README file. In the process,
    convert the README from .md to .rst using Pandoc, if possible."""
    rst_path = os.path.join(os.path.dirname(__file__), 'README.rst')
    md_path = os.path.join(os.path.dirname(__file__), 'README.md')

    try:
        # Imported here to avoid creating a dependency in the setup.py
        # if the .rst file already exists.

        # noinspection PyUnresolvedReferences,PyPackageRequirements
        from pypandoc import convert_file
    except ImportError:
        warnings.warn("Module pypandoc not installed. Unable to generate README.rst.")
    else:
        # First, try to use convert_file, assuming Pandoc is already installed.
        # If that fails, try to download & install it, and then try to convert
        # again.
        # noinspection PyBroadException
        try:
            # pandoc, you rock...
            rst_content = convert_file(md_path, 'rst')
            with open(rst_path, 'w') as rst_file:
                for line in rst_content.splitlines(keepends=False):
                    rst_file.write(line + '\n')
        except Exception:
            try:
                # noinspection PyUnresolvedReferences,PyPackageRequirements
                from pypandoc.pandoc_download import download_pandoc

                download_pandoc()
            except FileNotFoundError:
                warnings.warn("Unable to download & install pandoc. Unable to generate README.rst.")
            else:
                # pandoc, you rock...
                rst_content = convert_file(md_path, 'rst')
                with open(rst_path, 'w') as rst_file:
                    for line in rst_content.splitlines(keepends=False):
                        rst_file.write(line + '\n')

    if os.path.isfile(rst_path):
        with open(rst_path) as rst_file:
            return rst_file.read()
    else:
        # It will be messy, but it's better than nothing...
        with open(md_path) as md_file:
            return md_file.read()


setup(
    name='AIML Bot API',
    version='0.0',
    author='Aaron Hosford',
    author_email='aaron.hosford@ericsson.com',
    license='MIT',
    description='GraphQL API to AIML Bot',
    long_description=get_long_description(),
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
