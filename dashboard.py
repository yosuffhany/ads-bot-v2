"""
Ads Performance Dashboard v4 — Meta Ads
"""
import streamlit as st
import requests
import os
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

def get_secret(key):
    try:    return st.secrets[key]
    except: return os.getenv(key)

TOKEN = get_secret('LONG_LIVED_TOKEN')

# ── ACCOUNTS ─────────────────────────────────────────────────────────────────
ACCOUNTS = {
    'Mall':    {'id': 'act_2001687506868513', 'code': 'mall2024',   'color': '#1877F2'},
    'BSQ':     {'id': 'act_841897980911694',  'code': 'bsq2024',    'color': '#E91E63'},
    'Kemet':   {'id': 'act_345674018149436',  'code': 'kemet2024',  'color': '#FF6B00'},
    'Al Adel': {'id': 'act_1392109118185589', 'code': 'eladel2024', 'color': '#00875A'},
}
ADMIN_CODE = 'admin'

AWARENESS_OBJECTIVES = {'OUTCOME_AWARENESS', 'OUTCOME_REACH', 'REACH', 'AWARENESS'}
ACTION_PRIORITY = [
    'onsite_conversion.messaging_conversation_started_7d',
    'offsite_conversion.fb_pixel_purchase',
    'onsite_conversion.purchase',
    'onsite_conversion.lead_grouped',
    'lead',
]
PURCHASE_ACTIONS = {'offsite_conversion.fb_pixel_purchase', 'onsite_conversion.purchase'}
INSIGHTS_FIELDS  = 'spend,cpm,reach,impressions,clicks,inline_link_clicks,actions,cost_per_action_type'

# ── HELPERS ───────────────────────────────────────────────────────────────────
def auth_check(code):
    c = code.strip().lower()
    if c == ADMIN_CODE:
        return list(ACCOUNTS.keys())
    for name, info in ACCOUNTS.items():
        if c == info['code']:
            return [name]
    return None

