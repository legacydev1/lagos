#!/usr/bin/env python3
"""
LagosLife Bot — Hacker Design + Welcome Image + Animation + GC + DM Status
"""

import json
import random
import time
import threading
import asyncio
import queue
import os
import sys
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, CommandHandler, ContextTypes, filters

TELEGRAM_TOKEN = "8924966752:AAHASJW1QsBe9Q1rLtCdDcZm800wTueNV-o"
BASE = "https://lagoslife.app"
PORT = int(os.getenv("PORT", 10000))
ADMIN_IDS = [7941824028]
BOT_FILE = os.path.abspath(sys.argv[0])
WELCOME_PIC_FILE = "welcome_pic.json"

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
welcome_pic_id = None   # Telegram file_id of welcome image

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

load_welcome_pic()

# ─────────────────────────────────────────────
#  HACKER UI
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
         InlineKeyboardButton("📖  HELP", callback_data="help")]
    ]
    if user_id and is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👁  ADMIN PANEL", callback_data="admin")])
    return InlineKeyboardMarkup(keyboard)

def admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 SESSIONS", callback_data="sessions"),
         InlineKeyboardButton("👥 USERS", callback_data="users")],
        [InlineKeyboardButton("🛑 STOP USER", callback_data="stop_user"),
         InlineKeyboardButton("📢 BROADCAST", callback_data="broadcast")],
        [InlineKeyboardButton("🖼 SET WELCOME PIC", callback_data="set_pic")],
        [InlineKeyboardButton("🔄 UPDATE CORE", callback_data="update_bot")],
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
        f"  ▸ Module : Money Injector\n"
        f"  ▸ Mode   : Private + Groups\n"
        f"  ▸ Status → your DM\n\n"
        f"  Select operation below."
    )

# Realistic terminal-style hacking animation
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
#  CORE ENGINE
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

