# -*- coding: utf-8 -*-
"""TokensMonitor 托盘启动器
双击运行：启动监控服务 + 自动打开浏览器 + 最小化到系统托盘。
- 左键/双击托盘图标：打开面板
- 右键托盘图标：打开面板 / 退出
- 首次运行检测端口占用：若服务已在运行则直接打开浏览器
"""
import os
import sys
import socket
import threading
import webbrowser
from pathlib import Path

# PyInstaller 打包后数据文件在 _MEIPASS
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).parent)

import server  # noqa: E402  （与本文件同目录）

PORT = 8787
HOST = "0.0.0.0"
PANEL = f"http://127.0.0.1:{PORT}/"

if getattr(sys, "frozen", False):
    # 打包模式：配置/备份放 exe 所在目录（持久化），静态资源在解包目录
    exe_dir = Path(sys.executable).parent
    server.BASE_DIR = exe_dir
    server.CONFIG_FILE = exe_dir / "config.json"


def port_in_use(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def open_panel():
    webbrowser.open(PANEL)


def start_server():
    server.load_config()
    httpd = server.ThreadingHTTPServer((server.CONFIG.get("host", HOST),
                                        int(server.CONFIG.get("port", PORT))),
                                       server.Handler)
    httpd.serve_forever()


def main():
    server_was_running = port_in_use(PORT)
    if not server_was_running:
        threading.Thread(target=start_server, daemon=True).start()
        threading.Timer(1.0, open_panel).start()
    else:
        open_panel()

    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        # 未安装托盘依赖：退化为纯后台 + 打开浏览器
        print("托盘组件未安装（pip install pystray pillow），服务已在后台运行：", PANEL)
        if server_was_running:
            return
        try:
            while True:
                threading.Event().wait(3600)
        except KeyboardInterrupt:
            return

    # 生成托盘图标（金色硬币）
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.ellipse([2, 2, 62, 62], fill=(250, 204, 21), outline=(161, 98, 7), width=3)
    dr.ellipse([10, 10, 54, 54], outline=(253, 230, 138), width=2)
    dr.rectangle([22, 29, 42, 35], fill=(120, 53, 15))
    dr.polygon([(26, 40), (38, 40), (32, 46)], fill=(120, 53, 15))
    dr.rectangle([29, 18, 35, 29], fill=(120, 53, 15))

    def on_open(icon, item):
        open_panel()

    def on_exit(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("打开面板", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出（并停止服务）", on_exit),
    )
    icon = pystray.Icon("TokensMonitor", img,
                        f"TokensMonitor · {PANEL}", menu)
    icon.run()


if __name__ == "__main__":
    main()
