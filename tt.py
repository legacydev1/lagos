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

TELEGRAM_TOKEN = "8924966752:AAHASJW1QsBe9Q1rLtCdDcZm800wTueNV-o"
BASE = "https://lagoslife.app"
# Works on both Render Web Service (PORT set) and Background Worker / VPS (no PORT)
_PORT_ENV = os.getenv("PORT")
PORT = int(_PORT_ENV) if _PORT_ENV else None
IS_WEB_SERVICE = PORT is not None
ADMIN_IDS = [7941824028]
BOT_FILE = os.path.abspath(sys.argv[0])
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
welcome_pic_id = None

# Hosted bots registry
# {bot_id: {owner_id, name, path, main_file, kind, proc, log_path, created, env, token}}
hosted_bots = {}
pending_files = {}

# ─────────────────────────────────────────────
#  WEB SCRAPER STATE
# ─────────────────────────────────────────────
SCRAPER_MAX_ASSETS = 100
SCRAPER_MAX_PAGES = 20
SCRAPER_MAX_DEPTH = 2
SCRAPER_MAX_ZIP_MB = 48
SCRAPER_ASSET_WORKERS = 8
SCRAPER_MAX_ASSET_BYTES = 15 * 1024 * 1024
SCRAPER_MAX_HTML_BYTES = 8 * 1024 * 1024
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

_scraper_http = requests.Session()
_scraper_http.headers.update({
    "User-Agent": SCRAPER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})


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
         InlineKeyboardButton("🆘  SUPPORT", callback_data="support")]
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
        [InlineKeyboardButton("🕸 Crawl info", callback_data="sc_crawl"),
         InlineKeyboardButton("⚙️ Scraper settings", callback_data="sc_settings")],
        [InlineKeyboardButton("🕘 History", callback_data="sc_history"),
         InlineKeyboardButton("ℹ️ Scraper help", callback_data="sc_help")],
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
    headers = {"User-Agent": SCRAPER_MOBILE_UA} if mobile else {}
    r = _scraper_http.get(url, timeout=20, allow_redirects=True, headers=headers or None)
    r.raise_for_status()
    if max_bytes is not None and len(r.content) > max_bytes:
        raise ValueError("too large")
    return r


def _sc_download_asset(url, dest, mobile=False):
    try:
        r = _scraper_http.get(
            url, timeout=20, allow_redirects=True, stream=True,
            headers={"User-Agent": SCRAPER_MOBILE_UA if mobile else SCRAPER_UA},
        )
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        total = 0
        chunks = []
        for chunk in r.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > SCRAPER_MAX_ASSET_BYTES:
                return False, "large"
            chunks.append(chunk)
        data = b"".join(chunks)
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
        return False, str(e)[:80]


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
        except Exception:
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
                    ok, _ = fut.result()
                    if ok and dest.exists():
                        asset_ok += 1
                        url_to_local[aurl] = str(dest.relative_to(work_dir)).replace("\\", "/")
                    else:
                        asset_fail += 1
                        url_to_local.pop(aurl, None)

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
    (work_dir / "DOWNLOAD_REPORT.txt").write_text(
        f"Source: {start_url}\nFinal: {final_start}\nPages: {page_count}\nDepth: {depth}\n"
        f"Assets OK: {asset_ok}\nAssets FAIL: {asset_fail}\nSelector: {selector or '-'}\n",
        encoding="utf-8",
    )
    return {
        "final_url": final_start,
        "pages": page_count,
        "asset_ok": asset_ok,
        "asset_fail": asset_fail,
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
            bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=text[:4096], parse_mode="HTML",
                reply_markup=scraper_job_kb(job_id, running=True),
            )
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
                        bot.send_photo(chat_id=chat_id, photo=f, caption=result["final_url"][:200])
                except Exception:
                    pass

        zip_path = tmp / (_sc_folder(result["final_url"]) + ".zip")
        _sc_make_zip(work, zip_path)
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        mode = settings.get("mode") or "zip"
        summary = (
            f"✅ <b>Saved</b>\n<code>{html_lib.escape(result['final_url'])}</code>\n"
            f"Pages: <b>{result['pages']}</b>\n"
            f"Assets: <b>{result['asset_ok']}</b> ok · {result['asset_fail']} fail\n"
            f"Zip: <b>{size_mb:.2f} MB</b>"
        )

        if size_mb > SCRAPER_MAX_ZIP_MB:
            try:
                bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg_id,
                    text=summary + f"\n\n⚠️ Zip over {SCRAPER_MAX_ZIP_MB}MB — text only.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            with open(result["md_path"], "rb") as f:
                bot.send_document(chat_id=chat_id, document=f, caption="Markdown")
            with open(result["txt_path"], "rb") as f:
                bot.send_document(chat_id=chat_id, document=f, caption="Text")
        else:
            if mode in ("zip", "both"):
                with open(zip_path, "rb") as f:
                    bot.send_document(
                        chat_id=chat_id, document=f,
                        caption=(
                            f"📦 {zip_path.name}\n{result['final_url']}\n"
                            f"pages={result['pages']} assets={result['asset_ok']}"
                        ),
                    )
            if mode in ("md", "both"):
                with open(result["md_path"], "rb") as f:
                    bot.send_document(chat_id=chat_id, document=f, caption="Markdown")
            if mode in ("txt", "both"):
                with open(result["txt_path"], "rb") as f:
                    bot.send_document(chat_id=chat_id, document=f, caption="Plain text")
            try:
                bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg_id, text=summary,
                    parse_mode="HTML", reply_markup=scraper_job_kb(job_id, running=False),
                )
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
            bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=f"❌ HTTP {code}")
        except Exception:
            pass
    except Exception as e:
        try:
            bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=f"❌ {html_lib.escape(str(e)[:220])}", parse_mode="HTML",
            )
        except Exception:
            pass


