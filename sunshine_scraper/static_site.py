"""Build the public website as static files and publish it to GitHub Pages.

The live API needs this PC and PostgreSQL to be running. The public site must
stay up when they are not, so instead of answering questions on demand it
ships the answers ahead of time: most questions the page can ask have a fixed,
small set of possible answers (yearly totals, the top 100 titles, the top 100
salaries for each year), so they are written once as JSON files. The name
search has too many possible questions, so every person is pre-split into
"shard" files by the first two letters of the surname and the page downloads
just one. The page reads those files instead of calling /api/..., and any
free static host can serve them. Nothing on the public site ever reaches this computer.

The JSON is produced by the same response models the API uses (schemas.py),
so the page receives identical shapes in both modes.
"""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from pydantic import BaseModel

from .api.schemas import Salary, TitleStats, YearStats
from .storage.connection import DatabaseSettings, open_read_only_connection
from .storage.repository import MAX_LIMIT, PostgresSalaryRepository, SalaryReader

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / 'web'
# The tag in index.html that selects where app.js reads data from, and what
# the static build swaps it for.
LIVE_SOURCE_TAG = '<meta name="data-source" content="api">'
STATIC_SOURCE_TAG = '<meta name="data-source" content="static">'
# The page offers "Top 10" up to "Top 100", so the largest list the API would
# allow is stored and the page cuts it down to the size the visitor picked.
MAX_ROWS = MAX_LIMIT
# Refuse to publish a people index bigger than this, rather than discover at
# deploy time that GitHub Pages (about 1 GB) or a visitor's phone can't cope.
MAX_PEOPLE_BYTES = 500 * 1024 * 1024
MAX_SHARD_BYTES = 20 * 1024 * 1024

# The user:password@ (or token@) part of a URL such as
# https://user:token@github.com/owner/repo.git. Git accepts credentials there,
# so the origin URL and git's own error text may contain a secret.
URL_CREDENTIALS = re.compile(r'(?<=://)[^/@\s]+@')


class PublishError(RuntimeError):
    """The site could not be built or pushed; the message says why."""


def build_site(reader: SalaryReader, destination: Path, generated_at: datetime) -> int:
    """Write the complete static site into `destination` (which must not exist).

    Returns the number of years with salary data. Raises PublishError when the
    database has no records, so an empty database never replaces a good site.
    """
    years = reader.yearly_summary()
    listed_years = [summary.year for summary in years if summary.people > 0]
    if not listed_years:
        raise PublishError('The database has no salary records; run the scraper first')

    # Copy the page itself, then switch it to static mode (see the meta tag
    # in index.html: app.js reads it to decide where data comes from).
    shutil.copytree(WEB_DIR, destination)
    index = destination / 'index.html'
    html = index.read_text(encoding='utf-8')
    # A plain text swap: the tag is a fixed string, so no regex is needed.
    if html.count(LIVE_SOURCE_TAG) != 1:
        raise PublishError('index.html is missing its data-source meta tag')
    index.write_text(html.replace(LIVE_SOURCE_TAG, STATIC_SOURCE_TAG), encoding='utf-8')
    # GitHub Pages runs files through Jekyll unless this marker exists; the
    # site is already final, so skip that step.
    (destination / '.nojekyll').write_text('', encoding='utf-8')

    data = destination / 'data'
    write_json(data / 'years.json', [YearStats.from_summary(summary) for summary in years])
    write_json(data / 'titles.json',
               [TitleStats.from_count(count) for count in reader.top_job_titles(MAX_ROWS)])
    for year in listed_years:
        write_json(data / 'salaries' / f'{year}.json',
                   [Salary.from_result(result)
                    for result in reader.get_top_salaries(year, MAX_ROWS)])
    write_people_shards(reader, data / 'people')
    # Shown in the page header so visitors know how current the data is.
    write_json(data / 'meta.json',
               {'generated_at': generated_at.isoformat(timespec='seconds')})
    return len(listed_years)


def shard_key(folded_last_name: str) -> str:
    """The file a surname lives in: its first two letters a-z, or '_' if none.

    Everything but a-z is dropped so the key is always a safe filename
    (O'Brien -> "ob"). app.js computes the same key from what a visitor
    types, and the SQL ordering in iter_people uses the same rule.
    """
    return re.sub('[^a-z]', '', folded_last_name)[:2] or '_'


