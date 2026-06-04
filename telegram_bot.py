"""
Ads Telegram Bot — Polling mode for Railway hosting
- Any account name/number → get balance
- Auto alerts when watched accounts drop below 1000 or 500
"""
import os, re, random, requests, logging, json
from dotenv import load_dotenv
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
LONG_LIVED_TOKEN = os.environ.get('LONG_LIVED_TOKEN')   or os.getenv('LONG_LIVED_TOKEN')

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set!")

TEAM_IDS   = [-1003900496674]
WATCH_KEYS = {'mall', 'kemet', 'bsq', 'eladel', 'maspipe', 'sedra', 'showpink', 'belal'}
THRESHOLDS = [1000, 500]
ALERTS_FILE = '/tmp/sent_alerts.json'

def load_alerts():
    try:
        with open(ALERTS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_alerts(data):
    with open(ALERTS_FILE, 'w') as f:
        json.dump(data, f)

sent_alerts = load_alerts()

MESSAGES_1000 = [
    "⚠️ تنبيه: رصيد اكونت {name} وصل لـ {balance}",
]

MESSAGES_500 = [
    "🚨 تنبيه عاجل: رصيد اكونت {name} وصل لـ {balance}",
]

ACCOUNTS = [
    {'key': 'eladel',   'id': 'act_1392109118185589', 'label': 'Al Adel',       'ar': ['العادل', 'الادل', 'ادل', 'عادل', 'el adel', 'aladel']},
    {'key': 'bsq',      'id': 'act_841897980911694',  'label': 'BSQ',           'ar': ['بي اس كيو', 'بي إس كيو', 'بيإسكيو']},
    {'key': 'mall',     'id': 'act_2001687506868513', 'label': 'Mall',          'ar': ['مول', 'مال', 'المول']},
    {'key': 'kemet',    'id': 'act_345674018149436',  'label': 'Kemet',         'ar': ['كيميت', 'كيمت']},
    {'key': 'maspipe',  'id': 'act_1774284989787459', 'label': 'Mas-Pipe',      'ar': ['ماس بيب', 'ماسبيب', 'ماس-بيب', 'مسبيب']},
    {'key': 'showpink', 'id': 'act_1803969103895553', 'label': 'ShowPink',      'ar': ['شوبينك', 'شو بينك', 'شو-بينك']},
    {'key': 'belal',    'id': 'act_1091777362163635', 'label': 'Belal Khier',   'ar': ['بلال', 'بلال خير']},
    {'key': 'sedra',    'id': 'act_1303633554699002', 'label': 'Sedra',         'ar': ['سيدرا', 'سدرا', 'سدره', 'سيدره']},
    {'key': 'essam',    'id': 'act_325431983464353',  'label': 'Mohamed Essam', 'ar': ['محمد عصام', 'عصام', 'essam']},
    {'key': 'audiopiano', 'id': 'act_290197205187544', 'label': 'Audio Piano',   'ar': ['اوديو بيانو', 'بيانو', 'audio piano']},
]

ACCOUNTS_BY_INDEX = {i+1: a for i, a in enumerate(ACCOUNTS)}

def find_account(text):
    text = text.strip()
    if text.isdigit():
        return ACCOUNTS_BY_INDEX.get(int(text))
    tl = text.lower()
    for a in ACCOUNTS:
        if tl in a['label'].lower() or a['key'] in tl or tl == a['key']:
            return a
        for alias in a.get('ar', []):
            if alias in tl or tl in alias:
                return a
    return None

def get_balance_raw(acc):
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{acc['id']}",
            params={'access_token': LONG_LIVED_TOKEN, 'fields': 'balance,currency,funding_source_details'},
            timeout=15
        )
        d = r.json()
    except Exception as e:
        logger.error(f"Request failed for {acc['label']}: {e}")
        return f"{acc['label']}: خطأ في الاتصال", None

    if 'error' in d:
        err_msg = d['error'].get('message', str(d['error']))
        logger.warning(f"API error for {acc['label']}: {d['error']}")
        return f"{acc['label']}: خطأ — {err_msg}", None

    currency = d.get('currency', 'EGP')

    # 1) funding_source_details display_string
    display = d.get('funding_source_details', {}).get('display_string', '')
    if display:
        # normalize Arabic-Indic digits → ASCII
        ar_map = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
        norm = display.translate(ar_map).replace(',', '')
        # try parentheses first: "Visa (EGP 997.45)"
        match = re.search(r'\(([^)]*[\d][^)]*)\)', norm)
        if not match:
            # try without parentheses: "Fawry EGP 997.45" or "فوري: 997.45"
            match = re.search(r'([\d]+\.[\d]+|[\d]{3,})', norm)
        if match:
            num = re.sub(r'[^\d.]', '', match.group(1))
            try:
                value = float(num)
                if value > 10:
                    return f"{acc['label']}: {currency} {value:,.2f}", value
            except Exception:
                pass

    # 2) fallback: balance field (cents / 100)
    raw   = int(d.get('balance', 0))
    value = raw / 100
    return f"{acc['label']}: {currency} {value:,.2f}", value

