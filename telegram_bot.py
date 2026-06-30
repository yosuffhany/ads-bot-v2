"""
Ads Telegram Bot — Polling mode for Railway hosting
- Any account name/number → get spend data from Windsor
- Auto alerts when watched accounts drop below 1000 or 500 (Meta balance)
"""
import os, re, random, requests, logging, json
from datetime import date
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
WINDSOR_API_KEY  = os.environ.get('WINDSOR_API_KEY')    or os.getenv('WINDSOR_API_KEY')

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set!")

TEAM_IDS    = [-1003900496674]
WATCH_KEYS  = {'mall', 'kemet', 'bsq', 'eladel', 'maspipe', 'sedra', 'showpink', 'belal'}
THRESHOLDS  = [1000, 500]
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

MESSAGES_1000 = ["⚠️ تنبيه: رصيد اكونت {name} وصل لـ {balance}"]
MESSAGES_500  = ["🚨 تنبيه عاجل: رصيد اكونت {name} وصل لـ {balance}"]

ACCOUNTS = [
    {'key': 'eladel',     'id': 'act_1392109118185589', 'label': 'Al Adel',       'ar': ['العادل', 'الادل', 'ادل', 'عادل', 'el adel', 'aladel']},
    {'key': 'bsq',        'id': 'act_841897980911694',  'label': 'BSQ',           'ar': ['بي اس كيو', 'بي إس كيو', 'بيإسكيو']},
    {'key': 'mall',       'id': 'act_2001687506868513', 'label': 'Mall',          'ar': ['مول', 'مال', 'المول']},
    {'key': 'kemet',      'id': 'act_345674018149436',  'label': 'Kemet',         'ar': ['كيميت', 'كيمت']},
    {'key': 'maspipe',    'id': 'act_1774284989787459', 'label': 'Mas-Pipe',      'ar': ['ماس بيب', 'ماسبيب', 'ماس-بيب', 'مسبيب']},
    {'key': 'showpink',   'id': 'act_1803969103895553', 'label': 'ShowPink',      'ar': ['شوبينك', 'شو بينك', 'شو-بينك']},
    {'key': 'belal',      'id': 'act_1091777362163635', 'label': 'Belal Khier',   'ar': ['بلال', 'بلال خير']},
    {'key': 'sedra',      'id': 'act_1303633554699002', 'label': 'Sedra',         'ar': ['سيدرا', 'سدرا', 'سدره', 'سيدره']},
    {'key': 'essam',      'id': 'act_325431983464353',  'label': 'Mohamed Essam', 'ar': ['محمد عصام', 'عصام', 'essam']},
    {'key': 'audiopiano', 'id': 'act_290197205187544',  'label': 'Audio Piano',   'ar': ['اوديو بيانو', 'بيانو', 'audio piano']},
    # TikTok accounts
    {'key': 'tt_mall',  'id': '7477170011656896529', 'label': 'Mall (TikTok)',      'platform': 'tiktok', 'ar': ['مول تيك', 'mall tiktok']},
    {'key': 'tt_safaa', 'id': '7647455477714042881', 'label': 'Dr.Safaa (TikTok)', 'platform': 'tiktok', 'ar': ['صفاء', 'دكتوره صفاء', 'safaa']},
]

ACCOUNTS_BY_INDEX = {i+1: a for i, a in enumerate(ACCOUNTS)}

# ── HELPERS ───────────────────────────────────────────────────────────────────

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

def bare_id(acc_id):
    """Strip 'act_' prefix for Windsor queries."""
    return acc_id.replace('act_', '')

# ── WINDSOR ──────────────────────────────────────────────────────────────────

