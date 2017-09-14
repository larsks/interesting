import click
import json
import daiquiri
import sh
import urllib.parse

from functools import partial
from ruamel.yaml import YAML

git = sh.git
ssh = sh.ssh
gerrit = None
yaml = YAML(typ='safe')

LOG = daiquiri.getLogger(__name__)
SH_LOG = daiquiri.getLogger('sh')
SH_LOG.setLevel('WARNING')


class Interesting:
    def __init__(self, url, after=None):
        remote = parse_gerrit_remote(url)
        self.after = after
        self.remote = remote
        self.gerrit = partial(ssh, '-p',
                              remote['port'], remote['host'],
                              'gerrit')

    def find(self, interests, name='<unknown>'):
        results = {}
        for name, interest in interests:
            LOG.info('processing interest = %s', name)
            matches = self.handle_one_interest(interest)
            for change, file_matches in matches:
                if change['id'] not in results:
                    results[change['id']] = {
                        'change': change,
                        'matches': [],
                    }

                results[change['id']]['matches'].extend(file_matches)

        return results

    def handle_one_interest(self, interest):
        if self.after:
            query = '({}) AND after:{}'.format(
                interest['query'], self.after)
        else:
            query = interest['query']

        LOG.debug('gerrit query = %s', query)
        res = self.gerrit('query', '--current-patch-set', '--files',
                          '--format', 'JSON', query)

        doc = res.stdout.decode('utf-8')
        changes = self.extract_changes(doc)

        matches = []
        for spec in interest['specs']:
            for change in changes:
                summary=dict(id=change['id'],
                             url=change['url'],
                             msg=change['commitMessage'].splitlines()[0],
                             status=change['status'],
                             )

                file_matches = []
                for file_ in change['currentPatchSet'].get('files', []):
                    if file_['type'].lower() not in spec['type']:
                        continue
                    if not any(path in file_['file'] for path in spec['path']):
                        continue

                    file_matches.append(dict(path=file_['file'],
                                             type=file_['type'].lower()))

                if file_matches:
                    matches.append((summary, file_matches))

        return matches

    def extract_changes(self, doc):
        changes = []
        for line in doc.splitlines():
            change = json.loads(line)
            if change.get('type') == 'stats':
                continue

            if 'currentPatchSet' not in change:
                continue

            changes.append(change)

        return changes


def resolve_git_remote(remote):
    try:
        url = git.config('--get', 'remote.{}.url'.format(remote))
    except sh.ErrorReturnCode:
        raise click.ClickException('failed to resolve remote name "{}"'.format(
            remote))
    return url.stdout.decode('utf-8')


def parse_gerrit_remote(url):
    if not url.startswith('ssh://'):
        raise ValueError('This code only works with ssh:// repository urls')

    parsed = urllib.parse.urlparse(url)

    try:
        userhost, port = parsed.netloc.split(':')
    except ValueError:
        userhost = parsed.netloc
        port = None

    try:
        user, host = userhost.split('@')
    except ValueError:
        user = None
        host = userhost

    project = parsed.path[1:]
    if project.endswith('.git'):
        project = project[:-4]

    return {'user': user,
            'host': host,
            'port': port,
            'project': project,
            'url': url,
            }


@click.command()
@click.option('--remote', '-r', default='gerrit')
@click.option('--url', '-u')
@click.option('--interests', '-i', default='interests.yaml')
@click.option('--after', '-a')
@click.option('--debug', is_flag=True)
@click.argument('queries', nargs=-1)
def main(remote, url, interests, after, debug, queries):
    loglevel = 'DEBUG' if debug else 'INFO'
    daiquiri.setup(level=loglevel)

    if not url:
        url = resolve_git_remote(remote)

    LOG.debug('got url = %s', url)
    with open(interests) as fd:
        interests = yaml.load(fd)

    if not queries:
        selected = [(k,v) for k,v in interests.items()]
    else:
        selected = [(k,v) for k,v in interests.items()
                   if k in queries]

    I = Interesting(url, after=after)
    results = I.find(selected)

    for changeid, data in results.items():
        change = data['change']
        matches = data['matches']

        print('Change-Id: {id} ({url})\n\n    {msg}\n'.format(**change))
        for match in matches:
            print('    {type} {path}'.format(**match))

        print()