def fmt_k(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return str(int(n))

def fmt_usd(n):
    if n == 0: return "$0"
    return f"${n:,.1f}"

def fmt_pct(n):
    return f"{n:.2f}%"

def fmt_date(d_str):
    dt = pd.to_datetime(d_str)
    return f"{dt.strftime('%b')} {dt.day}"

# ── API ───────────────────────────────────────────────────────────────────────
def parse_insights(ins, objective_raw):
    spend       = round(float(ins.get('spend', 0)), 2)
    cpm         = round(float(ins.get('cpm', 0)), 2)
    impressions = int(ins.get('impressions', 0))
    clicks      = int(ins.get('clicks', 0))
    reach       = int(ins.get('reach', 0))
    link_clicks = int(ins.get('inline_link_clicks', 0))
    obj         = (objective_raw or '').upper()

    actions = ins.get('actions', [])
    costs   = ins.get('cost_per_action_type', [])

    purchases = sum(
        int(float(a['value'])) for a in actions
        if a['action_type'] in PURCHASE_ACTIONS
    )

    if obj in AWARENESS_OBJECTIVES:
        result, result_label = reach, 'Reach'
        cpr = round(spend / (reach / 1000), 2) if reach else 0.0
    else:
        result, cpr, result_label = 0, 0.0, 'Results'
        for at in ACTION_PRIORITY:
            act = next((a for a in actions if a['action_type'] == at), None)
            if act:
                result = int(float(act['value']))
                cost   = next((c for c in costs if c['action_type'] == at), None)
                cpr    = round(float(cost['value']) if cost else (spend / result if result else 0), 2)
                break

    return {
        'objective':     obj.replace('OUTCOME_', '').title(),
        'objective_raw': obj,
        'result':        result,
        'result_label':  result_label,
        'cpr':           cpr,
        'spend':         spend,
        'cpm':           cpm,
        'impressions':   impressions,
        'clicks':        clicks,
        'reach':         reach,
        'link_clicks':   link_clicks,
        'purchases':     purchases,
    }

@st.cache_data(ttl=300, show_spinner=False)
def fetch_campaigns(account_id, since, until):
    tr = f'{{"since":"{since}","until":"{until}"}}'
    r = requests.get(
        f'https://graph.facebook.com/v19.0/{account_id}/campaigns',
        params={
            'access_token': TOKEN,
            'fields': f'id,name,objective,status,insights.time_range({tr}){{{INSIGHTS_FIELDS}}}',
            'limit': 200,
        }
    )
    r.raise_for_status()
    out = []
    for c in r.json().get('data', []):
        ins  = (c.get('insights', {}).get('data') or [{}])[0]
        data = parse_insights(ins, c.get('objective', ''))
        data.update({'id': c['id'], 'name': c['name'], 'status': c.get('status', '')})
        out.append(data)
    return sorted(out, key=lambda x: x['spend'], reverse=True)

@st.cache_data(ttl=300, show_spinner=False)
def fetch_adsets(campaign_id, obj_raw, since, until):
    tr = f'{{"since":"{since}","until":"{until}"}}'
    try:
        r = requests.get(
            f'https://graph.facebook.com/v19.0/{campaign_id}/adsets',
            params={
                'access_token': TOKEN,
                'fields': f'id,name,status,insights.time_range({tr}){{{INSIGHTS_FIELDS}}}',
                'limit': 100,
            }
        )
        r.raise_for_status()
        out = []
        for a in r.json().get('data', []):
            ins  = (a.get('insights', {}).get('data') or [{}])[0]
            data = parse_insights(ins, obj_raw)
            data.update({'id': a['id'], 'name': a['name'], 'status': a.get('status', '')})
            out.append(data)
        return sorted(out, key=lambda x: x['spend'], reverse=True)
    except Exception:
        return []

@st.cache_data(ttl=300, show_spinner=False)
def fetch_ads(adset_id, obj_raw, since, until):
    tr = f'{{"since":"{since}","until":"{until}"}}'
    try:
        r = requests.get(
            f'https://graph.facebook.com/v19.0/{adset_id}/ads',
            params={
                'access_token': TOKEN,
                'fields': f'id,name,status,insights.time_range({tr}){{{INSIGHTS_FIELDS}}}',
                'limit': 100,
            }
        )
        r.raise_for_status()
        out = []
        for a in r.json().get('data', []):
            ins  = (a.get('insights', {}).get('data') or [{}])[0]
            data = parse_insights(ins, obj_raw)
            data.update({'id': a['id'], 'name': a['name'], 'status': a.get('status', '')})
            out.append(data)
        return sorted(out, key=lambda x: x['spend'], reverse=True)
    except Exception:
        return []

@st.cache_data(ttl=300, show_spinner=False)
def fetch_balance(account_id):
    r = requests.get(
        f'https://graph.facebook.com/v19.0/{account_id}',
        params={'access_token': TOKEN, 'fields': 'funding_source_details,currency'}
    )
    d = r.json()
    return d.get('funding_source_details', {}).get('display_string', '') or f"0.00 {d.get('currency','')}"

@st.cache_data(ttl=300, show_spinner=False)
def fetch_daily_insights(account_id, since, until):
    try:
        r = requests.get(
            f'https://graph.facebook.com/v19.0/{account_id}/insights',
            params={
                'access_token': TOKEN,
                'time_range': f'{{"since":"{since}","until":"{until}"}}',
                'time_increment': 1,
                'fields': 'date_start,spend,impressions,inline_link_clicks,actions',
            }
        )
        r.raise_for_status()
        rows = []
        for row in r.json().get('data', []):
            purchases = sum(
                int(float(a['value'])) for a in row.get('actions', [])
                if a['action_type'] in PURCHASE_ACTIONS
            )
            rows.append({
                'date':        row['date_start'],
                'impressions': int(row.get('impressions', 0)),
                'link_clicks': int(row.get('inline_link_clicks', 0)),
                'purchases':   purchases,
                'spend':       float(row.get('spend', 0)),
            })
        return sorted(rows, key=lambda x: x['date'])
    except Exception:
        return []

# ── DATE RANGE ────────────────────────────────────────────────────────────────
DATE_PRESETS = [
    'Today', 'Yesterday',
    'Last 7 days', 'Last 14 days', 'Last 28 days', 'Last 30 days',
    'This week', 'Last week',
    'This month', 'Last month',
    'Custom',
]

def resolve_dates(preset, cf=None, ct=None):
    today = date.today()
    if preset == 'Today':        return today, today
    if preset == 'Yesterday':    y = today - timedelta(1); return y, y
    if preset == 'Last 7 days':  return today - timedelta(6),  today
    if preset == 'Last 14 days': return today - timedelta(13), today
    if preset == 'Last 28 days': return today - timedelta(27), today
    if preset == 'Last 30 days': return today - timedelta(29), today
    if preset == 'This week':    return today - timedelta(today.weekday()), today
    if preset == 'Last week':
        s = today - timedelta(today.weekday() + 7)
        return s, s + timedelta(6)
    if preset == 'This month':   return today.replace(day=1), today
    if preset == 'Last month':
        first = today.replace(day=1)
        last  = first - timedelta(1)
        return last.replace(day=1), last
    return cf or today.replace(day=1), ct or today

# ── RECOMMENDATIONS ───────────────────────────────────────────────────────────
def get_recommendations(campaigns):
    if not campaigns:
        return []

    with_spend = [c for c in campaigns if c['spend'] > 0]
    if not with_spend:
        return [('info', 'No spend data in this period. No recommendations available.')]

    avg_cpr = (sum(c['cpr'] for c in with_spend if c['cpr'] > 0)
               / max(len([c for c in with_spend if c['cpr'] > 0]), 1))
    avg_cpm = (sum(c['cpm'] for c in with_spend if c['cpm'] > 0)
               / max(len([c for c in with_spend if c['cpm'] > 0]), 1))
    avg_ctr = (sum(c['clicks'] / c['impressions'] * 100
                   for c in with_spend if c['impressions'] > 0)
               / max(len([c for c in with_spend if c['impressions'] > 0]), 1))
    avg_spend = sum(c['spend'] for c in with_spend) / len(with_spend)

    recs = []
    for c in campaigns:
        n   = c['name']
        ctr = c['clicks'] / c['impressions'] * 100 if c['impressions'] > 0 else 0
        is_awareness = c['objective_raw'] in AWARENESS_OBJECTIVES

        if c['status'] == 'ACTIVE' and c['impressions'] == 0:
            recs.append(('error',
                f"🔴 **{n}**\n\n"
                f"**المشكلة:** الكامبين شغال بس مش بياخد impressions خالص.\n\n"
                f"**السبب المحتمل:** نفاد الميزانية، إعلان مرفوض، أو مشكلة في الـ payment.\n\n"
                f"**الحل:** راجع الـ delivery status في Meta وتأكد من الـ payment method."))

        elif c['spend'] > 0 and c['result'] == 0 and not is_awareness:
            recs.append(('error',
                f"🔴 **{n}**\n\n"
                f"**المشكلة:** صرف **{c['spend']:,.0f}** بدون أي نتيجة.\n\n"
                f"**السبب المحتمل:** Landing page معطل، كريتيف ضعيف، أو الـ audience مش مناسب.\n\n"
                f"**الحل:** وقف الكامبين دلوقتي وراجع الـ funnel كامل — من الإعلان للصفحة."))

        elif not is_awareness and avg_cpr > 0 and c['cpr'] > avg_cpr * 2.5:
            recs.append(('error',
                f"🔴 **{n}**\n\n"
                f"**المشكلة:** CPR = **{c['cpr']:.2f}** — {c['cpr']/avg_cpr:.1f}x متوسط الأكونت ({avg_cpr:.2f}).\n\n"
                f"**الحل:** وقف الأضعف من الـ ad sets، جرب كريتيف جديد، وضيق الـ audience."))

        elif not is_awareness and avg_cpr > 0 and c['cpr'] > avg_cpr * 1.5:
            recs.append(('warning',
                f"🟡 **{n}**\n\n"
                f"**CPR = {c['cpr']:.2f}** (متوسط الأكونت: {avg_cpr:.2f})\n\n"
                f"**الحل:** جرب كريتيف جديد أو خصص الميزانية للـ ad sets الأفضل أداءً."))

        elif avg_cpm > 0 and c['cpm'] > avg_cpm * 2 and c['spend'] > 0:
            recs.append(('warning',
                f"🟡 **{n}**\n\n"
                f"**CPM = {c['cpm']:.2f}** — {c['cpm']/avg_cpm:.1f}x المتوسط ({avg_cpm:.2f})\n\n"
                f"**السبب:** الـ audience مشبع أو ضيق جداً.\n\n"
                f"**الحل:** وسع الـ audience أو جرب placements تانية."))

        elif ctr < 0.5 and c['impressions'] > 5000 and not is_awareness:
            recs.append(('warning',
                f"🟡 **{n}**\n\n"
                f"**CTR = {ctr:.2f}%** (ضعيف جداً — متوسط الأكونت: {avg_ctr:.2f}%)\n\n"
                f"**{c['impressions']:,} impression** بس {c['clicks']:,} click فقط.\n\n"
                f"**الحل:** الكريتيف مش بيجذب الناس — غير الصورة أو الـ hook."))

        elif c['spend'] == 0 and c['status'] == 'ACTIVE':
            recs.append(('warning',
                f"🟡 **{n}**\n\n"
                f"**شغال بس مش صارف في الفترة دي.**\n\n"
                f"**السبب المحتمل:** نفاد الميزانية اليومية أو الكامبين متأخر في الـ schedule."))

        elif not is_awareness and avg_cpr > 0 and c['cpr'] < avg_cpr * 0.6 and c['spend'] < avg_spend:
            recs.append(('success',
                f"🟢 **{n}** — فرصة للـ Scale!\n\n"
                f"**CPR = {c['cpr']:.2f}** — {avg_cpr/c['cpr']:.1f}x أحسن من المتوسط ({avg_cpr:.2f})\n\n"
                f"**الكامبين ده بياخد نتايج بسعر كويس ومش بياخد ميزانية كافية.**\n\n"
                f"**الحل:** زود الميزانية اليومية بـ 20-30% وراقب الـ CPR."))

        elif ctr > 3 and c['spend'] > 0 and not is_awareness:
            recs.append(('success',
                f"🟢 **{n}** — كريتيف قوي!\n\n"
                f"**CTR = {ctr:.2f}%** (متوسط الأكونت: {avg_ctr:.2f}%)\n\n"
                f"الناس بتتفاعل مع الإعلان ده كويس — جرب توسيع الـ audience عشان توصل لناس أكتر."))

        elif is_awareness and avg_cpm > 0 and c['cpm'] < avg_cpm * 0.7 and c['spend'] > 0:
            recs.append(('success',
                f"🟢 **{n}** — Awareness بكفاءة عالية\n\n"
                f"**CPM = {c['cpm']:.2f}** — أرخص من المتوسط بـ {(1 - c['cpm']/avg_cpm)*100:.0f}%\n\n"
                f"وصول كبير بتكلفة قليلة. ممكن تزود الميزانية."))

        elif c['spend'] == 0:
            recs.append(('info',
                f"ℹ️ **{n}** — لا يوجد صرف في هذه الفترة ({c['status']})."))
        else:
            recs.append(('info',
                f"ℹ️ **{n}** — أداء طبيعي. "
                f"CPR: {c['cpr']:.2f} | CTR: {ctr:.2f}% | CPM: {c['cpm']:.2f}"))

    order = {'error': 0, 'warning': 1, 'success': 2, 'info': 3}
    return sorted(recs, key=lambda x: order.get(x[0], 4))

# ── CHART BUILDER ─────────────────────────────────────────────────────────────
def make_mini_chart(x, y, label):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, mode='lines',
        line=dict(color='#22C55E', width=2.5),
        name=label,
        showlegend=True,
    ))
    fig.update_layout(
        paper_bgcolor='white',
        plot_bgcolor='white',
        margin=dict(l=50, r=10, t=28, b=30),
        height=195,
        legend=dict(
            orientation='h', x=0, y=1.18,
            font=dict(size=11, color='#555'),
            itemsizing='constant',
        ),
        xaxis=dict(
            showgrid=False,
            showline=True,
            linecolor='#E0E0E0',
            tickfont=dict(size=10, color='#888'),
            nticks=6,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor='#F4F4F4',
            showline=True,
            linecolor='#E0E0E0',
            tickfont=dict(size=10, color='#888'),
            rangemode='tozero',
        ),
    )
    return fig

