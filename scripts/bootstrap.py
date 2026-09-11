#!/usr/bin/env python
"""一键启动驱动 — 阶段 6.1（goal §7 6.1；决策 D6）。

流程：检测 Python/Node → 建 .venv 装依赖 → 补 .env → 建库或补迁移
      → 构建前端 → 起后端（单端口托管前端）→ 打印局域网地址并开浏览器。

为什么逻辑不写在 start.bat 里（踩坑记录）：
  cmd.exe 读取批处理文件时，若文件是 UTF-8 且中途执行了 `chcp 65001`，
  在「控制台初始代码页不是 65001」的场景（= 用户双击，新控制台 CP936）
  会发生**行读取错位**：中文注释行的后半截被当作命令执行，实测报
  `'数据库' is not recognized as an internal or external command`。
  同一文件在 CP65001 的控制台里跑却完全正常（非确定性复现）。
  故 start.bat 只保留纯 ASCII 的两行引导（ASCII 字节数=字符数，错位无从发生），
  所有中文交互与判断集中在本脚本：既躲开 cmd 的解析缺陷，也让这套流程可被测试。

本脚本只用标准库，用**系统 Python** 运行（不是 .venv 里的），
所有需要在 venv 内执行的动作都以子进程方式调 .venv 的 python。

用法（一般由 start.bat 调用）：
  python -X utf8 scripts/bootstrap.py            # 一键启动
  python -X utf8 scripts/bootstrap.py 8080       # 指定端口
  python -X utf8 scripts/bootstrap.py --check    # 只自检与准备，不起服务
  python -X utf8 scripts/bootstrap.py --rebuild  # 强制重建前端产物
"""
from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "project" / "backend"
FRONTEND = ROOT / "project" / "frontend"
IS_WINDOWS = os.name == "nt"
VENV_DIR = BACKEND / ".venv"
VENV_PY = VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
DEPS_STAMP = VENV_DIR / ".deps-stamp"
REQUIREMENTS = BACKEND / "requirements.txt"
DB_PATH = BACKEND / "data" / "coc.db"
ENV_FILE = BACKEND / ".env"
ENV_EXAMPLE = BACKEND / ".env.example"
DIST_INDEX = FRONTEND / "dist" / "index.html"

DEFAULT_PORT = 8000
MIN_PYTHON = (3, 11)
MIN_NODE_MAJOR = 22
BROWSER_DELAY_SECONDS = 6.0

# 依赖就绪探测：这些包能 import 就认为现有环境可用（老仓库的 .venv 可能没有
# 我们写的 stamp 文件，此时不该无脑重装——requirements 的钉版回退会打乱能跑的环境）
PROBE_MODULES = ("fastapi", "sqlmodel", "uvicorn", "pypdf", "dotenv")


class BootstrapError(Exception):
    """带「人话处理办法」的启动失败。hint 会打印给用户。"""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


# ---------------------------------------------------------------- 输出与执行

def force_utf8_console() -> None:
    """把控制台调到 UTF-8，保证中文不花屏（不依赖批处理里的 chcp 是否生效）。"""
    if IS_WINDOWS:
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001 - 控制台不可用时静默降级
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 非 tty 流可能不支持 reconfigure
            pass


def info(text: str) -> None:
    print(text, flush=True)


def run(
    cmd: list[str],
    cwd: Path = ROOT,
    quiet: bool = False,
    allow_fail: bool = False,
) -> int:
    """跑子进程；非 0 退出码在 allow_fail=False 时抛 BootstrapError。

    quiet=True 只吞掉输出（用于 4 个增量迁移这类"跑着看看"的动作），
    失败信息仍会在 allow_fail 场景下由调用方打印。
    """
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
    )
    if result.returncode != 0 and not allow_fail:
        raise BootstrapError(
            f"命令执行失败（退出码 {result.returncode}）：{' '.join(cmd)}",
            "请看上面的报错输出；若与网络有关，可改用国内源重试。",
        )
    return result.returncode


