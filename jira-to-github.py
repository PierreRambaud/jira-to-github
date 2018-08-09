#!/usr/bin/env python
import argparse
import csv
import getpass
import json
import os
import pickle
import random
import re
import requests
from progressbar.bar import ProgressBar
from html.entities import name2codepoint
from lxml import objectify
from collections import defaultdict

class JiraToGithub:
    ##
    # Initialize github and Jira information
    #
    def __init__(
        self,
        xml_path,
        jira_project,
        github_orga,
        github_repo,
        github_user,
        github_password,
    ):
        self.xml_path = xml_path
        self.jira_project = jira_project
        self.github_orga = github_orga
        self.github_user = github_user
        self.github_repo = github_repo
        self.github_password = github_password
        self.github_url = 'https://api.github.com/repos/{}/{}'.format(github_user, github_repo)
        self.projects = {}
        self.dry_run = False
        self.cached_data = []

    ##
    # Set cache path and reload cached data if needed
    #
    def set_cache_path(self, cache_path):
        if cache_path is None:
            cache_path = os.path.abspath('cache.txt')


        self.cache_path = cache_path

        try:
            if os.path.getsize(self.cache_path) > 0:
                with open(self.cache_path, 'rb') as fp:
                    self.cached_data = pickle.load(fp)
        except FileNotFoundError:
            pass

    ##
    # Set cache path and reload cached data if needed
    #
    def set_aliases_path(self, aliases_path):
        self.aliases = dict()
        if aliases_path is not None:
            with open(aliases_path, encoding='utf-8') as f:
                r = csv.reader(f, delimiter=',', quotechar='"')
                self.aliases = dict(r)

   ##
    # Enable dry run mode
    #
    def set_dry_run(self, dry_run):
        if dry_run is True:
            print('Run into dry-run mode')
            self.dry_run = dry_run

    ##
    # Html entity decode
    #
    def htmlentitydecode(self, s):
        if s is None: return ''
        s = s.replace(' '*8, '')
        return re.sub('&(%s);' % '|'.join(name2codepoint),
            lambda m: chr(name2codepoint[m.group(1)]), s)

    ##
    # Extract issues from xml

    def extract(self):
        all_xml = objectify.fromstring(open(self.xml_path).read())

        for item in all_xml.channel.item:
            self._add_to_projects(item)

    ##
    # Add issues and informations into projects list
    #
    def _add_to_projects(self, item):
        try:
            proj = item.project.get('key')
        except AttributeError:
            proj = item.key.text.split('-')[0]

        if proj not in self.projects:
            self.projects[self.jira_project] = {
                'Milestones': defaultdict(int),
                'Components': defaultdict(int),
                'Labels': defaultdict(int),
                'Issues': []
            }

        try:
            resolved_at = ', resolved="' + item.resolved.text + '"'
        except AttributeError:
            resolved_at = ''

        self.projects[self.jira_project]['Issues'].append(
            {
                'title': item.title.text,
                'type': item.type.text,
                'key': item.key.text,
                'body': '<b><i>[reporter="' + item.reporter.get('username') + '", created="' + item.created.text + '"' + resolved_at + ']</i></b>\n' + self.htmlentitydecode(item.description.text),
                'labels': [item.status.text, item.type.text],
                'comments': [],
            }
        )
        try:
            self.projects[self.jira_project]['Milestones'][item.fixVersion.text] += 1
            # this prop will be deleted later:
            self.projects[self.jira_project]['Issues'][-1]['milestone_name'] = item.fixVersion.text
        except AttributeError:
            pass

        try:
            self.projects[self.jira_project]['Components'][item.component.text] += 1
            self.projects[self.jira_project]['Issues'][-1]['labels'].append(item.component.text)
        except AttributeError:
            pass

        try:
            for version in item.version:
                if re.match('^(\d+.){3}\d+$', version.text) is not None:
                    self.projects[self.jira_project]['Labels'][version.text] += 1
                    self.projects[self.jira_project]['Issues'][-1]['labels'].append(version.text)
        except AttributeError:
            pass

        try:
            self.projects[self.jira_project]['Labels'][item.priority.text] += 1
            self.projects[self.jira_project]['Issues'][-1]['labels'].append(item.priority.text)
        except AttributeError:
            pass

        try:
            for label in item.labels.label:
                self.projects[self.jira_project]['Labels'][label.text] += 1
                self.projects[self.jira_project]['Issues'][-1]['labels'].append(label.text)
        except AttributeError:
            pass

        try:
            for comment in item.comments.comment:
                self.projects[self.jira_project]['Issues'][-1]['comments'].append(
                    '<b><i>[author="' +
                    comment.get('author') + '", created="' +
                    comment.get('created') + '"]</i></b>\n' +
                    self.htmlentitydecode(comment.text)
                )
        except AttributeError:
            pass

    ##
    # Prettify data
    #
    def prettify(self):
        def hist(h):
            for key in h.keys():
                print('%30s(%5d): ' % (key, h[key]) + h[key]*'#')
            print('')

        for proj in iter(self.projects.keys()):
            print(proj + ':\n    Milestones:')
            hist(self.projects[proj]['Milestones'])
            print('    Components:')
            hist(self.projects[proj]['Components'])
            print('    Labels:')
            hist(self.projects[proj]['Labels'])
            print('')
            print('    Total Issues: {}'.format(len(self.projects[proj]['Issues'])))
            print('')

    ##
    # Check for github milestones
    #
    def milestones(self):
        print('Making milestones...', self.github_url + '/milestones')
        print('')

        r = requests.get(
            self.github_url + '/milestones'
        )

        def find_in_milestones(response, title):
            for milestone in r.json():
                if mkey == milestone['title']:
                    return True
            return False

        response_json = r.json()

        milestones = {}
        for mkey in iter(self.projects[self.jira_project]['Milestones'].keys()):
            if find_in_milestones(response_json, mkey) is False:
                self.projects[self.jira_project]['Milestones'][mkey] = None

    ##
    # Migrate issue to github
    #
    def migrate(self):
        print('Creating each issue...')

        bar = ProgressBar(max_value=len(self.projects[self.jira_project]['Issues']))
        cant_migrate = []
        for index, issue in enumerate(self.projects[self.jira_project]['Issues']):
            if issue['key'] in self.cached_data:
                bar.update(index)
                continue

            if 'milestone_name' in issue:
                issue['milestone'] = self.projects[self.jira_project]['Milestones'][issue['milestone_name']]
                if issue['milestone'] is None:
                    cant_migrate.append(issue)
                    continue

                del issue['milestone_name']

            if len(self.aliases) != 0:
                result = []
                for i, label in enumerate(issue['labels']):
                    if label in self.aliases:
                        if self.aliases[label] == 'DELETED':
                            continue

                        if self.aliases[label] != 'same':
                            result.append(self.aliases[label])
                    result.append(label)


            comments = issue['comments']
            del issue['comments']

            if self._save_issue(issue, comments) is False:
                cant_migrate.append(issue['title'])

            bar.update(index)
        bar.update(len(self.projects[self.jira_project]['Issues']))

    ##
    # Return github auth
    #
    def _github_auth(self):
        return (self.github_user, self.github_password)

    ##
    # Save issue into github
    #
    def _save_issue(self, issue, comments):
        if self.dry_run is False:
            response_create = requests.post(
                self.github_url + '/issues',
                json.dumps(issue),
                auth=self._github_auth(),
                headers={'Accept': 'application/vnd.github.beta.html+json'}
            )

            if response_create.status_code != 201:
                return False

        # Save cache
        self.cached_data.append(issue['key'])
        with open(self.cache_path, 'wb') as fp:
            pickle.dump(self.cached_data, fp)

        if self.dry_run:
            return True

        content = json.loads(response_create.content)
        for comment in comments:
            response_comment = requests.post(
                self.github_url + '/issues/' + str(content['number']) + '/comments',
                json.dumps({'body': comment}),
                auth=self._github_auth(),
                headers={'Accept': 'application/vnd.github.beta.html+json'}
            )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate Jira Issues to github.')
    parser.add_argument('--aliases-path', type=str, help='Labels aliases path')
    parser.add_argument('--cache-path', type=str, help='Cache path')
    parser.add_argument('--xml-path', type=str, help='Jira xml path')
    parser.add_argument('--jira-project', type=str, help='Jira Project to use')
    parser.add_argument('--github-orga', type=str, help='Github organisation')
    parser.add_argument('--github-repo', type=str, help='Github repository')
    parser.add_argument('--github-user', type=str, help='Github user')
    parser.add_argument('--github-password', type=str, help='Github password')
    parser.add_argument('--prettify', action='store_const', const=True, help='show prettify projects')
    parser.add_argument('--dry-run',action='store_const', const=True, help='Enable or disable dry-run')
    args = parser.parse_args()

    xml_path = args.xml_path if args.xml_path else raw_input('Jira xml path:')
    jira_project = args.jira_project if args.jira_project else raw_input('Jira project to use:')
    github_orga = args.github_orga if args.github_orga else raw_input('Github orga: ')
    github_repo = args.github_repo if args.github_repo else raw_input('Github repo: ')
    github_user = args.github_user if args.github_user else raw_input('Github username: ')
    github_password = args.github_password if args.github_password else getpass.getpass('Github password: ')

    jira_to_github = JiraToGithub(
        xml_path,
        jira_project,
        github_orga,
        github_repo,
        github_user,
        github_password,
    )
    jira_to_github.set_aliases_path(args.aliases_path)
    jira_to_github.set_cache_path(args.cache_path)
    jira_to_github.set_dry_run(args.dry_run)

    jira_to_github.extract()
    if args.prettify:
        jira_to_github.prettify()
    else:
        jira_to_github.milestones()
        jira_to_github.migrate()
