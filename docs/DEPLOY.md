# 天健湖 · 部署与上线

> **这份文档讲什么**：把天健湖部署到 macOS / Linux / Windows / Docker 的完整步骤，以及上线前的安全清单。
> **路径**：`docs/DEPLOY.md`
> **配套文件**：`deploy/nginx/tianjianhu.{macos,linux}.conf`、`deploy/nginx/security-headers.conf`、
> `deploy/systemd/tianjianhu.service`、`deploy/install_nginx.py`、`Dockerfile`、`docker-compose.yml`

## 先选一条路线

| 你的情况 | 走这条 | 需要装什么 |
|---|---|---|
| 只想跑起来看效果（任意系统） | **A. Docker** | Docker Desktop 或 Docker Engine |
| 有一台 Linux 服务器 | **B. Linux 原生** | Python 3.11/3.12、Node 18+、tesseract |
| 在 Mac 上用 | **C. macOS 原生** | Python 3.11/3.12、Node 18+、Xcode 命令行工具（OCR 用） |
| 在 Windows 上用 | **D. Windows 原生** | Python 3.11+、Node 18+、Tesseract 安装包 |

> 所有路线的运行期数据都在**一个目录**里（默认仓库根 `data/`，可用 `TJH_DATA_DIR` 改）。
> 打包这个目录就是完整备份；换机放回原位即可继续用。
> **`secret.key` 必须一起带走**，否则已保存的 API Key 解不开。

---

## 通用：跨平台任务入口

不管哪个系统，安装与启动都收敛到一个脚本：

```bash
python3 scripts/task.py setup     # 装依赖（后端 venv + 前端 node_modules）
python3 scripts/task.py start     # 构建前端（如需要）并启动，默认 127.0.0.1:8787
python3 scripts/task.py doctor    # 自检：环境、依赖、OCR 后端、数据目录
```

Windows 用同一条命令（或 `scripts\task.cmd setup`）。POSIX 系统也可以继续用熟命令：

```bash
./scripts/setup.sh      # = task.py setup
./scripts/start.sh      # = task.py start      （BUILD=1 强制重建前端）
./scripts/dev.sh        # = task.py dev        （后端热重载 + 前端 Vite）
make start / make test / make doctor / make backup
```

环境变量：`HOST`、`PORT`、`BUILD`、`PYTHON`、`TJH_DATA_DIR`（全部向后兼容旧脚本）。
第一次 `setup` 后，`requirements.txt` 没变就不会重复安装，启动是秒级。

---

## A. Docker（跨平台最省事）

```bash
docker compose up -d --build
# 打开 http://127.0.0.1:8787
```

镜像已经处理好平台差异：容器内用 tesseract 做 OCR，不依赖 macOS 的 Vision；
`./data` 挂载到容器 `/data`，删容器不丢数据。

单容器等价命令：

```bash
docker build -t tianjianhu:0.3.0 .
docker run -d -p 8787:8787 -v "$PWD/data:/data" --name tianjianhu tianjianhu:0.3.0
```

说明：
- 容器默认 `TJH_ENV=production`，`/api/docs` 是关的；
- 前面有 nginx/Caddy 做 TLS 时，把 `TJH_COOKIE_SECURE` 改成 `"true"`；
- 校园雷达需要出网，容器默认允许；如要禁网请关掉 `TJH_CAMPUS_SCHEDULER` 并改用外部投递。

---

## B. Linux 原生

```bash
sudo apt install -y python3.11 python3.11-venv nginx \
                    tesseract-ocr tesseract-ocr-chi-sim       # Debian/Ubuntu
# Fedora/RHEL：sudo dnf install python3.11 nginx tesseract tesseract-langpack-chi_sim
# Arch：      sudo pacman -S python nginx tesseract tesseract-data-chi_sim

# Node 18+（用发行版仓库或 nodesource），然后
cd /opt/tianjianhu
python3 scripts/task.py setup
python3 scripts/task.py doctor        # 确认 OCR 引擎=tesseract、PDF就绪=是
```

**前端构建 + 启动**：`python3 scripts/task.py start` 会构建 `apps/web/dist` 并监听 `127.0.0.1:8787`。

**做成服务（开机自启）**：

```bash
sudo cp deploy/systemd/tianjianhu.service /etc/systemd/system/
sudo sed -i "s|<SITE_ROOT>|/opt/tianjianhu|g; s|<USER>|tianjianhu|g" /etc/systemd/system/tianjianhu.service
sudo systemctl daemon-reload && sudo systemctl enable --now tianjianhu
journalctl -u tianjianhu -f
```

**nginx 反代**（对外 80/443，后端只听本机）：

```bash
sudo python3 deploy/install_nginx.py --domain example.com
```

脚本会按平台自动选 `tianjianhu.linux.conf`、替换占位符、备份原配置，`nginx -t` 不通过会自动回滚。

> 抓取需要出网。如果服务器在受限网络里，校园雷达会显示 `error` 并在下轮重试，不影响其他功能。

---

## C. macOS 原生

```bash
brew install python@3.12 node nginx
xcode-select --install          # 可选但强烈建议：OCR 走系统 Vision，中文识别更好且不用装 tesseract

cd <仓库目录>
python3 scripts/task.py setup
python3 scripts/task.py start
```

**nginx**：

```bash
python3 deploy/install_nginx.py --domain example.com
# 只预览不写入：--domain example.com --dry-run
# 回滚：      --uninstall
```

Homebrew 的 nginx 配置在 `/opt/homebrew/etc/nginx/nginx.conf`（Apple Silicon）
或 `/usr/local/etc/nginx/nginx.conf`（Intel），脚本会自动识别。

**开机自启**：`brew services start nginx`；后端用 launchd plist，或直接把 `scripts/task.py start` 包一层。