def scraper_start_job(bot, chat_id, url):
    now = time.time()
    if now - scraper_cooldown.get(chat_id, 0) < 2:
        bot.send_message(chat_id=chat_id, text="⏳ Wait 2s between jobs.")
        return
    scraper_cooldown[chat_id] = now
    with scraper_lock:
        cur = scraper_jobs.get(chat_id)
        if cur and cur.get("result") is None:
            bot.send_message(chat_id=chat_id, text="Job already running. Cancel first.")
            return
        prev = scraper_jobs.pop(chat_id, None)
    if prev and prev.get("tmp"):
        shutil.rmtree(prev["tmp"], ignore_errors=True)
    msg = bot.send_message(
        chat_id=chat_id,
        text=f"⏳ Queued\n<code>{html_lib.escape(url)}</code>",
        parse_mode="HTML",
    )
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
        waiting_for[user_id] = f"update_{bot_id}"
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

    # ── LAGOSLIFE ──
    
    # ── Scraper menu ──
    if data == "scraper":
        await safe_edit(query, card("SCRAPER", "  Offline page saver\n  Zip · MD · Text · Crawl"), scraper_menu())
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
        await safe_edit(query, card("CRAWL", f"  Depth now: {s['depth']}\n  0=single · 1-2=same domain\n  Cap: {SCRAPER_MAX_PAGES} pages"), scraper_settings_kb(user_id))
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
            f"  Selector : {s['selector'] or '-'}"
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
            "  1. Save URL → paste link\n"
            "  2. Batch → many links\n"
            "  3. Settings → depth/assets/mode\n"
            "  4. After job: MD/TXT/ZIP buttons\n\n"
            f"  BS4={HAS_BS4} h2t={HAS_H2T} pw={HAS_PW}"), scraper_menu())
        return
    if data.startswith("scset:"):
        key = data.split(":", 1)[1]
        s = scraper_settings[user_id]
        if key == "depth":
            s["depth"] = (s["depth"] + 1) % (SCRAPER_MAX_DEPTH + 1)
        elif key == "assets":
            opts = [20, 40, 60, 100, 150, 0]
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
            scraper_start_job(context.bot, user_id, hist[idx]["url"])
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
        del waiting_for[user_id]
        if not urls:
            await update.message.reply_text(card("ERROR", "  No URL found"), reply_markup=scraper_menu())
            return
        scraper_start_job(context.bot, user_id, urls[0])
        return

    if state == "sc_batch":
        urls = _sc_extract_urls(text)
        del waiting_for[user_id]
        if not urls:
            await update.message.reply_text(card("ERROR", "  No URLs found"), reply_markup=scraper_menu())
            return
        await update.message.reply_text(card("BATCH", f"  Starting {len(urls)} URL(s)"))
        for u in urls[:20]:
            scraper_start_job(context.bot, user_id, u)
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

    # Update files for existing bot
    if user_id in waiting_for and waiting_for[user_id].startswith("update_"):
        bot_id = waiting_for[user_id].replace("update_", "")
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
            # Backup old core
            try:
                if os.path.exists(BOT_FILE):
                    shutil.copy2(BOT_FILE, BOT_FILE + ".bak")
            except Exception:
                pass

            # Write new core
            with open(BOT_FILE, "wb") as f:
                f.write(new_code)

            if user_id in waiting_for:
                del waiting_for[user_id]

            await status_msg.edit_text(
                card("SUCCESS", f"  Core updated ({len(new_code)} bytes)\n  Restarting in 2s...")
            )
            await asyncio.sleep(2)

            # Render-friendly restart:
            # os.execv often fails on Render — exit so the platform restarts the process
            try:
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                pass
            # Fallback: force process exit → Render / systemd will restart it
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
    global app_instance
    app_instance = app
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
