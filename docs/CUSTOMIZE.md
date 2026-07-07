# TinOJ — Hướng dẫn tùy biến sau khi fork

Những chỗ cần đụng đến để biến VNOJ thành OJ mang thương hiệu riêng, xếp theo
thứ tự ưu tiên: **config → dữ liệu admin → template/SCSS → Python**.
Càng ở tầng trên càng dễ làm và càng ít gây conflict khi merge code mới từ VNOI.

## Tầng 1 — Không sửa code

### 1a. Qua `dmoj/local_settings.py`

| Muốn gì | Thêm/sửa dòng |
|---|---|
| Tên site (navbar, title, email...) | `SITE_NAME = 'TinOJ'` |
| Tên đầy đủ | `SITE_LONG_NAME = 'TinOJ: Online Judge'` |
| Email quản trị | `SITE_ADMIN_EMAIL = '...'` |
| Đăng nhập Google | `SOCIAL_AUTH_GOOGLE_OAUTH2_KEY` / `..._SECRET` (lấy từ Google Cloud Console) |
| Đăng nhập Facebook | `SOCIAL_AUTH_FACEBOOK_KEY` / `..._SECRET` |
| Đăng nhập GitHub | `SOCIAL_AUTH_GITHUB_SECURE_KEY` / `..._SECRET` |
| Gửi email (kích hoạt tài khoản, quên mật khẩu) | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS = True`, `DEFAULT_FROM_EMAIL` (Gmail thì dùng App Password) |

Sửa xong khởi động lại `runserver` là ăn.

### 1b. Qua trang Admin (http://127.0.0.1:8000/admin)

| Muốn gì | Vào đâu |
|---|---|
| Thêm/bớt/đổi menu navbar | Admin → **Navigation bar** |
| Trang Giới thiệu, Nội quy, FAQ... | Admin → **Flat pages** |
| **Logo** (không cần sửa code!) | Admin → **Misc config** → thêm key `site_logo`, value = URL ảnh logo |
| **Footer** | Misc config → key `footer` (nhận HTML) |
| Thông báo nổi đầu trang | Misc config → key `announcement` hoặc `top_notification` |
| Khối nội dung đầu trang chủ | Misc config → key `home_page_top` |
| SEO meta description/keywords | Misc config → key `meta_description`, `meta_keywords` |
| Google Analytics | Misc config → key `analytics` |
| Link mời Discord | Misc config → key `discord_invite_link` |

> Misc config là bảng key–value tự do — template nào có `{{ misc_config.xxx }}`
> thì key `xxx` dùng được. Danh sách trên là toàn bộ key hiện có trong templates.

## Tầng 2 — Nhận diện thương hiệu (sửa file tĩnh)

| Muốn gì | Sửa ở đâu |
|---|---|
| Logo mặc định (nếu không dùng misc_config) | thay file `resources/icons/logo.svg` |
| Favicon + icon mobile/PWA | thay bộ ảnh trong `resources/icons/` — **giữ nguyên tên file** (android-chrome-*.png, apple-touch-icon-*.png, favicon.ico...) |
| **Bảng màu toàn site** | `resources/vars-default.scss` (theme sáng) và `resources/vars-dark.scss` (theme tối). Đổi `$color_link*` (màu link/chủ đạo), `$color_primary*` (nền/chữ/viền) là cả site đổi theo |
| Bố cục trang chủ | `templates/home.html` |
| Khung chung mọi trang (header, footer HTML) | `templates/base.html` |
| Giao diện từng khu vực | `templates/problem/`, `templates/contest/`, `templates/user/`... |

**Sau khi sửa phải build lại:**

```bash
# sửa .scss (màu sắc):
./make_style.sh && ./venv/bin/python manage.py collectstatic --noinput
# sửa template .html: không cần gì, F5 là thấy (khi DEBUG=True)
# thay ảnh trong resources/: chỉ cần collectstatic
```

## Tầng 3 — Tính năng (sửa Python)

Khi muốn đổi *hành vi* chứ không chỉ bề ngoài. Bản đồ code:

- `judge/models/` — dữ liệu: bài tập, contest, user, submission, rating...
- `judge/views/` — logic từng trang
- `judge/judgeapi.py` — giao tiếp site ↔ bridge ↔ judge
- `dmoj/urls.py` — định tuyến URL
- `dmoj/settings.py` — mặc định toàn hệ thống (**đừng sửa trực tiếp** — override trong `local_settings.py` để tránh conflict khi merge upstream)

Lưu ý khi đổi models: phải tạo migration và giữ nó trong git

```bash
./venv/bin/python manage.py makemigrations && ./venv/bin/python manage.py migrate
```

## Quy tắc làm việc (để sau này merge code VNOI không khổ)

1. Mọi thay đổi commit lên nhánh `custom`, **mỗi thay đổi một commit riêng** có message rõ ràng.
2. Ưu tiên tầng 1 > tầng 2 > tầng 3 — không sửa code khi config/admin làm được.
3. Không bao giờ commit `dmoj/local_settings.py` (đã gitignore) — secrets nằm đó.
4. Định kỳ lấy cập nhật từ VNOI: `git fetch upstream && git merge upstream/master`,
   test kỹ ở local rồi mới deploy ([DEPLOY.md](DEPLOY.md) mục 8).
5. Sửa xong tầng 2/3 nhớ chạy lại bước build tương ứng trước khi kết luận "không ăn".

## Liên quan

- Dựng môi trường từ đầu: [SETUP.md](SETUP.md)
- Đưa lên production + cập nhật code: [DEPLOY.md](DEPLOY.md)