def get_balance(acc):
    text, _ = get_balance_raw(acc)
    return text

def accounts_list():
    lines = ["الاكونتات المتاحة:\n"]
    for i, a in enumerate(ACCOUNTS, 1):
        lines.append(f"{i}. {a['label']}")
    lines.append("\nابعت الاسم او الرقم عشان تعرف الرصيد")
    return '\n'.join(lines)

async def check_balances(context):
    bot = context.bot
    watch_accounts = [a for a in ACCOUNTS if a['key'] in WATCH_KEYS]
    for acc in watch_accounts:
        display, value = get_balance_raw(acc)
        if value is None:
            continue
        key = acc['key']
        if key not in sent_alerts:
            sent_alerts[key] = {}
        for threshold in THRESHOLDS:
            alert_key = str(threshold)
            if value <= threshold and not sent_alerts[key].get(alert_key):
                msgs = MESSAGES_1000 if threshold == 1000 else MESSAGES_500
                balance_display = f"{value:,.0f} جنيه"
                msg = random.choice(msgs).format(name=acc['label'], balance=balance_display)
                for chat_id in TEAM_IDS:
                    try:
                        await bot.send_message(chat_id=chat_id, text=msg)
                    except Exception as e:
                        logger.error(f"Failed to send to {chat_id}: {e}")
                sent_alerts[key][alert_key] = True
                save_alerts(sent_alerts)
            elif value > threshold and sent_alerts[key].get(alert_key):
                sent_alerts[key][alert_key] = False
                save_alerts(sent_alerts)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    # في الجروب: رد بس لو فيه منشن للبوت
    if update.message.chat.type in ['group', 'supergroup']:
        bot_username = f"@{context.bot.username}"
        if bot_username.lower() not in text.lower():
            return
        text = text.replace(bot_username, '').replace(bot_username.lower(), '').strip()

    tl   = text.lower()

    if any(w in tl for w in ['رصيد كل', 'كل', 'all', 'الكل', 'list', 'قائمة']):
        await update.message.reply_text(accounts_list())
        return

    acc = find_account(text)
    if acc:
        await update.message.reply_text("جاري الجلب...")
        await update.message.reply_text(get_balance(acc))
        return

    await update.message.reply_text(
        "مش فاهم 🤔\n\nجرب:\n- كل — عرض الاكونتات\n- ابعت اسم الاكونت او رقمه"
    )

def kb_accounts():
    rows = []
    for i in range(0, len(ACCOUNTS), 3):
        rows.append([
            InlineKeyboardButton(a['label'], callback_data=f"bal:{a['key']}")
            for a in ACCOUNTS[i:i+3]
        ])
    return InlineKeyboardMarkup(rows)

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اختار الاكونت 👇", reply_markup=kb_accounts())

async def on_balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith('bal:'):
        return
    key = query.data.split(':')[1]
    acc = next((a for a in ACCOUNTS if a['key'] == key), None)
    if not acc:
        await query.edit_message_text("مش لاقي الاكونت ده.")
        return
    await query.edit_message_text("⏳ جاري الجلب...")
    balance_text = get_balance(acc)
    await query.edit_message_text(balance_text, reply_markup=kb_accounts())

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"User ID: `{update.message.from_user.id}`\nChat ID: `{update.message.chat.id}`",
        parse_mode='Markdown'
    )

async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != 932647337:
        return
    await update.message.reply_text("بفحص الارصدة...")
    await check_balances(context)
    await update.message.reply_text("خلص الفحص")


async def watched_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != 932647337:
        return
    await update.message.reply_text("جاري الجلب...")
    watch_accounts = [a for a in ACCOUNTS if a['key'] in WATCH_KEYS]
    lines = []
    for acc in watch_accounts:
        display, value = get_balance_raw(acc)
        icon = '✅' if value and value > 1000 else ('⚠️' if value and value > 500 else '🚨')
        lines.append(f"{display} ({icon})" if value else display)
    await update.message.reply_text('\n'.join(lines))

def build_app():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('balance', cmd_balance))
    app.add_handler(CommandHandler('myid', myid))
    app.add_handler(CommandHandler('test', test_cmd))
    app.add_handler(CommandHandler('watched', watched_cmd))
    app.add_handler(CallbackQueryHandler(on_balance_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(check_balances, interval=7200, first=60)
    return app

def main():
    build_app().run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
