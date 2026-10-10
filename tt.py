#!/usr/bin/env python3
"""
LagosLife Bot — Full Inline Buttons + Multi-write + Hidden Admin
Clean working version
"""

import json
import random
import time
import threading
import asyncio
import queue
import os
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.error import BadRequest, TimedOut, NetworkError

TELEGRAM_TOKEN = "8924966752:AAHASJW1QsBe9Q1rLtCdDcZm800wTueNV-o"
BASE = "https://lagoslife.app"
PORT = int(os.getenv("PORT", 10000))

WRITES_PER_CYCLE = 10
ADMIN_IDS = [7941824028]   # your Telegram ID

UA_POOL = [
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"'
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"'
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "sec-ch-ua": None
    }
]

user_sessions = {}
edit_queue = queue.Queue()
all_users = set()
waiting_for = {}

def is_admin(uid):
    return uid in ADMIN_IDS

def main_menu():
    keyboard = [
        [InlineKeyboardButton("🔑 Login", callback_data="login"),
         InlineKeyboardButton("⚙ Set Amount", callback_data="set_amount")],
        [InlineKeyboardButton("▶ Run", callback_data="run"),
         InlineKeyboardButton("⏹ Stop", callback_data="stop")],
        [InlineKeyboardButton("📊 Status", callback_data="status"),
         InlineKeyboardButton("ℹ Help", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_menu():
    keyboard = [
        [InlineKeyboardButton("🔑 Login", callback_data="login"),
         InlineKeyboardButton("⚙ Set Amount", callback_data="set_amount")],
        [InlineKeyboardButton("▶ Run", callback_data="run"),
         InlineKeyboardButton("⏹ Stop", callback_data="stop")],
        [InlineKeyboardButton("📊 Status", callback_data="status"),
         InlineKeyboardButton("👑 Admin", callback_data="admin")],
        [InlineKeyboardButton("📋 Sessions", callback_data="sessions"),
         InlineKeyboardButton("👥 Users", callback_data="users")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="broadcast")]
    ]
    return InlineKeyboardMarkup(keyboard)

def banner(title):
    return f"╭──────────────────────────╮\n│  {title.center(22)}  │\n╰──────────────────────────╯"

def card(title, body):
    return f"┌─ {title} ────────────────\n{body}\n└──────────────────────────"

def progress_bar(current, total=14):
    filled = min(current % (total + 1), total)
    return "▓" * filled + "░" * (total - filled)

def live_status(cycle, bal, accepted, amount, running=True, extra=""):
    state = "🟢 RUNNING" if running else "🔴 STOPPED"
    bar = progress_bar(accepted)
    total = amount * WRITES_PER_CYCLE
    text = (
        f"{banner('LIVE STATUS')}\n\n"
        f"Per write : ₦{amount:,}\n"
        f"Per cycle : ₦{total:,} ({WRITES_PER_CYCLE}x)\n"
        f"State     : {state}\n"
        f"Cycle     : {cycle}\n"
        f"Balance   : ₦{bal:,}\n"
        f"Success   : {accepted}\n"
        f"{bar}"
    )
    if extra:
        text += f"\n\n{extra}"
    return text

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
    base = 1.5 + min(successes * 0.06, 2.8)
    time.sleep(random.uniform(base, base + 1.3))

def raw(session, path, method, body_dict=None):
    url = BASE + path
    try:
        if method == "GET":
            res = session.get(url, allow_redirects=False, timeout=18)
        elif method == "POST":
            res = session.post(url, json=body_dict, allow_redirects=False, timeout=18)
        elif method == "PUT":
            res = session.put(url, json=body_dict, allow_redirects=False, timeout=18)
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

def set_money_with_retry(session, v, retries=3):
    for attempt in range(retries):
        cur = read_save(session)
        if not cur or "game" not in cur:
            return {"status": 500, "stored": None}
        g = json.loads(json.dumps(cur["game"]))
        g["money"] = v
        timestamp = cur.get("updatedAt")
        r = raw(session, "/api/save", "PUT", {"game": g, "base": timestamp})
        time.sleep(0.8)
        back = read_save(session)
        stored = back.get("game", {}).get("money") if isinstance(back, dict) else None
        if r["status"] == 409:
            time.sleep(1.2 + attempt * 0.8)
            continue
        return {"status": r["status"], "stored": stored}
    return {"status": 409, "stored": None}

def progression_loop(chat_id, status_msg_id):
    state = user_sessions[chat_id]
    session = state["session"]
    amount = state.get("amount", 50000)
    telemetry = state["telemetry"]
    cycle = 0
    total_accepted = 0
    last_bal = 0
    consecutive_409 = 0

    cur = read_save(session)
    if cur and "game" in cur:
        last_bal = cur["game"].get("money", 0)

    edit_queue.put((chat_id, status_msg_id, live_status(0, last_bal, 0, amount, extra="Starting multi-write...")))

    while state["running"]:
        try:
            cur = read_save(session)
            if not cur or "game" not in cur:
                edit_queue.put((chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, extra="⚠️ Fetch failed")))
                time.sleep(4)
                continue

            bal = cur["game"].get("money", 0)
            last_bal = bal
            success_writes = 0

            for i in range(WRITES_PER_CYCLE):
                if not state["running"]:
                    break
                new_bal = last_bal + amount
                r = set_money_with_retry(session, new_bal)

                if r["status"] == 409:
                    consecutive_409 += 1
                    if consecutive_409 >= 4:
                        edit_queue.put((chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, extra="🛑 Too many 409 — paused")))
                        time.sleep(15)
                        consecutive_409 = 0
                    continue

                consecutive_409 = 0
                if (r["status"] == 200 and r["stored"] == new_bal) or (isinstance(r["stored"], (int, float)) and r["stored"] > last_bal):
                    success_writes += 1
                    last_bal = r["stored"] if r["stored"] else new_bal
                else:
                    time.sleep(0.7)

            cycle += 1
            if success_writes > 0:
                total_accepted += 1

            extra = f"Wrote {success_writes}/{WRITES_PER_CYCLE}" if success_writes < WRITES_PER_CYCLE else ""
            edit_queue.put((chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, extra=extra)))
            adaptive_delay(total_accepted)

        except Exception as e:
            edit_queue.put((chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, extra=f"Err: {str(e)[:25]}")))
            time.sleep(3)

    edit_queue.put((chat_id, status_msg_id, live_status(cycle, last_bal, total_accepted, amount, running=False)))
    fname = f"telemetry_{chat_id}.json"
    with open(fname, "w") as f:
        json.dump(telemetry, f, indent=2)
    edit_queue.put((chat_id, None, card("STOPPED", f"File → {fname}\nAccepted cycles: {total_accepted}")))

