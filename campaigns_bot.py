"""
Campaigns Telegram Bot — Meta API direct
- /report → interactive buttons: account → period → campaign → metrics
- Text shortcut: "سيدرا" → list, "3 مايو" → metrics
"""
import os, re, logging
from datetime import date, timedelta
from io import BytesIO
from dotenv import load_dotenv
import requests
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

import tiktok_api as tt

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
    {'key': 'audiopiano', 'id': 'act_290197205187544', 'label': 'Audio Piano',   'ar': ['اوديو بيانو', 'بيانو', 'audio piano']},
    # TikTok accounts
    {'key': 'tt_mall',  'id': '7477170011656896529', 'label': 'Mall 🎵',          'platform': 'tiktok', 'ar': ['مول تيك', 'mall tiktok']},
    {'key': 'tt_safaa', 'id': '7647455477714042881', 'label': 'Dr.Safaa 🎵',      'platform': 'tiktok', 'ar': ['صفاء', 'دكتوره صفاء', 'safaa']},
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

def fmt_k(n):
    if n is None: return '—'
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1000: return f"{n/1000:.1f}K"
    return str(int(n))

def h(text):
    """Escape HTML special chars."""
    return str(text).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

# ── IMAGE CARD ────────────────────────────────────────────────────────────────

_FONT_B = _FONT = _FONT_S = None

