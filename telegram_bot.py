"""
Ads Telegram Bot — balance queries only (runs on Railway)
Commands:
  رصيد مول / balance mall     → Mall balance
  رصيد bsq                   → BSQ balance
  رصيد كيميت / balance kemet → Kemet balance
  رصيد كل / balance all      → All balances
"""
import os, re, requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

load_dotenv()  # local only, ignored on Railway

TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
LONG_LIVED_TOKEN = os.environ.get('LONG_LIVED_TOKEN')   or os.getenv('LONG_LIVED_TOKEN')

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set!")

ACCOUNTS = {
    'mall':  {'id': 'act_2001687506868513', 'label': 'Mall'},
    'bsq':   {'id': 'act_841897980911694',  'label': 'BSQ'},
    'kemet': {'id': 'act_345674018149436',  'label': 'Kemet'},
}

KEYWORDS = {
    'mall':  ['mall', 'مول'],
    'bsq':   ['bsq', 'بي اس كيو', 'بيسكيو'],
    'kemet': ['kemet', 'كيميت'],
    'all':   ['كل', 'all', 'الكل'],
}

def detect_account(text):
    text = text.lower()
    for key, words in KEYWORDS.items():
        if any(w in text for w in words):
            return key
    return None

def detect_action(text):
    text = text.lower()
    if any(w in text for w in ['رصيد', 'balance', 'فلوس', 'كام']):
        return 'balance'
    return None

def get_balance(account_key):
    acc = ACCOUNTS[account_key]
    r = requests.get(
        f"https://graph.facebook.com/v19.0/{acc['id']}",
        params={'access_token': LONG_LIVED_TOKEN, 'fields': 'funding_source_details,currency'}
    )
    d = r.json()
    display = d.get('funding_source_details', {}).get('display_string', 'N/A')
    match = re.search(r'\((.+?)\)', display)
    amount = match.group(1) if match else display
    return f"{acc['label']}: {amount}"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text    = update.message.text or ''
    action  = detect_action(text)
    account = detect_account(text)

    if not action:
        await update.message.reply_text(
            "مش فاهم 🤔\n\n"
            "جرب:\n"
            "• رصيد مول\n"
            "• رصيد bsq\n"
            "• رصيد كيميت\n"
            "• رصيد كل"
        )
        return

    if action == 'balance':
        keys = list(ACCOUNTS.keys()) if account in ('all', None) else [account]
        await update.message.reply_text("جاري الجلب...")
        lines = []
        for k in keys:
            try:
                lines.append(get_balance(k))
            except Exception as e:
                lines.append(f"{ACCOUNTS[k]['label']}: خطأ ({e})")
        await update.message.reply_text('\n'.join(lines))

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot running...")
    app.run_polling()

if __name__ == '__main__':
    main()