def npm(*args: str, allow_fail: bool = False) -> int:
    """.cmd 形式的 npm 不能被 CreateProcess 直接执行，Windows 下走 cmd /c。"""
    cmd = ["cmd", "/c", "npm", *args] if IS_WINDOWS else ["npm", *args]
    return run(cmd, cwd=FRONTEND, allow_fail=allow_fail)


# ---------------------------------------------------------------- 各项检查

def port_in_use(port: int) -> bool:
    """连接探测：能连上说明已有进程在监听（比解析 netstat 稳且快）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def node_ready() -> str:
    node = shutil.which("node")
    if not node:
        raise BootstrapError(
            "没有找到 Node.js。",
            "请安装 Node.js 22 LTS 或以上版本：https://nodejs.org/\n"
            "     装完请重开一个窗口（PATH 需要刷新）再运行 start.bat。",
        )
    major = subprocess.run(
        [node, "-e", "process.stdout.write(process.versions.node.split('.')[0])"],
        capture_output=True, text=True,
    ).stdout.strip()
    version = subprocess.run([node, "-v"], capture_output=True, text=True).stdout.strip()
    if major.isdigit() and int(major) < MIN_NODE_MAJOR:
        info(f"[!] Node.js 版本偏低（当前 {version}，建议 {MIN_NODE_MAJOR} 及以上），"
             "前端构建可能报引擎不兼容；若构建失败请升级后重试。")
    return version


def ensure_venv() -> None:
    if VENV_PY.exists():
        return
    info("[3/5] 创建 Python 虚拟环境 .venv（首次约 30 秒）...")
    code = run([sys.executable, "-m", "venv", str(VENV_DIR)], allow_fail=True)
    if code != 0 or not VENV_PY.exists():
        raise BootstrapError(
            "创建虚拟环境失败。",
            f"请手动执行：cd {BACKEND}\n     python -m venv .venv",
        )


def pip_available() -> bool:
    return subprocess.run(
        [str(VENV_PY), "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def deps_ready() -> bool:
    """stamp 与 requirements.txt 时间戳一致 → 就绪；没有 stamp 则探测 import。"""
    try:
        stamp = DEPS_STAMP.read_text(encoding="utf-8").strip()
    except OSError:
        stamp = ""
    if stamp:
        return stamp == _requirements_mtime()
    probe = subprocess.run(
        [str(VENV_PY), "-c", f"import {', '.join(PROBE_MODULES)}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return probe.returncode == 0


def _requirements_mtime() -> str:
    return f"{REQUIREMENTS.stat().st_mtime:.0f}"


def ensure_deps() -> None:
    if deps_ready():
        info("[3/5] 后端依赖已就绪，跳过安装")
        DEPS_STAMP.write_text(_requirements_mtime(), encoding="utf-8")
        return

    info("[3/5] 安装后端依赖（首次约 1~3 分钟，请勿关闭窗口）...")
    if not pip_available():
        info("       虚拟环境缺少 pip，正在自动修复（ensurepip）...")
        run([str(VENV_PY), "-m", "ensurepip", "--upgrade"], quiet=True, allow_fail=True)
    if not pip_available():
        raise BootstrapError(
            "虚拟环境损坏（没有 pip 可用）。",
            f"删除目录 {VENV_DIR} 后重新运行 start.bat。",
        )
    code = run([
        str(VENV_PY), "-m", "pip", "install", "-q", "--disable-pip-version-check",
        "--no-input", "-r", str(REQUIREMENTS),
    ], allow_fail=True)
    if code != 0:
        raise BootstrapError(
            "后端依赖安装失败。",
            "多为网络问题，可换国内源重试：\n"
            f'     "{VENV_PY}" -m pip install -r "{REQUIREMENTS}" '
            "-i https://pypi.tuna.tsinghua.edu.cn/simple",
        )
    DEPS_STAMP.write_text(_requirements_mtime(), encoding="utf-8")


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        info("[4/5] backend\\.env 已存在，保留原有配置")
        return
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    info("[4/5] 已生成 backend\\.env")


def llm_configured() -> bool:
    """是否已配好可用模型：llm_config 表为准（4.4 起 DB 权威），表空回退看 .env。"""
    if DB_PATH.exists():
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT api_key, model FROM llm_config WHERE id = 1"
                ).fetchall()
            if rows:
                api_key, model = (rows[0][0] or ""), (rows[0][1] or "")
                return bool(str(model).strip()) and (
                    str(model).strip().lower() == "mock" or bool(str(api_key).strip())
                )
        except sqlite3.Error:
            pass  # 表不存在 / 结构异常都按未配置处理，下面再看 .env
    try:
        text = ENV_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("LLM_API_KEY="):
            return bool(line.split("=", 1)[1].strip().strip('"').strip("'"))
    return False


def ensure_database() -> None:
    if not DB_PATH.exists():
        info("       首次建库：创建表结构并灌入职业 / 技能 / 武器种子数据...")
        code = run([str(VENV_PY), "-X", "utf8", "scripts/init_db.py"],
                   cwd=BACKEND, allow_fail=True)
        if code != 0:
            raise BootstrapError(
                "建库失败。",
                "请确认 project\\backend\\app\\seed\\ 下有 occupations.json 与 skills.json，"
                "然后手动执行：\n"
                f'     cd "{BACKEND}" && ".venv\\Scripts\\python.exe" -X utf8 scripts\\init_db.py',
            )
        return
    info("       已有数据库，补齐增量迁移（幂等，不会动房间与存档）...")
    for version in (44, 45, 46, 47):
        code = run([str(VENV_PY), "-X", "utf8", f"scripts/migrate_{version}.py"],
                   cwd=BACKEND, quiet=True, allow_fail=True)
        if code != 0:
            info(f"       [!] migrate_{version}.py 执行失败，已跳过（不影响新结构建表；"
                 "它只补老库缺的列/表）")


def ensure_frontend(rebuild: bool) -> None:
    if not rebuild and DIST_INDEX.exists():
        info("[5/5] 前端产物已存在，跳过构建（改过前端代码时用 start.bat --rebuild 强制重建）")
        return

    info("[5/5] 构建前端产物（首次约 1~3 分钟，请勿关闭窗口）...")
    if not (FRONTEND / "node_modules").exists():
        info("       安装前端依赖...")
        lock = FRONTEND / "package-lock.json"
        code = npm("ci", allow_fail=True) if lock.exists() else npm("install", allow_fail=True)
        if code != 0:
            raise BootstrapError(
                "前端依赖安装失败。",
                f"可手动执行：cd {FRONTEND}\n     npm install",
            )

    if npm("run", "build", allow_fail=True) != 0:
        info("[!] 类型检查未通过，回退为仅打包（跳过 vue-tsc）...")
        if npm("run", "build-only", allow_fail=True) != 0:
            raise BootstrapError("前端构建失败。", "请看上面的报错信息，修好后重试。")
        info("[!] 本次产物跳过了类型检查：提交代码前请在 project\\frontend 跑一次 npm run type-check")


# ---------------------------------------------------------------- 启动服务

def lan_addresses() -> list[str]:
    """本机可被局域网访问的 IPv4：默认路由网卡优先，其余（虚拟网卡/VPN）次之。"""
    ordered: list[str] = []
    for target in ("8.8.8.8", "223.5.5.5"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((target, 80))  # UDP connect 不产生流量，只取路由结果
                ordered.append(sock.getsockname()[0])
        except OSError:
            continue
    try:
        ordered.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    seen: list[str] = []
    for ip in ordered:
        if ip and not ip.startswith("127.") and ip not in seen:
            seen.append(ip)
    return seen


def serve(port: int, open_browser: bool) -> int:
    local_url = f"http://127.0.0.1:{port}/"
    ips = lan_addresses()
    info("")
    info("=" * 60)
    info(" 启动中，服务就绪后浏览器会自动打开...")
    info("")
    info(f"   本机访问：  {local_url}")
    if ips:
        info("   局域网访问（把这行发给一起跑团的人）：")
        for ip in ips:
            suffix = "        <-默认网卡" if ip == ips[0] else ""
            info(f"               http://{ip}:{port}/{suffix}")
    else:
        info("   [!] 没探测到局域网地址：用 ipconfig 看本机 IPv4 后访问 http://<IP>:%d/" % port)
    info("")
    info("   停止服务：在本窗口按 Ctrl+C")
    info("=" * 60)
    info("")

    if open_browser:
        timer = threading.Timer(BROWSER_DELAY_SECONDS, webbrowser.open, args=(local_url,))
        timer.daemon = True  # 不拖住退出
        timer.start()

    return run([
        str(VENV_PY), "-X", "utf8", "-m", "uvicorn", "app.main:app",
        "--host", "0.0.0.0", "--port", str(port),
    ], cwd=BACKEND, allow_fail=True)


# ---------------------------------------------------------------- 主流程

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description="COC 跑团助手一键启动驱动（由 start.bat 调用）",
    )
    parser.add_argument("port", nargs="?", type=int, default=DEFAULT_PORT,
                        help=f"服务端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--check", action="store_true",
                        help="只做环境自检与准备，不起服务")
    parser.add_argument("--rebuild", action="store_true",
                        help="强制重建前端产物")
    parser.add_argument("--no-browser", action="store_true",
                        help="不自动打开浏览器")
    return parser


def require_free_port(port: int) -> None:
    """端口占用检查。--check 不起服务、--rebuild 以重建产物为主，
    这两种用法都不该被"上一次没关掉的 uvicorn"挡住，故预检阶段跳过
    （真要起服务时还会在 serve 前再查一次）。"""
    if port_in_use(port):
        raise BootstrapError(
            f"端口 {port} 已被占用，启动中止。",
            "处理办法：\n"
            "     1) 关掉占用该端口的程序（多半是上一次没关掉的 uvicorn）：\n"
            f"        netstat -ano | findstr :{port}  拿到 PID 后到任务管理器结束\n"
            f"     2) 或者换一个端口启动：start.bat {port + 1}",
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    force_utf8_console()

    info("=" * 60)
    info(" 雾都疑云 · CoC 跑团助手 — 一键启动")
    info("=" * 60)

    try:
        # [0] 端口：先查，避免白等几分钟构建（--check / --rebuild 不在此列）
        if args.check or args.rebuild:
            info(f"[0/5] 端口 {args.port} 预检跳过（--check / --rebuild 不起服务）")
        else:
            require_free_port(args.port)
            info(f"[0/5] 端口 {args.port} 可用")

        # [1] Python
        if sys.version_info < MIN_PYTHON:
            raise BootstrapError(
                f"Python 版本过低（当前 {sys.version.split()[0]}，需要 3.11 及以上）。",
                "请升级 Python 后重试：https://www.python.org/downloads/",
            )
        info(f"[1/5] Python {sys.version.split()[0]} 正常")

        # [2] Node
        info(f"[2/5] Node.js {node_ready()} 正常")

        # [3] venv + 依赖
        ensure_venv()
        ensure_deps()

        # [4] 配置文件 + 数据库
        ensure_env_file()
        ensure_database()
        if not llm_configured():
            info("       提示：还没配置大模型 API Key。不配也能玩——")
            info("             进入大厅后点顶部引导条的「启用演示模式」，或用「API / 模型配置」填 Key。")

        # [5] 前端产物
        ensure_frontend(args.rebuild)

        if args.check:
            info("")
            info("[自检完成] 环境、依赖、数据库与前端产物均已就绪（未启动服务）。")
            info("           去掉 --check 参数即可正式启动：start.bat")
            return 0

        # 真的要起服务：预检被跳过的场景（--rebuild）在这里兜底复检
        require_free_port(args.port)
        return serve(args.port, open_browser=not args.no_browser)

    except BootstrapError as exc:
        info("")
        info(f"[X] {exc.message}")
        if exc.hint:
            info(f"    {exc.hint}")
        info("")
        info("启动中止。按上面的提示处理后重新双击 start.bat 即可。")
        if IS_WINDOWS and sys.stdin is not None and sys.stdin.isatty():
            try:
                input("按回车键退出...")
            except EOFError:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
