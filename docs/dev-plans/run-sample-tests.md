# Plan: Tính năng "Chạy thử sample test + custom input" trên trang đề

> **Trạng thái: ĐÃ IMPLEMENT (08/07/2026).** File này giữ lại làm tài liệu thiết kế.
> Khác biệt so với plan khi làm thật: (1) map `PY2` dùng runtime `python2` của Piston
> (package cài dưới tên `python` 2.7.18 nhưng đăng ký runtime là `python2`);
> (2) Piston bind `127.0.0.1:2000` thay vì mở mọi interface; (3) endpoint chỉ nhận
> POST qua `http_method_names` để tránh 500 khi GET; (4) `run_url` đưa vào context
> từ server thay vì build trong template.

---

## 0. Bối cảnh & môi trường (cho session mới đọc lạnh)

- Repo site: `/home/tin/OJ` — fork VNOJ (`TranKimTin/OJ`), nhánh làm việc `custom`, upstream = VNOI-Admin/OJ. Venv: `./venv/`. Config cá nhân: `dmoj/local_settings.py` (gitignored).
- Dev services chạy bằng `bash /home/tin/oj-data/start-dev.sh` (web :8000 + bridged :9999 + celery + judge). Test bài nằm ở `/home/tin/oj-data/problems/`.
- Mục tiêu: người dùng viết code trong form nộp bài nhúng trên trang đề (Ace editor, có sẵn từ commit `01145df` upstream), bấm **Chạy sample** hoặc **Chạy với input tự nhập**, thấy kết quả AC/WA/TLE/RTE/CE từng case ngay tại chỗ — không tạo Submission, không đụng judge/bridge thật.
- Đã chốt với chủ repo: sandbox = **Piston self-host bằng Docker** (không dùng public API), phạm vi = **cả sample lẫn custom input**.
- Docker CHƯA cài trên máy dev — bước 1 sẽ cài.
- Bài demo `aplusb` có file test rời (`1.in/1.out/2.in/2.out` + init.yml viết tay) nhưng **chưa có row `ProblemTestCase` trong DB** — bước verify sẽ tạo qua web editor.

## 1. Kiến trúc

```
Trang đề (Ace editor #id_source, select #id_language)
        │  $.ajax POST /problem/<code>/run  (JSON; CSRF đã global trong resources/common.js)
        ▼
ProblemRunAjax (view mới, judge/views/problem_run.py)
        │  đọc sample case: DB (is_sample=True) + nội dung file (zip hoặc file rời)
        ▼
Piston container (Docker, http://localhost:2000/api/v2/execute) — sandbox cô lập
```

- Feature flag: `VNOJ_PISTON_URL = None` mặc định (tắt) → không render UI, endpoint 404. Bật bằng 1 dòng trong `local_settings.py`.
- "Sample" = test case được setter tick ô **Sample?** mới trong trình sửa test data (`/problem/<code>/test_data`). Tick sample ⇒ người dùng thấy full input/expected của case đó (bản chất tính năng, ghi vào help_text).

## 2. Settings — `dmoj/settings.py`

Thêm block sau `VNOJ_TESTCASE_VISIBLE_LENGTH = 60` (dòng ~134):

```python
# In-browser test runner (Piston). Set VNOJ_PISTON_URL (e.g. 'http://localhost:2000')
# in local_settings.py to enable; None disables the feature entirely.
VNOJ_PISTON_URL = None
VNOJ_PISTON_LANGUAGE_MAP = {
    'C':     {'language': 'c',       'version': '*'},
    'C11':   {'language': 'c',       'version': '*'},
    'CPP03': {'language': 'c++',     'version': '*'},
    'CPP11': {'language': 'c++',     'version': '*'},
    'CPP14': {'language': 'c++',     'version': '*'},
    'CPP17': {'language': 'c++',     'version': '*'},
    'CPP20': {'language': 'c++',     'version': '*'},
    'JAVA':  {'language': 'java',    'version': '*'},
    'KOTLIN': {'language': 'kotlin', 'version': '*'},
    'PAS':   {'language': 'pascal',  'version': '*'},
    'PY2':   {'language': 'python2', 'version': '*'},
    'PY3':   {'language': 'python',  'version': '*'},
}
VNOJ_PISTON_MAX_SAMPLES = 5
VNOJ_PISTON_MAX_SOURCE_LENGTH = 65536
VNOJ_PISTON_MAX_CUSTOM_INPUT = 65536
VNOJ_PISTON_MAX_TESTCASE_SIZE = 1048576
VNOJ_PISTON_MAX_DISPLAY = 4096
VNOJ_PISTON_COMPILE_TIMEOUT = 10.0
VNOJ_PISTON_RUN_TIMEOUT_CAP = 3.0
VNOJ_PISTON_TOTAL_BUDGET = 25.0
VNOJ_PISTON_REQUEST_TIMEOUT = 20.0
VNOJ_PISTON_RUNTIMES_CACHE_TTL = 300
VNOJ_PISTON_RATE_LIMIT_WINDOW = 60
VNOJ_PISTON_RATE_LIMIT_COUNT = 100
```