def notify_admin(text):
    if not app_instance:
        return
    for admin_id in ADMIN_IDS:
        try:
            asyncio.run_coroutine_threadsafe(
                app_instance.bot.send_message(chat_id=admin_id, text=text),
                asyncio.get_event_loop()
            )
        except:
            pass

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
    """Realistic terminal-style animation in the user's DM"""
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
#  HANDLERS
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
    """Admin only — bot leaves the current group"""
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
    """Works for both text messages and photo+caption messages"""
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

    if data == "login":
        waiting_for[user_id] = "login"
        await safe_edit(
            query,
            card("AUTH", "  Send credentials:\n  username password\n\n  Example:\n  legacy_dev mypass"),
            back_only()
        )
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
        await safe_edit(query, card("TARGET", "  Send target balance\n  Example: 50000000\n\n  Send 0 to disable"), back_only()
        )
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

        # Confirm in current chat first
        if chat_id != user_id:
            await safe_edit(query, card("INJECT", "  Launching...\n  Live feed → your DM"), main_menu(user_id)
            )
        else:
            await safe_edit(query, card("INJECT", "  Launching..."), main_menu(user_id))

        # Play hacking animation in DM
        try:
            await play_hack_animation(context.bot, user_id)
        except:
            pass

        # Send live status to DM
        try:
            msg = await context.bot.send_message(
                chat_id=user_id,
                text=live_status(0, 0, 0, amount, 0, target, extra="Initializing...")
            )
            status_chat_id = user_id
            status_msg_id = msg.message_id
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=card("ERROR", "  Open private chat with bot\n  and press /start first")
            )
            return

        user_sessions[user_id]["status_chat_id"] = status_chat_id
        user_sessions[user_id]["status_msg_id"] = status_msg_id
        user_sessions[user_id]["running"] = True

        t = threading.Thread(
            target=progression_loop,
            args=(user_id, status_chat_id, status_msg_id),
            daemon=True
        )
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
                 "  2. SET AMOUNT (payload)\n"
                 "  3. Optional TARGET\n"
                 "  4. INJECT to start\n\n"
                 "  Live status always goes\n"
                 "  to your private DM.\n\n"
                 "  Admin can set welcome pic\n"
                 "  from Admin Panel."), main_menu(user_id)
        )
        return

    # ADMIN
    if not is_admin(user_id):
        return

    if data == "admin":
        running = sum(1 for s in user_sessions.values() if s.get("running"))
        await safe_edit(
            query,
            f"{banner('ADMIN')}\n\n"
            f"  Total users : {len(all_users)}\n"
            f"  Logged in   : {len(user_sessions)}\n"
            f"  Active      : {running}",
            admin_panel()
        )
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
        await safe_edit(
            query,
            card("USERS", f"  Unique  : {len(all_users)}\n  Logged  : {len(user_sessions)}\n  Active  : {running}"),
            admin_panel()
        )
        return

    if data == "stop_user":
        waiting_for[user_id] = "stop_user"
        await safe_edit(query, card("STOP USER", "  Send username to kill"), back_only())
        return

    if data == "broadcast":
        waiting_for[user_id] = "broadcast"
        await safe_edit(query, card("BROADCAST", "  Send text or media"), back_only())
        return

    if data == "set_pic":
        waiting_for[user_id] = "set_pic"
        await safe_edit(
            query,
            card("WELCOME PIC", "  Send the new photo now\n  It will be used on /start"),
            back_only()
        )
        return

    if data == "update_bot":
        waiting_for[user_id] = "update_bot"
        await safe_edit(query, card("UPDATE", "  Send new .py file"), back_only())
        return

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

    if user_id not in waiting_for:
        # Normal start-style reply
        if welcome_pic_id:
            try:
                await update.message.reply_photo(photo=welcome_pic_id, caption=welcome_caption(), reply_markup=main_menu(user_id))
                return
            except:
                pass
        await update.message.reply_text(welcome_caption(), reply_markup=main_menu(user_id))
        return

    state = waiting_for[user_id]

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
        all_users.add(user_id)
        del waiting_for[user_id]
        await update.message.reply_text(
            card("ACCESS GRANTED", f"  User    : {username}\n  Default : ₦50,000"),
            reply_markup=main_menu(user_id)
        )
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
        success = fail = 0
        for uid in list(all_users):
            try:
                await context.bot.send_message(chat_id=uid, text=f"📢 BROADCAST\n\n{text}")
                success += 1
            except:
                fail += 1
        del waiting_for[user_id]
        await update.message.reply_text(card("DONE", f"  Sent   : {success}\n  Failed : {fail}"), reply_markup=admin_panel())
        return

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    # Set welcome picture
    if user_id in waiting_for and waiting_for[user_id] == "set_pic":
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            save_welcome_pic(file_id)
            del waiting_for[user_id]
            await update.message.reply_text(
                card("PIC SET", "  Welcome image updated\n  It will show on /start"),
                reply_markup=admin_panel()
            )
            return
        else:
            await update.message.reply_text(card("ERROR", "  Send a photo (not file)"), reply_markup=back_only())
            return

    if user_id in waiting_for and waiting_for[user_id] == "update_bot":
        doc = update.message.document
        if not doc or not doc.file_name.endswith(".py"):
            await update.message.reply_text(card("ERROR", "  Send a .py file"), reply_markup=back_only())
            return
        await update.message.reply_text(card("UPDATE", "  Downloading new core..."))
        file = await context.bot.get_file(doc.file_id)
        new_code = await file.download_as_bytearray()
        try:
            os.rename(BOT_FILE, BOT_FILE + ".bak")
        except:
            pass
        with open(BOT_FILE, "wb") as f:
            f.write(new_code)
        await update.message.reply_text(card("SUCCESS", "  Core updated\n  Restarting..."))
        del waiting_for[user_id]
        os.execv(sys.executable, [sys.executable] + sys.argv)
        return

    if user_id in waiting_for and waiting_for[user_id] == "broadcast":
        success = fail = 0
        caption = update.message.caption or "📢 BROADCAST"
        for uid in list(all_users):
            try:
                if update.message.photo:
                    await context.bot.send_photo(chat_id=uid, photo=update.message.photo[-1].file_id, caption=caption)
                elif update.message.video:
                    await context.bot.send_video(chat_id=uid, video=update.message.video.file_id, caption=caption)
                elif update.message.document:
                    await context.bot.send_document(chat_id=uid, document=update.message.document.file_id, caption=caption)
                success += 1
            except:
                fail += 1
        del waiting_for[user_id]
        await update.message.reply_text(card("DONE", f"  Sent   : {success}\n  Failed : {fail}"), reply_markup=admin_panel())
        return

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"LagosLife Core Online")
    def log_message(self, *args):
        pass

def start_http_server():
    HTTPServer(("0.0.0.0", PORT), DummyHandler).serve_forever()

async def post_init(app):
    global app_instance
    app_instance = app
    asyncio.create_task(edit_worker(app))

def main():
    threading.Thread(target=start_http_server, daemon=True).start()
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

    print("[*] LagosLife Core — Hacker Design + Pic + Animation + Leave")
    app.run_polling()

if __name__ == "__main__":
    main()
