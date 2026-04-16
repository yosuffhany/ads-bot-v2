"""
Ads Telegram Bot
- "رصيد كل"  → list of all Ad Motion accounts
- account name or number → get balance
- Auto alerts when watched accounts drop below 1000 or 500
"""
import os, re, random, requests, logging
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

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

# Team IDs to receive alerts
TEAM_IDS = [7205504412, 1285453461, 932647337]  # Nsayedb, Aliaa, Yosuff

# Accounts to watch for balance alerts
WATCH_KEYS = {'mall', 'kemet', 'bsq', 'eladel', 'maspipe', 'showpink'}

# Alert thresholds
THRESHOLDS = [1000, 500]

# Persist sent alerts to file so restarts don't resend
ALERTS_FILE = '/tmp/sent_alerts.json'

def load_alerts():
    try:
        import json
        with open(ALERTS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_alerts(data):
    import json
    with open(ALERTS_FILE, 'w') as f:
        json.dump(data, f)

sent_alerts = load_alerts()

# Funny Egyptian messages per threshold
MESSAGES_1000 = [
    "⚠️ يا تيم! رصيد {name} بدأ يتضاوق — فضل {balance} بس، شحنوا قبل ما يتقفل علينا 😅",
    "🚨 آدي {name} بيصرخ من جوه — رصيده {balance}، متسيبوهوش يجوع 🥲",
    "😬 يا جماعة {name} بدأ يبعت إشارات استغاثة — الرصيد {balance}، حد يشحن؟",
    "💸 {name} بيبص على رصيده وبيعيط — {balance} بس فاضلين، التيم فين؟! 😂",
    "🔔 تنبيه من {name}: الرصيد {balance}، يعني لسه بخير بس متبقوش تعملوا أبطال 😄",
]

MESSAGES_500 = [
    "💀 يا جماعة {name} على وشك الإغماء — رصيده {balance} بس، أنقذوه بسرعة!! 😭",
    "🆘 SOS من {name}!! الرصيد {balance} ومش هيفضل طويل، شحنوا دلوقتي أو ودعوا الكامبينز 😂",
    "😱 {name} بيودع الكامبينز — {balance} بس وخلاص!! في حد صاحي؟ شحنوا بسرعة!!",
    "🚒 الإسعاف جه لـ {name}!! رصيده {balance} — إيه ده؟! شحنوا قبل ما يتوفى 😭😂",
    "⛽ {name} بنزينه على الآخر — {balance} ومشيناها، يلا يا تيم اشحنوا اشحنوا!! 🏃",
]

# All Ad Motion accounts
ACCOUNTS = [
    {'key': 'totti',        'id': 'act_3046772235501325', 'label': 'Totti Gallery',    'ar': ['توتي', 'توتى', 'توتي جاليري']},
    {'key': 'maspipe',      'id': 'act_1774284989787459', 'label': 'Mas-Pipe',         'ar': ['ماس بيب', 'ماسبيب', 'ماس-بيب', 'مسبيب']},
    {'key': 'sofy',         'id': 'act_650311242463923',  'label': 'Sofy',             'ar': ['صوفي', 'صوفى', 'سوفي']},
    {'key': 'menna',        'id': 'act_10150765286975596','label': 'Menna Hossam',     'ar': ['منه', 'منة', 'منه حسام', 'منة حسام']},
    {'key': 'bison',        'id': 'act_465578978509965',  'label': 'Bison Ads',        'ar': ['بايسون', 'بيسون']},
    {'key': 'effect1',      'id': 'act_5394586653914394', 'label': 'Effect ADV 01',    'ar': ['افيكت 1', 'إيفيكت 1', 'ايفيكت 01']},
    {'key': 'effect2',      'id': 'act_5046299818809474', 'label': 'Effect ADV 02',    'ar': ['افيكت 2', 'إيفيكت 2', 'ايفيكت 02']},
    {'key': 'effect3adv',   'id': 'act_1220478902144380', 'label': 'Effect ADV 03',    'ar': ['افيكت 3', 'ايفيكت 03']},
    {'key': 'eladel_old',   'id': 'act_276905741576386',  'label': 'Al Adel (old)',    'ar': ['العادل القديم', 'الادل القديم']},
    {'key': 'fawry1',       'id': 'act_648289100485879',  'label': 'Effect Fawry 1',   'ar': ['فوري 1', 'فوري واحد']},
    {'key': 'essam',        'id': 'act_325431983464353',  'label': 'Mohamed Essam',    'ar': ['محمد عصام', 'عصام']},
    {'key': 'eladel',       'id': 'act_1392109118185589', 'label': 'Al Adel',          'ar': ['العادل', 'الادل', 'ادل', 'عادل', 'el adel', 'aladel']},
    {'key': 'sua',          'id': 'act_925588948913339',  'label': 'Effect SUA',       'ar': ['سوا', 'اس يو ايه']},
    {'key': 'mall',         'id': 'act_2001687506868513', 'label': 'Mall',             'ar': ['مول', 'مال', 'المول']},
    {'key': 'kemet',        'id': 'act_345674018149436',  'label': 'Kemet',            'ar': ['كيميت', 'كيمت', 'كيمت']},
    {'key': 'divine',       'id': 'act_434106209039266',  'label': 'Divine by JJ',     'ar': ['ديفاين', 'دايفاين', 'دفاين']},
    {'key': 'diesel',       'id': 'act_674712451469435',  'label': 'Diesel Caravan',   'ar': ['ديزل', 'كارافان', 'ديزل كارافان']},
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
    {'key': 'showpink',     'id': 'act_1803969103895553', 'label': 'ShowPink',         'ar': ['شوبينك', 'شو بينك', 'شو-بينك', 'شوو بينك']},
    {'key': 'move',         'id': 'act_710148088755737',  'label': 'Move',             'ar': ['موف']},
    {'key': 'safaa',        'id': 'act_921309847313811',  'label': 'Safaa Ahmed',      'ar': ['صفاء', 'صفاء احمد', 'سفاء']},
    {'key': 'vip',          'id': 'act_1123106382965581', 'label': 'Vip Perfume',      'ar': ['فيب', 'فيب برفيوم', 'vip برفيوم']},
    {'key': 'yaqoot',       'id': 'act_769479552712823',  'label': 'YaqootEG',         'ar': ['ياقوت', 'ياقوت إيجي', 'ياقوت ايجي']},
    {'key': 'belal',        'id': 'act_1091777362163635', 'label': 'Belal Khier',      'ar': ['بلال', 'بلال خير']},
    {'key': 'yakootcoffee', 'id': 'act_1136771131607775', 'label': 'Yakoot Coffee',   'ar': ['ياقوت كوفي', 'ياقوت قهوة']},
    {'key': 'looklook',     'id': 'act_879890704620098',  'label': 'Look Look',        'ar': ['لوك لوك', 'لوكلوك']},
]

ACCOUNTS_BY_INDEX = {i+1: a for i, a in enumerate(ACCOUNTS)}

def find_account(text):
    text = text.strip()
    if text.isdigit():
        return ACCOUNTS_BY_INDEX.get(int(text))
    tl = text.lower()
    for a in ACCOUNTS:
        # Match English label or key
        if tl in a['label'].lower() or a['key'] in tl or tl == a['key']:
            return a
        # Match Arabic aliases
        for alias in a.get('ar', []):
            if alias in tl or tl in alias:
                return a
    return None

def get_balance_raw(acc):
    """Returns (display_str, numeric_value)"""
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{acc['id']}",
            params={'access_token': LONG_LIVED_TOKEN, 'fields': 'balance,currency,funding_source_details'},
            timeout=15
        )
        d = r.json()
    except Exception as e:
        logger.error(f"Request failed for {acc['label']}: {e}")
        return f"{acc['label']}: ❌ خطأ في الاتصال", None

    if 'error' in d:
        logger.error(f"API error for {acc['label']}: {d['error']}")
        return f"{acc['label']}: ❌ خطأ", None

    currency = d.get('currency', '')
    display  = d.get('funding_source_details', {}).get('display_string', '')
    match    = re.search(r'\((.+?)\)', display)
    if match:
        amount_str = match.group(1)
        # Extract numeric value
        num = re.sub(r'[^\d.]', '', amount_str.replace(',', ''))
        try:
            value = float(num)
        except Exception:
            value = None
        logger.info(f"{acc['label']} balance: {amount_str} → value={value}")
        return f"{acc['label']}: {amount_str}", value

    # Fallback: use balance field (in cents)
    raw = int(d.get('balance', 0))
    value = raw / 100
    logger.info(f"{acc['label']} balance (raw): {raw} → {value} {currency}")
    return f"{acc['label']}: {currency} {value:,.2f}", value