`JAVA8/PYPY/PYPY3/SCRATCH/OUTPUT/TEXT` cố ý không map (không có runtime Piston / file-only) — client disable nút, server trả 400.

## 3. Model + editor test data (đánh dấu sample)

- `judge/models/problem_data.py` — trong `ProblemTestCase` (dòng ~136-155), ngay sau `is_pretest` (~149):
  ```python
  is_sample = models.BooleanField(verbose_name=_('sample case?'), default=False,
      help_text=_('Users can run their code on this case in the browser; its input/output become visible to them.'))
  ```
  `default=False` BẮT BUỘC (`is_pretest` không có default — đừng bắt chước điểm đó). Chạy `makemigrations judge` + `migrate` (migration mới sau `0231_contest_replay_version.py`; lưu ý có hai file `0229_*` — cứ để makemigrations tự chọn dependency).
- `judge/views/problem_data.py:98-100` — thêm `'is_sample',` vào `ProblemCaseForm.Meta.fields` (sau `'is_pretest',`).
- `templates/problem/data.html`:
  - Header (~dòng 1043-1046): chèn `<th>{{ _('Sample?') }}</th>` giữa cột Points và block Pretest — **KHÔNG** bọc `{% if request.user.is_staff %}` (khác Pretest: mọi editor của bài đều được tick).
  - Row (~dòng 1079): chèn `<td>{{ form.is_sample.errors }}{{ form.is_sample }}</td>` sau cell points, ngoài gate staff. KHÔNG dùng pattern `as_hidden()`.
  - Colspan dòng ~1060: `{{ 9 + cases_formset.can_delete }}` → `{{ 10 + cases_formset.can_delete }}`.
  - JS clone row (`add-case-row-below`, ~dòng 431) clone nguyên `<tr>` — không cần sửa.
- `ProblemDataCompiler` (`judge/utils/problem_data.py:109+`, sinh init.yml) chỉ đọc field được nêu tên — KHÔNG cần sửa; các `case.save(update_fields=...)` dòng ~260/285 giữ nguyên.

## 4. Đọc full nội dung test — `judge/utils/problem_data.py`

Hàm hiện có `get_problem_testcases_data` (dòng 65-106) cắt nội dung còn 60 ký tự (`get_visible_content`, phục vụ preview trang submission) — KHÔNG sửa nó. Viết hàm mới bên cạnh:

```python
def get_full_case_contents(problem, cases, max_size):
    """[{'input': str, 'output': str}] cho các ProblemTestCase truyền vào.
    Hỗ trợ cả archive (init.yml có key 'archive:' → mở zip qua problem_data_storage)
    lẫn file rời trên disk. Raise ProblemDataError(msg dịch được) khi lỗi."""
```

- Đọc `<code>/init.yml` (thiếu → ProblemDataError). Có `archive:` → mở zip, check `getinfo(name).file_size <= max_size` trước khi `read`. Không có → `problem_data_storage.open('%s/%s' % (problem.code, case.input_file))`, check `.size()` trước.
- Decode `errors='ignore'` (như dòng 55). Không normalize ở đây.
- Caller chọn case: `problem.cases.filter(is_sample=True, type='C').exclude(input_file='').order_by('order')[:VNOJ_PISTON_MAX_SAMPLES]`.

## 5. Piston client — file mới `judge/utils/piston.py`

Mô phỏng `judge/utils/pdfoid.py` (module-level URL + flag, `requests`, logger `judge.piston`):

