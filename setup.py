

from setuptools import setup

setup(
    name='aiml_bot_api',
    version='0.0',
    modules=['aiml_bot_api'],
    url='https://github.com/hosford42/aiml_bot_api',
    license='MIT',
    author='Aaron Hosford',
    author_email='aaron.hosford@ericsson.com',
    description='Json API to AIML Bot',
    install_requires=[
        'flask',
        'flask_graphql',
        'graphene',
        'aiml_bot',
    ]
)