def get_balance(acc):
    text, _ = get_balance_raw(acc)
    return text

def accounts_list():
    lines = ["الأكونتات المتاحة:\n"]
    for i, a in enumerate(ACCOUNTS, 1):
        lines.append(f"{i}. {a['label']}")
    lines.append("\nابعت الاسم أو الرقم عشان تعرف الرصيد")
    return '\n'.join(lines)

async def check_balances(context):
    """Check watched accounts and send alerts if below thresholds"""
    bot = context.bot
    watch_accounts = [a for a in ACCOUNTS if a['key'] in WATCH_KEYS]
    logger.info(f"check_balances fired — checking {len(watch_accounts)} accounts")

    for acc in watch_accounts:
        display, value = get_balance_raw(acc)
        logger.info(f"  {acc['label']}: display={display}, value={value}")

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

                logger.info(f"  Sending {threshold} alert for {acc['label']} (balance={value})")
                for chat_id in TEAM_IDS:
                    try:
                        await bot.send_message(chat_id=chat_id, text=msg)
                    except Exception as e:
                        logger.error(f"  Failed to send to {chat_id}: {e}")

                sent_alerts[key][alert_key] = True
                save_alerts(sent_alerts)

            # Reset alert if balance goes back up (after recharge)
            elif value > threshold and sent_alerts[key].get(alert_key):
                logger.info(f"  Resetting {threshold} alert for {acc['label']} (balance={value})")
                sent_alerts[key][alert_key] = False
                save_alerts(sent_alerts)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()
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
        "مش فاهم 🤔\n\nجرب:\n• رصيد كل — عرض الأكونتات\n• ابعت اسم الأكونت أو رقمه"
    )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: `{update.message.from_user.id}`", parse_mode='Markdown')

