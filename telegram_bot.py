"""
Ads Telegram Bot
- "رصيد كل"  → list of all Ad Motion accounts
- account name or number → get balance
"""
import os, re, requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
LONG_LIVED_TOKEN = os.environ.get('LONG_LIVED_TOKEN')   or os.getenv('LONG_LIVED_TOKEN')

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set!")

# All Ad Motion accounts (owned + client)
ACCOUNTS = [
    {'key': 'totti',        'id': 'act_3046772235501325', 'label': 'Totti Gallery'},
    {'key': 'maspipe',      'id': 'act_1774284989787459', 'label': 'Mas-Pipe'},
    {'key': 'sofy',         'id': 'act_650311242463923',  'label': 'Sofy'},
    {'key': 'menna',        'id': 'act_10150765286975596','label': 'Menna Hossam'},
    {'key': 'bison',        'id': 'act_465578978509965',  'label': 'Bison Ads'},
    {'key': 'effect1',      'id': 'act_5394586653914394', 'label': 'Effect ADV 01'},
    {'key': 'effect2',      'id': 'act_5046299818809474', 'label': 'Effect ADV 02'},
    {'key': 'effect3adv',   'id': 'act_1220478902144380', 'label': 'Effect ADV 03'},
    {'key': 'eladel_old',   'id': 'act_276905741576386',  'label': 'Al Adel (old)'},
    {'key': 'fawry1',       'id': 'act_648289100485879',  'label': 'Effect Fawry 1'},
    {'key': 'essam',        'id': 'act_325431983464353',  'label': 'Mohamed Essam'},
    {'key': 'eladel',       'id': 'act_1392109118185589', 'label': 'Al Adel'},
    {'key': 'sua',          'id': 'act_925588948913339',  'label': 'Effect SUA'},
    {'key': 'mall',         'id': 'act_2001687506868513', 'label': 'Mall (Chromakey)'},
    {'key': 'kemet',        'id': 'act_345674018149436',  'label': 'Kemet'},
    {'key': 'divine',       'id': 'act_434106209039266',  'label': 'Divine by JJ'},
    {'key': 'diesel',       'id': 'act_674712451469435',  'label': 'Diesel Caravan'},
    {'key': 'abdelfattah',  'id': 'act_2378819405831678', 'label': 'Abdelfattah'},
    {'key': 'bsq',          'id': 'act_841897980911694',  'label': 'BSQ'},
    {'key': 'padel',        'id': 'act_1289017779213803', 'label': 'Play Padel'},
    {'key': 'effect3egp',   'id': 'act_568221719329142',  'label': 'Effect 3'},
    {'key': 'fawry2',       'id': 'act_878027737746620',  'label': 'Effect Fawry 2'},
    {'key': 'studio',       'id': 'act_580360561671663',  'label': 'Effect Studio'},
    {'key': 'ideasport',    'id': 'act_859756096002270',  'label': 'Idea Sport'},
    {'key': 'sara',         'id': 'act_1279182850047520', 'label': 'Sara Essam'},
    {'key': 'mriya',        'id': 'act_1212371947222820', 'label': 'Mriya Homes'},
    {'key': 'tamra1',       'id': 'act_1272360541135475', 'label': 'Tamra & Balaha 1'},
    {'key': 'yass',         'id': 'act_1489770438885179', 'label': 'Yass Coffee'},
    {'key': 'tamra2',       'id': 'act_1818266555783618', 'label': 'Tamra & Balaha 2'},
    {'key': 'showpink',     'id': 'act_1803969103895553', 'label': 'ShowPink'},
    {'key': 'move',         'id': 'act_710148088755737',  'label': 'Move'},
    {'key': 'safaa',        'id': 'act_921309847313811',  'label': 'Safaa Ahmed'},
    {'key': 'vip',          'id': 'act_1123106382965581', 'label': 'Vip Perfume'},
    {'key': 'yaqoot',       'id': 'act_769479552712823',  'label': 'YaqootEG'},
    {'key': 'belal',        'id': 'act_1091777362163635', 'label': 'Belal Khier'},
    {'key': 'yakootcoffee', 'id': 'act_1136771131607775', 'label': 'Yakoot Coffee'},
    {'key': 'looklook',     'id': 'act_879890704620098',  'label': 'Look Look'},
]

# Build lookup by key and label
ACCOUNTS_BY_KEY   = {a['key']: a for a in ACCOUNTS}
ACCOUNTS_BY_INDEX = {i+1: a for i, a in enumerate(ACCOUNTS)}

def find_account(text):
    """Find account by name substring (case-insensitive) or number"""
    text = text.strip()
    # by number
    if text.isdigit():
        return ACCOUNTS_BY_INDEX.get(int(text))
    # by label
    tl = text.lower()
    for a in ACCOUNTS:
        if tl in a['label'].lower() or a['key'] in tl:
            return a
    return None

def get_balance(acc):
    r = requests.get(
        f"https://graph.facebook.com/v19.0/{acc['id']}",
        params={'access_token': LONG_LIVED_TOKEN, 'fields': 'balance,currency,funding_source_details'}
    )
    d = r.json()
    if 'error' in d:
        return f"{acc['label']}: ❌ خطأ"
    currency = d.get('currency', '')
    display  = d.get('funding_source_details', {}).get('display_string', '')
    match    = re.search(r'\((.+?)\)', display)
    if match:
        return f"{acc['label']}: {match.group(1)}"
    raw = int(d.get('balance', 0))
    return f"{acc['label']}: {currency} {raw/100:,.2f}"

def accounts_list():
    lines = ["الأكونتات المتاحة:\n"]
    for i, a in enumerate(ACCOUNTS, 1):
        lines.append(f"{i}. {a['label']}")
    lines.append("\nابعت الاسم أو الرقم عشان تعرف الرصيد")
    return '\n'.join(lines)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()
    tl   = text.lower()

    # "رصيد كل" or "كل" → show list
    if any(w in tl for w in ['رصيد كل', 'كل', 'all', 'الكل', 'list', 'قائمة']):
        await update.message.reply_text(accounts_list())
        return

    # Try to find account
    acc = find_account(text)
    if acc:
        await update.message.reply_text("جاري الجلب...")
        await update.message.reply_text(get_balance(acc))
        return

    # Unknown
    await update.message.reply_text(
        "مش فاهم 🤔\n\nجرب:\n• رصيد كل — عرض الأكونتات\n• ابعت اسم الأكونت أو رقمه"
    )

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot running...")
    app.run_polling()

if __name__ == '__main__':
    main()
