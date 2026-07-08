import json
import time

import requests
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.utils.translation import gettext as _
from django.views.generic import View
from django.views.generic.detail import SingleObjectMixin

from judge.models import Language
from judge.utils import piston
from judge.utils.problem_data import ProblemDataError, get_full_case_contents
from judge.views.problem import ProblemMixin


def normalize_output(text):
    lines = [line.rstrip() for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n')]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def truncate_display(text):
    limit = settings.VNOJ_PISTON_MAX_DISPLAY
    if len(text) > limit:
        return text[:limit], True
    return text, False


def is_interpreter_syntax_error(stderr):
    return 'SyntaxError' in stderr or 'IndentationError' in stderr


class ProblemRunAjax(LoginRequiredMixin, ProblemMixin, SingleObjectMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        if not piston.PISTON_ENABLED:
            raise Http404()

        self.object = self.get_object()

        rate_key = 'piston-run!%d' % request.profile.id
        cache.add(rate_key, 0, timeout=settings.VNOJ_PISTON_RATE_LIMIT_WINDOW)
        if cache.incr(rate_key) > settings.VNOJ_PISTON_RATE_LIMIT_COUNT:
            return HttpResponse(_('You are running tests too quickly. Please wait a moment.'),
                                content_type='text/plain', status=429)

        lock_key = 'piston-lock!%d' % request.profile.id
        if not cache.add(lock_key, 1, timeout=45):
            return HttpResponse(_('You already have a test run in progress.'),
                                content_type='text/plain', status=429)
        try:
            return self.run(request)
        finally:
            cache.delete(lock_key)

    def run(self, request):
        problem = self.object

        try:
            body = json.loads(request.body)
        except ValueError:
            return HttpResponseBadRequest(_('Invalid request.'), content_type='text/plain')

        source = body.get('source', '')
        mode = body.get('mode', 'samples')
        if not isinstance(source, str) or not source.strip():
            return HttpResponseBadRequest(_('No source code was provided.'), content_type='text/plain')
        if len(source) > settings.VNOJ_PISTON_MAX_SOURCE_LENGTH:
            return HttpResponseBadRequest(_('The source code is too long.'), content_type='text/plain')
        if mode not in ('samples', 'custom'):
            return HttpResponseBadRequest(_('Invalid request.'), content_type='text/plain')

        try:
            language = Language.objects.get(id=int(body.get('language')))
        except (Language.DoesNotExist, TypeError, ValueError):
            return HttpResponseBadRequest(_('Invalid language.'), content_type='text/plain')
        if language.file_only or language.key not in settings.VNOJ_PISTON_LANGUAGE_MAP or \
                not problem.usable_languages.filter(id=language.id).exists():
            return HttpResponseBadRequest(_('This language is not supported by the test runner.'),
                                          content_type='text/plain')

        if mode == 'samples':
            sample_cases = problem.cases.filter(is_sample=True, type='C').exclude(input_file='') \
                                        .order_by('order')[:settings.VNOJ_PISTON_MAX_SAMPLES]
            if not sample_cases:
                return HttpResponseBadRequest(_('This problem has no sample tests to run.'),
                                              content_type='text/plain')
            try:
                contents = get_full_case_contents(problem, sample_cases,
                                                  settings.VNOJ_PISTON_MAX_TESTCASE_SIZE)
            except ProblemDataError as e:
                return HttpResponse(e.message, content_type='text/plain', status=503)
        else:
            custom_input = body.get('custom_input', '')
            if not isinstance(custom_input, str):
                return HttpResponseBadRequest(_('Invalid request.'), content_type='text/plain')
            if len(custom_input) > settings.VNOJ_PISTON_MAX_CUSTOM_INPUT:
                return HttpResponseBadRequest(_('The custom input is too long.'), content_type='text/plain')
            contents = [{'input': custom_input, 'output': None}]

        spec = settings.VNOJ_PISTON_LANGUAGE_MAP[language.key]
        try:
            runtime = piston.resolve_runtime(spec['language'], spec['version'])
        except piston.PistonError as e:
            return HttpResponse(e.message, content_type='text/plain', status=503)
        if runtime is None:
            return HttpResponse(_('The required runtime is not installed on the test runner.'),
                                content_type='text/plain', status=503)

        # Piston runs a single file; for JVM languages the entry point must be Main.
        if language.key in ('JAVA', 'JAVA8'):
            file_name = 'Main.java'
        elif language.key == 'KOTLIN':
            file_name = 'Main.kt'
        else:
            file_name = 'main.%s' % (language.extension or 'txt')

        run_timeout_ms = int(min(problem.time_limit, settings.VNOJ_PISTON_RUN_TIMEOUT_CAP) * 1000)
        run_memory_limit = problem.memory_limit * 1024  # KB -> bytes
        interpreted = language.key in ('PY2', 'PY3')

        cases = []
        overall = 'AC' if mode == 'samples' else 'OK'
        compile_error = None
        start = time.monotonic()

        for index, case in enumerate(contents, 1):
            if time.monotonic() - start > settings.VNOJ_PISTON_TOTAL_BUDGET:
                cases.append({'index': index, 'status': 'SK'})
                continue

            try:
                result = piston.execute(
                    language=runtime[0], version=runtime[1], file_name=file_name,
                    source=source, stdin=case['input'],
                    compile_timeout_ms=int(settings.VNOJ_PISTON_COMPILE_TIMEOUT * 1000),
                    run_timeout_ms=run_timeout_ms, run_memory_limit=run_memory_limit,
                )
            except (piston.PistonError, requests.RequestException):
                return HttpResponse(_('The test runner is currently unavailable.'),
                                    content_type='text/plain', status=503)

            compile_stage = result.get('compile')
            if compile_stage and compile_stage.get('code') not in (0, None):
                compile_error, _truncated = truncate_display(
                    compile_stage.get('stderr') or compile_stage.get('output') or '')
                overall = 'CE'
                break

            run = result.get('run') or {}
            stdout = run.get('stdout') or ''
            stderr = run.get('stderr') or ''
            wall_time = run.get('wall_time')  # milliseconds on recent Piston builds

            if run.get('status') == 'TO' or (
                    run.get('signal') == 'SIGKILL' and
                    (wall_time is None or wall_time >= run_timeout_ms)):
                status = 'TLE'
            elif run.get('code') != 0 or run.get('signal'):
                if interpreted and is_interpreter_syntax_error(stderr):
                    compile_error, _truncated = truncate_display(stderr)
                    overall = 'CE'
                    break
                status = 'RTE'
            elif case['output'] is not None:
                status = 'AC' if normalize_output(stdout) == normalize_output(case['output']) else 'WA'
            else:
                status = 'OK'

            if mode == 'samples' and status != 'AC' and overall == 'AC':
                overall = status

            display_input, input_truncated = truncate_display(case['input'])
            display_output, output_truncated = truncate_display(stdout)
            display_stderr, _stderr_truncated = truncate_display(stderr)
            if case['output'] is not None:
                display_expected, expected_truncated = truncate_display(case['output'])
            else:
                display_expected, expected_truncated = None, False

            cases.append({
                'index': index,
                'status': status,
                'time': round(wall_time / 1000, 3) if wall_time is not None
                        else round(result.get('site_wall_time', 0), 3),
                'input': display_input,
                'expected': display_expected,
                'output': display_output,
                'stderr': display_stderr,
                'code': run.get('code'),
                'signal': run.get('signal'),
                'truncated': {'input': input_truncated, 'expected': expected_truncated,
                              'output': output_truncated},
            })

        if any(case.get('status') == 'SK' for case in cases) and overall == 'AC':
            overall = 'SK'

        return JsonResponse({
            'result': overall,
            'runtime': {'language': runtime[0], 'version': runtime[1]},
            'compile_error': compile_error,
            'cases': cases,
        })
