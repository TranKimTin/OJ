# TinOJ — Hướng dẫn deploy production

Tiếp nối [SETUP.md](SETUP.md) (môi trường dev thủ công). File này hướng dẫn đưa TinOJ
lên VPS chạy thật bằng **vnoj-docker** cho phần site, và judge cài from source trên máy riêng.

> ✅ Đã kiểm chứng trên VPS thật (Ubuntu 24.04, 4GB RAM, 2026-07-09): site + judge chung VPS
> + Piston + backup đều chạy, đã chấm AC bài đầu tiên qua đúng luồng web.
> Riêng mục 5 (HTTPS/certbot — cần domain) và biến thể nhiều máy chấm là chưa thử.

## Kiến trúc production

```
Internet ──► nginx (host, HTTPS) ──► docker compose         VPS #2 (judge)
                                     ├─ site (Django)        ┌────────────┐
                                     ├─ nginx (nội bộ)  9999 │ dmoj judge │
                                     ├─ bridged ◄────────────┤ (source)   │
                                     ├─ db (MySQL)           └────────────┘
                                     ├─ redis / celery
                                     └─ wsevent (websocket)
```

- **VPS #1 (site)**: Ubuntu 22.04/24.04, tối thiểu 2GB RAM (4GB thoải mái), domain trỏ A record về IP.
- **VPS #2 (judge)**: 2 vCPU / 2GB là đủ khởi đầu. Eo hẹp thì chạy judge chung VPS #1 cũng được
  (chấp nhận cách ly kém hơn — xem ghi chú bảo mật cuối file).

## 1. Cài Docker trên VPS site

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # đăng xuất/vào lại để có hiệu lực
```

## 2. Clone vnoj-docker và trỏ sang fork của bạn

Mã nguồn site nằm ở submodule `dmoj/repo` (mặc định trỏ về VNOI-Admin/OJ).
Đổi nó sang fork + nhánh `custom` của bạn:

```bash
git clone --recursive https://github.com/VNOI-Admin/vnoj-docker.git
cd vnoj-docker/dmoj/repo
git remote set-url origin https://github.com/TranKimTin/OJ.git
git fetch origin
git checkout custom
git submodule update --init --recursive
cd ..   # quay về vnoj-docker/dmoj
```

> Về lâu dài nên fork luôn `vnoj-docker` và sửa `.gitmodules` trỏ thẳng vào
> `TranKimTin/OJ` — mọi chỉnh sửa compose/nginx được lưu vào git của bạn.

## 3. Khởi tạo cấu hình

```bash
./scripts/initialize

cp environment/mysql-admin.env.example environment/mysql-admin.env
cp environment/mysql.env.example       environment/mysql.env
cp environment/site.env.example        environment/site.env
```

Sửa từng file:

- `environment/mysql.env` + `mysql-admin.env`: đặt mật khẩu MySQL mạnh.
- `environment/site.env`: đặt `SECRET_KEY` mới (sinh bằng
  `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`) và host = domain của bạn.
- `nginx/conf.d/nginx.conf`: sửa `server_name` thành domain của bạn.

## 4. Build và khởi tạo database

```bash
# Build image base TRƯỚC: các image khác FROM vnoj/vnoj-base:latest — image này chỉ có
# local, không có trên Docker Hub. Build cả cụm ngay sẽ fail vì BuildKit đi pull nó về.
docker compose build base
docker compose build          # lần đầu rất lâu (build image site)

docker compose up -d site db redis celery
./scripts/migrate
./scripts/copy_static   # thấy "cp: cannot stat 'logo.png'" là bình thường (repo không có logo.png ở gốc)

# Production KHÔNG load fixture demo (nó tạo admin/admin + bài mẫu)
./scripts/manage.py loaddata navbar
./scripts/manage.py loaddata language_small
./scripts/manage.py createsuperuser

