from setuptools import setup

setup(
    name='aiml_bot_api',
    version='0.0',
    packages=['aiml_bot_api'],
    url='',
    license='MIT',
    author='Aaron Hosford',
    author_email='aaron.hosford@ericsson.com',
    description='Json API to AIML Bot',
    install_requires=[
        'flask',
        'flask_graphql',
        'graphene',
        'aiml_bot'
    ]
)
