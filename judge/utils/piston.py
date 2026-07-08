import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils.translation import gettext as _

logger = logging.getLogger('judge.piston')


PISTON_URL = settings.VNOJ_PISTON_URL
PISTON_ENABLED = PISTON_URL is not None

RUNTIMES_CACHE_KEY = 'piston:runtimes'


class PistonError(Exception):
    def __init__(self, message):
        super(PistonError, self).__init__(message)
        self.message = message


def get_runtimes():
    runtimes = cache.get(RUNTIMES_CACHE_KEY)
    if runtimes is not None:
        return runtimes
    try:
        response = requests.get('%s/api/v2/runtimes' % PISTON_URL,
                                timeout=settings.VNOJ_PISTON_REQUEST_TIMEOUT)
        response.raise_for_status()
        runtimes = response.json()
    except Exception:
        logger.exception('Failed to fetch Piston runtimes')
        raise PistonError(_('The test runner is currently unavailable.'))
    cache.set(RUNTIMES_CACHE_KEY, runtimes, settings.VNOJ_PISTON_RUNTIMES_CACHE_TTL)
    return runtimes


def resolve_runtime(language, version_spec='*'):
    """Find an installed Piston runtime matching `language` (name or alias) and
    `version_spec` ('*' for any, or a version prefix like '2' / '3.12').
    Returns (language, version) with the highest matching version, or None.
    """
    def version_key(version):
        return [int(part) if part.isdigit() else 0 for part in version.split('.')]

    def version_matches(version):
        if version_spec == '*':
            return True
        return version == version_spec or version.startswith(version_spec + '.')

    best = None
    for runtime in get_runtimes():
        if language != runtime['language'] and language not in runtime.get('aliases', []):
            continue
        if not version_matches(runtime['version']):
            continue
        if best is None or version_key(runtime['version']) > version_key(best[1]):
            best = (runtime['language'], runtime['version'])
    return best


def execute(*, language, version, file_name, source, stdin,
            compile_timeout_ms, run_timeout_ms, run_memory_limit=-1):
    """Run `source` against `stdin` on Piston. Returns the parsed response dict
    with an added 'site_wall_time' (seconds, measured around the HTTP call).
    """
    body = {
        'language': language,
        'version': version,
        'files': [{'name': file_name, 'content': source}],
        'stdin': stdin,
        'args': [],
        'compile_timeout': int(compile_timeout_ms),
        'run_timeout': int(run_timeout_ms),
        'compile_memory_limit': -1,
        'run_memory_limit': run_memory_limit,
    }
    start = time.monotonic()
    response = requests.post('%s/api/v2/execute' % PISTON_URL, json=body,
                             timeout=settings.VNOJ_PISTON_REQUEST_TIMEOUT)
    elapsed = time.monotonic() - start
    if response.status_code != 200:
        try:
            message = response.json().get('message', '')
        except ValueError:
            message = response.text[:200]
        logger.error('Piston execute failed (%d): %s', response.status_code, message)
        raise PistonError(_('The test runner is currently unavailable.'))
    data = response.json()
    data['site_wall_time'] = elapsed
    return data
