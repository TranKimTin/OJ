# TinOJ — Hướng dẫn setup từ đầu

Ghi lại toàn bộ các bước dựng TinOJ (fork từ VNOJ/DMOJ) chạy trên một máy Linux,
từ fork repo đến chấm được bài đầu tiên. Làm theo từ trên xuống là xong.

> Môi trường đã kiểm chứng: Ubuntu 24.04, Python 3.12, MySQL 8.0, Redis, Node 20.
> MariaDB dùng thay MySQL cũng được.

## Kiến trúc tổng quan

```
┌─────────────┐   port 9999    ┌──────────────┐
│  Site (web) │◄──────────────►│ Judge (chấm) │
│  Django     │    bridge      │ dmoj         │
└──────┬──────┘                └──────────────┘
       │
  MySQL + Redis + Celery
```

- **Site**: repo `TranKimTin/OJ` (fork của `VNOI-Admin/OJ`) — web Django.
- **Judge**: repo `TranKimTin/judge-server` (fork của `VNOI-Admin/judge-server`) — máy chấm, kết nối vào site qua bridge (port 9999).
- Hai repo clone **cạnh nhau**, không lồng vào nhau.

### Vai trò 3 repo — sửa code thì sửa ở đâu?

| Repo | Vai trò | Tần suất đụng vào |
|---|---|---|
| **OJ** (site) | Mọi thứ người dùng thấy và mọi tính năng: giao diện, trang đề, contest, rating, tài khoản, cả tính năng tự viết (như nút "Chạy thử sample"). | **95% thời gian** — dev hằng ngày là ở đây |
| **judge-server** | Engine thực thi và chấm code. Fork chủ yếu để **khóa phiên bản** khớp với site, không phải để sửa. | Hiếm khi: thêm compiler mới, grader đặc biệt; định kỳ merge upstream để nhận vá bảo mật sandbox |
| **vnoj-docker** (chưa fork, để đến lúc deploy) | Không phải code — chỉ là config deploy: docker-compose, nginx, template env. | Lần đầu lên VPS + khi hạ tầng đổi (thêm service, đổi port); xong để yên hàng tháng |

Hình dung: OJ là **ngôi nhà** liên tục trang trí sửa sang, judge-server là
**hệ thống điện nước** chỉ gọi thợ khi hỏng, vnoj-docker là **bản vẽ móng**
chỉ dùng khi xây nhà mới. Máy dev hằng ngày chỉ cần theo dõi repo OJ;
judge-server clone một lần để chạy; vnoj-docker đến giai đoạn deploy hẵng quan tâm.

## 1. Fork repo (làm 1 lần duy nhất)

Fork 2 repo về tài khoản GitHub của bạn (nút Fork trên web, hoặc API):

- `VNOI-Admin/OJ` → `TranKimTin/OJ`
- `VNOI-Admin/judge-server` → `TranKimTin/judge-server`

## 2. Clone site + tạo nhánh

```bash
git clone --recursive https://github.com/TranKimTin/OJ.git ~/OJ
cd ~/OJ
git remote add upstream https://github.com/VNOI-Admin/OJ.git
git checkout -b custom   # mọi tùy biến nằm ở nhánh này, master giữ sạch để merge upstream
```

Sau này lấy cập nhật từ VNOI: `git fetch upstream && git merge upstream/master`.

## 3. Cài gói hệ thống

```bash
sudo apt update
sudo apt install -y python3-dev python3-venv gcc g++ make \
    pkg-config gettext default-libmysqlclient-dev \
    mysql-server redis-server
# Node 20+: cài qua nvm hoặc apt (cần cho build CSS/JS)
```

## 4. Python venv + dependencies

```bash
cd ~/OJ
python3 -m venv venv
./venv/bin/pip install --upgrade pip wheel
./venv/bin/pip install -r requirements.txt
```

## 5. Tạo database MySQL

```bash
sudo mysql   # nếu bị Access denied, dùng: sudo mysql --defaults-file=/etc/mysql/debian.cnf
```

```sql
CREATE DATABASE IF NOT EXISTS dmoj DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_general_ci;
CREATE USER 'dmoj'@'localhost' IDENTIFIED BY '<MẬT_KHẨU_DB>';
GRANT ALL PRIVILEGES ON dmoj.* TO 'dmoj'@'localhost';
FLUSH PRIVILEGES;
```

## 6. Thư mục dữ liệu + file cấu hình

```bash
mkdir -p ~/oj-data/problems ~/oj-data/static ~/oj-data/media
```