async def test_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual trigger for balance check — only works for Yosuff"""
    if update.message.from_user.id != 932647337:
        return
    await update.message.reply_text("🔄 بفحص الأرصدة دلوقتي...")
    await check_balances(context)
    await update.message.reply_text("✅ خلص الفحص — شوف فوق لو في تنبيهات")

async def balance_all_watched(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show balances of all watched accounts — only for Yosuff"""
    if update.message.from_user.id != 932647337:
        return
    await update.message.reply_text("جاري الجلب...")
    watch_accounts = [a for a in ACCOUNTS if a['key'] in WATCH_KEYS]
    lines = []
    for acc in watch_accounts:
        display, value = get_balance_raw(acc)
        lines.append(f"{display}" + (f" ({'✅' if value and value > 1000 else '⚠️' if value and value > 500 else '🚨'})" if value else ""))
    await update.message.reply_text('\n'.join(lines))

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('myid', myid))
    app.add_handler(CommandHandler('test', test_alerts))
    app.add_handler(CommandHandler('watched', balance_all_watched))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Check balances every 2 hours, first check after 60s
    app.job_queue.run_repeating(check_balances, interval=7200, first=60)
    logger.info("Bot running with balance alerts every 2 hours...")
    app.run_polling()

if __name__ == '__main__':
    main()
