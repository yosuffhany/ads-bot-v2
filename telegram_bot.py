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

TEAM_IDS   = [-1002900496674]
WATCH_KEYS = {'mall', 'kemet', 'bsq', 'eladel', 'maspipe', 'sedra'}
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
    {'key': 'totti',        'id': 'act_3046772235501325', 'label': 'Totti Gallery',    'ar': ['توتي', 'توتى', 'توتي جاليري']},
    {'key': 'maspipe',      'id': 'act_1774284989787459', 'label': 'Mas-Pipe',         'ar': ['ماس بيب', 'ماسبيب', 'ماس-بيب', 'مسبيب']},
    {'key': 'sofy',         'id': 'act_650311242463923',  'label': 'Sofy',             'ar': ['صوفي', 'صوفى', 'سوفي']},
    {'key': 'menna',        'id': 'act_10150765286975596','label': 'Menna Hossam',     'ar': ['منه', 'منة', 'منه حسام', 'منة حسام']},
    {'key': 'bison',        'id': 'act_465578978509965',  'label': 'Bison Ads',        'ar': ['بايسون', 'بيسون']},
    {'key': 'effect1',      'id': 'act_5394586653914394', 'label': 'Effect ADV 01',    'ar': ['افيكت 1', 'إيفيكت 1', 'ايفيكت 01']},
    {'key': 'eladel_old',   'id': 'act_276905741576386',  'label': 'Al Adel (old)',    'ar': ['العادل القديم', 'الادل القديم']},
    {'key': 'fawry1',       'id': 'act_648289100485879',  'label': 'Effect Fawry 1',   'ar': ['فوري 1', 'فوري واحد']},
    {'key': 'essam',        'id': 'act_325431983464353',  'label': 'Mohamed Essam',    'ar': ['محمد عصام', 'عصام']},
    {'key': 'eladel',       'id': 'act_1392109118185589', 'label': 'Al Adel',          'ar': ['العادل', 'الادل', 'ادل', 'عادل', 'el adel', 'aladel']},
    {'key': 'sua',          'id': 'act_925588948913339',  'label': 'Effect SUA',       'ar': ['سوا', 'اس يو ايه']},
    {'key': 'mall',         'id': 'act_2001687506868513', 'label': 'Mall',             'ar': ['مول', 'مال', 'المول']},
    {'key': 'kemet',        'id': 'act_345674018149436',  'label': 'Kemet',            'ar': ['كيميت', 'كيمت']},
    {'key': 'divine',       'id': 'act_434106209039266',  'label': 'Divine by JJ',     'ar': ['ديفاين', 'دايفاين', 'دفاين']},
    {'key': 'abdelfattah',  'id': 'act_2378819405831678', 'label': 'Abdelfattah',      'ar': ['عبدالفتاح', 'عبد الفتاح']},
    {'key': 'bsq',          'id': 'act_841897980911694',  'label': 'BSQ',              'ar': ['بي اس كيو', 'بي إس كيو', 'بيإسكيو']},
    {'key': 'padel',        'id': 'act_1289017779213803', 'label': 'Play Padel',       'ar': ['بلاي بادل', 'بادل', 'padel']},
    {'key': 'effect3egp',   'id': 'act_568221719329142',  'label': 'Effect 3',         'ar': ['افيكت ثري', 'ايفيكت 3']},
    {'key': 'fawry2',       'id': 'act_878027737746620',  'label': 'Effect Fawry 2',   'ar': ['فوري 2', 'فوري اتنين']},
    {'key': 'studio',       'id': 'act_580360561671663',  'label': 'Effect Studio',    'ar': ['ستوديو', 'افيكت ستوديو']},
    {'key': 'ideasport',    'id': 'act_859756096002270',  'label': 'Idea Sport',       'ar': ['ايديا سبورت', 'فكرة سبورت']},
    {'key': 'sara',         'id': 'act_1279182850047520', 'label': 'Sara Essam',       'ar': ['سارة عصام', 'سارا عصام', 'سارة']},
    {'key': 'mriya',        'id': 'act_1212371947222820', 'label': 'Mriya Homes',      'ar': ['مريا', 'مريا هومز', 'مريا هوم']},
    {'key': 'tamra1',       'id': 'act_1272360541135475', 'label': 'Tamra & Balaha 1', 'ar': ['تمرة 1', 'تمرة وبلحة 1', 'تمرة وبلحة']},
    {'key': 'yass',         'id': 'act_1489770438885179', 'label': 'Yass Coffee',      'ar': ['ياس', 'ياس كوفي', 'ياس قهوة']},
    {'key': 'tamra2',       'id': 'act_1818266555783618', 'label': 'Tamra & Balaha 2', 'ar': ['تمرة 2', 'تمرة وبلحة 2']},
    {'key': 'showpink',     'id': 'act_1803969103895553', 'label': 'ShowPink',         'ar': ['شوبينك', 'شو بينك', 'شو-بينك']},
    {'key': 'move',         'id': 'act_710148088755737',  'label': 'Move',             'ar': ['موف']},
    {'key': 'vip',          'id': 'act_1123106382965581', 'label': 'Vip Perfume',      'ar': ['فيب', 'فيب برفيوم']},
    {'key': 'yaqoot',       'id': 'act_769479552712823',  'label': 'YaqootEG',         'ar': ['ياقوت', 'ياقوت إيجي']},
    {'key': 'belal',        'id': 'act_1091777362163635', 'label': 'Belal Khier',      'ar': ['بلال', 'بلال خير']},
    {'key': 'yakootcoffee', 'id': 'act_1136771131607775', 'label': 'Yakoot Coffee',    'ar': ['ياقوت كوفي', 'ياقوت قهوة']},
    {'key': 'looklook',     'id': 'act_879890704620098',  'label': 'Look Look',        'ar': ['لوك لوك', 'لوكلوك']},
    {'key': 'sedra',        'id': 'act_1303633554699002', 'label': 'Sedra',            'ar': ['سيدرا', 'سدرا', 'سدره', 'سيدره']},
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
        return f"{acc['label']}: خطأ", None

    currency = d.get('currency', '')
    display  = d.get('funding_source_details', {}).get('display_string', '')
    match    = re.search(r'\((.+?)\)', display)
    if match:
        amount_str = match.group(1)
        num = re.sub(r'[^\d.]', '', amount_str.replace(',', ''))
        try:
            value = float(num)
        except Exception:
            value = None
        return f"{acc['label']}: {amount_str}", value

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
    await update.message.reply_text(f"Your ID: `{update.message.from_user.id}`", parse_mode='Markdown')

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