Tạo `~/OJ/dmoj/local_settings.py` (file này đã nằm trong `.gitignore`, KHÔNG commit):

```python
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = '<CHUỖI_NGẪU_NHIÊN_DÀI>'   # sinh: python3 -c "import secrets;print(secrets.token_urlsafe(48))"
DEBUG = True                             # production thì False
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

SITE_NAME = 'TinOJ'
SITE_LONG_NAME = 'TinOJ: Online Judge'
SITE_ADMIN_EMAIL = 'kimtin.tr@gmail.com'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'dmoj',
        'USER': 'dmoj',
        'PASSWORD': '<MẬT_KHẨU_DB>',
        'HOST': '127.0.0.1',
        'OPTIONS': {
            'charset': 'utf8mb4',
            'sql_mode': 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION',
        },
    },
}

# Bắt buộc dùng Redis (không dùng cache local-memory) để site và bridge thấy chung cache.
# Nếu Redis có mật khẩu (xem /etc/redis/redis.conf, dòng requirepass):
# dùng dạng redis://:<MẬT_KHẨU_REDIS>@127.0.0.1:6379/1
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    },
}

CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

# Thư mục chứa test của các bài — judge và site cùng đọc chỗ này
DMOJ_PROBLEM_DATA_ROOT = os.path.expanduser('~/oj-data/problems')

# Thiếu 2 dòng này thì collectstatic/compress sẽ báo ImproperlyConfigured
STATIC_ROOT = os.path.expanduser('~/oj-data/static')
MEDIA_ROOT = os.path.expanduser('~/oj-data/media')

LANGUAGE_CODE = 'vi'
TIME_ZONE = 'Asia/Ho_Chi_Minh'
DEFAULT_USER_TIME_ZONE = 'Asia/Ho_Chi_Minh'
```

## 7. Build frontend + bản dịch

```bash
cd ~/OJ
npm ci                 # cài sass, postcss, autoprefixer...
./make_style.sh        # biên dịch SCSS (theme sáng + tối)
./venv/bin/python manage.py collectstatic --noinput
./venv/bin/python manage.py compilemessages
./venv/bin/python manage.py compilejsi18n
```

## 8. Khởi tạo database

```bash
./venv/bin/python manage.py migrate
./venv/bin/python manage.py loaddata navbar language_small demo
```

**Lưu ý:** fixture `demo` tạo sẵn tài khoản `admin` với mật khẩu `admin` — phải đổi ngay:

```bash
./venv/bin/python manage.py changepassword admin
```

(`demo` cũng tạo sẵn bài `aplusb` trong DB — tiện để test judge ở bước 11.)

## 9. Chạy site

Cần 3 tiến trình chạy song song (3 terminal, hoặc dùng script ở bước 12):

```bash
./venv/bin/python manage.py runserver 127.0.0.1:8000   # web
./venv/bin/python manage.py runbridged                  # bridge (port 9999 cho judge)
./venv/bin/celery -A dmoj_celery worker -l warning      # tác vụ nền
```

Mở http://127.0.0.1:8000 — thấy trang chủ là OK.

## 10. Cài judge (máy chấm)

```bash
sudo apt install -y libseccomp-dev
git clone --recursive https://github.com/TranKimTin/judge-server.git ~/judge-server
cd ~/judge-server
python3 -m venv venv
./venv/bin/pip install --upgrade pip wheel cython
./venv/bin/pip install -e .
```

Sinh danh sách runtime có trên máy, rồi tạo file cấu hình:

```bash
./venv/bin/dmoj-autoconf > runtimes.yml
```

Tạo `~/judge-server/judge.yml` gồm id, key, đường dẫn test, và nội dung `runtimes.yml` nối vào sau:

```yaml
id: judge1
key: <JUDGE_KEY>        # sinh: python3 -c "import secrets;print(secrets.token_urlsafe(48))"
problem_storage_globs:
  - /home/tin/oj-data/problems/*
# ... dán toàn bộ nội dung runtimes.yml vào dưới đây (bắt đầu bằng "runtime:")
```

Đăng ký judge với site (chạy trong `~/OJ`):

```bash
cd ~/OJ && ./venv/bin/python manage.py addjudge judge1 '<JUDGE_KEY>'
```

Chạy judge (site + bridge phải đang chạy):

```bash
cd ~/judge-server && ./venv/bin/dmoj -c judge.yml localhost
```

Log hiện `Judge "judge1" online` là thành công. (Nếu thấy traceback về OBJC/Objective-C
lúc khởi động thì kệ — chỉ là self-test runtime không có trên máy, judge tự bỏ qua.)

