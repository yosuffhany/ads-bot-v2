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
    'mall':         {'id': 'act_2001687506868513', 'label': 'Mall'},
    'bsq':          {'id': 'act_841897980911694',  'label': 'BSQ'},
    'kemet':        {'id': 'act_345674018149436',  'label': 'Kemet'},
    'maspipe':      {'id': 'act_1774284989787459', 'label': 'Mas-Pipe'},
    'menna':        {'id': 'act_10150765286975596','label': 'Menna Hossam'},
    'belal':        {'id': 'act_296236770520467',  'label': 'Belal Khier'},
    'sofy':         {'id': 'act_650311242463923',  'label': 'Sofy'},
    'bison':        {'id': 'act_465578978509965',  'label': 'Bison Ads'},
    'effect1':      {'id': 'act_5394586653914394', 'label': 'Effect ADV 01'},
    'eladel':       {'id': 'act_276905741576386',  'label': 'Al Adel'},
    'konafa':       {'id': 'act_631525635606460',  'label': 'كنافة ستى'},
    'fawry1':       {'id': 'act_648289100485879',  'label': 'Effect Fawry 1'},
    'padel':        {'id': 'act_1289017779213803', 'label': 'Play Padel'},
    'effect3':      {'id': 'act_568221719329142',  'label': 'Effect 3'},
    'fawry2':       {'id': 'act_878027737746620',  'label': 'Effect Fawry 2'},
    'studio':       {'id': 'act_580360561671663',  'label': 'Effect Studio'},
    'ideasport':    {'id': 'act_859756096002270',  'label': 'Idea Sport'},
    'sara':         {'id': 'act_1279182850047520', 'label': 'Sara Essam'},
    'byj':          {'id': 'act_620476160959708',  'label': 'ByJ Apparel'},
    'mriya':        {'id': 'act_1212371947222820', 'label': 'Mriya Homes'},
    'yosuff':       {'id': 'act_1832160170733994', 'label': 'Yosuff'},
    'darsaeed':     {'id': 'act_1239543650977780', 'label': 'دار السعيد'},
    'yaqoot':       {'id': 'act_769479552712823',  'label': 'YaqootEG'},
    'totti':        {'id': 'act_3046772235501325', 'label': 'Totti Gallery'},
    'tamra1':       {'id': 'act_1272360541135475', 'label': 'Tamra & Balaha 1'},
    'yakootcoffee': {'id': 'act_1136771131607775', 'label': 'Yakoot Coffee'},
    'yass':         {'id': 'act_1489770438885179', 'label': 'Yass Coffee'},
    'vip':          {'id': 'act_1123106382965581', 'label': 'Vip Perfume'},
    'looklook':     {'id': 'act_879890704620098',  'label': 'Look Look'},
    'tamra2':       {'id': 'act_1818266555783618', 'label': 'Tamra & Balaha 2'},
    'showpink':     {'id': 'act_1803969103895553', 'label': 'ShowPink'},
    'nox':          {'id': 'act_1368567068278092', 'label': 'NOX'},
    'dyafa':        {'id': 'act_880962087659690',  'label': 'Dyafa'},
    'move':         {'id': 'act_710148088755737',  'label': 'Move'},
}

def detect_account(text):
    text = text.lower().strip()
    # Direct keyword match
    KEYWORDS = {
        'mall':         ['mall', 'مول', 'chromakey'],
        'bsq':          ['bsq', 'بي اس كيو', 'bright star'],
        'kemet':        ['kemet', 'كيميت'],
        'maspipe':      ['mas-pipe', 'maspipe', 'ماس بايب', 'ماس'],
        'menna':        ['menna', 'منة', 'منه'],
        'belal':        ['belal', 'بلال'],
        'sofy':         ['sofy', 'صوفي'],
        'bison':        ['bison', 'بايسون'],
        'effect1':      ['effect adv', 'effect 01', 'effect1'],
        'eladel':       ['eladel', 'العادل', 'adel'],
        'konafa':       ['كنافة', 'konafa'],
        'fawry1':       ['fawry1', 'فوري 1', 'fawry 1'],
        'padel':        ['padel', 'بادل'],
        'effect3':      ['effect 3', 'effect3'],
        'fawry2':       ['fawry2', 'فوري 2', 'fawry 2'],
        'studio':       ['studio', 'ستوديو'],
        'ideasport':    ['idea sport', 'ideasport', 'idea'],
        'sara':         ['sara', 'سارة', 'ساره'],
        'byj':          ['byj apparel', 'byj'],
        'mriya':        ['mriya', 'مريا'],
        'yosuff':       ['yosuff yahya'],
        'darsaeed':     ['دار السعيد', 'darsaeed'],
        'yaqoot':       ['yaqoot', 'ياقوت'],
        'totti':        ['totti', 'توتي'],
        'tamra1':       ['tamra 1', 'tamra1', 'تمرة 1'],
        'yakootcoffee': ['yakoot coffee', 'ياقوت كوفي'],
        'yass':         ['yass', 'ياس'],
        'vip':          ['vip', 'فيب'],
        'looklook':     ['look look', 'لوك'],
        'tamra2':       ['tamra 2', 'tamra2', 'تمرة 2'],
        'showpink':     ['showpink', 'شو بينك'],
        'nox':          ['nox', 'نوكس'],
        'dyafa':        ['dyafa', 'ضيافة'],
        'move':         ['move', 'موف'],
    }
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
        # Try to detect account name alone (no action word)
        if account and account != 'all':
            await update.message.reply_text("جاري الجلب...")
            try:
                await update.message.reply_text(get_balance(account))
            except Exception as e:
                await update.message.reply_text(f"خطأ: {e}")
        else:
            await update.message.reply_text(
                "مش فاهم 🤔\n\nجرب:\n• ماس بايب\n• مول\n• bsq\n• كيميت\n• رصيد كل"
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
