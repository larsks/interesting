import sh
from functools import partial

@click.command()
@click.option('--remote', default='gerrit')
@click.option('--url')
def main(remote, url):
    print('remote:', remote)
    print('url:', url)