- `PISTON_ENABLED = settings.VNOJ_PISTON_URL is not None` (đổi flag cần restart — nhất quán convention).
- `class PistonError(Exception)` — message an toàn cho user.
- `get_runtimes()`: GET `/api/v2/runtimes`, cache `'piston:runtimes'` TTL 300s.
- `resolve_runtime(lang, version_spec)`: khớp `language` hoặc `aliases`; `'*'` → version cao nhất; không có → None (caller trả 400 "runtime chưa cài trên runner").
- `execute(language, version, file_name, source, stdin, compile_timeout_ms, run_timeout_ms, run_memory_limit)`: POST `/api/v2/execute`:
  ```json
  {"language": "c++", "version": "10.2.0",
   "files": [{"name": "main.cpp", "content": "..."}],
   "stdin": "...", "args": [],
   "compile_timeout": 10000, "run_timeout": 3000,
   "compile_memory_limit": -1, "run_memory_limit": -1}
  ```
  `requests.post(timeout=VNOJ_PISTON_REQUEST_TIMEOUT)`. Response: `{compile?: {stdout,stderr,code,signal}, run: {stdout,stderr,code,signal, wall_time?, memory?}}` — đọc wall_time bằng `.get()`, fallback đo `time.monotonic()` quanh call (ghi chú "xấp xỉ").
- Tên file: `'main.' + language.extension`; riêng Java → `Main.java`, Kotlin → `Main.kt` (Piston chạy single-file; class public phải tên Main — ghi vào tooltip).

## 6. Endpoint — file mới `judge/views/problem_run.py` + URL

```python
class ProblemRunAjax(LoginRequiredMixin, ProblemMixin, SingleObjectMixin, View):
    def post(self, request, *args, **kwargs): ...
```
`ProblemMixin` (judge/views/problem.py:67) có sẵn lookup theo code + 404 theo `is_accessible_by` — dùng nguyên.

**Request JSON**: `{"source": "...", "language": <pk>, "mode": "samples"|"custom", "custom_input": "..."}` (`language` = pk từ `#id_language`, giống `LanguageTemplateAjax` ở problem.py:750).

**Guards theo thứ tự** (lỗi trả plain-text để JS hiện `responseText` — convention của site):
1. `if not PISTON_ENABLED: raise Http404()`
2. Rate limit (copy idiom judge/views/user.py:710-715, key theo profile): `cache.add('piston-run!%d' % request.profile.id, 0, timeout=WINDOW)`; `cache.incr > COUNT` → 429 `_('You are running tests too quickly...')`.
3. Mutex: `cache.add('piston-lock!%d' % profile.id, 1, timeout=45)` fail → 429; `cache.delete` trong `finally`.
4. Parse JSON (400 nếu hỏng); validate: source nonempty ≤ MAX_SOURCE; Language pk tồn tại, thuộc `problem.usable_languages`, key có trong MAP, không `file_only` → 400.
5. mode samples: load case (mục 4), rỗng → 400 `_('This problem has no sample tests to run.')`. mode custom: input ≤ MAX_CUSTOM_INPUT.
6. `resolve_runtime` fail / `PistonError` / `requests.Timeout|ConnectionError` → 503 `_('The test runner is currently unavailable.')`.

**Vòng chạy**: tuần tự; `run_timeout_ms = int(min(problem.time_limit, RUN_TIMEOUT_CAP) * 1000)`; `run_memory_limit = problem.memory_limit * 1024`. Compile stage `code != 0` → verdict CE (kèm compile.stderr cắt MAX_DISPLAY), dừng luôn. Verdict case: SIGKILL (+wall_time ≥ timeout nếu có) → TLE; `code != 0 or signal` → RTE; còn lại so sánh → AC/WA. Custom mode: không so sánh → OK/RTE/TLE. Python/PY2 không có compile stage: sniff `SyntaxError|IndentationError` trong stderr → relabel CE. Quá `TOTAL_BUDGET` (25s) → các case còn lại status SK, dừng.

**So sánh output (standard checker DMOJ)**:
```python
def normalize(text):
    lines = [l.rstrip() for l in text.replace('\r\n', '\n').replace('\r', '\n').split('\n')]
    while lines and not lines[-1]:
        lines.pop()
    return lines
# AC ⟺ normalize(actual) == normalize(expected)
```
Bỏ qua field `checker` của case ở v1 (checker tùy chỉnh/float ngoài phạm vi).

**Response 200**:
```json
{"result": "AC|WA|TLE|RTE|CE|OK",
 "runtime": {"language": "c++", "version": "10.2.0"},
 "compile_error": null,
 "cases": [{"index": 1, "status": "AC", "time": 0.012,
            "input": "1 2\n", "expected": "3\n", "output": "3\n", "stderr": "",
            "code": 0, "signal": null,
            "truncated": {"input": false, "expected": false, "output": false}}]}
```
Mọi stream cắt server-side còn `VNOJ_PISTON_MAX_DISPLAY` (4KB) kèm cờ `truncated`.

**URL** — `dmoj/urls.py`, trong block `path('problem/<str:problem>', include([...]))` sau `'/submit'` (~dòng 131):
```python
path('/run', problem_run.ProblemRunAjax.as_view(), name='problem_run_ajax'),
```

