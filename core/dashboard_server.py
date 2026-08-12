"""
智汇中枢 - 大屏本地 HTTP 服务

常驻一个 daemon 线程 serve 导出目录，提供
http://127.0.0.1:{port}/dashboard_xxx.html 形式的链接，
方便用户复制到浏览器或局域网内其他设备访问。
"""

import os
import threading
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

DEFAULT_PORT = 8756


class _DashboardHandler(SimpleHTTPRequestHandler):
    """serve 指定目录，静默日志"""

    def log_message(self, fmt, *args):
        pass


def _make_handler(directory):
    return partial(_DashboardHandler, directory=directory)


class DashboardServer:
    """本地静态文件服务（懒启动，端口被占用自动 +1）"""

    def __init__(self):
        self._httpd = None
        self._thread = None
        self._port = None

    @property
    def port(self):
        return self._port

    @property
    def running(self):
        return self._httpd is not None

    def start(self, directory, port=DEFAULT_PORT):
        """启动服务，返回实际端口；已在运行则直接返回当前端口"""
        if self._httpd:
            return self._port
        os.makedirs(directory, exist_ok=True)
        httpd = None
        for p in range(port, port + 20):
            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", p), _make_handler(directory))
                break
            except OSError:
                httpd = None
                continue
        if httpd is None:
            raise RuntimeError("无法启动本地服务，端口范围均被占用")
        self._httpd = httpd
        self._port = httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return self._port

    def stop(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            try:
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
            self._port = None

    def url_for(self, filename):
        """把本地文件路径转成 http:// 链接；未启动返回空串"""
        if not self._httpd or not self._port:
            return ""
        return f"http://127.0.0.1:{self._port}/{os.path.basename(filename)}"


# 全局单例：聊天面板与主窗口共用同一个服务实例
_global_server = DashboardServer()


def get_global_server():
    return _global_server
