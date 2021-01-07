#!/usr/bin/env python

from setuptools import setup

setup(
    name='Jira2Github',
    version='1.0',
    description='''
    Python script to migrate Jira tickets to GitHUb issues
    ''',
    author='Pierre Rambaud (GoT)',
    author_email='pierre.rambaud86@gmail.com',
    url='https://github.com/PierreRambaud/jira2github',
    license='GPLv3',
    scripts=['jira2github'],
    packages=['jira2github'],
    install_requires=[
        'argparse==1.4.0',
        'lxml==4.6.2',
        'progressbar2==3.38.0',
        'requests==2.19.1',
    ],
    tests_require=[
        'coverage',
        'pep8',
        'flake8',
        'nose',
        'mock'
    ],
)