## 7. Frontend

- `judge/views/problem.py` — `get_submit_context()` (dòng ~263; phủ cả ProblemDetail:458 lẫn ProblemSubmit:794) thêm:
  ```python
  'piston_enabled': PISTON_ENABLED,
  'piston_langs': json.dumps(sorted(settings.VNOJ_PISTON_LANGUAGE_MAP.keys())),
  'has_sample_cases': PISTON_ENABLED and self.object.cases.filter(is_sample=True, type='C').exists(),
  ```
  (import `PISTON_ENABLED` cạnh import `PDF_RENDERING_ENABLED` dòng ~38; `json` đã import.)
- `templates/problem/submit-form.html`:
  - Thêm `data-key="{{ lang.key }}"` vào `<option>` ngôn ngữ (~dòng 57-61).
  - Sau `.submit-bar` (~74-78), trong `{% else %}` của `no_judges`, block `{% if piston_enabled %}`: nút `type="button"` `#run-samples` "{{ _('Run sample tests') }}" (chỉ render `{% if has_sample_cases %}`) + `#run-custom-toggle` "{{ _('Run with custom input') }}". **type="button" bắt buộc** — kẻo trigger submit handler của `#problem_submit` (submit-js.html:134).
  - Sau `</form>` (~80): textarea `#custom-input` (ẩn mặc định) + nút `#run-custom` + panel `<div id="test-run-results" class="hidden">`.
- `templates/problem/submit-js.html` (trong `{% compress js %}`, gate `{% if piston_enabled %}`):
  - `var piston_langs = {{ piston_langs }};` + `var run_url = '{{ url('problem_run_ajax', problem.code) }}';` (kiểm tra tên biến context ở trang submit riêng — problem vs object).
  - Mở rộng `on_language_change()` (~dòng 158): `data-key` không thuộc piston_langs hoặc `data-fileonly=='True'` → disable nút + title giải thích.
  - Lấy source: `window.ace_source.getSession().getValue()` (fallback `$('#id_source').val()`); check rỗng + ≤65536 (mirror dòng 135). `$.ajax({type:'POST', contentType:'application/json', data: JSON.stringify(...)})` — CSRF tự động (resources/common.js:158-163).
  - States: đang chạy → disable nút + spinner `fa-spinner fa-pulse`; `.fail` → hiện `jqXHR.responseText`; `.always` → re-enable.
  - Render bằng `$('<pre>').text(...)` — TUYỆT ĐỐI không `.html()` với dữ liệu server (output do code người dùng sinh → XSS). Badge verdict tái dùng class toàn cục `.AC/.WA/.TLE/.RTE/.CE` (resources/status.scss — dark theme tự ăn). Block Input/Expected/Output/Stderr gấp mở được, đánh dấu "(đã cắt bớt)" theo cờ `truncated`.
- `resources/problem.scss` — thêm block `#test-run-results`: `pre.test-run-io { max-height: 12em; overflow-y: auto; }`, border trung tính (không hardcode nền sáng để dark theme override được). Build: `./make_style.sh && ./venv/bin/python manage.py collectstatic --noinput`.
- i18n: mọi chuỗi `{{ _('...') }}` / `_()`; chạy `manage.py makemessages -l vi`, dịch ~15 chuỗi trong `locale/vi`, `compilemessages`.

## 8. Piston setup (máy dev Ubuntu, kernel 6.17 = cgroup v2)

```bash
# Cài Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # logout/login

# Chạy Piston — PISTON_OUTPUT_MAX_SIZE là LOAD-BEARING:
# default 1024 byte sẽ cắt stdout → so sánh sai → WA oan
docker run -d --name piston --restart unless-stopped --privileged \
    -p 2000:2000 \
    -v $HOME/piston/packages:/piston/packages \
    -e PISTON_OUTPUT_MAX_SIZE=1048576 \
    ghcr.io/engineer-man/piston

# Xem package có sẵn rồi cài runtime (chậm — tải toolchain; version lấy từ /packages)
curl -s http://localhost:2000/api/v2/packages | python3 -m json.tool | less
for pkg in '{"language":"gcc","version":"10.2.0"}' \
           '{"language":"python","version":"3.10.0"}' \
           '{"language":"python2","version":"2.7.18"}' \
           '{"language":"java","version":"15.0.2"}' \
           '{"language":"kotlin","version":"1.8.20"}' \
           '{"language":"pascal","version":"3.2.2"}'; do
  curl -X POST http://localhost:2000/api/v2/packages -H 'Content-Type: application/json' -d "$pkg"
done

# Smoke test
curl -s http://localhost:2000/api/v2/runtimes
curl -s -X POST http://localhost:2000/api/v2/execute -H 'Content-Type: application/json' \
  -d '{"language":"c++","version":"*","files":[{"name":"main.cpp","content":"#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<\"\\n\";}"}],"stdin":"1 2\n"}'
```

