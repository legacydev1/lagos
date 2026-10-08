#!/usr/bin/env python3
"""
LagosLife Progression Bot — Custom amount per cycle
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
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest, TimedOut, NetworkError

TELEGRAM_TOKEN = "8924966752:AAHASJW1QsBe9Q1rLtCdDcZm800wTueNV-o"   # your token
BASE = "https://lagoslife.app"
PORT = int(os.getenv("PORT", 10000))

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

def banner(title: str) -> str:
    return (
        "╭──────────────────────────╮\n"
        f"│  {title.center(22)}  │\n"
        "╰──────────────────────────╯"
    )

def card(title: str, body: str) -> str:
    return (
        f"┌─ {title} ────────────────\n"
        f"{body}\n"
        "└──────────────────────────"
    )

def progress_bar(current: int, total: int = 14) -> str:
    filled = min(current % (total + 1), total)
    return "▓" * filled + "░" * (total - filled)

def live_status(cycle, bal, accepted, amount, running=True, extra=""):
    state = "🟢 RUNNING" if running else "🔴 STOPPED"
    bar = progress_bar(accepted)
    text = (
        f"{banner('LIVE STATUS')}\n\n"
        f"Amount   : ₦{amount:,}\n"
        f"State    : {state}\n"
        f"Cycle    : {cycle}\n"
        f"Balance  : ₦{bal:,}\n"
        f"Success  : {accepted}\n"
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
    base = 1.8 + min(successes * 0.08, 3.5)
    time.sleep(random.uniform(base, base + 1.6))

def raw(session, path, method, body_dict=None):
    url = BASE + path
    try:
        if method == "GET":
            res = session.get(url, allow_redirects=False, timeout=20)
        elif method == "POST":
            res = session.post(url, json=body_dict, allow_redirects=False, timeout=20)
        elif method == "PUT":
            res = session.put(url, json=body_dict, allow_redirects=False, timeout=20)
        else:
            return {"status": 400, "json": None}
        try:
            data = res.json()
        except Exception:
            try:
                data = json.loads(res.content.decode("utf-8", errors="ignore"))
            except Exception:
                data = res.text
        return {"status": res.status_code, "json": data}
    except Exception as err:
        return {"status": 500, "json": str(err)}

def read_save(session):
    res = raw(session, "/api/save", "GET")
    if res["status"] != 200 or not isinstance(res["json"], dict):
        return None
    return res["json"]

def set_money_with_sync(session, v):
    cur = read_save(session)
    if not cur or "game" not in cur:
        return {"status": 500, "code": "INVALID_SAVE", "stored": None}
    g = json.loads(json.dumps(cur["game"]))
    g["money"] = v
    timestamp = cur.get("updatedAt")
    r = raw(session, "/api/save", "PUT", {"game": g, "base": timestamp})
    time.sleep(1.2)
    back = read_save(session)
    code = r["json"].get("code", "") if isinstance(r["json"], dict) else ""
    stored = back.get("game", {}).get("money") if isinstance(back, dict) else None
    return {"status": r["status"], "code": code, "stored": stored}

def progression_loop(chat_id, status_msg_id):
    state = user_sessions[chat_id]
    session = state["session"]
    amount = state.get("amount", 75000)
    telemetry = state["telemetry"]
    cycle = 0
    total_accepted = 0
    last_bal = 0

    cur = read_save(session)
    if cur and "game" in cur:
        last_bal = cur["game"].get("money", 0)
    edit_queue.put((chat_id, status_msg_id, live_status(0, last_bal, 0, amount, extra="Starting...")))

    while state["running"]:
        try:
            cur = read_save(session)
            if not cur or "game" not in cur:
                edit_queue.put((chat_id, status_msg_id,
                                live_status(cycle, last_bal, total_accepted, amount, extra="⚠️ Fetch failed")))
                time.sleep(5)
                continue

            bal = cur["game"].get("money", 0)
            last_bal = bal
            new_bal = bal + amount

            r = set_money_with_sync(session, new_bal)

            telemetry["runs"].append({
                "cycle": cycle + 1,
                "target": new_bal,
                "status": r["status"],
                "stored": r["stored"],
                "amount": amount
            })

            if r["status"] in (429, 403):
                edit_queue.put((chat_id, status_msg_id,
                                live_status(cycle, last_bal, total_accepted, amount, extra="⚠️ Rate limit – cooling")))
                time.sleep(28)
                continue

            cycle += 1
            if (r["status"] == 200 and r["stored"] == new_bal) or \
               (isinstance(r["stored"], (int, float)) and r["stored"] > last_bal):
                total_accepted += 1
                last_bal = r["stored"] if r["stored"] else new_bal
                extra = ""
            else:
                extra = f"⚠️ Sync {r['status']}"

            edit_queue.put((chat_id, status_msg_id,
                            live_status(cycle, last_bal, total_accepted, amount, extra=extra)))

            adaptive_delay(total_accepted)

        except Exception as e:
            edit_queue.put((chat_id, status_msg_id,
                            live_status(cycle, last_bal, total_accepted, amount, extra=f"Err: {str(e)[:28]}")))
            time.sleep(4)

    edit_queue.put((chat_id, status_msg_id,
                    live_status(cycle, last_bal, total_accepted, amount, running=False)))

    fname = f"telemetry_{chat_id}.json"
    with open(fname, "w") as f:
        json.dump(telemetry, f, indent=2)

    edit_queue.put((chat_id, None,
                    card("STOPPED", f"File → {fname}\nAccepted: {total_accepted}")))

async def edit_worker(app):
    while True:
        try:
            chat_id, msg_id, text = edit_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.35)
            continue
        try:
            if msg_id is None:
                await app.bot.send_message(chat_id=chat_id, text=text)
            else:
                await app.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
        except (BadRequest, TimedOut, NetworkError):
            pass
        except Exception:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔑 Login", callback_data="help_login")],
        [InlineKeyboardButton("⚙ Set Amount", callback_data="help_set"),
         InlineKeyboardButton("▶ Run", callback_data="help_run")],
        [InlineKeyboardButton("⏹ Stop", callback_data="help_stop"),
         InlineKeyboardButton("📊 Status", callback_data="help_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"{banner('LAGOS LIFE BOT')}\n\n"
        "• /login <user> <pass>\n"
        "• /set <amount>   → set money per cycle\n"
        "• /run            → start with your amount\n"
        "• /stop\n"
        "• /status\n"
        "• /help"
    )
    await update.message.reply_text(text, reply_markup=reply_markup)

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(card("USAGE", "/login <username> <password>"))
        return

    username = context.args[0]
    password = " ".join(context.args[1:])
    session = make_session()
    login_res = raw(session, "/api/auth/login", "POST", {"username": username, "password": password})

    if login_res["status"] != 200:
        await update.message.reply_text(card("AUTH FAILED", f"Status {login_res['status']}"))
        return

    user_sessions[chat_id] = {
        "session": session,
        "username": username,
        "running": False,
        "thread": None,
        "telemetry": {"runs": []},
        "status_msg_id": None,
        "amount": 75000
    }
    await update.message.reply_text(
        card("LOGGED IN", f"User : {username}\nDefault amount: ₦75,000\nUse /set to change")
    )

async def set_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions:
        await update.message.reply_text(card("ERROR", "Not logged in.\nUse /login first."))
        return
    if not context.args:
        await update.message.reply_text(card("USAGE", "/set <amount>\nExample: /set 500000"))
        return

    try:
        amount = int(context.args[0].replace(",", "").replace("₦", ""))
        if amount < 1000:
            await update.message.reply_text(card("ERROR", "Amount too small (min 1000)"))
            return
    except ValueError:
        await update.message.reply_text(card("ERROR", "Invalid number"))
        return

    user_sessions[chat_id]["amount"] = amount
    await update.message.reply_text(
        card("AMOUNT SET", f"Now adding ₦{amount:,} every cycle\nUse /run to start")
    )

async def run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions:
        await update.message.reply_text(card("ERROR", "Not logged in.\nUse /login first."))
        return
    if user_sessions[chat_id]["running"]:
        await update.message.reply_text(card("INFO", "Already running."))
        return

    amount = user_sessions[chat_id].get("amount", 75000)
    msg = await update.message.reply_text(live_status(0, 0, 0, amount, extra="Starting..."))
    user_sessions[chat_id]["status_msg_id"] = msg.message_id
    user_sessions[chat_id]["running"] = True

    t = threading.Thread(
        target=progression_loop,
        args=(chat_id, msg.message_id),
        daemon=True
    )
    user_sessions[chat_id]["thread"] = t
    t.start()

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions or not user_sessions[chat_id]["running"]:
        await update.message.reply_text(card("INFO", "Nothing is running."))
        return
    user_sessions[chat_id]["running"] = False
    await update.message.reply_text(card("STOPPING", "Finishing current cycle..."))

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions:
        await update.message.reply_text(card("ERROR", "Not logged in."))
        return

    save = read_save(user_sessions[chat_id]["session"])
    if not save or "game" not in save:
        await update.message.reply_text(card("ERROR", "Could not read save."))
        return

    bal = save["game"].get("money", 0)
    running = user_sessions[chat_id]["running"]
    amount = user_sessions[chat_id].get("amount", 75000)
    status_txt = "🟢 RUNNING" if running else "⚪ IDLE"

    await update.message.reply_text(
        card("STATUS", f"User    : {user_sessions[chat_id]['username']}\n"
                       f"Amount  : ₦{amount:,}\n"
                       f"Balance : ₦{bal:,}\n"
                       f"State   : {status_txt}")
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    mapping = {
        "help_login": ("LOGIN", "/login <username> <password>"),
        "help_set": ("SET AMOUNT", "/set <amount>\nExample: /set 250000"),
        "help_run": ("RUN", "/run → start with your amount"),
        "help_stop": ("STOP", "/stop → halt safely"),
        "help_status": ("STATUS", "/status → show current info")
    }
    if data in mapping:
        title, body = mapping[data]
        await query.edit_message_text(card(title, body))

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"LagosLife Bot is running")
    def log_message(self, format, *args):
        pass

def start_http_server():
    server = HTTPServer(("0.0.0.0", PORT), DummyHandler)
    print(f"[*] Dummy HTTP server on port {PORT}")
    server.serve_forever()

async def post_init(app: Application):
    asyncio.create_task(edit_worker(app))

def main():
    threading.Thread(target=start_http_server, daemon=True).start()
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("set", set_amount))
    app.add_handler(CommandHandler("run", run_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("[*] LagosLife Bot online – Custom amount mode")
    app.run_polling()

if __name__ == "__main__":
    main()