## 11. Tạo test cho bài và nộp thử

Judge đọc test từ thư mục `DMOJ_PROBLEM_DATA_ROOT/<mã bài>/`. Ví dụ bài `aplusb`:

```bash
mkdir -p ~/oj-data/problems/aplusb
cd ~/oj-data/problems/aplusb
printf "1 2\n" > 1.in;  printf "3\n"  > 1.out
printf "5 7\n" > 2.in;  printf "12\n" > 2.out
cat > init.yml <<'EOF'
test_cases:
- {in: 1.in, out: 1.out, points: 50}
- {in: 2.in, out: 2.out, points: 50}
EOF
```

Judge tự phát hiện thư mục bài mới (không cần khởi động lại). Vào web, đăng nhập,
mở bài A Plus B, nộp code C++:

```cpp
#include <bits/stdc++.h>
int main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<std::endl;}
```

Kết quả **AC** = toàn bộ hệ thống hoạt động.

## 12. Chạy tất cả bằng 1 lệnh

```bash
bash ~/oj-data/start-dev.sh
```

Script này khởi động web + bridge + celery + judge cùng lúc (xem nội dung trong file).

## 13. Piston — nút "Chạy thử sample" trên trang đề (tùy chọn)

Tính năng chạy thử sample/custom input cần container Piston (cần Docker):

```bash
# Cài Docker nếu chưa có
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER

# Chạy Piston (bind localhost, KHÔNG mở ra mạng ngoài)
sudo docker run -d --name piston --restart unless-stopped --privileged \
    -p 127.0.0.1:2000:2000 \
    -v $HOME/piston/packages:/piston/packages \
    -e PISTON_OUTPUT_MAX_SIZE=1048576 \
    ghcr.io/engineer-man/piston

# Cài runtime (tải toolchain, hơi lâu)
for pkg in '{"language":"gcc","version":"10.2.0"}' '{"language":"python","version":"3.12.0"}' \
           '{"language":"python","version":"2.7.18"}' '{"language":"java","version":"15.0.2"}' \
           '{"language":"kotlin","version":"1.8.20"}' '{"language":"pascal","version":"3.2.2"}'; do
  curl -X POST http://localhost:2000/api/v2/packages -H 'Content-Type: application/json' -d "$pkg"
done
```

Thêm vào `dmoj/local_settings.py` rồi khởi động lại web:

```python
VNOJ_PISTON_URL = 'http://localhost:2000'
```

Cuối cùng, vào trang sửa test data của bài (`/problem/<mã>/test_data`) tick ô
**Sample?** cho các test muốn cho chạy thử. Không đặt `VNOJ_PISTON_URL` thì
tính năng tự ẩn. Thiết kế chi tiết: `dev-plans/run-sample-tests.md`.

## Xử lý lỗi đã gặp

| Lỗi | Nguyên nhân / cách sửa |
|---|---|
| `COMPRESS_ROOT defaults to STATIC_ROOT` khi collectstatic | Thiếu `STATIC_ROOT` trong local_settings — thêm như bước 6 |
| `redis.exceptions.AuthenticationError: HELLO must be called...` | Redis có mật khẩu — thêm `:<mật khẩu>@` vào mọi URL redis trong local_settings |
| `Access denied for user 'root'@'localhost'` khi vào MySQL | Dùng `sudo mysql --defaults-file=/etc/mysql/debian.cnf` |
| `createsuperuser` báo username đã tồn tại | Fixture `demo` đã tạo user `admin` — chỉ cần `changepassword admin` |
| Judge báo `unsupported operand type... NoneType` cho OBJC | Self-test Objective-C thiếu runtime, vô hại, judge tự bỏ qua |

## Ghi chú vận hành

- **Không commit** `dmoj/local_settings.py`, `judge.yml`, `~/.git-credentials` — chứa mật khẩu.
- Cập nhật code từ VNOI: `git fetch upstream && git merge upstream/master` (trên nhánh `custom` hoặc merge vào `master` trước rồi rebase).
- Sau khi sửa SCSS/JS phải chạy lại bước 7; sau khi kéo code mới nên chạy lại cả `migrate`.
- Lên production: xem hướng dẫn đầy đủ trong [DEPLOY.md](DEPLOY.md) (vnoj-docker + HTTPS + judge tách máy riêng).
- Tùy biến thương hiệu/giao diện/tính năng: xem [CUSTOMIZE.md](CUSTOMIZE.md).