def write_people_shards(reader: SalaryReader, folder: Path) -> None:
    """Write data/people/<key>.json for every surname group, in constant memory.

    iter_people arrives sorted by shard, so one shard is held at a time. Titles
    and employers repeat heavily, so each shard stores every string once and
    its rows point at them by position.
    """
    total_bytes = 0
    largest = ('', 0)
    shards = 0
    current = None
    employers: dict[str, int] = {}
    titles: dict[str, int] = {}
    people: dict[str, list] = {}

    def flush():
        nonlocal total_bytes, largest, shards
        path = folder / f'{current}.json'
        write_json(path, {'employers': list(employers), 'titles': list(titles),
                          'people': people})
        size = path.stat().st_size
        if size > MAX_SHARD_BYTES:
            raise PublishError(f'People shard {current} is {size:,} bytes; too large to publish')
        total_bytes += size
        if total_bytes > MAX_PEOPLE_BYTES:
            raise PublishError('The people index is too large to publish')
        shards += 1
        largest = max(largest, (current, size), key=lambda item: item[1])

    for last_key, first_key, row in reader.iter_people():
        key = shard_key(last_key)
        if key != current:
            if current is not None:
                flush()
            current = key
            employers, titles, people = {}, {}, {}
        # setdefault(x, len(d)) hands out the next free position to a new string.
        title_index = titles.setdefault(row.job_title, len(titles))
        employer_index = employers.setdefault(row.employer, len(employers))
        people.setdefault(f'{last_key}|{first_key}', []).append(
            [row.first_name, row.last_name, row.year, row.salary_cents,
             title_index, employer_index])
    if current is not None:
        flush()
    logger.info('Wrote %d people shards, %.1f MB total; largest is %s (%.1f MB)',
                shards, total_bytes / 1e6, largest[0], largest[1] / 1e6)


def write_json(path: Path, value) -> None:
    """Write Pydantic models (or plain data) as compact UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, list):
        # isinstance, not a model_dump attribute check: only real response
        # models are converted, so an unexpected object fails loudly in
        # json.dumps instead of being half-serialized.
        value = [item.model_dump() if isinstance(item, BaseModel) else item for item in value]
    # ensure_ascii=False keeps accented names readable; separators drop
    # spaces, which matters for the larger files.
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')),
                    encoding='utf-8')


def build_from_database(destination: Path, settings: DatabaseSettings | None = None) -> int:
    """Build the site from PostgreSQL, replacing `destination` only on success.

    Everything is read in one read-only transaction, so all files describe the
    same moment even if a scraper run commits halfway through. The new site is
    built in a temporary folder first; a failure leaves the old one untouched.
    """
    settings = settings or DatabaseSettings.from_environment()
    destination = Path(destination)
    workspace = Path(tempfile.mkdtemp(prefix='sunshine-site-'))
    try:
        built = workspace / 'site'
        with open_read_only_connection(settings) as connection:
            years = build_site(PostgresSalaryRepository(connection), built,
                               datetime.now(timezone.utc))
        if destination.exists():
            # Only ever delete a folder this function built (it has the
            # .nojekyll marker), so a mistyped site_dir such as '.' can't
            # wipe out the project.
            if not (destination / '.nojekyll').is_file():
                raise PublishError(f'{destination} exists but is not a built site; '
                                   'choose an empty or new site_dir')
            shutil.rmtree(destination)
        shutil.move(str(built), str(destination))
        return years
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def publish(site_dir: Path, branch: str, repository: Path = Path('.')) -> str:
    """Push `site_dir` to `branch` of the repository's `origin` remote.

    The branch holds only the latest build. It is rebuilt as a single fresh
    commit and force-pushed each time: old builds have no value and would
    otherwise grow the repository with every publish. That is why it must be
    a branch used for nothing else.

    Returns the URL of the remote it pushed to, without any credentials, so
    the caller can log it safely.
    """
    if not (Path(site_dir) / 'index.html').is_file():
        raise PublishError(f'{site_dir} has no index.html; build the site first')
    remote = git(['remote', 'get-url', 'origin'], cwd=repository).strip()
    # A throwaway repository inside a temp copy of the site, so the project's
    # own working tree, index, and branches are never touched.
    with tempfile.TemporaryDirectory(prefix='sunshine-publish-') as workspace:
        staging = Path(workspace) / 'site'
        shutil.copytree(site_dir, staging)
        git(['init', '--quiet'], cwd=staging)
        git(['add', '--all'], cwd=staging)
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        git(['commit', '--quiet', '-m', f'Publish site ({stamp})'], cwd=staging)
        git(['push', '--force', '--quiet', remote, f'HEAD:refs/heads/{branch}'], cwd=staging)
    return hide_credentials(remote)


def hide_credentials(text: str) -> str:
    """Replace any credentials inside URLs in `text` with ***."""
    return URL_CREDENTIALS.sub('***@', text)


def git(arguments: list[str], cwd: Path) -> str:
    """Run one git command (no shell, so no quoting problems) and return its output."""
    try:
        completed = subprocess.run(['git', *arguments], cwd=cwd, capture_output=True,
                                   text=True, check=False)
    except FileNotFoundError as error:
        raise PublishError('git is not installed or not on PATH') from error
    if completed.returncode != 0:
        # git may echo the remote URL (credentials included) in its error text.
        raise PublishError(f'git {arguments[0]} failed: '
                           f'{hide_credentials(completed.stderr.strip())}')
    return completed.stdout
