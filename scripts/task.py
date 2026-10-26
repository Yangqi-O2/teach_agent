#!/usr/bin/env python3
"""跨平台任务入口：macOS / Linux / Windows 用同一套命令。

    python scripts/task.py setup     # 安装后端与前端依赖
    python scripts/task.py start     # 构建前端（如需）并启动服务
    python scripts/task.py dev       # 后端热重载 + 前端 Vite
    python scripts/task.py build     # 只构建前端
    python scripts/task.py test      # 运行后端测试
    python scripts/task.py backup    # 打包 data/
    python scripts/task.py doctor    # 自检：环境、依赖、OCR 后端、数据目录

为什么用 Python 而不是继续写 shell
----------------------------------
原来的 scripts/*.sh 依赖 bash、`bin/python` 这类 POSIX 路径，Windows 上跑不了。
把逻辑收敛到一个 Python 脚本后：
- POSIX 交给 `scripts/*.sh` 这层薄包装（保持原有命令不变）；
- Windows 交给 `scripts/task.cmd`；
- 三条路径共用同一份实现，不会出现「.sh 和 .ps1 行为不一致」。

环境变量（都向后兼容原来的 shell 脚本）：
    HOST=127.0.0.1  PORT=8787  BUILD=1  PYTHON=python3.11  TJH_DATA_DIR=...
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "apps" / "server"
WEB = ROOT / "apps" / "web"
VENV = SERVER / ".venv"
IS_WINDOWS = os.name == "nt"

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = os.environ.get("PORT", "8787")


# ---------------------------------------------------------------- 基础工具

def log(message: str) -> None:
    print(f"▸ {message}", flush=True)


def fail(message: str) -> NoReturn:
    print(f"✗ {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def venv_python() -> Path:
    """venv 里的解释器路径。Windows 是 Scripts\\python.exe，其他是 bin/python。"""
    if IS_WINDOWS:
        candidate = VENV / "Scripts" / "python.exe"
        return candidate if candidate.exists() else VENV / "Scripts" / "python"
    return VENV / "bin" / "python"


def venv_bin(name: str) -> Path:
    folder = "Scripts" if IS_WINDOWS else "bin"
    suffix = ".exe" if IS_WINDOWS else ""
    return VENV / folder / f"{name}{suffix}"


def run(
    command: list[str | Path],
    *,
    cwd: Path | None = None,
    check: bool = True,
    extra_env: dict[str, str] | None = None,
) -> int:
    printable = " ".join(str(part) for part in command)
    log(printable)
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd) if cwd else None,
        env=env,
    )
    if check and proc.returncode != 0:
        fail(f"命令失败（退出码 {proc.returncode}）：{printable}")
    return proc.returncode


def capture(command: list[str | Path], *, cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(
            [str(part) for part in command],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return (proc.stdout or "").strip() or (proc.stderr or "").strip()


def base_python() -> str:
    """建 venv 用的解释器。

    优先挑 3.11/3.12：项目依赖是在这个区间验证的。系统只有 3.13+ 时也能用，
    但会提示一句——比悄悄装出一个没验证过的环境更好。
    """
    requested = os.environ.get("PYTHON")
    if requested:
        resolved = shutil.which(requested)
        if not resolved:
            fail(f"找不到 {requested}，请安装 Python 3.11+ 或用 PYTHON=/path/to/python 指定")
        return resolved

    for name in ("python3.12", "python3.11"):
        found = shutil.which(name)
        if found:
            return found

    if sys.version_info < (3, 11):
        fail(
            "需要 Python 3.11 或更高版本，当前是 "
            f"{sys.version_info.major}.{sys.version_info.minor}。"
            "可以用 PYTHON=/path/to/python3.11 指定解释器。"
        )
    if sys.version_info >= (3, 13):
        log(
            f"没有找到 3.11/3.12，将使用 Python "
            f"{sys.version_info.major}.{sys.version_info.minor} 创建环境"
        )
        log("项目主要在 3.11/3.12 上验证；若安装依赖报错，用 PYTHON=python3.11 重新运行")
    return sys.executable


def package_manager() -> str:
    """优先 pnpm（有 lockfile），没有就用 npm——Windows 上 npm 通常现成可用。"""
    for name in ("pnpm", "npm"):
        if shutil.which(name):
            return name
    fail("找不到 pnpm 或 npm，请先安装 Node.js 18+（https://nodejs.org）")
    return "npm"


# ---------------------------------------------------------------- 子命令

def requirements_stamp() -> Path:
    return VENV / ".requirements-stamp"


def ensure_backend(force: bool = False) -> None:
    """确保 venv 就绪。

    只在「venv 不存在」或「requirements.txt 变过」时才 pip install。
    之前每次启动都全量重装一遍依赖，启动要等十几秒，没必要。
    """
    created = False
    if not venv_python().exists():
        log("首次运行，创建 Python 虚拟环境…")
        run([base_python(), "-m", "venv", str(VENV)])
        created = True

    requirements = SERVER / "requirements.txt"
    stamp = requirements_stamp()
    stale = not stamp.exists() or requirements.stat().st_mtime > stamp.stat().st_mtime
    if not (force or created or stale):
        return

    log("安装后端依赖…")
    run([venv_python(), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    run([venv_python(), "-m", "pip", "install", "-q", "-r", str(requirements)])
    stamp.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")


def web_ready() -> bool:
    """前端依赖是否可用。只判断关键包，避免误判后白白重装。"""
    return (WEB / "node_modules" / "vite" / "package.json").exists()


def ensure_web_deps(force: bool = False) -> None:
    """安装前端依赖。

    已经装好就跳过：`pnpm install` 在无 TTY 环境下遇到版本差异会要求清空
    node_modules 并中止（ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY），
    为了一个本来能用的依赖树去冒险重装不值得。CI=true 让它在需要时能非交互执行。
    """
    if web_ready() and not force:
        return
    log("安装前端依赖…")
    run([package_manager(), "install"], cwd=WEB, extra_env={"CI": "true"})


def cmd_setup(args: argparse.Namespace) -> None:
    # 不加 force：requirements 没变就不重装，setup 才能反复执行而不浪费时间
    ensure_backend(force=args.force)
    ensure_web_deps(force=args.force)
    log("完成。下一步：python scripts/task.py start")


def build_frontend(force: bool = False) -> None:
    ensure_web_deps()
    if force or not (WEB / "dist" / "index.html").exists():
        log("构建前端…")
        run([package_manager(), "run", "build"], cwd=WEB)


def cmd_build(args: argparse.Namespace) -> None:
    build_frontend(force=args.force)


def cmd_start(args: argparse.Namespace) -> None:
    ensure_backend()
    build_frontend(force=args.build or os.environ.get("BUILD") == "1")
    serve(reload=False, host=args.host, port=str(args.port))


def cmd_dev(args: argparse.Namespace) -> None:
    """后端 --reload + 前端 Vite。两个子进程，Ctrl+C 一起收。"""
    ensure_backend()
    ensure_web_deps()

    backend = subprocess.Popen(
        [
            str(venv_python()),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--reload",
        ],
        cwd=str(SERVER),
    )
    frontend = subprocess.Popen([package_manager(), "run", "dev"], cwd=str(WEB))
    log(f"后端 http://{args.host}:{args.port} · 前端由 Vite 提供（见下方端口）")
    try:
        while backend.poll() is None and frontend.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (frontend, backend):
            if proc.poll() is None:
                proc.terminate()
        print()


def cmd_test(args: argparse.Namespace) -> None:
    ensure_backend()
    command: list[str | Path] = [venv_python(), "-m", "pytest", "-q"]
    if args.expression:
        command.append(args.expression)
    run(command, cwd=SERVER)


def cmd_backup(_: argparse.Namespace) -> None:
    """打包 data/。不依赖 tar，Windows 上也能跑。"""
    import tarfile

    data_dir = Path(os.environ.get("TJH_DATA_DIR") or (ROOT / "data"))
    if not data_dir.exists():
        fail(f"数据目录不存在：{data_dir}")
    target_dir = ROOT / "backups"
    target_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"tianjianhu-{stamp}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(data_dir, arcname="data")
    size_mb = target.stat().st_size / 1024 / 1024
    log(f"已备份到 {target}（{size_mb:.1f} MB）")
    log("换机时把 data/ 放回原位即可继续用；secret.key 必须一起带走，否则已存的 API Key 解不开。")


def cmd_doctor(_: argparse.Namespace) -> None:
    log(f"平台：{sys.platform} · Python {sys.version.split()[0]}")
    node = capture(["node", "--version"]) or "未安装"
    log(f"Node：{node} · 包管理器：{package_manager()}")
    log(f"虚拟环境：{'已创建' if venv_python().exists() else '未创建（运行 setup）'}")
    log(f"前端产物：{'已构建' if (WEB / 'dist' / 'index.html').exists() else '未构建（运行 build）'}")

    data_dir = Path(os.environ.get("TJH_DATA_DIR") or (ROOT / "data"))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe_file = data_dir / ".write-test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        log(f"数据目录：{data_dir}（可写）")
    except OSError as exc:
        log(f"数据目录：{data_dir}（不可写：{exc}）")

    if not venv_python().exists():
        log("OCR：跳过探测（后端依赖未安装）")
        return
    raw = capture(
        [
            venv_python(),
            "-c",
            "import json;from app.capabilities.library import ocr;"
            "print(json.dumps(ocr.probe(), ensure_ascii=False))",
        ],
        cwd=SERVER,
    )
    try:
        info = json.loads(raw.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        log(f"OCR：探测失败（{raw[:120]}）")
        return
    log(
        "OCR：引擎={engine} 栅格化={raster} PDF就绪={ready} 平台={platform}".format(
            engine=info.get("preferred") or "无",
            raster=info.get("rasterizer") or "无",
            ready="是" if info.get("pdf_ready") else "否",
            platform=info.get("platform"),
        )
    )
    if info.get("hint"):
        log(f"提示：{info['hint']}")


def serve(*, reload: bool, host: str, port: str) -> None:
    command = [venv_python(), "-m", "uvicorn", "app.main:app", "--host", host, "--port", port]
    if reload:
        command.append("--reload")
    log(f"天健湖启动中： http://{host}:{port}")
    try:
        run(command, cwd=SERVER)
    except KeyboardInterrupt:
        print()


# ---------------------------------------------------------------- 入口

def main() -> None:
    parser = argparse.ArgumentParser(
        description="天健湖跨平台任务入口（macOS / Linux / Windows 通用）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_runtime_args(target: argparse.ArgumentParser) -> None:
        """把 --host/--port 挂在子命令上，而不是全局。

        这样 `task.py start --port 9000`（最自然的写法）能正常工作；
        挂在全局的话必须写成 `task.py --port 9000 start`，容易踩坑。
        """
        target.add_argument("--host", default=HOST)
        target.add_argument("--port", default=PORT)

    setup = sub.add_parser("setup", help="安装后端与前端依赖")
    setup.add_argument("--force", action="store_true", help="强制重装前端依赖")
    setup.set_defaults(func=cmd_setup)
    start = sub.add_parser("start", help="构建前端（如需）并启动服务")
    start.add_argument("--build", action="store_true", help="强制重新构建前端")
    add_runtime_args(start)
    start.set_defaults(func=cmd_start)
    dev = sub.add_parser("dev", help="后端热重载 + 前端 Vite")
    add_runtime_args(dev)
    dev.set_defaults(func=cmd_dev)
    build = sub.add_parser("build", help="只构建前端")
    build.add_argument("--force", action="store_true")
    build.set_defaults(func=cmd_build)
    test = sub.add_parser("test", help="运行后端测试")
    test.add_argument("expression", nargs="?", help="可选的 pytest 表达式，如 tests/test_campus.py")
    test.set_defaults(func=cmd_test)
    sub.add_parser("backup", help="打包 data/ 到 backups/").set_defaults(func=cmd_backup)
    sub.add_parser("doctor", help="自检环境与 OCR 后端").set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
