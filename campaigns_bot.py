"""
Campaigns Telegram Bot — Meta API direct
- /report → interactive buttons: account → period → campaign → metrics
- Text shortcut: "سيدرا" → list, "3 مايو" → metrics
"""
import os, re, logging
from datetime import date, timedelta
from dotenv import load_dotenv
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

load_dotenv()

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get('CAMPAIGNS_BOT_TOKEN') or os.getenv('CAMPAIGNS_BOT_TOKEN')
LONG_LIVED_TOKEN = os.environ.get('LONG_LIVED_TOKEN')   or os.getenv('LONG_LIVED_TOKEN')

if not TELEGRAM_TOKEN:
    raise RuntimeError("CAMPAIGNS_BOT_TOKEN not set!")

# ── ACCOUNTS ──────────────────────────────────────────────────────────────────

ACCOUNTS = [
    {'key': 'eladel',   'id': 'act_1392109118185589', 'label': 'Al Adel',       'ar': ['العادل', 'الادل', 'ادل', 'عادل']},
    {'key': 'bsq',      'id': 'act_841897980911694',  'label': 'BSQ',           'ar': ['بي اس كيو', 'بيإسكيو']},
    {'key': 'mall',     'id': 'act_2001687506868513', 'label': 'Mall',          'ar': ['مول', 'مال', 'المول']},
    {'key': 'kemet',    'id': 'act_345674018149436',  'label': 'Kemet',         'ar': ['كيميت', 'كيمت']},
    {'key': 'maspipe',  'id': 'act_1774284989787459', 'label': 'Mas-Pipe',      'ar': ['ماس بيب', 'ماسبيب', 'ماس-بيب']},
    {'key': 'showpink', 'id': 'act_1803969103895553', 'label': 'ShowPink',      'ar': ['شوبينك', 'شو بينك']},
    {'key': 'belal',    'id': 'act_1091777362163635', 'label': 'Belal Khier',   'ar': ['بلال', 'بلال خير']},
    {'key': 'sedra',    'id': 'act_1303633554699002', 'label': 'Sedra',         'ar': ['سيدرا', 'سدرا', 'سدره']},
    {'key': 'essam',    'id': 'act_325431983464353',  'label': 'Mohamed Essam', 'ar': ['محمد عصام', 'عصام', 'essam']},
]
ACCOUNTS_BY_KEY = {a['key']: a for a in ACCOUNTS}

PURCHASE_ACTIONS = {'offsite_conversion.fb_pixel_purchase', 'onsite_conversion.purchase'}
AWARENESS_OBJS   = {'OUTCOME_AWARENESS', 'OUTCOME_REACH', 'REACH', 'AWARENESS'}

PERIODS = [
    ('7 أيام',        '7'),
    ('30 يوم',        '30'),
    ('الشهر ده',      'month'),
    ('الشهر اللي فات','last'),
    ('مايو',          'may'),
    ('أبريل',         'apr'),
]

# ── HELPERS ───────────────────────────────────────────────────────────────────

def find_account(text):
    tl = text.lower().strip()
    for a in ACCOUNTS:
        if tl == a['key'] or tl in a['label'].lower() or a['key'] in tl:
            return a
        for alias in a['ar']:
            if alias in tl or tl in alias:
                return a
    return None