docker compose up -d          # bật toàn bộ dịch vụ
```

Đến đây site chạy ở port 80 của VPS (HTTP).

## 5. HTTPS

Cách gọn nhất: để compose bind vào port nội bộ, đặt nginx của host + certbot đứng trước.

1. Sửa mapping port của service nginx trong `docker-compose.yml`:
   `80:80` → `127.0.0.1:8080:80`, rồi `docker compose up -d`.
2. Cài nginx + certbot trên host:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

3. Tạo `/etc/nginx/sites-available/tinoj`:

```nginx
server {
    listen 80;
    server_name oj.example.com;   # domain của bạn

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # websocket (live update trạng thái chấm bài)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/tinoj /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d oj.example.com   # tự cấp và gia hạn SSL
```

## 6. Nối judge từ máy riêng

**Trên VPS site:**

1. Sửa port mapping của bridge: compose **mặc định đã publish cả `9998:9998` lẫn
   `9999:9999` ra mọi interface**. Port 9999 (judge kết nối) giữ nguyên; port 9998
   (API nội bộ site→bridge, không có xác thực) phải sửa thành `127.0.0.1:9998:9998`
   hoặc xóa hẳn mapping (các container nói chuyện qua network nội bộ của compose,
   không cần publish). Xong chạy `docker compose up -d bridged`.
2. Firewall chỉ cho IP của máy judge vào port 9999:

```bash
sudo ufw allow from <IP_MÁY_JUDGE> to any port 9999 proto tcp
```

3. Đăng ký judge:

```bash
./scripts/manage.py addjudge judge-prod-1 '<JUDGE_KEY>'
```

**Trên máy judge:** judge **từ chối chạy bằng root** («running the judge as root is
unsafe») nên phải có user thường trước:

```bash
adduser --disabled-password --gecos "" judge
```

Rồi cài đúng như [SETUP.md](SETUP.md) mục 10 (libseccomp, venv, `pip install -e .`,
`dmoj-autoconf`, `judge.yml`) **bằng user `judge`, trong `/home/judge`** — cài xong
đừng di chuyển thư mục, venv chứa đường dẫn tuyệt đối, move là hỏng. Chỉ khác
lệnh chạy — trỏ về VPS site:

```bash
./venv/bin/dmoj -c judge.yml <IP_HOẶC_DOMAIN_VPS_SITE>
```

**Đồng bộ test bài:** test upload qua web nằm trong volume problems của VPS site,
judge cần bản sao trong `problem_storage_globs` của nó. Cách đơn giản: rsync mỗi khi thêm bài

```bash
rsync -avz --delete vps-site:/path/to/problems/ /home/judge/problems/
```

(hoặc cron 5 phút/lần; xịn hơn thì NFS/sshfs mount chung).

**Chạy judge như service** (tự khởi động lại khi rớt) — tạo `/etc/systemd/system/dmoj-judge.service`:

```ini
[Unit]
Description=DMOJ Judge
After=network.target

[Service]
User=judge
WorkingDirectory=/home/judge/judge-server
ExecStart=/home/judge/judge-server/venv/bin/dmoj -c judge.yml <IP_VPS_SITE>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now dmoj-judge
```

### Biến thể: judge chạy chung VPS site (tiết kiệm, 1 máy duy nhất)

Khi chưa có VPS thứ hai, cài judge from source ngay trên VPS site, cạnh Docker:

1. Đưa bridge **về nội bộ**: trong `docker-compose.yml`, **sửa 2 mapping có sẵn**
   của service `bridged` thành `127.0.0.1:9998:9998` và `127.0.0.1:9999:9999`
   (mặc định chúng mở ra Internet — không cần và không nên), rồi
   `docker compose up -d bridged`. Không cần đụng firewall.
2. Tạo user `judge` (xem trên — judge không chạy bằng root) và cài như
   [SETUP.md](SETUP.md) mục 10, ngay trên VPS.
3. Trong `judge.yml`, trỏ `problem_storage_globs` **thẳng vào thư mục volume problems**
   của compose (`<chỗ clone vnoj-docker>/dmoj/problems/*`) — dùng chung dữ liệu test
   với site, không cần rsync. **Chú ý quyền đọc**: nếu vnoj-docker clone trong `/root`
   thì user `judge` không đọc nổi; hoặc clone vnoj-docker vào chỗ đọc được
   (vd `/opt/vnoj-docker`), hoặc cấp quyền qua ACL:

   ```bash
   apt install -y acl
   setfacl -m u:judge:x /root /root/vnoj-docker /root/vnoj-docker/dmoj
   setfacl -R -m u:judge:rX /root/vnoj-docker/dmoj/problems
   setfacl -R -d -m u:judge:rX /root/vnoj-docker/dmoj/problems   # default ACL cho bài thêm sau
   ```

4. Đăng ký và chạy: `./scripts/manage.py addjudge judge1 '<KEY>'`, rồi judge kết nối
   về `127.0.0.1` (dùng systemd service như trên, đổi `<IP_VPS_SITE>` thành `127.0.0.1`).

Đánh đổi: code người dùng nộp chạy cùng máy với database — sandbox của judge là lớp
bảo vệ duy nhất, và bài chấm lúc site đang tải nặng có thể đo thời gian kém ổn định.
Có điều kiện thì tách ra máy riêng theo mục 6, chỉ mất ~15 phút vì các bước giống hệt.

### Biến thể: nhiều máy chấm (scale khi tổ chức contest đông)

Kiến trúc DMOJ hỗ trợ sẵn nhiều judge — tất cả cùng kết nối vào một bridge,
bridge tự chia bài cho judge nào đang rảnh. Không phải sửa code hay config site.

Thêm mỗi judge mới:

1. **Mỗi judge một tên + key riêng** (không dùng chung key giữa các máy):

```bash
./scripts/manage.py addjudge judge-prod-2 '<KEY_RIÊNG_2>'
./scripts/manage.py addjudge judge-prod-3 '<KEY_RIÊNG_3>'
```

2. Cài từng máy giống hệt mục 6 (mỗi máy một `judge.yml` với id/key của nó,
   systemd service, cùng trỏ về `<IP_VPS_SITE>`).
3. Mở firewall cho từng IP judge:

```bash
sudo ufw allow from <IP_JUDGE_2> to any port 9999 proto tcp
```

4. **Đồng bộ test tới TẤT CẢ judge** — sửa script rsync thành vòng lặp đẩy tới cả đội:

```bash
for h in judge2.example.com judge3.example.com; do
  rsync -avz --delete /path/to/problems/ judge@$h:/home/judge/problems/
done
```

Lưu ý khi chạy nhiều judge:

- **Các máy judge nên cùng cấu hình CPU** (cùng loại VPS). Bridge không chuẩn hóa
  tốc độ giữa các máy — bài sát time limit có thể AC trên máy nhanh nhưng TLE trên
  máy chậm, gây kết quả không nhất quán.
- Judge nào cài thiếu runtime nào thì bridge sẽ không giao bài cần runtime đó cho nó —
  nên cài bộ compiler giống nhau trên mọi máy.
- Xem trạng thái cả đội judge: trang `/status/` của site, hoặc Admin → Judges
  (thấy judge nào online, tải, ping).
- Contest xong có thể tắt bớt judge thuê thêm (`systemctl stop dmoj-judge` rồi hủy VPS) —
  site không cần đụng gì, bản ghi judge trong admin để đó dùng lại lần sau.

## 6b. Piston — sandbox cho nút "Chạy thử sample" (tùy chọn)

Tính năng chạy thử sample/custom input trên trang đề cần một container Piston
chạy cạnh site (thiết kế chi tiết: `dev-plans/run-sample-tests.md`):

```bash
docker run -d --name piston --restart unless-stopped --privileged \
    -p 127.0.0.1:2000:2000 \
    -v $HOME/piston/packages:/piston/packages \
    -e PISTON_OUTPUT_MAX_SIZE=1048576 \
    ghcr.io/engineer-man/piston

# cài runtime (xem version có sẵn: GET /api/v2/packages)
for pkg in '{"language":"gcc","version":"10.2.0"}' '{"language":"python","version":"3.12.0"}' \
           '{"language":"python","version":"2.7.18"}' '{"language":"java","version":"15.0.2"}' \
           '{"language":"kotlin","version":"1.8.20"}' '{"language":"pascal","version":"3.2.2"}'; do
  curl -X POST http://localhost:2000/api/v2/packages -H 'Content-Type: application/json' -d "$pkg"
done
```

Site chạy trong Docker compose thì **bind Piston vào `172.17.0.1`** (gateway docker0 —
container trên mọi network của compose đều với tới được, đã kiểm chứng): trong lệnh
`docker run` ở trên thay `-p 127.0.0.1:2000:2000` bằng `-p 172.17.0.1:2000:2000`,
và các lệnh `curl` cài package cũng gọi `http://172.17.0.1:2000`. Rồi khai báo:

```bash
echo "VNOJ_PISTON_URL = 'http://172.17.0.1:2000'" >> repo/dmoj/local_settings.py
docker compose restart site
```

(Thêm cả vào `config/local_settings.py` — file gốc mà `scripts/initialize` copy ra —
để chạy lại initialize không bị mất dòng này.)
Không đặt biến này thì tính năng tự tắt, site hoạt động bình thường.

**Dung lượng đĩa**: package `gcc` giải nén cỡ ~4GB, `python` ~1GB — kiểm tra
`df -h` trước khi cài; đĩa đầy giữa chừng sẽ làm crash container Piston (và có thể
lây sang MySQL). Xóa package lỗi trong `$HOME/piston/packages/` rồi
`docker restart piston` là hồi.

**Lưu ý bảo mật**: chỉ bind Piston vào interface nội bộ, tuyệt đối không mở
port 2000 ra Internet — đó là một endpoint thực thi code tùy ý.

## 7. Backup (cron hằng ngày trên VPS site)

```bash
# database — 2 chú ý: image mariadb KHÔNG có lệnh `mysqldump` (dùng `mariadb-dump`),
# và $MYSQL_ROOT_PASSWORD phải nở BÊN TRONG container (escape \$) vì host không có biến này
docker compose exec -T db sh -c "mariadb-dump -uroot -p\"\$MYSQL_ROOT_PASSWORD\" dmoj" | gzip > backup/db-$(date +%F).sql.gz
# test bài + media (đường dẫn volume xem trong docker-compose.yml)
tar czf backup/problems-$(date +%F).tar.gz /path/to/problems /path/to/media
# giữ 7 bản gần nhất
ls -t backup/db-*.gz | tail -n +8 | xargs -r rm
```

Nên rsync thư mục `backup/` sang máy khác (backup nằm cùng VPS thì cháy là mất cả hai).

## 8. Quy trình cập nhật code sau này

Dev ở máy nhà → push nhánh `custom` → trên VPS:

```bash
cd vnoj-docker/dmoj/repo && git pull
cd ..
docker compose build site
./scripts/migrate        # nếu có migration mới
./scripts/copy_static    # nếu có sửa giao diện
docker compose up -d
```

Lấy cập nhật từ VNOI upstream: merge `upstream/master` vào `custom` ở máy dev,
test kỹ ở local trước rồi mới push + deploy.

## Lỗi đã gặp khi kiểm chứng

| Lỗi | Nguyên nhân / cách xử lý |
|---|---|
| `docker compose build` báo `pull access denied ... vnoj/vnoj-base` | Image base chỉ build local — chạy `docker compose build base` trước (đã ghi ở mục 4) |
| Warning `the attribute "version" is obsolete` mỗi lệnh compose | Vô hại; muốn hết thì xóa dòng `version: '3.7'` đầu `docker-compose.yml` |
| apt báo `Could not get lock /var/lib/dpkg/lock-frontend` | unattended-upgrade đang giữ khóa — thường chờ là xong; kiểm tra `ps -o etime -p <PID>`, nếu kẹt nhiều ngày thì `kill` rồi chạy `dpkg --configure -a` |
| Judge crash-loop `running the judge as unsafe...root` | Judge không chạy bằng root — dùng user thường trong systemd unit (`User=judge`) |
| `ModuleNotFoundError: No module named 'dmoj'` khi chạy judge | Thư mục judge-server bị move sau khi `pip install -e .` — venv chứa đường dẫn tuyệt đối; cài lại đúng chỗ, đừng move |
| Đĩa cạn dần trong lúc vận hành | `docker builder prune -af` (dọn cache build) và `journalctl --vacuum-size=200M` (journald có thể phình vài GB) |

## 9. Checklist bảo mật trước khi mở công khai

- [ ] `DEBUG = False`, `SECRET_KEY` sinh mới (không dùng lại key dev)
- [ ] Không load fixture `demo`; nếu lỡ load: đổi mật khẩu hoặc xóa user `admin`
- [ ] Mật khẩu MySQL/Redis mạnh, không trùng với dev
- [ ] Firewall: chỉ mở 80/443, SSH (nên đổi port + tắt password login), 9999 chỉ cho IP judge
- [ ] Port 9998 (API bridge) không bind ra ngoài — `127.0.0.1` hoặc xóa mapping (mặc định compose mở ra Internet!)
- [ ] HTTPS hoạt động, HTTP redirect sang HTTPS
- [ ] Backup tự động đã chạy thử và **khôi phục thử** thành công ít nhất 1 lần
- [ ] Nếu judge chạy chung VPS site: hiểu rằng sandbox judge là lớp phòng thủ duy nhất
      giữa code người lạ và database — nên tách máy ngay khi có điều kiện