Nếu container lỗi cgroup: fallback `git clone https://github.com/engineer-man/piston && docker compose up -d api` (compose chính chủ có sẵn tmpfs/privileged đúng). Bật flag: thêm `VNOJ_PISTON_URL = 'http://localhost:2000'` vào `dmoj/local_settings.py`.

## 9. Thứ tự implement

1. Settings block (settings.py) + `VNOJ_PISTON_URL` trong local_settings.
2. Model field + makemigrations + migrate.
3. `ProblemCaseForm.fields` + data.html (cột Sample? + colspan).
4. `get_full_case_contents` (utils/problem_data.py).
5. `judge/utils/piston.py`.
6. `judge/views/problem_run.py` + urls.py.
7. `get_submit_context` + submit-form.html + submit-js.html + problem.scss + build style.
8. Piston Docker + runtimes (làm song song lúc chờ cũng được).
9. makemessages/dịch vi/compilemessages.
10. Verify (mục 10) → cập nhật docs/CUSTOMIZE.md + docs/DEPLOY.md (mục Piston cho production: chạy container cạnh compose, `VNOJ_PISTON_URL` trong site.env) → commit lên `custom`.

## 10. Checklist verify

1. Curl Piston: runtimes đủ gcc/python/java/pascal/kotlin; a+b trả `run.stdout == "3\n"`.
2. `migrate` sạch; `/problem/aplusb/test_data` hiện cột "Sample?" với editor thường (không staff); cột "Pretest?" vẫn staff-only.
3. Seed aplusb: tạo 2 row (1.in/1.out, 2.in/2.out) qua web editor, tick Sample case 1, save — init.yml không hỏng (layout file rời).
4. Trang đề `/problem/aplusb`: nút hiện; code C++ đúng → AC; sai → WA (thấy expected vs output); `while(1);` → TLE ~3s; chia 0 → RTE kèm signal; thiếu `;` → CE kèm stderr; Python sai cú pháp → CE (qua sniff stderr).
5. Custom input: dán stdin → stdout/stderr, không verdict.
6. PYPY3 (không map) → nút disabled; forge POST → 400. Spam 7 lượt/phút → 429.
7. `VNOJ_PISTON_URL=None` → không UI, POST → 404. Nộp bài thật vẫn chạy; `Submission.objects.count()` không đổi sau khi chạy thử.
8. Bài dùng zip archive: đánh dấu sample 1 case, chạy — verify đường zip của `get_full_case_contents`.
9. Dark theme: badge + panel đọc được.
10. Trong contest: mở bài thuộc contest đang chạy — v1 cho phép chạy thử (chỉ lộ sample mà setter đã opt-in); ghi nhận hành vi.

## 11. Rủi ro & gotchas (đọc trước khi code)

- **Piston compile lại mỗi case** (không có compile-once API): chấp nhận với MAX_SAMPLES=5 + CE dừng sớm + budget 25s. Nâng cấp sau: chạy case 1 trước, các case sau song song.
- **View giữ worker ~25s**: dev runserver OK; production gunicorn sync worker timeout 30s → TOTAL_BUDGET phải < timeout; đường scale là Celery + polling (ghi chú trong code).
- **PISTON_OUTPUT_MAX_SIZE mặc định 1KB cắt output lặng lẽ** → env var 1MB là bắt buộc; thêm hint khi `len(output)` đúng bằng cap.
- **TLE heuristic**: Piston trả SIGKILL cho cả timeout lẫn OOM — dùng wall_time khi build Piston có, không thì label "TLE/killed".
- **Java/Kotlin**: gửi tên `Main.java` — class public phải tên `Main` (khác judge thật; ghi tooltip).
- **Cache runtimes 300s** có thể stale sau khi cài thêm package — flush key `piston:runtimes` là xong.
- **Sample disclosure**: tick sample = công khai full input/output case đó cho mọi người xem được bài — ghi rõ trong help_text để setter không bất ngờ.
- **Không tin JS**: mọi cap (source/input size) enforce lại server-side (đã có trong guards).
- Hai file migration `0229_*` tồn tại song song trong repo — để makemigrations tự xử dependency, đừng đặt tay số migration.