macOS 上 OCR 不需要装任何东西：首次使用时用 `swiftc` 编译一个小工具到 `data/cache/ocr/`，
之后按页计费（实测密集中文约 0.4 秒/页）。没有 `swiftc` 时会自动退回 tesseract。

---

## D. Windows 原生

```powershell
# 1. 装 Python 3.11+（勾选 "Add python.exe to PATH"）与 Node 18+
# 2. 装 Tesseract（含 chi_sim 中文包）
#    https://github.com/UB-Mannheim/tesseract/wiki
#    安装时勾选 "Add to PATH"；没勾就设环境变量指向可执行文件：
set TJH_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# 3. 安装与启动
cd <仓库目录>
python scripts\task.py setup
python scripts\task.py doctor
python scripts\task.py start
```

浏览器打开 http://127.0.0.1:8787 。

Windows 上不需要 nginx 也能局域网访问：`set HOST=0.0.0.0` 后再 start，
然后在防火墙里放行 8787 端口。想对外提供 HTTPS，建议用 Caddy（自带证书申请）或直接上 Docker。

开机自启可以用「任务计划程序」新建一个登录时运行 `python scripts\task.py start` 的任务，
或用 [NSSM](https://nssm.cc/) 把它注册成 Windows 服务。

---

## 平台差异一览

| 项目 | macOS | Linux | Windows |
|---|---|---|---|
| 启动入口 | `scripts/task.py` / `*.sh` | `scripts/task.py` / `*.sh` / systemd | `scripts\task.py` / `task.cmd` |
| OCR 识别 | 系统 Vision（推荐）或 tesseract | tesseract | tesseract |
| OCR 栅格化 | Vision 一站式 | pypdfium2（pip 自带） | pypdfium2（pip 自带） |
| 装 tesseract | `brew install tesseract tesseract-lang` | `apt/dnf/pacman` | 安装包 + `TJH_TESSERACT_CMD` |
| 反代 | `deploy/install_nginx.py`（Homebrew 路径） | 同左（`/etc/nginx`） | 建议 Caddy 或 Docker |
| 数据目录 | 仓库根 `data/` | 同左（建议 `/var/lib/tianjianhu`） | `data\` |

`python3 scripts/task.py doctor` 会直接打印当前平台实际用的是哪个 OCR 后端，不用猜。

---

## 上线安全清单（所有平台都要过一遍）

- [ ] `TJH_ENV=production` → `/api/docs` 自动关闭
- [ ] 上 HTTPS 后 `TJH_COOKIE_SECURE=true`
- [ ] 上 HTTPS 后 `TJH_HSTS_SECONDS=31536000`
- [ ] 首个管理员建好后，在「成员管理」里关闭自助注册
- [ ] 确认响应头有 `Content-Security-Policy` / `X-Frame-Options`
- [ ] 确认 `/api/docs` 返回 404
- [ ] `data/` 权限 700，且不在任何静态目录下
- [ ] 备份已生效：`python3 scripts/task.py backup`（跨平台，不依赖 tar）

---

## 校园雷达的出网要求

抓取要能访问目标学校站点，部署前确认：

```bash
curl -I https://www.zzu.edu.cn/index/tzgg.htm     # 期望 200
```

- 只在「立即更新」或到点时才发请求，不会持续打对方站点；
- 单源失败只记 `error` 并在下轮重试，不影响其他源；
- 断网/内网演示：管理面板点「导入示例数据」（带「示例」标记，可随时清除）；
- 单次默认最多抓 24 篇详情，可在管理面板调低；
- 不想用内置定时器：`TJH_CAMPUS_SCHEDULER=0`，只保留手动更新。

---

## 常见坑

**通用**
- **改了前端代码但页面没变化**：`dist/` 是构建产物，必须 `BUILD=1 ./scripts/start.sh`
  或 `python3 scripts/task.py build`。Windows 同理。
- **登录后立刻被踢回登录页**：多半是 HTTPS + 没设 `TJH_COOKIE_SECURE=true`。
- **页面白屏、控制台报 CSP 拦截**：检查是否往 `index.html` 加了内联 `<script>`。
  主题引导脚本已外置到 `public/theme-init.js`，新增内联脚本会破坏 `script-src 'self'`。
- **扫描件提示「没有可用的 OCR 引擎」**：跑 `python3 scripts/task.py doctor` 看具体缺什么；
  提示里会按当前平台给出可直接复制的安装命令。
- **pnpm 报 `ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`**：依赖树与 pnpm 版本不一致时，
  它想清空 `node_modules` 但拿不到确认。`task.py` 在依赖已就绪时会跳过安装；
  真要重装就显式执行 `python3 scripts/task.py setup --force`。

**macOS**
- `nginx -t` 报 `could not open error log file / pid ... Operation not permitted`：
  说明在受限环境（App 沙箱里的终端）执行，换 iTerm / 系统「终端」。
- nginx 起不来先 `mkdir -p /opt/homebrew/var/log/nginx`。

**Linux**
- systemd 启动失败看 `journalctl -u tianjianhu -n 50`；常见是 `User=` 不存在或
  `data/` 目录属主不对（`sudo chown -R tianjianhu:tianjianhu /opt/tianjianhu/data`）。
- SELinux（RHEL 系）下 nginx 反代 127.0.0.1 需要 `setsebool -P httpd_can_network_connect 1`。

**Windows**
- 提示找不到 `python`：重装时勾选 Add to PATH，或改用 `py -3 scripts\task.py start`。
- OCR 报找不到 tesseract：设 `TJH_TESSERACT_CMD` 指向 `tesseract.exe`，`doctor` 会显示是否识别到。
- 中文路径：建议仓库放在不含空格的路径下（如 `C:\tianjianhu`），避免少数依赖的路径解析问题。
