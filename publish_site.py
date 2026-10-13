"""Publish the public website: build static files from PostgreSQL and push them.

    python publish_site.py              build, then push to GitHub Pages
    python publish_site.py --no-push    build only, to preview in site_dir

Run the scraper first if you want the newest data; this only reads the
database. Exit codes: 0 ok, 1 failure.
"""
import argparse
import logging
from pathlib import Path

import config
from sunshine_scraper.static_site import PublishError, build_from_database, publish
from sunshine_scraper.storage.connection import DatabaseAccessError, DatabaseConfigurationError

logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build and publish the static Sunshine List website')
    parser.add_argument('--no-push', action='store_true',
                        help=f'only build into {config.site_dir}/ without publishing')
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
    # Same setting as the scraper; INFO above stays as the handler's fallback.
    logging.getLogger().setLevel(config.log_level)
    site_dir = Path(config.site_dir)
    try:
        years = build_from_database(site_dir)
        logger.info('Built %s with data for %d years', site_dir, years)
        if arguments.no_push:
            logger.info('Preview it with: python -m http.server --directory %s 8001', site_dir)
            return 0
        remote = publish(site_dir, config.pages_branch)
        logger.info('Pushed to the %s branch of %s', config.pages_branch, remote)
        logger.info('GitHub Pages usually shows the update within a minute or two')
        return 0
    except (PublishError, DatabaseConfigurationError, DatabaseAccessError, OSError) as error:
        # Database messages never include the connection URL.
        logger.error('Publish stopped: %s', error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
