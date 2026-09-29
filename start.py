# start.py — ShopPilot 一键启动（开发环境）
#
# 用法（必须用项目 conda 环境的 python 运行）：
#   conda activate shop_pilot
#   python start.py
#
# 行为：
#   1. 检查 Docker 基建（postgres/minio/etcd/milvus）端口，未就绪则 docker-compose 拉起
#   2. 结束占用 8000/3000 的旧进程，启动后端 uvicorn + 前端 vite
#   3. 子进程日志实时转发到本终端（[后端]/[前端] 前缀）
#   4. 轮询健康检查，通过后打印访问地址与测试账号
#   5. Ctrl+C 退出时结束全部子进程（含 node 进程树）
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable  # 用启动本脚本的解释器（应为 Edu_Agent 的 python）

TAGS = {"backend": "[后端]", "frontend": "[前端]", "sys": "[启动]"}


def log(tag: str, msg: str) -> None:
    print(f"{TAGS[tag]} {msg}", flush=True)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    """探测端口。vite/node 在 Windows 上可能只监听 IPv6 localhost(::1)，故双栈探测。"""
    candidates = [(host, port)]
    if host == "127.0.0.1":
        candidates.append(("::1", port))
    for addr, p in candidates:
        family = socket.AF_INET6 if ":" in addr else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                target = (addr, p, 0, 0) if family == socket.AF_INET6 else (addr, p)
                if s.connect_ex(target) == 0:
                    return True
        except OSError:
            continue
    return False


def wait_ports(ports: list[int], timeout: float, label: str) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(port_open(p) for p in ports):
            return True
        time.sleep(2)
    return False


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def kill_port(port: int) -> None:
    """结束占用该端口的进程（PowerShell Get-NetTCPConnection，含进程树）。"""
    ps = (
        f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue; "
        "if ($c) { $c.OwningProcess | Select-Object -Unique | ForEach-Object { "
        "taskkill /F /T /PID $_ 2>$null } }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=15)
        log("sys", f"已清理 {port} 端口占用")
    except Exception as e:
        log("sys", f"清理 {port} 端口失败：{e}")


def stream_output(name: str, proc: subprocess.Popen) -> None:
    """把子进程输出按行转发到本终端。"""
    prefix = TAGS[name]
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"{prefix} {line.rstrip()}", flush=True)


def ensure_infra() -> None:
    """基建端口检查；未就绪则 docker-compose up -d。"""
    ports = [5433, 9002, 19531]  # postgres / minio / milvus
    names = {5433: "PostgreSQL", 9002: "MinIO", 19531: "Milvus"}
    if all(port_open(p) for p in ports):
        log("sys", "基础设施已在运行（5433/9002/19531），跳过 docker-compose")
        return
    missing = [names[p] for p in ports if not port_open(p)]
    log("sys", f"检测到未就绪：{', '.join(missing)}，尝试 docker-compose 拉起…")
    compose = shutil.which("docker-compose") or shutil.which("docker")
    env_file = ROOT / ".env.local"
    if compose is None or not env_file.exists():
        log("sys", "未找到 docker-compose 或 .env.local，无法自动拉起基建")
        log("sys", "请手动执行：docker-compose --env-file .env.local up -d postgres minio etcd milvus")
        sys.exit(1)
    cmd = [compose, "--env-file", str(env_file), "up", "-d", "postgres", "minio", "etcd", "milvus"]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        print(f"{TAGS['sys']} {line.rstrip()}", flush=True)
    proc.wait()
    if not wait_ports(ports, timeout=180, label="infra"):
        still = [names[p] for p in ports if not port_open(p)]
        log("sys", f"超时：{', '.join(still)} 仍未就绪，请手动检查 docker")
        sys.exit(1)
    log("sys", "基础设施就绪")


def main() -> None:
    os.chdir(ROOT)
    print("=" * 56)
    print("  ShopPilot 一键启动（开发环境）")
    print(f"  Python: {PY}")
    print("  退出：Ctrl+C")
    print("=" * 56, flush=True)

    ensure_infra()

    kill_port(8000)
    kill_port(3000)
    time.sleep(1)

    # ── 后端 uvicorn ──
    log("sys", "启动后端 uvicorn（:8000）…")
    backend = subprocess.Popen(
        [PY, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
    )
    threading.Thread(target=stream_output, args=("backend", backend), daemon=True).start()

    # ── 前端 vite ──
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        log("sys", "未找到 npm，跳过前端启动（后端仍可用 :8000/docs）")
        frontend = None
    else:
        log("sys", "启动前端 vite（:3000）…")
        frontend = subprocess.Popen(
            [npm, "run", "dev"],
            cwd=str(ROOT / "frontend"), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
        )
        threading.Thread(target=stream_output, args=("frontend", frontend), daemon=True).start()

    # ── 健康检查 ──
    log("sys", "等待服务就绪（后端首次启动需预热本地模型，最多约 3 分钟）…")
    backend_ok = wait_ports([8000], timeout=180, label="backend") and http_ok("http://127.0.0.1:8000/health")
    if not backend_ok:
        log("sys", "后端健康检查失败，请看上方 [后端] 日志")
    else:
        log("sys", "后端健康检查通过 → http://localhost:8000/health")
    if frontend is not None:
        deadline = time.time() + 90
        frontend_ok = False
        while time.time() < deadline:
            if port_open(3000) or http_ok("http://127.0.0.1:3000"):
                frontend_ok = True
                break
            time.sleep(2)
        if frontend_ok:
            log("sys", "前端已就绪 → http://localhost:3000")
        else:
            log("sys", "前端 3000 端口未就绪，请看上方 [前端] 日志")

    if backend_ok:
        print()
        print("-" * 56)
        print("  ✅ ShopPilot 已启动")
        print("  前端     http://localhost:3000")
        print("  接口文档 http://localhost:8000/docs")
        print("  顾客账号 student01@shoppilot.local / Student@123456")
        print("  运营账号 teacher01@shoppilot.local / Teacher@123456")
        print("  按 Ctrl+C 退出并停止全部服务")
        print("-" * 56, flush=True)

    # ── 保持前台，持续转发日志；Ctrl+C 退出 ──
    try:
        while True:
            if backend.poll() is not None:
                log("sys", f"后端进程已退出（code={backend.returncode}）")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        log("sys", "收到 Ctrl+C，正在停止全部服务…")
    finally:
        for name, proc in (("backend", backend), ("frontend", frontend)):
            if proc is None or proc.poll() is not None:
                continue
            log("sys", f"停止 {name}（PID={proc.pid}）")
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, text=True)
        log("sys", "已全部退出 👋")


if __name__ == "__main__":
    main()