def resolve_period(code):
    """Returns (since, until, label) from period code."""
    # custom: "custom|since|until|label"
    if code.startswith('custom|'):
        parts = code.split('|')
        return parts[1], parts[2], parts[3]
    today = date.today()
    if code.isdigit():
        days  = int(code)
        return str(today - timedelta(days=days-1)), str(today), f"آخر {days} يوم"
    if code == 'month':
        return str(date(today.year, today.month, 1)), str(today), "الشهر الحالي"
    if code == 'last':
        first = date(today.year, today.month, 1) - timedelta(days=1)
        return str(date(first.year, first.month, 1)), str(first), "الشهر الماضي"
    months = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
              'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
    if code in months:
        n  = months[code]
        last_day = (date(today.year, n % 12 + 1, 1) - timedelta(days=1)).day if n < 12 else 31
        s  = date(today.year, n, 1)
        u  = min(date(today.year, n, last_day), today)
        ar = {'jan':'يناير','feb':'فبراير','mar':'مارس','apr':'أبريل','may':'مايو',
              'jun':'يونيو','jul':'يوليو','aug':'أغسطس','sep':'سبتمبر',
              'oct':'أكتوبر','nov':'نوفمبر','dec':'ديسمبر'}
        return str(s), str(u), ar.get(code, code)
    return str(today - timedelta(days=29)), str(today), "آخر 30 يوم"

ARABIC_MONTHS = {
    'يناير':'jan','فبراير':'feb','مارس':'mar','ابريل':'apr','أبريل':'apr',
    'مايو':'may','يونيو':'jun','يوليو':'jul','اغسطس':'aug','أغسطس':'aug',
    'سبتمبر':'sep','أكتوبر':'oct','اكتوبر':'oct','نوفمبر':'nov','ديسمبر':'dec',
}

def parse_period_text(text):
    tl = (text or '').lower().strip()
    if any(w in tl for w in ['الشهر ده','هذا الشهر','this month']):
        return resolve_period('month')
    if any(w in tl for w in ['الشهر اللي فات','الشهر الماضي','last month']):
        return resolve_period('last')
    for ar, code in ARABIC_MONTHS.items():
        if ar in tl:
            return resolve_period(code)
    m = re.search(r'(\d+)\s*(?:أيام|ايام|يوم|days?)?', tl)
    if m:
        return resolve_period(m.group(1))
    return resolve_period('30')

def fmt(n, d=0):
    if n is None: return '—'
    return f"{n:,.{d}f}" if d else f"{int(n):,}"

def h(text):
    """Escape HTML special chars."""
    return str(text).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

# ── META API ──────────────────────────────────────────────────────────────────

def api_get(url, params):
    params['access_token'] = LONG_LIVED_TOKEN
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def get_campaigns(account_id):
    data = api_get(
        f'https://graph.facebook.com/v19.0/{account_id}/campaigns',
        {
            'fields':           'id,name,objective,status,created_time',
            'effective_status': '["ACTIVE","PAUSED"]',
            'limit':            50,
        }
    )
    camps = data.get('data', [])
    camps.sort(key=lambda c: c.get('created_time', ''), reverse=True)
    return camps

def get_insights(campaign_id, since, until):
    data = api_get(
        f'https://graph.facebook.com/v19.0/{campaign_id}/insights',
        {
            'time_range': f'{{"since":"{since}","until":"{until}"}}',
            'fields':     'spend,impressions,reach,clicks,inline_link_clicks,cpm,actions,cost_per_action_type,results,cost_per_result,objective,account_currency',
            'level':      'campaign',
            'limit':      1,
        }
    )
    rows = data.get('data', [])
    return rows[0] if rows else None