async def edit_worker(app):
    while True:
        try:
            chat_id, msg_id, text = edit_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.3)
            continue
        try:
            if msg_id is None:
                await app.bot.send_message(chat_id=chat_id, text=text)
            else:
                await app.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
        except:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    kb = admin_menu() if is_admin(user_id) else main_menu()
    text = f"{banner('LAGOS LIFE BOT')}\n\nChoose an option below:"
    if update.message:
        await update.message.reply_text(text, reply_markup=kb)
    else:
        await update.callback_query.edit_message_text(text, reply_markup=kb)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data

    if data == "login":
        waiting_for[chat_id] = "login"
        await query.edit_message_text(card("LOGIN", "Send your username and password\n\nExample:\nlegacy_dev mypassword"))
        return

    if data == "set_amount":
        if chat_id not in user_sessions:
            await query.edit_message_text(card("ERROR", "Please Login first"), reply_markup=main_menu())
            return
        waiting_for[chat_id] = "amount"
        await query.edit_message_text(card("SET AMOUNT", "Send the amount per write\n\nExample: 30000"))
        return

    if data == "run":
        if chat_id not in user_sessions:
            await query.edit_message_text(card("ERROR", "Please Login first"), reply_markup=main_menu())
            return
        if user_sessions[chat_id]["running"]:
            await query.edit_message_text(card("INFO", "Already running"), reply_markup=main_menu())
            return
        amount = user_sessions[chat_id].get("amount", 50000)
        msg = await query.message.reply_text(live_status(0, 0, 0, amount, extra="Starting..."))
        user_sessions[chat_id]["status_msg_id"] = msg.message_id
        user_sessions[chat_id]["running"] = True
        t = threading.Thread(target=progression_loop, args=(chat_id, msg.message_id), daemon=True)
        user_sessions[chat_id]["thread"] = t
        t.start()
        await query.edit_message_text(card("STARTED", "Multi-write started"), reply_markup=main_menu())
        return

    if data == "stop":
        if chat_id not in user_sessions or not user_sessions[chat_id]["running"]:
            await query.edit_message_text(card("INFO", "Nothing is running"), reply_markup=main_menu())
            return
        user_sessions[chat_id]["running"] = False
        await query.edit_message_text(card("STOPPING", "Finishing current cycle..."), reply_markup=main_menu())
        return

    if data == "status":
        if chat_id not in user_sessions:
            await query.edit_message_text(card("ERROR", "Please Login first"), reply_markup=main_menu())
            return
        save = read_save(user_sessions[chat_id]["session"])
        if not save or "game" not in save:
            await query.edit_message_text(card("ERROR", "Could not read save"), reply_markup=main_menu())
            return
        bal = save["game"].get("money", 0)
        running = user_sessions[chat_id]["running"]
        amount = user_sessions[chat_id].get("amount", 50000)
        status_txt = "🟢 RUNNING" if running else "⚪ IDLE"
        total = amount * WRITES_PER_CYCLE
        await query.edit_message_text(
            card("STATUS", f"User     : {user_sessions[chat_id]['username']}\n"
                           f"Per write: ₦{amount:,}\n"
                           f"Per cycle: ₦{total:,}\n"
                           f"Balance  : ₦{bal:,}\n"
                           f"State    : {status_txt}"),
            reply_markup=main_menu()
        )
        return

    if data == "help":
        await query.edit_message_text(
            f"{banner('HELP')}\n\n"
            "1. Login with your account\n"
            "2. Set amount per write\n"
            "3. Press Run\n\n"
            f"One cycle = {WRITES_PER_CYCLE} small writes",
            reply_markup=main_menu()
        )
        return

    if is_admin(user_id):
        if data == "admin":
            running = sum(1 for s in user_sessions.values() if s.get("running"))
            await query.edit_message_text(
                f"{banner('ADMIN PANEL')}\n\n"
                f"Total users      : {len(all_users)}\n"
                f"Logged in now    : {len(user_sessions)}\n"
                f"Currently running: {running}",
                reply_markup=admin_menu()
            )
            return
        if data == "sessions":
            if not user_sessions:
                await query.edit_message_text(card("SESSIONS", "No active sessions"), reply_markup=admin_menu())
                return
            lines = [f"• {s.get('username','?')} | {'🟢 RUNNING' if s.get('running') else '⚪ IDLE'} | ₦{s.get('amount',0):,}" for s in user_sessions.values()]
            await query.edit_message_text(card("ACTIVE SESSIONS", "\n".join(lines)), reply_markup=admin_menu())
            return
        if data == "users":
            running = sum(1 for s in user_sessions.values() if s.get("running"))
            await query.edit_message_text(
                card("USERS", f"Total unique : {len(all_users)}\nLogged in    : {len(user_sessions)}\nRunning now  : {running}"),
                reply_markup=admin_menu()
            )
            return
        if data == "broadcast":
            waiting_for[chat_id] = "broadcast"
            await query.edit_message_text(card("BROADCAST", "Send the message you want to broadcast"))
            return

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if chat_id not in waiting_for:
        kb = admin_menu() if is_admin(user_id) else main_menu()
        await update.message.reply_text(f"{banner('LAGOS LIFE BOT')}\n\nChoose an option:", reply_markup=kb)
        return

    state = waiting_for[chat_id]

    if state == "login":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(card("ERROR", "Send: username password"))
            return
        username, password = parts[0], parts[1]
        session = make_session()
        login_res = raw(session, "/api/auth/login", "POST", {"username": username, "password": password})
        if login_res["status"] != 200:
            await update.message.reply_text(card("AUTH FAILED", f"Status {login_res['status']}"))
            del waiting_for[chat_id]
            return
        user_sessions[chat_id] = {
            "session": session, "username": username, "running": False,
            "thread": None, "telemetry": {"runs": []}, "status_msg_id": None, "amount": 50000
        }
        all_users.add(chat_id)
        del waiting_for[chat_id]
        total = 50000 * WRITES_PER_CYCLE
        kb = admin_menu() if is_admin(user_id) else main_menu()
        await update.message.reply_text(card("LOGGED IN", f"User : {username}\nDefault: ₦50,000 × {WRITES_PER_CYCLE} = ₦{total:,}"), reply_markup=kb)
        return

    if state == "amount":
        try:
            amount = int(text.replace(",", "").replace("₦", ""))
            if amount < 1000:
                await update.message.reply_text(card("ERROR", "Minimum 1000"))
                return
        except:
            await update.message.reply_text(card("ERROR", "Invalid number"))
            return
        if chat_id not in user_sessions:
            await update.message.reply_text(card("ERROR", "Login first"))
            del waiting_for[chat_id]
            return
        user_sessions[chat_id]["amount"] = amount
        total = amount * WRITES_PER_CYCLE
        del waiting_for[chat_id]
        kb = admin_menu() if is_admin(user_id) else main_menu()
        await update.message.reply_text(card("AMOUNT SET", f"Per write : ₦{amount:,}\nPer cycle : ₦{total:,}"), reply_markup=kb)
        return

    if state == "broadcast" and is_admin(user_id):
        success = fail = 0
        for cid in list(all_users):
            try:
                await context.bot.send_message(chat_id=cid, text=f"📢 Broadcast:\n\n{text}")
                success += 1
            except:
                fail += 1
        del waiting_for[chat_id]
        await update.message.reply_text(card("BROADCAST DONE", f"Sent: {success}\nFailed: {fail}"), reply_markup=admin_menu())
        return

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"LagosLife Bot running")
    def log_message(self, *args):
        pass

def start_http_server():
    server = HTTPServer(("0.0.0.0", PORT), DummyHandler)
    server.serve_forever()

async def post_init(app):
    asyncio.create_task(edit_worker(app))

def main():
    threading.Thread(target=start_http_server, daemon=True).start()
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.COMMAND, start))

    print("[*] LagosLife Bot — Full Inline Buttons + Multi-write")
    app.run_polling()

if __name__ == "__main__":
    main()