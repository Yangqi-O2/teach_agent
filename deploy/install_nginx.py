#!/usr/bin/env python3
"""把天健湖的 nginx 配置装到本机（macOS / Linux 通用）。

    python3 deploy/install_nginx.py --domain example.com          # 安装并重载
    python3 deploy/install_nginx.py --domain example.com --dry-run # 只生成，不动系统
    python3 deploy/install_nginx.py --uninstall                    # 回滚到备份

做的事：
1. 按平台选配置模板（macOS → tianjianhu.macos.conf，Linux → tianjianhu.linux.conf）
2. 替换 <SITE_ROOT> 与 <DOMAIN>
3. 备份原有 nginx.conf（只在第一次备份，避免备份被覆盖成坏版本）
4. 写入配置，`nginx -t` 校验通过后才 reload；校验不过自动回滚
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONF_DIR = ROOT / "deploy" / "nginx"


def log(message: str) -> None:
    print(f"▸ {message}", flush=True)


def fail(message: str) -> None:
    print(f"✗ {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def target_conf() -> Path:
    """本机 nginx 主配置路径。"""
    if sys.platform == "darwin":
        for candidate in (
            Path("/opt/homebrew/etc/nginx/nginx.conf"),   # Apple Silicon
            Path("/usr/local/etc/nginx/nginx.conf"),      # Intel
        ):
            if candidate.exists() or candidate.parent.exists():
                return candidate
        return Path("/opt/homebrew/etc/nginx/nginx.conf")
    return Path("/etc/nginx/nginx.conf")


def template(platform: str) -> Path:
    name = "tianjianhu.macos.conf" if platform == "darwin" else "tianjianhu.linux.conf"
    path = CONF_DIR / name
    if not path.exists():
        fail(f"找不到模板：{path}")
    return path


def render(platform: str, site_root: Path, domain: str) -> str:
    text = template(platform).read_text(encoding="utf-8")
    text = text.replace("<SITE_ROOT>", str(site_root))
    text = text.replace("<DOMAIN>", domain or "_")
    # 占位符要替换干净，残留会导致 nginx 起不来且报错不直观
    for leftover in ("<SITE_ROOT>", "<DOMAIN>"):
        if leftover in text:
            fail(f"配置里仍有未替换的占位符：{leftover}")
    return text


def nginx_bin() -> str | None:
    return shutil.which("nginx")


def run_nginx(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    binary = nginx_bin()
    if not binary:
        fail("找不到 nginx，请先安装（macOS: brew install nginx / Debian: sudo apt install nginx）")
    proc = subprocess.run([binary, *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        fail(f"nginx {' '.join(args)} 失败：\n{proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def ensure_log_dir(platform: str) -> None:
    directory = Path("/opt/homebrew/var/log/nginx") if platform == "darwin" else Path("/var/log/nginx")
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"无法创建日志目录 {directory}（{exc}），如果 nginx 起不来请手动 mkdir -p")


def install(site_root: Path, domain: str, *, dry_run: bool) -> None:
    platform = sys.platform
    conf = target_conf()
    content = render(platform, site_root, domain)

    if dry_run:
        preview = CONF_DIR / "generated.conf"
        preview.write_text(content, encoding="utf-8")
        log(f"已生成预览：{preview}")
        return

    ensure_log_dir(platform)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    first_backup = conf.with_suffix(conf.suffix + ".bak")
    if conf.exists() and not first_backup.exists():
        shutil.copy2(conf, first_backup)
        log(f"已备份原始配置 → {first_backup}")
    rollback = conf.with_suffix(conf.suffix + f".bak-{stamp}")
    if conf.exists():
        shutil.copy2(conf, rollback)
        log(f"本次备份 → {rollback}")

    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(content, encoding="utf-8")
    log(f"已写入 {conf}")

    # 先校验再重载：校验不过就还原，别把一个起不来的配置留在系统里
    check = run_nginx(["-t"], check=False)
    if check.returncode != 0:
        if rollback.exists():
            shutil.copy2(rollback, conf)
            log("配置校验失败，已自动回滚到安装前的版本")
        fail(check.stderr.strip() or check.stdout.strip())
    log("nginx -t 通过")

    reload_proc = run_nginx(["-s", "reload"], check=False)
    if reload_proc.returncode != 0:
        log("reload 失败，尝试启动 nginx…")
        run_nginx(["-c", str(conf)], check=False)
    log("完成。验证：")
    print("    curl -i http://127.0.0.1/api/health")
    print(f"    浏览器打开 http://{ '127.0.0.1' if domain == '_' else domain }/")


def uninstall() -> None:
    conf = target_conf()
    backup = conf.with_suffix(conf.suffix + ".bak")
    if not backup.exists():
        fail(f"没有找到备份：{backup}")
    shutil.copy2(backup, conf)
    log(f"已还原 {conf}")
    run_nginx(["-t"])
    run_nginx(["-s", "reload"], check=False)
    log("已回滚并重载")


def main() -> None:
    parser = argparse.ArgumentParser(description="安装天健湖的 nginx 配置（macOS / Linux 通用）")
    parser.add_argument("--domain", default="_", help="域名或 IP；纯本地访问用默认 _")
    parser.add_argument("--root", default=str(ROOT), help="仓库根目录，默认自动检测")
    parser.add_argument("--dry-run", action="store_true", help="只生成预览，不改系统配置")
    parser.add_argument("--uninstall", action="store_true", help="回滚到安装前的备份")
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
        return
    install(Path(args.root).resolve(), args.domain, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
