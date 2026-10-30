FLIT DARK LUXURY MINI APP v1
================================

WHAT IS INCLUDED
- Dark Luxury responsive Telegram Mini App frontend.
- FastAPI backend with Telegram WebApp initData signature verification.
- Uses the same SQLite game_bot.db as your existing bot.
- Profile / balances / XP / game record.
- Harem list with search, rarity filter and pagination.
- Character market: browse, buy, list and withdraw-ready backend.
- Auction house: active auction list and bid support.
- Wallet activity list.

IMPORTANT
1. The uploaded v14 Python bot file does not include game_bot.db. The app reads the database beside this folder by default.
2. Do not run the bot and Mini App against two different copies of game_bot.db. Set GAME_BOT_DB to the exact same database path used by the bot.
3. Telegram Mini Apps require a publicly reachable HTTPS URL. Hosting was selected as NONE, so this package can be previewed locally in demo mode, but it cannot yet be opened by other Telegram users.
4. The Arcade tab displays game records only. Wager-based casino play is intentionally not exposed inside this Mini App.
5. Never share your bot token. Put it only in a private .env file on your server.

LOCAL PREVIEW ON TERMUX
-----------------------
cd ~/storage/downloads/FLIT_Dark_Luxury_MiniApp_v1
pkg update -y
pkg install python -y
pip install -r requirements.txt
export MINIAPP_DEMO=1
uvicorn miniapp_server:app --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000 in your phone browser.
Demo mode uses sample data and does not write to your real bot database.

REAL DATABASE MODE
------------------
- Copy this folder beside your existing bot script and game_bot.db.
- Create a .env file with:
  BOT_TOKEN=YOUR_BOT_TOKEN
  GAME_BOT_DB=/full/path/to/game_bot.db
- Stop demo mode (unset MINIAPP_DEMO or set it to 0).
- Start:
  uvicorn miniapp_server:app --host 127.0.0.1 --port 8000

For a real Telegram Mini App, deploy this same app on a secure HTTPS host and set its URL in BotFather / your bot's Web App button. A local 127.0.0.1 URL is not public and will not work inside Telegram for other users.

BOT WEB APP BUTTON (AFTER HTTPS HOSTING)
----------------------------------------
Add a command/button to your existing bot after you have a public HTTPS URL:

from telebot import types

@bot.message_handler(commands=["miniapp"])
def open_miniapp(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "✨ OPEN FLIT MINI APP",
        web_app=types.WebAppInfo(url="https://YOUR-PUBLIC-HTTPS-URL/")
    ))
    bot.reply_to(message, "Open your FLIT Universe dashboard:", reply_markup=markup)

Do not put a placeholder URL into the live bot. Replace it with your real HTTPS URL first.

DATABASE SAFETY
---------------
The API uses SQLite transactions (BEGIN IMMEDIATE) for market purchases, listings and auction bids.
Keep backups of game_bot.db before testing real transactions.