def _load_fonts():
    global _FONT_B, _FONT, _FONT_S
    if _FONT_B: return
    for path in [
        'C:/Windows/Fonts/arialbd.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ]:
        try:
            _FONT_B = ImageFont.truetype(path, 24)
            _FONT   = ImageFont.truetype(path.replace('bd','').replace('-Bold',''), 20)
            _FONT_S = ImageFont.truetype(path.replace('bd','').replace('-Bold',''), 18)
            return
        except Exception:
            continue
    _FONT_B = _FONT = _FONT_S = ImageFont.load_default()

def generate_ads_table(rows_data, camp_name, period_label):
    """
    rows_data: list of {'name', 'thumb_url', 'results', 'result_type', 'cost', 'spend', 'impr', 'reach', 'currency'}
    Returns BytesIO PNG — all ads in one image stacked vertically.
    """
    _load_fonts()
    COLS   = ['', 'Ad Name', 'Results', 'Cost/result', 'Spend', 'Impressions', 'Reach']
    WIDTHS = [90, 320, 160,  160,       130,           155,     130]
    ROW_H  = 90
    HEAD_H = 54
    TITLE_H= 56
    W      = sum(WIDTHS)
    H      = TITLE_H + HEAD_H + ROW_H * len(rows_data)

    BG      = (18, 20, 30)
    HDR_BG  = (28, 32, 50)
    ROW_A   = (22, 25, 38)
    ROW_B   = (26, 30, 44)
    LINE    = (48, 53, 76)
    WHITE   = (255, 255, 255)
    GRAY    = (140, 145, 170)
    GREEN   = (80, 210, 120)
    ACCENT  = (60, 130, 220)

    img  = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    # title bar
    draw.rectangle([0, 0, W, TITLE_H], fill=HDR_BG)
    title = f"{camp_name[:45]}  —  {period_label}"
    draw.text((12, (TITLE_H-18)//2), title, font=_FONT_B, fill=WHITE)
    draw.line([(0, TITLE_H), (W, TITLE_H)], fill=ACCENT, width=2)

    # column headers
    y0 = TITLE_H
    x  = 0
    for col, cw in zip(COLS, WIDTHS):
        draw.rectangle([x, y0, x+cw, y0+HEAD_H], fill=HDR_BG)
        tw = draw.textlength(col, font=_FONT_S)
        draw.text((x+(cw-tw)//2, y0+(HEAD_H-13)//2), col, font=_FONT_S, fill=GRAY)
        draw.line([(x+cw, y0), (x+cw, y0+HEAD_H)], fill=LINE, width=1)
        x += cw
    draw.line([(0, y0+HEAD_H), (W, y0+HEAD_H)], fill=LINE, width=2)

    EN_LABELS = {
        # Arabic labels
        'رسالة':'Messages','شراء':'Purchases','ليد':'Leads',
        'لايك بيدج':'Page Likes','زيارة موقع':'LP Views',
        'زيارة بروفايل':'P.Visits','تفاعل بيدج':'Engagement',
        'مشاهدة فيديو':'Video Views','كليك':'Clicks','ريتش':'Reach','نتيجة':'Results',
        # Raw indicators from Meta API
        'total_profile_visits':'P.Visits',
        'reach':'Reach',
        'total_messaging_connection':'Messages',
        'actions:onsite_conversion.messaging_conversation_started_7d':'Messages',
        'like':'Page Likes',
        'landing_page_view':'LP Views',
        'post_engagement':'Engagement',
        'video_view':'Video Views',
        'link_click':'Clicks',
        'lead':'Leads',
        'offsite_conversion.fb_pixel_purchase':'Purchases',
        'onsite_conversion.purchase':'Purchases',
    }

    for ri, row in enumerate(rows_data):
        ry  = TITLE_H + HEAD_H + ri * ROW_H
        bg  = ROW_A if ri % 2 == 0 else ROW_B
        draw.rectangle([0, ry, W, ry+ROW_H], fill=bg)
        mid = ry + (ROW_H - 14) // 2
        x   = 0

        # thumbnail
        TH = ROW_H - 10
        try:
            tr    = requests.get(row['thumb_url'], timeout=8)
            thumb = Image.open(BytesIO(tr.content)).convert('RGB')
            sz    = min(thumb.size)
            thumb = thumb.crop(((thumb.width-sz)//2,(thumb.height-sz)//2,
                                 (thumb.width+sz)//2,(thumb.height+sz)//2))
            thumb = thumb.resize((TH, TH), Image.LANCZOS)
            img.paste(thumb, (x+(WIDTHS[0]-TH)//2, ry+5))
        except Exception:
            pass
        draw.line([(x+WIDTHS[0], ry),(x+WIDTHS[0], ry+ROW_H)], fill=LINE, width=1)
        x += WIDTHS[0]

        # name
        draw.text((x+8, mid), row['name'][:28], font=_FONT_S, fill=WHITE)
        draw.line([(x+WIDTHS[1], ry),(x+WIDTHS[1], ry+ROW_H)], fill=LINE, width=1)
        x += WIDTHS[1]

        # results
        rt_en = EN_LABELS.get(row['result_type'], row['result_type'])
        res_text = f"{row['results']}  {rt_en}"
        tw = draw.textlength(res_text, font=_FONT_B)
        draw.text((x+(WIDTHS[2]-tw)//2, mid), res_text, font=_FONT_B, fill=GREEN)
        draw.line([(x+WIDTHS[2], ry),(x+WIDTHS[2], ry+ROW_H)], fill=LINE, width=1)
        x += WIDTHS[2]

        # remaining cols
        vals = [f"{row['cost']} {row['currency']}", f"{row['spend']} {row['currency']}",
                row['impr'], row['reach']]
        for vi, (val, cw) in enumerate(zip(vals, WIDTHS[3:])):
            tw = draw.textlength(val, font=_FONT_S)
            draw.text((x+(cw-tw)//2, mid), val, font=_FONT_S, fill=GRAY)
            draw.line([(x+cw, ry),(x+cw, ry+ROW_H)], fill=LINE, width=1)
            x += cw

        draw.line([(0, ry+ROW_H),(W, ry+ROW_H)], fill=LINE, width=1)

    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

def fetch_ad_thumbnails(ad_ids):
    if not ad_ids: return {}
    try:
        r = requests.get(
            'https://graph.facebook.com/v19.0/',
            params={
                'access_token': LONG_LIVED_TOKEN,
                'ids':    ','.join(ad_ids[:50]),
                'fields': 'creative{thumbnail_url,image_url}',
            },
            timeout=20
        )
        out = {}
        for ad_id, info in r.json().items():
            c = info.get('creative', {})
            url = c.get('thumbnail_url') or c.get('image_url', '')
            if url: out[ad_id] = url
        return out
    except Exception as e:
        logger.error(f"thumbnails error: {e}")
        return {}

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

def get_adset_insights(campaign_id, since, until):
    data = api_get(
        f'https://graph.facebook.com/v19.0/{campaign_id}/insights',
        {
            'time_range': f'{{"since":"{since}","until":"{until}"}}',
            'fields':     'adset_id,adset_name,spend,impressions,reach,results,cost_per_result,actions,cost_per_action_type,objective,account_currency',
            'level':      'adset',
            'limit':      50,
        }
    )
    return data.get('data', [])

def get_ad_insights(campaign_id, since, until):
    data = api_get(
        f'https://graph.facebook.com/v19.0/{campaign_id}/insights',
        {
            'time_range': f'{{"since":"{since}","until":"{until}"}}',
            'fields':     'ad_id,ad_name,spend,impressions,reach,results,cost_per_result,actions,cost_per_action_type,objective,account_currency',
            'level':      'ad',
            'limit':      100,
        }
    )
    return data.get('data', [])

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
        # indicators (results field)
        'total_profile_visits':                                'زيارة بروفايل',
        'total_messaging_connection':                          'رسالة',
        'offsite_conversion.fb_pixel_purchase':                'شراء',
        'onsite_conversion.purchase':                          'شراء',
        'onsite_conversion.lead_grouped':                      'ليد',
        'lead':                                                'ليد',
        'link_click':                                          'كليك',
        'landing_page_view':                                   'زيارة موقع',
        'like':                                                'لايك بيدج',
        'video_view':                                          'مشاهدة فيديو',
        'post_engagement':                                     'تفاعل بيدج',
        'page_engagement':                                     'تفاعل بيدج',
        'visit_instagram_profile':                             'زيارة بروفايل',
        'omni_add_to_cart':                                    'أضاف للسلة',
        'omni_initiated_checkout':                             'بدأ الشراء',
        'onsite_conversion.messaging_conversation_started_7d':          'رسالة',
        'actions:onsite_conversion.messaging_conversation_started_7d':   'رسالة',
        'reach':                                                          'ريتش',
        'page_visit_view':                                                'زيارة بيدج',
    }

    if obj in AWARENESS_OBJS:
        results, result_label = reach, 'ريتش'
        cpr = round(spend/(reach/1000), 2) if reach else 0
    else:
        # Use Meta's own results field (same as Ads Manager "Results" column)
        # Structure: [{"indicator": "total_profile_visits", "values": [{"value": "670"}]}]
        api_results  = ins.get('results', [])
        api_cpr_list = ins.get('cost_per_result', [])
        if api_results:
            r0           = api_results[0]
            raw_val      = r0.get('values', [{}])[0].get('value', 0)
            results      = int(float(raw_val))
            indicator    = r0.get('indicator', '')
            result_label = ACTION_LABELS.get(indicator, indicator or 'نتيجة')
            c0           = api_cpr_list[0] if api_cpr_list else {}
            raw_cpr      = c0.get('values', [{}])[0].get('value', 0)
            cpr          = round(float(raw_cpr) if raw_cpr else (spend/results if results else 0), 2)
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

def _res_line(ins, currency):
    """Return (res_val, res_type, cost_val, cost_lbl) for any ins dict."""
    if ins['result_label'] == 'رسالة' and ins['messages'] > 0:
        return ins['messages'], 'رسالة', ins['cpm_msg'], 'سعر الرسالة'
    if ins['obj'] in AWARENESS_OBJS:
        return ins['reach'], 'ريتش', ins['cpr'], 'تكلفة/1000 ريتش'
    if ins['results'] > 0:
        return ins['results'], ins['result_label'], ins['cpr'], 'سعر النتيجة'
    return 0, 'نتيجة', 0, 'سعر النتيجة'

def format_full_report(camp_name, ins, adsets_raw, ads_raw, period_label, currency, obj_raw):
    m = ins
    res_val, res_type, cost_val, cost_lbl = _res_line(m, currency)

    lines = [
        f"📊 <b>{h(camp_name)}</b>",
        f"📅 {period_label}",
        "─────────────────",
        f"🎯 نتيجة: <b>{fmt(res_val)}</b>  <i>({res_type})</i>",
        f"💵 {cost_lbl}: <b>{fmt(cost_val, 2)} {currency}</b>",
        f"💰 إنفاق: <b>{fmt(m['spend'], 2)} {currency}</b>",
        f"👁 <b>{fmt_k(m['impr'])}</b> إمبريشن  |  👥 <b>{fmt_k(m['reach'])}</b> ريتش",
    ]

    # ── Adsets ──
    adsets = sorted(adsets_raw, key=lambda x: float(x.get('spend', 0)), reverse=True)[:8]
    if adsets:
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📦 <b>الأد ستس</b>")
        for row in adsets:
            ai = parse_insights(row, row.get('objective', obj_raw))
            if not ai or ai['spend'] == 0: continue
            rv, rt, cv, _ = _res_line(ai, currency)
            lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
            lines.append(f"<b>{h(row.get('adset_name','')[:35])}</b>")
            lines.append(f"🎯 {fmt(rv)} {rt}  💰 {fmt(cv,2)} {currency}")
            lines.append(f"💵 {fmt(ai['spend'],2)}  👁 {fmt_k(ai['impr'])}  👥 {fmt_k(ai['reach'])}")

    return '\n'.join(lines)

def _format_tiktok_report(camp_name, ins, adgroups_raw, period_label, currency='USD'):
    m = ins
    lines = [
        f"📊 <b>{h(camp_name)}</b>  🎵",
        f"📅 {period_label}",
        "─────────────────",
        f"🎯 Result:  <b>{fmt(m['results'])}</b>  <i>({m['result_label']})</i>",
        f"💵 Cost/Result: <b>{fmt(m['cpr'], 2)} {currency}</b>",
        f"💰 Spend:   <b>{fmt(m['spend'], 2)} {currency}</b>",
        f"👁 <b>{fmt_k(m['impr'])}</b> Impressions  |  👥 <b>{fmt_k(m['reach'])}</b> Reach",
        f"📈 CPM:     <b>{fmt(m['cpm'], 2)} {currency}</b>",
    ]
    adgroups = sorted(adgroups_raw, key=lambda x: float(x.get('spend', 0) or 0), reverse=True)[:8]
    if adgroups:
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📦 <b>Ad Groups</b>")
        for ag in adgroups:
            sp  = round(float(ag.get('spend', 0) or 0), 2)
            if sp == 0: continue
            conv = int(float(ag.get('conversion', 0) or 0))
            lp   = int(float(ag.get('total_landing_page_view', 0) or 0))
            res  = conv if conv > 0 else lp
            cpr_raw = ag.get('cost_per_conversion', '0') or '0'
            try:
                cpr_v = round(float(cpr_raw), 2) if cpr_raw and cpr_raw != '--' else (sp/res if res else 0)
            except Exception:
                cpr_v = sp/res if res else 0
            impr = int(ag.get('impressions', 0) or 0)
            reach= int(ag.get('reach', 0) or 0)
            name = ag.get('adgroup_name', '')[:35]
            lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
            lines.append(f"<b>{h(name)}</b>")
            lines.append(f"🎯 {fmt(res)}  💰 {fmt(cpr_v,2)} {currency}")
            lines.append(f"💵 {fmt(sp,2)}  👁 {fmt_k(impr)}  👥 {fmt_k(reach)}")
    return '\n'.join(lines)


# ── KEYBOARDS ─────────────────────────────────────────────────────────────────

def kb_platform():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📘 Meta",    callback_data="plt:meta"),
        InlineKeyboardButton("🎵 TikTok",  callback_data="plt:tiktok"),
    ]])

def kb_accounts(platform='meta'):
    accs = [a for a in ACCOUNTS if (a.get('platform','meta') == platform)]
    rows = []
    for i in range(0, len(accs), 3):
        rows.append([
            InlineKeyboardButton(a['label'], callback_data=f"acc:{a['key']}")
            for a in accs[i:i+3]
        ])
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data="back:platform")])
    return InlineKeyboardMarkup(rows)

def kb_periods(acc_key):
    platform = ACCOUNTS_BY_KEY.get(acc_key, {}).get('platform', 'meta')
    rows = []
    for i in range(0, len(PERIODS), 3):
        rows.append([
            InlineKeyboardButton(label, callback_data=f"per:{acc_key}:{code}")
            for label, code in PERIODS[i:i+3]
        ])
    rows.append([InlineKeyboardButton("📅 تاريخ مخصص", callback_data=f"custom:{acc_key}")])
    rows.append([InlineKeyboardButton("↩️ رجوع",        callback_data=f"back:plt:{platform}")])
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
        "اختار المنصة 👇",
        reply_markup=kb_platform()
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── platform selected ─────────────────────────────────────────────────────
    if data.startswith('plt:'):
        platform = data.split(':')[1]
        label = "📘 Meta" if platform == 'meta' else "🎵 TikTok"
        await query.edit_message_text(
            f"{label}\n\nاختار الاكونت 👇",
            reply_markup=kb_accounts(platform)
        )

    # ── account selected ──────────────────────────────────────────────────────
    elif data.startswith('acc:'):
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
            if acc.get('platform') == 'tiktok':
                camps = tt.get_campaigns_list(acc['id'])
            else:
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
        acc = ACCOUNTS_BY_KEY.get(acc_key, {})
        is_tiktok = acc.get('platform') == 'tiktok'

        try:
            if is_tiktok:
                metrics    = tt.get_campaign_report(acc['id'], camp_id, since, until)
                ins        = tt.parse_campaign_insights(metrics, camp.get('objective_type','') if camp else '')
                adsets_raw = tt.get_adgroup_report(acc['id'], camp_id, since, until)
                ads_raw    = tt.get_ad_report(acc['id'], camp_id, since, until)
            else:
                ins_raw    = get_insights(camp_id, since, until)
                ins        = parse_insights(ins_raw, obj_raw or (ins_raw.get('objective','') if ins_raw else ''))
                adsets_raw = get_adset_insights(camp_id, since, until)
                ads_raw    = get_ad_insights(camp_id, since, until)
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
            return
        if not ins or ins['spend'] == 0:
            await query.edit_message_text("مفيش داتا للفترة دي. 📭")
            return

        currency = ins.get('currency', 'EGP')
        back_btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ كامبين تاني", callback_data=f"per:{acc_key}:{period_code}")
        ]])

        if is_tiktok:
            text = _format_tiktok_report(camp_name, ins, adsets_raw, label, currency)
        else:
            text = format_full_report(camp_name, ins, adsets_raw, ads_raw, label, currency, obj_raw)
        if len(text) > 4000:
            text = text[:4000] + '\n...'
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=back_btn)

        # ads table image
        if is_tiktok:
            tt_ads     = [r for r in ads_raw if tt._float(r.get('spend', 0)) > 0][:10]
            thumbnails = tt.get_ad_thumbnails(acc['id'], camp_id)
            rows_data  = []
            for row in tt_ads:
                conv = int(tt._float(row.get('conversion', 0)))
                lp   = int(tt._float(row.get('total_landing_page_view', 0)))
                rv   = conv if conv > 0 else lp
                cpr_raw = row.get('cost_per_conversion', '0') or '0'
                try:
                    cv = round(float(cpr_raw), 2) if cpr_raw and cpr_raw != '--' else (tt._float(row.get('spend',0))/rv if rv else 0)
                except Exception:
                    cv = 0
                rows_data.append({
                    'name':        row.get('ad_name', '')[:40],
                    'thumb_url':   thumbnails.get(row.get('_ad_id', ''), ''),
                    'results':     fmt(rv),
                    'result_type': ins['result_label'],
                    'cost':        fmt(cv, 2),
                    'spend':       fmt(round(tt._float(row.get('spend', 0)), 2), 2),
                    'impr':        fmt_k(int(tt._float(row.get('impressions', 0)))),
                    'reach':       fmt_k(int(tt._float(row.get('reach', 0)))),
                    'currency':    currency,
                })
            if rows_data:
                try:
                    img = generate_ads_table(rows_data, camp_name, label)
                    await context.bot.send_photo(chat_id=query.message.chat_id, photo=img)
                except Exception as e:
                    logger.error(f"TikTok ads table error: {e}")
        else:
            ads_sorted = sorted(ads_raw, key=lambda x: float(x.get('spend', 0)), reverse=True)[:10]
            ad_ids     = [r.get('ad_id', '') for r in ads_sorted if r.get('ad_id')]
            thumbnails = fetch_ad_thumbnails(ad_ids)
            rows_data  = []
            for row in ads_sorted:
                ai = parse_insights(row, row.get('objective', obj_raw))
                if not ai or ai['spend'] == 0: continue
                rv, rt, cv, _ = _res_line(ai, currency)
                rows_data.append({
                    'name':        row.get('ad_name', ''),
                    'thumb_url':   thumbnails.get(row.get('ad_id', ''), ''),
                    'results':     fmt(rv),
                    'result_type': rt,
                    'cost':        fmt(cv, 2),
                    'spend':       fmt(ai['spend'], 2),
                    'impr':        fmt_k(ai['impr']),
                    'reach':       fmt_k(ai['reach']),
                    'currency':    currency,
                })
            if rows_data:
                try:
                    img = generate_ads_table(rows_data, camp_name, label)
                    await context.bot.send_photo(chat_id=query.message.chat_id, photo=img)
                except Exception as e:
                    logger.error(f"ads table error: {e}")

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
            if acc.get('platform') == 'tiktok':
                camps = tt.get_campaigns_list(acc['id'])
            else:
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
    elif data == 'back:platform':
        await query.edit_message_text("اختار المنصة 👇", reply_markup=kb_platform())

    elif data.startswith('back:plt:'):
        platform = data.split(':')[2]
        label = "📘 Meta" if platform == 'meta' else "🎵 TikTok"
        await query.edit_message_text(f"{label}\n\nاختار الاكونت 👇", reply_markup=kb_accounts(platform))

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