def parse_insights(ins, objective_raw):
    if not ins: return None
    spend  = round(float(ins.get('spend', 0)), 2)
    impr   = int(ins.get('impressions', 0))
    reach  = int(ins.get('reach', 0))
    clicks = int(ins.get('clicks', 0))
    lc     = int(ins.get('inline_link_clicks', 0))
    obj    = (objective_raw or '').upper()
    actions = ins.get('actions', [])
    costs   = ins.get('cost_per_action_type', [])

    msg_act  = next((a for a in actions if a['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), None)
    messages = int(float(msg_act['value'])) if msg_act else 0
    msg_cost = next((c for c in costs if c['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), None)
    cpm_msg  = round(float(msg_cost['value']) if msg_cost else (spend/messages if messages else 0), 2)

    ACTION_LABELS = {
        'onsite_conversion.messaging_conversation_started_7d': 'رسالة',
        'offsite_conversion.fb_pixel_purchase':                'شراء',
        'onsite_conversion.purchase':                          'شراء',
        'onsite_conversion.lead_grouped':                      'ليد',
        'lead':                                                'ليد',
        'like':                                                'لايك بيدج',
        'landing_page_view':                                   'زيارة موقع',
        'visit_instagram_profile':                             'زيارة بروفايل',
        'omni_add_to_cart':                                    'أضاف للسلة',
        'omni_initiated_checkout':                             'بدأ الشراء',
        'link_click':                                          'كليك',
        'video_view':                                          'مشاهدة فيديو',
        'post_engagement':                                     'تفاعل بيدج',
        'page_engagement':                                     'تفاعل بيدج',
    }

    if obj in AWARENESS_OBJS:
        results, result_label = reach, 'ريتش'
        cpr = round(spend/(reach/1000), 2) if reach else 0
    else:
        # Use Meta's own results field (same as Ads Manager "Results" column)
        api_results = ins.get('results', [])
        api_cpr_list = ins.get('cost_per_result', [])
        if api_results:
            r0 = api_results[0]
            results      = int(float(r0.get('value', 0)))
            at           = r0.get('action_type') or r0.get('indicator', '')
            result_label = ACTION_LABELS.get(at, at or 'نتيجة')
            cpr_item     = api_cpr_list[0] if api_cpr_list else {}
            cpr          = round(float(cpr_item.get('value', spend/results if results else 0)), 2)
        else:
            # fallback: action priority by objective
            OBJECTIVE_PRIORITY = {
                'OUTCOME_TRAFFIC':    ['landing_page_view', 'visit_instagram_profile',
                                       'onsite_conversion.messaging_conversation_started_7d', 'link_click'],
                'OUTCOME_ENGAGEMENT': ['like', 'onsite_conversion.messaging_conversation_started_7d',
                                       'video_view', 'post_engagement'],
                'OUTCOME_LEADS':      ['onsite_conversion.lead_grouped', 'lead',
                                       'onsite_conversion.messaging_conversation_started_7d'],
                'OUTCOME_SALES':      ['offsite_conversion.fb_pixel_purchase', 'onsite_conversion.purchase',
                                       'omni_initiated_checkout', 'omni_add_to_cart',
                                       'onsite_conversion.messaging_conversation_started_7d'],
            }
            results, cpr, result_label = 0, 0, 'نتيجة'
            priority = OBJECTIVE_PRIORITY.get(obj, list(ACTION_LABELS.keys()))
            for at in priority:
                lbl = ACTION_LABELS.get(at)
                if not lbl: continue
                act = next((a for a in actions if a['action_type'] == at), None)
                if act:
                    results      = int(float(act['value']))
                    result_label = lbl
                    cost         = next((c for c in costs if c['action_type'] == at), None)
                    cpr          = round(float(cost['value']) if cost else (spend/results if results else 0), 2)
                    break

    cpm      = round(spend/impr*1000, 2) if impr else 0
    currency = ins.get('account_currency', 'EGP')
    return dict(spend=spend, impr=impr, reach=reach, clicks=clicks, lc=lc,
                cpm=cpm, messages=messages, cpm_msg=cpm_msg,
                results=results, result_label=result_label, cpr=cpr,
                obj=obj, currency=currency)

def format_report(name, ins, period_label, currency='EGP'):
    m = ins

    if m['result_label'] == 'رسالة' and m['messages'] > 0:
        res_val  = m['messages']
        res_type = "رسالة"
        cost_val = m['cpm_msg']
        cost_lbl = "سعر الرسالة"
    elif m['obj'] in AWARENESS_OBJS:
        res_val  = m['reach']
        res_type = "ريتش"
        cost_val = m['cpr']
        cost_lbl = "تكلفة/1000 ريتش"
    elif m['results'] > 0:
        res_val  = m['results']
        res_type = m.get('result_label', 'نتيجة')
        cost_val = m['cpr']
        cost_lbl = "سعر النتيجة"
    else:
        res_val  = 0
        res_type = "نتيجة"
        cost_val = 0
        cost_lbl = "سعر النتيجة"

    return '\n'.join([
        f"📊 <b>{h(name)}</b>",
        f"📅 {period_label}",
        "─────────────────",
        f"🎯 نتيجة:      <b>{fmt(res_val)}</b>  <i>({res_type})</i>",
        f"💵 {cost_lbl}: <b>{fmt(cost_val, 2)} {currency}</b>",
        f"💰 إنفاق:      <b>{fmt(m['spend'], 2)} {currency}</b>",
        f"👁 إمبريشن:    <b>{fmt(m['impr'])}</b>",
        f"👥 ريتش:       <b>{fmt(m['reach'])}</b>",
        f"📈 CPM:         <b>{fmt(m['cpm'], 2)} {currency}</b>",
    ])

# ── KEYBOARDS ─────────────────────────────────────────────────────────────────

def kb_accounts():
    rows = []
    for i in range(0, len(ACCOUNTS), 3):
        rows.append([
            InlineKeyboardButton(a['label'], callback_data=f"acc:{a['key']}")
            for a in ACCOUNTS[i:i+3]
        ])
    return InlineKeyboardMarkup(rows)

def kb_periods(acc_key):
    rows = []
    for i in range(0, len(PERIODS), 3):
        rows.append([
            InlineKeyboardButton(label, callback_data=f"per:{acc_key}:{code}")
            for label, code in PERIODS[i:i+3]
        ])
    rows.append([InlineKeyboardButton("📅 تاريخ مخصص", callback_data=f"custom:{acc_key}")])
    rows.append([InlineKeyboardButton("↩️ رجوع",        callback_data="back:accounts")])
    return InlineKeyboardMarkup(rows)

def kb_campaigns(acc_key, period_code, camps):
    rows = []
    for c in camps:
        icon = '🟢' if c.get('status') == 'ACTIVE' else '⏸'
        label = f"{icon} {c['name'][:35]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"camp:{acc_key}:{period_code}:{c['id']}")])
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=f"back:periods:{acc_key}")])
    return InlineKeyboardMarkup(rows)

# ── CALENDAR PICKER ───────────────────────────────────────────────────────────

AR_MONTHS = ['يناير','فبراير','مارس','أبريل','مايو','يونيو',
             'يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']

def _days_in(y, m):
    import calendar
    return calendar.monthrange(y, m)[1]

def kb_year(prefix, back_cb):
    today = date.today()
    years = [today.year - 1, today.year]
    rows  = [[InlineKeyboardButton(str(y), callback_data=f"{prefix}:{y}") for y in years]]
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def kb_month(prefix, back_cb):
    rows = []
    for i in range(0, 12, 3):
        rows.append([
            InlineKeyboardButton(AR_MONTHS[j], callback_data=f"{prefix}:{j+1}")
            for j in range(i, min(i+3, 12))
        ])
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def kb_day(prefix, year, month, back_cb):
    total = _days_in(year, month)
    rows  = []
    for start in range(1, total+1, 7):
        rows.append([
            InlineKeyboardButton(str(d), callback_data=f"{prefix}:{d}")
            for d in range(start, min(start+7, total+1))
        ])
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

# ── STATE ──────────────────────────────────────────────────────────────────────

user_state = {}  # uid → {account, map}

# ── HANDLERS ──────────────────────────────────────────────────────────────────

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "اختار الاكونت 👇",
        reply_markup=kb_accounts()
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── account selected ──────────────────────────────────────────────────────
    if data.startswith('acc:'):
        acc_key = data.split(':')[1]
        await query.edit_message_text(
            f"✅ {ACCOUNTS_BY_KEY[acc_key]['label']}\n\nاختار الفترة 👇",
            reply_markup=kb_periods(acc_key)
        )

    # ── period selected → fetch campaigns ─────────────────────────────────────
    elif data.startswith('per:'):
        _, acc_key, period_code = data.split(':')
        acc = ACCOUNTS_BY_KEY[acc_key]
        await query.edit_message_text("⏳ جاري جلب الكامبينز...")
        try:
            camps = get_campaigns(acc['id'])
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
            return
        if not camps:
            await query.edit_message_text("مفيش كامبينز شغالة.")
            return
        # cache camps in state
        uid = query.from_user.id
        user_state[uid] = {
            'acc_key': acc_key,
            'period_code': period_code,
            'camps': {c['id']: c for c in camps},
        }
        _, _, label = resolve_period(period_code)
        await query.edit_message_text(
            f"✅ {acc['label']} — {label}\n\nاختار الكامبين 👇",
            reply_markup=kb_campaigns(acc_key, period_code, camps)
        )

    # ── campaign selected → fetch & show report ────────────────────────────────
    elif data.startswith('camp:'):
        parts = data.split(':')
        acc_key, period_code, camp_id = parts[1], parts[2], parts[3]
        uid = query.from_user.id

        # look up camp name from state (all levels)
        camp = (user_state.get(uid, {}).get('camps', {}).get(camp_id) or
                user_state.get(uid, {}).get('map', {}) and
                next((c for c in user_state.get(uid,{}).get('map',{}).values()
                      if isinstance(c, dict) and c.get('id') == camp_id), None))
        camp_name = camp['name'] if camp else camp_id
        obj_raw   = camp.get('objective', '') if camp else ''

        if period_code == 'CUSTOM':
            custom = user_state.get(uid, {}).get('custom_period')
            if not custom:
                await query.edit_message_text("❌ انتهت الجلسة، ابدأ من /report")
                return
            since, until, label = custom
        else:
            since, until, label = resolve_period(period_code)
        await query.edit_message_text("⏳ جاري جلب البيانات...")
        try:
            ins_raw = get_insights(camp_id, since, until)
            ins     = parse_insights(ins_raw, obj_raw or (ins_raw.get('objective','') if ins_raw else ''))
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
            return
        if not ins:
            await query.edit_message_text("مفيش داتا للفترة دي.")
            return

        acc = ACCOUNTS_BY_KEY.get(acc_key)
        back_btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ كامبين تاني", callback_data=f"per:{acc_key}:{period_code}")
        ]])
        await query.edit_message_text(
            format_report(camp_name, ins, label, ins.get('currency','EGP')),
            parse_mode='HTML',
            reply_markup=back_btn
        )

    # ── custom date: start year ───────────────────────────────────────────────
    elif data.startswith('custom:'):
        acc_key = data.split(':')[1]
        acc     = ACCOUNTS_BY_KEY[acc_key]
        await query.edit_message_text(
            f"✅ {acc['label']}\n📅 اختار سنة البداية:",
            reply_markup=kb_year(f"cp:sm:{acc_key}", f"back:periods:{acc_key}")
        )

    # ── cp:sm:{acc}:{sy} → start month ───────────────────────────────────────
    elif data.startswith('cp:sm:'):
        _, _, acc_key, sy = data.split(':')
        await query.edit_message_text(
            f"📅 سنة البداية: <b>{sy}</b>\nاختار الشهر:",
            parse_mode='HTML',
            reply_markup=kb_month(f"cp:sd:{acc_key}:{sy}", f"custom:{acc_key}")
        )

    # ── cp:sd:{acc}:{sy}:{sm} → start day ────────────────────────────────────
    elif data.startswith('cp:sd:'):
        parts = data.split(':')
        acc_key, sy, sm = parts[2], int(parts[3]), int(parts[4])
        await query.edit_message_text(
            f"📅 البداية: <b>{AR_MONTHS[sm-1]} {sy}</b>\nاختار اليوم:",
            parse_mode='HTML',
            reply_markup=kb_day(f"cp:ey:{acc_key}:{sy}:{sm}",
                                sy, sm,
                                f"cp:sm:{acc_key}:{sy}")
        )

    # ── cp:ey:{acc}:{sy}:{sm}:{sd} → end year ────────────────────────────────
    elif data.startswith('cp:ey:'):
        parts   = data.split(':')
        acc_key, sy, sm, sd = parts[2], parts[3], parts[4], int(parts[5])
        acc     = ACCOUNTS_BY_KEY[acc_key]
        start_s = f"{sd:02d}/{AR_MONTHS[int(sm)-1]}/{sy}"
        await query.edit_message_text(
            f"✅ البداية: <b>{start_s}</b>\n📅 اختار سنة النهاية:",
            parse_mode='HTML',
            reply_markup=kb_year(f"cp:em:{acc_key}:{sy}:{sm}:{sd}",
                                 f"cp:sd:{acc_key}:{sy}:{sm}")
        )

    # ── cp:em:{acc}:{sy}:{sm}:{sd}:{ey} → end month ──────────────────────────
    elif data.startswith('cp:em:'):
        parts = data.split(':')
        acc_key, sy, sm, sd, ey = parts[2], parts[3], parts[4], parts[5], parts[6]
        await query.edit_message_text(
            f"📅 سنة النهاية: <b>{ey}</b>\nاختار الشهر:",
            parse_mode='HTML',
            reply_markup=kb_month(f"cp:ed:{acc_key}:{sy}:{sm}:{sd}:{ey}",
                                  f"cp:ey:{acc_key}:{sy}:{sm}:{sd}")
        )

    # ── cp:ed:{acc}:{sy}:{sm}:{sd}:{ey}:{em} → end day ──────────────────────
    elif data.startswith('cp:ed:'):
        parts = data.split(':')
        acc_key, sy, sm, sd, ey, em = parts[2], parts[3], parts[4], parts[5], parts[6], int(parts[7])
        await query.edit_message_text(
            f"📅 النهاية: <b>{AR_MONTHS[em-1]} {ey}</b>\nاختار اليوم:",
            parse_mode='HTML',
            reply_markup=kb_day(f"cp:go:{acc_key}:{sy}:{sm}:{sd}:{ey}:{em}",
                                int(ey), em,
                                f"cp:em:{acc_key}:{sy}:{sm}:{sd}:{ey}")
        )

    # ── cp:go:{acc}:{sy}:{sm}:{sd}:{ey}:{em}:{ed} → fetch camps ─────────────
    elif data.startswith('cp:go:'):
        parts = data.split(':')
        acc_key, sy, sm, sd, ey, em, ed = parts[2], int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6]), int(parts[7]), int(parts[8])
        acc   = ACCOUNTS_BY_KEY[acc_key]
        since = str(date(sy, sm, sd))
        until = str(date(ey, em, ed))
        label = f"{sd:02d}/{AR_MONTHS[sm-1]}/{sy} → {ed:02d}/{AR_MONTHS[em-1]}/{ey}"
        await query.edit_message_text("⏳ جاري جلب الكامبينز...")
        try:
            camps = get_campaigns(acc['id'])
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
            return
        if not camps:
            await query.edit_message_text("مفيش كامبينز شغالة.")
            return
        uid = query.from_user.id
        user_state[uid] = {
            'account': acc,
            'camps': {c['id']: c for c in camps},
            'custom_period': (since, until, label),
        }
        await query.edit_message_text(
            f"✅ {h(acc['label'])} — {h(label)}\n\nاختار الكامبين 👇",
            parse_mode='HTML',
            reply_markup=kb_campaigns(acc_key, 'CUSTOM', camps)
        )

    # ── back buttons ──────────────────────────────────────────────────────────
    elif data == 'back:accounts':
        await query.edit_message_text("اختار الاكونت 👇", reply_markup=kb_accounts())

    elif data.startswith('back:periods:'):
        acc_key = data.split(':')[2]
        await query.edit_message_text(
            f"✅ {ACCOUNTS_BY_KEY[acc_key]['label']}\n\nاختار الفترة 👇",
            reply_markup=kb_periods(acc_key)
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()
    uid  = update.message.from_user.id

    if update.message.chat.type in ['group', 'supergroup']:
        bot_username = f"@{context.bot.username}"
        if bot_username.lower() not in text.lower():
            return
        text = re.sub(re.escape(bot_username), '', text, flags=re.IGNORECASE).strip()

    tl = text.lower()

    # account name → list campaigns (text shortcut)
    acc = find_account(text)
    if acc and not re.search(r'\d+\s*(?:يوم|أيام|ايام|days?)', tl):
        await update.message.reply_text("⏳ جاري الجلب...")
        try:
            camps = get_campaigns(acc['id'])
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")
            return
        if not camps:
            await update.message.reply_text("مفيش كامبينز شغالة.")
            return
        camp_map = {}
        lines = [f"📋 <b>{h(acc['label'])} — الكامبينز</b>\n"]
        for i, c in enumerate(camps, 1):
            icon = '🟢' if c.get('status') == 'ACTIVE' else '⏸'
            lines.append(f"{icon} <b>{i}.</b> {h(c['name'])}")
            camp_map[i] = c
        user_state[uid] = {'account': acc, 'map': camp_map}
        lines.append("\n💡 ابعت رقم + فترة\nمثال: <code>3 آخر 30 يوم</code> أو <code>3 مايو</code>")
        await update.message.reply_text('\n'.join(lines), parse_mode='HTML')
        return

    # number only (custom period stored) or number + period
    m_num = re.match(r'^(\d+)\s*(.*)?$', text.strip())
    if m_num and uid in user_state and 'map' in user_state[uid]:
        num      = int(m_num.group(1))
        rest     = (m_num.group(2) or '').strip()
        camp_map = user_state[uid]['map']
        acc      = user_state[uid]['account']
        custom   = user_state[uid].get('custom_period')
        if num in camp_map and acc:
            c = camp_map[num]
            if custom:
                since, until, label = custom
            elif rest:
                since, until, label = parse_period_text(rest)
            else:
                await update.message.reply_text("💡 ابعت رقم + فترة. مثال: <code>3 آخر 30 يوم</code>", parse_mode='HTML')
                return
            await update.message.reply_text("⏳ جاري الجلب...")
            try:
                ins_raw = get_insights(c['id'], since, until)
                ins     = parse_insights(ins_raw, c.get('objective',''))
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {e}")
                return
            if not ins:
                await update.message.reply_text("مفيش داتا للفترة دي.")
                return
            await update.message.reply_text(format_report(c['name'], ins, label, ins.get('currency','EGP')), parse_mode='HTML')
            return

    # campaign ID directly
    m = re.match(r'^(\d{10,})\s*(.*)?$', text.strip())
    if m:
        cid = m.group(1)
        since, until, label = parse_period_text(m.group(2))
        await update.message.reply_text("⏳ جاري الجلب...")
        try:
            ins_raw = get_insights(cid, since, until)
            ins     = parse_insights(ins_raw, ins_raw.get('objective','') if ins_raw else '')
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")
            return
        if not ins:
            await update.message.reply_text("مفيش داتا للفترة دي.")
            return
        await update.message.reply_text(format_report(f"Campaign {cid}", ins, label, ins.get('currency','EGP')), parse_mode='HTML')
        return

    await update.message.reply_text(
        "💡 اكتب <code>/report</code> واختار من الأزرار\n"
        "أو ابعت اسم الاكونت مباشرة: <i>سيدرا / Mall</i>",
        parse_mode='HTML'
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: <code>{update.message.from_user.id}</code>", parse_mode='HTML')


def build_app():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('report', cmd_report))
    app.add_handler(CommandHandler('myid',   myid))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app

def main():
    build_app().run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