def windsor_fetch(date_preset, account_id=None):
    """
    Fetch spend+performance from Windsor for one account or all.
    Returns dict: {bare_account_id: {spend, clicks, impressions, reach, cpm}}
    """
    if not WINDSOR_API_KEY:
        return {}
    params = {
        'api_key':     WINDSOR_API_KEY,
        'date_preset': date_preset,
        'fields':      'account_id,spend,clicks,impressions,reach,cpm',
        '_renderer':   'json',
    }
    if account_id:
        params['select_accounts'] = f'facebook__{account_id}'
    try:
        r = requests.get(
            'https://connectors.windsor.ai/facebook',
            params=params,
            timeout=20
        )
        if r.status_code != 200:
            logger.error(f"Windsor HTTP {r.status_code}: {r.text[:200]}")
            return {}
        rows = r.json().get('data', [])
        result = {}
        for row in rows:
            aid = str(row.get('account_id', ''))
            if aid not in result:
                result[aid] = {'spend': 0.0, 'clicks': 0, 'impressions': 0, 'reach': 0, 'cpm': 0.0}
            result[aid]['spend']       += float(row.get('spend',       0) or 0)
            result[aid]['clicks']      += int(float(row.get('clicks',      0) or 0))
            result[aid]['impressions'] += int(float(row.get('impressions', 0) or 0))
            result[aid]['reach']       += int(float(row.get('reach',       0) or 0))
        # CPM: recalculate from totals
        for aid, d in result.items():
            if d['impressions'] > 0:
                d['cpm'] = round(d['spend'] / d['impressions'] * 1000, 2)
        return result
    except Exception as e:
        logger.error(f"Windsor error: {e}")
        return {}

def get_windsor_account_data(acc):
    """Returns formatted string with Windsor spend data for one Meta account."""
    aid = bare_id(acc['id'])
    month = windsor_fetch('this_monthT', aid)
    week  = windsor_fetch('last_7d',     aid)

    d_month = month.get(aid, {})
    d_week  = week.get(aid, {})

    lines = [f"📊 *{acc['label']}*\n"]

    if d_month:
        lines.append(f"📅 *إنفاق الشهر:* {d_month['spend']:,.2f} EGP")
        lines.append(f"👁 إمبريشنز: {d_month['impressions']:,}")
        lines.append(f"🖱 كليكات: {d_month['clicks']:,}")
        if d_month['cpm']:
            lines.append(f"💰 CPM: {d_month['cpm']:,.2f}")
    else:
        lines.append("📅 إنفاق الشهر: لا توجد بيانات")

    if d_week:
        lines.append(f"\n📆 *آخر 7 أيام:* {d_week.get('spend', 0):,.2f} EGP")

    return '\n'.join(lines)

# ── TIKTOK ───────────────────────────────────────────────────────────────────

def get_tiktok_spend(acc):
    """Returns formatted string for TikTok accounts."""
    tok = os.getenv('TIKTOK_ACCESS_TOKEN', '')
    if not tok:
        return f"{acc['label']}: TIKTOK_ACCESS_TOKEN missing"
    today = date.today()
    since = str(date(today.year, today.month, 1))
    until = str(today)
    try:
        import json as _json
        r = requests.get(
            'https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/',
            headers={'Access-Token': tok},
            params={
                'advertiser_id': acc['id'],
                'report_type':   'BASIC',
                'data_level':    'AUCTION_ADVERTISER',
                'dimensions':    _json.dumps(['advertiser_id']),
                'metrics':       _json.dumps(['spend', 'currency']),
                'start_date':    since,
                'end_date':      until,
                'page_size':     1,
            },
            timeout=15
        )
        d = r.json()
        if d.get('code') != 0:
            return f"{acc['label']}: خطأ — {d.get('message','')}"
        rows = d.get('data', {}).get('list', [])
        if not rows:
            return f"📊 *{acc['label']}*\n📅 إنفاق الشهر: 0.00 EGP"
        m        = rows[0]['metrics']
        spend    = round(float(m.get('spend', 0)), 2)
        currency = m.get('currency', 'EGP')
        return f"📊 *{acc['label']}*\n📅 إنفاق الشهر: {currency} {spend:,.2f}"
    except Exception as e:
        logger.error(f"TikTok spend error {acc['label']}: {e}")
        return f"{acc['label']}: خطأ في الاتصال"

# ── META BALANCE (alerts only) ────────────────────────────────────────────────