# ── CARD RENDERER ─────────────────────────────────────────────────────────────
NAVY = '#0B2447'

def metric_box_html(label, value):
    return (
        f'<div style="background:{NAVY};color:white;border-radius:8px;'
        f'padding:12px 14px;flex:1;min-width:0;box-sizing:border-box">'
        f'<div style="font-size:11px;opacity:0.75;margin-bottom:5px;white-space:nowrap">{label}</div>'
        f'<div style="font-size:20px;font-weight:700;line-height:1.1">{value}</div>'
        f'</div>'
    )

def render_metric_card(col, title, boxes, fig):
    chart_html = pio.to_html(
        fig, full_html=False, include_plotlyjs=False,
        config={'displayModeBar': False},
        default_height='195px',
    )
    boxes_html = ''.join(metric_box_html(lbl, val) for lbl, val in boxes)
    with col:
        st.markdown(
            f'<div style="background:white;border-radius:14px;padding:22px 22px 8px;'
            f'box-shadow:0 2px 10px rgba(0,0,0,0.07);margin-bottom:4px">'
            f'<div style="font-size:17px;font-weight:700;color:#1C1E21;margin-bottom:14px">{title}</div>'
            f'<div style="display:flex;gap:8px;margin-bottom:10px">{boxes_html}</div>'
            f'{chart_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

# ── THEME CSS ─────────────────────────────────────────────────────────────────
LIGHT = {
    'bg':         '#F0F2F5',
    'card':       '#FFFFFF',
    'border':     '#E4E6EB',
    'text':       '#1C1E21',
    'text2':      '#65676B',
    'shadow':     'rgba(0,0,0,0.06)',
    'hover_sh':   'rgba(24,119,242,0.12)',
    'sidebar_bg': '#1877F2',
    'inp_bg':     'rgba(255,255,255,0.18)',
    'inp_bdr':    'rgba(255,255,255,0.35)',
    'tab_bg':     '#FFFFFF',
    'badge_act':  ('#E6F4EA', '#1E7E34'),
    'badge_pau':  ('#FFF3E0', '#C55A00'),
    'inner_card': '#F8F9FB',
}
DARK = {
    'bg':         '#18191A',
    'card':       '#242526',
    'border':     '#3E4042',
    'text':       '#E4E6EB',
    'text2':      '#B0B3B8',
    'shadow':     'rgba(0,0,0,0.3)',
    'hover_sh':   'rgba(24,119,242,0.25)',
    'sidebar_bg': '#1A1A2E',
    'inp_bg':     'rgba(255,255,255,0.10)',
    'inp_bdr':    'rgba(255,255,255,0.2)',
    'tab_bg':     '#242526',
    'badge_act':  ('#1E3A2A', '#4ADE80'),
    'badge_pau':  ('#3A2A0A', '#FBBF24'),
    'inner_card': '#2D2E2F',
}

def inject_css(t, acct_color):
    badge_act_bg, badge_act_fg = t['badge_act']
    badge_pau_bg, badge_pau_fg = t['badge_pau']
    st.markdown(f"""
<style>
#MainMenu, footer, header {{ visibility: hidden; }}
.block-container {{ padding: 1.5rem 2.5rem 3rem !important; }}
.stApp {{ background: {t['bg']} !important; }}

.login-card {{
    background: {t['card']};
    border-radius: 18px;
    padding: 44px 44px 36px;
    box-shadow: 0 6px 32px {t['shadow']};
    max-width: 420px;
    margin: 0 auto;
    border: 1px solid {t['border']};
}}

.nav-bar {{
    background: {t['card']};
    border-radius: 14px;
    padding: 16px 26px;
    margin-bottom: 20px;
    box-shadow: 0 1px 4px {t['shadow']};
    border: 1px solid {t['border']};
    display: flex;
    align-items: center;
    justify-content: space-between;
}}
.nav-title {{ font-size:20px; font-weight:700; color:{t['text']}; margin:0; }}
.nav-sub   {{ font-size:13px; color:{t['text2']}; margin:4px 0 0 0; }}

[data-testid="metric-container"] {{
    background: {t['card']} !important;
    border: 1px solid {t['border']} !important;
    border-radius: 14px !important;
    padding: 20px 22px !important;
    box-shadow: 0 1px 4px {t['shadow']} !important;
    transition: box-shadow 0.2s, border-color 0.2s;
}}
[data-testid="metric-container"]:hover {{
    box-shadow: 0 4px 14px {t['hover_sh']} !important;
    border-color: {acct_color} !important;
}}
[data-testid="metric-container"] label {{
    font-size: 11px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.7px !important;
    color: {t['text2']} !important;
}}
[data-testid="stMetricValue"] {{
    font-size: 24px !important;
    font-weight: 700 !important;
    color: {t['text']} !important;
}}

[data-testid="stExpander"] {{
    background: {t['card']} !important;
    border: 1px solid {t['border']} !important;
    border-radius: 14px !important;
    margin-bottom: 8px !important;
    box-shadow: 0 1px 3px {t['shadow']} !important;
    transition: all 0.2s !important;
}}
[data-testid="stExpander"]:hover {{
    border-color: {acct_color} !important;
    box-shadow: 0 4px 14px {t['hover_sh']} !important;
}}
[data-testid="stExpander"] > details > summary {{
    padding: 16px 20px !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    color: {t['text']} !important;
}}
[data-testid="stExpander"] [data-testid="stExpander"] {{
    background: {t['inner_card']} !important;
    border-radius: 10px !important;
    box-shadow: none !important;
}}

[data-testid="stTabs"] {{
    background: {t['tab_bg']};
    border-radius: 14px;
    padding: 0 20px;
    border: 1px solid {t['border']};
    box-shadow: 0 1px 3px {t['shadow']};
}}
button[data-baseweb="tab"] {{
    font-size: 14px !important;
    font-weight: 600 !important;
    padding: 14px 22px !important;
    color: {t['text2']} !important;
    background: transparent !important;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
    color: {acct_color} !important;
    border-bottom: 3px solid {acct_color} !important;
}}

[data-testid="stSidebar"] {{ background: {t['sidebar_bg']} !important; }}
[data-testid="stSidebar"] * {{ color: white !important; }}
[data-testid="stSidebar"] .stSelectbox > div > div,
[data-testid="stSidebar"] .stDateInput > div > div {{
    background: {t['inp_bg']} !important;
    border: 1px solid {t['inp_bdr']} !important;
    color: white !important;
}}
[data-testid="stSidebar"] .stButton > button {{
    background: rgba(255,255,255,0.18) !important;
    border: 1px solid rgba(255,255,255,0.35) !important;
    color: white !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(255,255,255,0.28) !important;
}}

.badge-active {{
    background:{badge_act_bg}; color:{badge_act_fg};
    padding:3px 12px; border-radius:20px;
    font-size:12px; font-weight:700; display:inline-block;
}}
.badge-paused {{
    background:{badge_pau_bg}; color:{badge_pau_fg};
    padding:3px 12px; border-radius:20px;
    font-size:12px; font-weight:700; display:inline-block;
}}

.sec-hdr {{
    font-size:11px; font-weight:800; color:{t['text2']};
    text-transform:uppercase; letter-spacing:1px;
    margin:12px 0 10px 0; padding-bottom:8px;
    border-bottom: 2px solid {t['border']};
}}

.spend-bar-bg   {{ background:{t['border']}; border-radius:4px; height:5px; margin-top:4px; }}
.spend-bar-fill {{ border-radius:4px; height:5px; }}

[data-testid="stDataFrame"] {{
    border-radius: 10px !important;
    overflow: hidden !important;
    border: 1px solid {t['border']} !important;
}}

button[kind="primary"] {{
    background: {acct_color} !important;
    border-color: {acct_color} !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
}}

hr {{ border-color: {t['border']} !important; margin:14px 0 !important; }}
[data-testid="stAlert"] {{ border-radius:10px !important; border:none !important; }}

.stApp p, .stApp h1, .stApp h2, .stApp h3 {{
    color: {t['text']};
}}
.stCaption {{ color: {t['text2']} !important; }}

/* Top Campaigns table */
.top-camp-table {{
    width:100%;
    border-collapse:collapse;
    font-size:14px;
    color:{t['text']};
}}
.top-camp-table th {{
    background:{NAVY};
    color:white;
    padding:12px 16px;
    text-align:left;
    font-weight:600;
    font-size:13px;
}}
.top-camp-table th:not(:first-child) {{ text-align:right; }}
.top-camp-table td {{
    padding:11px 16px;
    border-bottom:1px solid {t['border']};
    background:{t['card']};
}}
.top-camp-table td:not(:first-child) {{ text-align:right; font-variant-numeric:tabular-nums; }}
.top-camp-table tr:last-child td {{ border-bottom:none; }}
.top-camp-num {{ color:{t['text2']}; font-size:13px; width:36px; }}
</style>
""", unsafe_allow_html=True)

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Ads Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════════
if 'allowed_accounts' not in st.session_state:
    inject_css(LIGHT, '#1877F2')
    st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.1, 1])
    with col:
        st.markdown("""
        <div class="login-card">
            <div style="text-align:center; margin-bottom:28px">
                <div style="font-size:52px; margin-bottom:12px">📊</div>
                <h2 style="margin:0; font-size:26px">Ads Dashboard</h2>
                <p style="margin:10px 0 0 0; font-size:14px">
                    Enter your access code to continue
                </p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.form('login', clear_on_submit=False):
            code = st.text_input(
                'code', type='password',
                placeholder='Enter access code...',
                label_visibility='collapsed',
            )
            ok = st.form_submit_button('Sign In →', use_container_width=True, type='primary')

        if ok:
            result = auth_check(code)
            if result:
                st.session_state['allowed_accounts'] = result
                st.session_state['dark_mode'] = False
                st.rerun()
            else:
                st.error('Invalid access code. Please try again.')
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
allowed = st.session_state['allowed_accounts']

if 'dark_mode'   not in st.session_state: st.session_state['dark_mode']   = False
if 'preset'      not in st.session_state: st.session_state['preset']      = 'This month'
if 'show_paused' not in st.session_state: st.session_state['show_paused'] = False

with st.sidebar:
    st.markdown("### 📊 Ads Dashboard")
    st.divider()
    dark_mode = st.toggle("🌙 Dark Mode", value=st.session_state['dark_mode'])
    st.session_state['dark_mode'] = dark_mode
    st.divider()
    if st.button("🔄 Refresh Data", use_container_width=True, type='primary'):
        st.cache_data.clear()
        st.rerun()
    if st.button("Logout", use_container_width=True):
        for k in ['allowed_accounts', 'dark_mode']:
            st.session_state.pop(k, None)
        st.rerun()

theme = DARK if dark_mode else LIGHT

# ══════════════════════════════════════════════════════════════════════════════
# TOP CONTROLS
# ══════════════════════════════════════════════════════════════════════════════
ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([2, 2, 2, 0.6])

with ctrl1:
    if len(allowed) > 1:
        acct_name = st.selectbox("Account", options=allowed, label_visibility="collapsed")
    else:
        acct_name = allowed[0]

acct_color = ACCOUNTS[acct_name]['color']
inject_css(theme, acct_color)

with ctrl2:
    preset = st.selectbox(
        "Date Range", DATE_PRESETS,
        index=DATE_PRESETS.index('This month'),
        label_visibility="collapsed",
    )

cf = ct = None
if preset == 'Custom':
    with ctrl3:
        cf = st.date_input("From", value=date.today().replace(day=1), label_visibility="collapsed")
    _, cto = st.columns([4.6, 2])
    with cto:
        ct = st.date_input("To", value=date.today(), label_visibility="collapsed")
else:
    with ctrl3:
        st.markdown("")

with ctrl4:
    if st.button("🔄", help="Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

since, until = resolve_dates(preset, cf, ct)

# ══════════════════════════════════════════════════════════════════════════════
# FETCH
# ══════════════════════════════════════════════════════════════════════════════
acct_id = ACCOUNTS[acct_name]['id']
since_s = since.strftime('%Y-%m-%d')
until_s = until.strftime('%Y-%m-%d')

with st.spinner("Loading..."):
    try:
        balance   = fetch_balance(acct_id)
        campaigns = fetch_campaigns(acct_id, since_s, until_s)
        daily     = fetch_daily_insights(acct_id, since_s, until_s)
    except Exception as e:
        st.error(f"Meta API Error: {e}")
        st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════
active_count = len([c for c in campaigns if c['status'] == 'ACTIVE'])
paused_count = len([c for c in campaigns if c['status'] != 'ACTIVE'])

st.markdown(f"""
<div class="nav-bar">
    <div>
        <p class="nav-title">
            <span style="color:{acct_color}; font-size:16px">●</span>&nbsp; {acct_name}
        </p>
        <p class="nav-sub">
            📅 {since.strftime('%b %d')} — {until.strftime('%b %d, %Y')}
            &nbsp;·&nbsp;
            🟢 {active_count} active &nbsp; 🟡 {paused_count} paused
            &nbsp;·&nbsp; 💳 Balance: <b>{balance}</b>
        </p>
    </div>
    <div style="font-size:22px; opacity:0.4">📊</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TOTALS
# ══════════════════════════════════════════════════════════════════════════════
total_spend       = sum(c['spend']       for c in campaigns)
total_impr        = sum(c['impressions'] for c in campaigns)
total_link_clicks = sum(c['link_clicks'] for c in campaigns)
total_purchases   = sum(c['purchases']   for c in campaigns)
total_reach       = sum(c['reach']       for c in campaigns)
total_res         = sum(c['result']      for c in campaigns)

avg_cpm = round(total_spend / (total_impr / 1000), 2) if total_impr else 0
avg_cpc = round(total_spend / total_link_clicks, 2)   if total_link_clicks else 0
ctr_all = round(total_link_clicks / total_impr * 100, 2) if total_impr else 0
cvr     = round(total_purchases / total_link_clicks * 100, 2) if total_link_clicks else 0
cpa     = round(total_spend / total_purchases, 2)      if total_purchases else 0

# Daily series for charts
dates_fmt    = [fmt_date(d['date']) for d in daily]
impr_series  = [d['impressions']   for d in daily]
lc_series    = [d['link_clicks']   for d in daily]
purch_series = [d['purchases']     for d in daily]

# ══════════════════════════════════════════════════════════════════════════════
# THREE METRIC CARDS
# ══════════════════════════════════════════════════════════════════════════════
c1, c2, c3 = st.columns(3)

render_metric_card(
    c1,
    "Cost & Impressions",
    [
        ("Amount Spend", fmt_usd(total_spend)),
        ("CPM",          fmt_usd(avg_cpm)),
        ("Impressions",  fmt_k(total_impr)),
    ],
    make_mini_chart(dates_fmt, impr_series, "Impressions"),
)

render_metric_card(
    c2,
    "Clicks",
    [
        ("Link clicks", fmt_k(total_link_clicks)),
        ("CTR (all)",   fmt_pct(ctr_all)),
        ("CPC",         fmt_usd(avg_cpc)),
    ],
    make_mini_chart(dates_fmt, lc_series, "Link clicks"),
)

render_metric_card(
    c3,
    "Conversions",
    [
        ("Purchases", str(total_purchases) if total_purchases else "0"),
        ("CVR",       fmt_pct(cvr)         if total_purchases else "0.00%"),
        ("CPA",       fmt_usd(cpa)         if total_purchases else "No data"),
    ],
    make_mini_chart(dates_fmt, purch_series, "Website purchases"),
)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TOP CAMPAIGNS TABLE
# ══════════════════════════════════════════════════════════════════════════════
top_camps = sorted(
    [c for c in campaigns if c['impressions'] > 0],
    key=lambda x: x['impressions'],
    reverse=True,
)[:15]

if top_camps:
    rows_html = ''
    for i, c in enumerate(top_camps, 1):
        rows_html += (
            f'<tr>'
            f'<td class="top-camp-num">{i}.</td>'
            f'<td>{c["name"]}</td>'
            f'<td>{c["impressions"]:,}</td>'
            f'<td>{c["link_clicks"]:,}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="background:{theme["card"]};border-radius:14px;'
        f'padding:24px 24px 8px;box-shadow:0 2px 10px rgba(0,0,0,0.07);'
        f'margin-bottom:20px">'
        f'<div style="font-size:17px;font-weight:700;color:{theme["text"]};margin-bottom:16px">'
        f'Top Campaigns</div>'
        f'<table class="top-camp-table">'
        f'<thead><tr>'
        f'<th style="width:40px"></th>'
        f'<th>Ad name</th>'
        f'<th style="text-align:right">Impressions ↕</th>'
        f'<th style="text-align:right">Link clicks ↕</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_camp, tab_chart, tab_rec = st.tabs(["📋  Campaigns", "📊  Charts", "💡  Recommendations"])

# ── CAMPAIGNS ─────────────────────────────────────────────────────────────────
with tab_camp:
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if not campaigns:
        st.info("No campaigns found for this period.")
    else:
        all_statuses = sorted(set(c['status'] for c in campaigns))
        status_labels = {
            'ACTIVE': '🟢 Active', 'PAUSED': '🟡 Paused',
            'ARCHIVED': '🗄 Archived', 'DELETED': '🗑 Deleted',
            'WITH_ISSUES': '⚠️ Issues', 'IN_PROCESS': '⏳ In Process',
        }

        f_col1, f_col2 = st.columns([3, 1])
        with f_col1:
            selected_statuses = st.multiselect(
                "Filter by status",
                options=all_statuses,
                default=all_statuses,
                format_func=lambda s: status_labels.get(s, s),
                label_visibility="collapsed",
            )
        with f_col2:
            st.caption(f"{len([c for c in campaigns if c['status'] in (selected_statuses or all_statuses)])} campaigns shown")

        filtered = [c for c in campaigns if c['status'] in (selected_statuses or all_statuses)]

        h0, h1, h2, h3, h4, h5, h6, h7 = st.columns([3, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1])
        for col, lbl in zip(
            [h0, h1, h2, h3, h4, h5, h6, h7],
            ['Campaign', 'Impressions', 'Reach', 'Results', 'Clicks', 'Link Clicks', 'Cost', 'Status']
        ):
            col.markdown(
                f"<p style='font-size:11px;font-weight:800;color:{theme['text2']};"
                f"text-transform:uppercase;letter-spacing:0.6px;margin:0 0 8px 0'>{lbl}</p>",
                unsafe_allow_html=True
            )

        for camp in filtered:
            spend_pct = camp['spend'] / total_spend * 100 if total_spend else 0
            status_map = {
                'ACTIVE': ('🟢', 'badge-active'),
                'PAUSED': ('🟡', 'badge-paused'),
            }
            s_ico, badge_cls = status_map.get(camp['status'], ('⚫', 'badge-paused'))

            with st.expander(
                f"{s_ico} **{camp['name']}**"
                f"   ·   Impr: {camp['impressions']:,}"
                f"   ·   Reach: {camp['reach']:,}"
                f"   ·   {camp['result_label']}: {camp['result']:,}"
                f"   ·   Clicks: {camp['clicks']:,}"
                f"   ·   Link Clicks: {camp['link_clicks']:,}"
                f"   ·   Cost: {camp['spend']:,.0f}"
                f"   ·   CPR: {camp['cpr']:.2f}"
            ):
                m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
                m1.metric("Impressions",  f"{camp['impressions']:,}")
                m2.metric("Reach",        f"{camp['reach']:,}")
                m3.metric(camp['result_label'], f"{camp['result']:,}")
                m4.metric("Clicks",       f"{camp['clicks']:,}")
                m5.metric("Link Clicks",  f"{camp['link_clicks']:,}")
                m6.metric("Cost",         f"{camp['spend']:,.2f}")
                m7.metric("CPR",          f"{camp['cpr']:.2f}")

                st.markdown(
                    f"<p style='margin:8px 0 3px 0; font-size:12px; color:{theme['text2']}'>"
                    f"<b>Objective:</b> {camp['objective']} &nbsp;·&nbsp; "
                    f"<span class='{badge_cls}'>{camp['status']}</span> &nbsp;·&nbsp; "
                    f"<b>{spend_pct:.1f}%</b> of total spend</p>"
                    f"<div class='spend-bar-bg'>"
                    f"<div class='spend-bar-fill' "
                    f"style='width:{min(spend_pct,100):.1f}%;background:{acct_color}'></div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    f"<div class='sec-hdr' style='margin-top:16px'>Ad Sets</div>",
                    unsafe_allow_html=True
                )

                with st.spinner("Loading ad sets..."):
                    adsets = fetch_adsets(camp['id'], camp['objective_raw'], since_s, until_s)

                if not adsets:
                    st.caption("No ad sets with spend in this period.")
                else:
                    for adset in adsets:
                        a_ico = "🟢" if adset['status'] == 'ACTIVE' else "🟡"
                        with st.expander(
                            f"{a_ico} **{adset['name']}**"
                            f"   ·   Reach: {adset['reach']:,}"
                            f"   ·   Results: {adset['result']:,}"
                            f"   ·   Clicks: {adset['clicks']:,}"
                            f"   ·   Link Clicks: {adset['link_clicks']:,}"
                            f"   ·   Cost: {adset['spend']:,.0f}"
                            f"   ·   CPR: {adset['cpr']:.2f}"
                        ):
                            a1, a2, a3, a4, a5, a6, a7 = st.columns(7)
                            a1.metric("Impressions", f"{adset['impressions']:,}")
                            a2.metric("Reach",       f"{adset['reach']:,}")
                            a3.metric("Results",     f"{adset['result']:,}")
                            a4.metric("Clicks",      f"{adset['clicks']:,}")
                            a5.metric("Link Clicks", f"{adset['link_clicks']:,}")
                            a6.metric("Cost",        f"{adset['spend']:,.2f}")
                            a7.metric("CPR",         f"{adset['cpr']:.2f}")

                            st.markdown(
                                f"<div class='sec-hdr'>Ads</div>",
                                unsafe_allow_html=True
                            )

                            with st.spinner("Loading ads..."):
                                ads = fetch_ads(adset['id'], camp['objective_raw'], since_s, until_s)

                            if not ads:
                                st.caption("No ads with spend in this period.")
                            else:
                                df = pd.DataFrame([{
                                    '':            '🟢' if a['status'] == 'ACTIVE' else '🟡',
                                    'Ad Name':     a['name'],
                                    'Impr.':       a['impressions'],
                                    'Reach':       a['reach'],
                                    'Results':     a['result'],
                                    'Clicks':      a['clicks'],
                                    'Link Clicks': a['link_clicks'],
                                    'Cost':        a['spend'],
                                    'CPR':         a['cpr'],
                                    'CPM':         a['cpm'],
                                } for a in ads])
                                st.dataframe(
                                    df,
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config={
                                        '':            st.column_config.TextColumn(width=40),
                                        'Impr.':       st.column_config.NumberColumn(format='%d'),
                                        'Reach':       st.column_config.NumberColumn(format='%d'),
                                        'Results':     st.column_config.NumberColumn(format='%d'),
                                        'Clicks':      st.column_config.NumberColumn(format='%d'),
                                        'Link Clicks': st.column_config.NumberColumn(format='%d'),
                                        'Cost':        st.column_config.NumberColumn(format='%.2f'),
                                        'CPR':         st.column_config.NumberColumn(format='%.2f'),
                                        'CPM':         st.column_config.NumberColumn(format='%.2f'),
                                    }
                                )

# ── CHARTS ────────────────────────────────────────────────────────────────────
with tab_chart:
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    with_spend = [c for c in campaigns if c['spend'] > 0]

    if not with_spend:
        st.info("No spend data to chart for this period.")
    else:
        names_short = [(c['name'][:28] + '…') if len(c['name']) > 28 else c['name']
                       for c in with_spend]

        bg   = theme['card']
        txt  = theme['text']
        grid = theme['border']
        plot_layout = dict(
            paper_bgcolor=bg, plot_bgcolor=bg,
            font=dict(color=txt, size=12),
            margin=dict(l=10, r=10, t=40, b=10),
            xaxis=dict(gridcolor=grid, linecolor=grid),
            yaxis=dict(gridcolor=grid, linecolor=grid),
            showlegend=False,
        )

        ch1, ch2 = st.columns(2)

        with ch1:
            fig = go.Figure(go.Bar(
                x=names_short,
                y=[c['spend'] for c in with_spend],
                marker_color=acct_color,
                text=[f"{c['spend']:,.0f}" for c in with_spend],
                textposition='outside',
            ))
            fig.update_layout(**plot_layout, title="💰 Cost by Campaign", height=320)
            st.plotly_chart(fig, use_container_width=True)

        with ch2:
            avg_cpr_chart = (sum(c['cpr'] for c in with_spend if c['cpr'] > 0)
                             / max(len([c for c in with_spend if c['cpr'] > 0]), 1))
            cpr_colors = [
                '#EF4444' if c['cpr'] > avg_cpr_chart * 1.5
                else '#22C55E' if c['cpr'] < avg_cpr_chart * 0.7
                else acct_color
                for c in with_spend
            ]
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=names_short,
                y=[c['cpr'] for c in with_spend],
                marker_color=cpr_colors,
                text=[f"{c['cpr']:.2f}" for c in with_spend],
                textposition='outside',
            ))
            fig2.add_hline(
                y=avg_cpr_chart, line_dash='dash',
                line_color='#94A3B8', line_width=1.5,
                annotation_text=f"Avg: {avg_cpr_chart:.2f}",
                annotation_font_color='#94A3B8',
            )
            fig2.update_layout(**plot_layout,
                               title="📉 CPR by Campaign (🔴 high · 🟢 low · avg line)",
                               height=320)
            st.plotly_chart(fig2, use_container_width=True)

        ch3, ch4 = st.columns(2)

        with ch3:
            fig3 = go.Figure(go.Bar(
                x=names_short,
                y=[c['reach'] for c in with_spend],
                marker_color='#A78BFA',
                text=[f"{c['reach']:,}" for c in with_spend],
                textposition='outside',
            ))
            fig3.update_layout(**plot_layout, title="👥 Reach by Campaign", height=320)
            st.plotly_chart(fig3, use_container_width=True)

        with ch4:
            nr = [c for c in with_spend if c['result'] > 0]
            if nr:
                fig4 = go.Figure(go.Bar(
                    x=[(c['name'][:28]+'…') if len(c['name'])>28 else c['name'] for c in nr],
                    y=[c['result'] for c in nr],
                    marker_color='#22C55E',
                    text=[str(c['result']) for c in nr],
                    textposition='outside',
                ))
                fig4.update_layout(**plot_layout, title="🎯 Results by Campaign", height=320)
                st.plotly_chart(fig4, use_container_width=True)
            else:
                st.info("No results data for this period.")

        st.markdown(f"<p class='sec-hdr'>Full Summary</p>", unsafe_allow_html=True)
        summary_df = pd.DataFrame([{
            'Status':      '🟢' if c['status'] == 'ACTIVE' else '🟡',
            'Campaign':    c['name'],
            'Impressions': c['impressions'],
            'Reach':       c['reach'],
            'Results':     c['result'],
            'Clicks':      c['clicks'],
            'Link Clicks': c['link_clicks'],
            'Cost':        c['spend'],
            'CPR':         c['cpr'],
            'CPM':         c['cpm'],
            'CTR%':        round(c['link_clicks']/c['impressions']*100, 2) if c['impressions'] else 0,
        } for c in with_spend])
        st.dataframe(
            summary_df, use_container_width=True, hide_index=True,
            column_config={
                'Status':      st.column_config.TextColumn(width=55),
                'Impressions': st.column_config.NumberColumn(format='%d'),
                'Reach':       st.column_config.NumberColumn(format='%d'),
                'Results':     st.column_config.NumberColumn(format='%d'),
                'Clicks':      st.column_config.NumberColumn(format='%d'),
                'Link Clicks': st.column_config.NumberColumn(format='%d'),
                'Cost':        st.column_config.NumberColumn(format='%.2f'),
                'CPR':         st.column_config.NumberColumn(format='%.2f'),
                'CPM':         st.column_config.NumberColumn(format='%.2f'),
                'CTR%':        st.column_config.NumberColumn(format='%.2f'),
            }
        )

# ── RECOMMENDATIONS ───────────────────────────────────────────────────────────
with tab_rec:
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    recs = get_recommendations(campaigns)

    counts = {'error': 0, 'warning': 0, 'success': 0, 'info': 0}
    for level, _ in recs:
        counts[level] = counts.get(level, 0) + 1

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("🔴 Critical",      counts['error'])
    s2.metric("🟡 Warnings",      counts['warning'])
    s3.metric("🟢 Opportunities", counts['success'])
    s4.metric("ℹ️ Info",          counts['info'])

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    if not recs:
        st.info("No recommendations available.")
    else:
        for level, msg in recs:
            if level == 'error':     st.error(msg)
            elif level == 'warning': st.warning(msg)
            elif level == 'success': st.success(msg)
            else:                    st.info(msg)

# ── FOOTER ────────────────────────────────────────────────────────────────────
st.markdown(
    f"<p style='text-align:center; color:{theme['text2']}; font-size:12px; margin-top:2rem'>"
    f"Auto-refreshes every 5 min &nbsp;·&nbsp; Meta Ads API &nbsp;·&nbsp; "
    f"{date.today().strftime('%d %b %Y')}</p>",
    unsafe_allow_html=True
)