def get_meta_balance_raw(acc):
    """Used only for balance alerts — returns (display_text, float_value)."""
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{acc['id']}",
            params={'access_token': LONG_LIVED_TOKEN, 'fields': 'balance,currency,funding_source_details'},
            timeout=15
        )
        d = r.json()
    except Exception as e:
        logger.error(f"Meta balance error {acc['label']}: {e}")
        return acc['label'] + ': خطأ', None

    if 'error' in d:
        return acc['label'] + ': خطأ — ' + d['error'].get('message', ''), None

    currency = d.get('currency', 'EGP')
    display  = d.get('funding_source_details', {}).get('display_string', '')
    if display:
        ar_map = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
        norm   = display.translate(ar_map).replace(',', '')
        match  = re.search(r'\(([^)]*[\d][^)]*)\)', norm) or re.search(r'([\d]+\.[\d]+)', norm)
        if match:
            num = re.sub(r'[^\d.]', '', match.group(1))
            try:
                value = float(num)
                if value > 10:
                    return f"{acc['label']}: {currency} {value:,.2f}", value
            except Exception:
                pass

    raw   = int(d.get('balance', 0))
    value = raw / 100
    return f"{acc['label']}: {currency} {value:,.2f}", value

# ── MAIN ACCOUNT MESSAGE ──────────────────────────────────────────────────────

def build_account_msg(acc):
    if acc.get('platform') == 'tiktok':
        return get_tiktok_spend(acc)
    return get_windsor_account_data(acc)

# ── ACCOUNTS LIST ─────────────────────────────────────────────────────────────

def accounts_list():
    lines = ["الاكونتات المتاحة:\n"]
    for i, a in enumerate(ACCOUNTS, 1):
        lines.append(f"{i}. {a['label']}")
    lines.append("\nابعت الاسم او الرقم عشان تعرف الإنفاق")
    return '\n'.join(lines)

# ── BALANCE ALERTS (every 2 hours) ───────────────────────────────────────────

async def check_balances(context):
    bot = context.bot
    watch_accounts = [a for a in ACCOUNTS if a['key'] in WATCH_KEYS and not a.get('platform')]
    for acc in watch_accounts:
        _, value = get_meta_balance_raw(acc)
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

# ── HANDLERS ─────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    if update.message.chat.type in ['group', 'supergroup']:
        bot_username = f"@{context.bot.username}"
        if bot_username.lower() not in text.lower():
            return
        text = text.replace(bot_username, '').replace(bot_username.lower(), '').strip()

    tl = text.lower()

    if any(w in tl for w in ['رصيد كل', 'كل', 'all', 'الكل', 'list', 'قائمة']):
        await update.message.reply_text(accounts_list())
        return

    acc = find_account(text)
    if acc:
        await update.message.reply_text("⏳ جاري الجلب من Windsor...")
        msg = build_account_msg(acc)
        await update.message.reply_text(msg, parse_mode='Markdown')
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
    await query.edit_message_text("⏳ جاري الجلب من Windsor...")
    msg = build_account_msg(acc)
    await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_accounts())

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
    await update.message.reply_text("⏳ جاري الجلب من Windsor...")
    watch_accounts = [a for a in ACCOUNTS if a['key'] in WATCH_KEYS and not a.get('platform')]

    # Batch Windsor call for all watched accounts
    all_data = windsor_fetch('this_monthT')
    lines = []
    for acc in watch_accounts:
        aid  = bare_id(acc['id'])
        d    = all_data.get(aid, {})
        spend = d.get('spend', 0)
        # Balance for status icon
        _, bal = get_meta_balance_raw(acc)
        icon = '✅' if bal and bal > 1000 else ('⚠️' if bal and bal > 500 else '🚨')
        bal_str = f"{bal:,.0f} جنيه" if bal is not None else "N/A"
        lines.append(f"{icon} *{acc['label']}* — رصيد: {bal_str} | إنفاق الشهر: {spend:,.2f} EGP")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

# ── BUILD & RUN ───────────────────────────────────────────────────────────────

def build_app():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('balance', cmd_balance))
    app.add_handler(CommandHandler('myid',    myid))
    app.add_handler(CommandHandler('test',    test_cmd))
    app.add_handler(CommandHandler('watched', watched_cmd))
    app.add_handler(CallbackQueryHandler(on_balance_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(check_balances, interval=7200, first=60)
    return app

def main():
    build_app().run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
