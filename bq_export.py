"""
Meta Ads -> BigQuery exporter
Tables: unified  (single source of truth)
level field: account / campaign / adset / ad / balance
All charts in Looker Studio use one data source.
"""
import os, re, requests
from datetime import date, timedelta
from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2.service_account import Credentials

load_dotenv()

TOKEN            = os.getenv('LONG_LIVED_TOKEN')
CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'google_credentials.json')
GCP_PROJECT      = os.getenv('GCP_PROJECT_ID')
BQ_DATASET       = os.getenv('BQ_DATASET', 'meta_ads')

ACCOUNTS = {
    'Mall':    'act_2001687506868513',
    'BSQ':     'act_841897980911694',
    'Kemet':   'act_345674018149436',
    'Al Adel': 'act_1392109118185589',
}

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

SINCE = str(date.today() - timedelta(days=90))
UNTIL = str(date.today())
TODAY = str(date.today())

# ── SCHEMAS ───────────────────────────────────────────────────────────────────



UNIFIED_SCHEMA = [
    bigquery.SchemaField('date',             'DATE'),
    bigquery.SchemaField('date_updated',     'DATE'),
    bigquery.SchemaField('account',          'STRING'),
    bigquery.SchemaField('level',            'STRING'),   # campaign / adset / ad
    bigquery.SchemaField('campaign_id',      'STRING'),
    bigquery.SchemaField('campaign_name',    'STRING'),
    bigquery.SchemaField('campaign_status',  'STRING'),
    bigquery.SchemaField('objective',        'STRING'),
    bigquery.SchemaField('adset_id',         'STRING'),
    bigquery.SchemaField('adset_name',       'STRING'),
    bigquery.SchemaField('adset_status',     'STRING'),
    bigquery.SchemaField('ad_id',            'STRING'),
    bigquery.SchemaField('ad_name',          'STRING'),
    bigquery.SchemaField('ad_status',        'STRING'),
    bigquery.SchemaField('thumbnail_url',    'STRING'),
    bigquery.SchemaField('spend',            'FLOAT'),
    bigquery.SchemaField('impressions',      'INTEGER'),
    bigquery.SchemaField('reach',            'INTEGER'),
    bigquery.SchemaField('clicks',           'INTEGER'),
    bigquery.SchemaField('link_clicks',      'INTEGER'),
    bigquery.SchemaField('cpm',              'FLOAT'),
    bigquery.SchemaField('results',          'INTEGER'),
    bigquery.SchemaField('result_label',     'STRING'),
    bigquery.SchemaField('cpr',              'FLOAT'),
    bigquery.SchemaField('purchases',        'INTEGER'),
    bigquery.SchemaField('messages',         'INTEGER'),
    bigquery.SchemaField('cost_per_message', 'FLOAT'),
    bigquery.SchemaField('balance',          'FLOAT'),
    bigquery.SchemaField('currency',         'STRING'),
]

# ── HELPERS ───────────────────────────────────────────────────────────────────

def paginate(url, params):
    """Fetch all pages from a Meta Graph API endpoint."""
    rows = []
    while url:
        r = requests.get(url, params=params)
        r.raise_for_status()
        body = r.json()
        rows.extend(body.get('data', []))
        url    = body.get('paging', {}).get('next')
        params = None   # next URL already has all params baked in
    return rows

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

    msg_action = next((a for a in actions
                       if a['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), None)
    messages   = int(float(msg_action['value'])) if msg_action else 0
    msg_cost   = next((c for c in costs
                       if c['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), None)
    cost_per_message = round(
        float(msg_cost['value']) if msg_cost else (spend / messages if messages else 0), 2
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

    action_types  = {a['action_type'] for a in actions}
    has_messages  = messages > 0
    has_purchases = purchases > 0
    has_page_likes  = 'like' in action_types
    has_video_views = 'video_view' in action_types
    has_post_engage = 'post_engagement' in action_types

    if obj == 'OUTCOME_AWARENESS':
        objective_label = 'Awareness'
    elif obj in ('OUTCOME_REACH', 'REACH'):
        objective_label = 'Reach'
    elif obj == 'OUTCOME_TRAFFIC':
        objective_label = 'Messages (Traffic)' if has_messages else 'Traffic'
    elif obj == 'OUTCOME_ENGAGEMENT':
        if has_messages:        objective_label = 'Messages'
        elif has_page_likes:    objective_label = 'Page Likes'
        elif has_video_views:   objective_label = 'Video Views'
        elif has_post_engage:   objective_label = 'Post Engagement'
        else:                   objective_label = 'Engagement'
    elif obj == 'OUTCOME_LEADS':
        objective_label = 'Messages (Leads)' if has_messages else 'Leads'
    elif obj == 'OUTCOME_SALES':
        if has_messages:        objective_label = 'Messages (Sales)'
        elif has_purchases:     objective_label = 'Sales'
        else:                   objective_label = 'Conversions'
    elif obj == 'OUTCOME_APP_PROMOTION':
        objective_label = 'App Installs'
    else:
        objective_label = obj.replace('OUTCOME_', '').title()

    return {
        'objective': objective_label,
        'result': result, 'result_label': result_label, 'cpr': cpr,
        'spend': spend, 'cpm': cpm, 'impressions': impressions,
        'clicks': clicks, 'reach': reach, 'link_clicks': link_clicks,
        'purchases': purchases, 'messages': messages, 'cost_per_message': cost_per_message,
    }

# ── META API FETCHERS ─────────────────────────────────────────────────────────

def fetch_campaigns(account_id):
    tr = f'{{"since":"{SINCE}","until":"{UNTIL}"}}'
    try:
        rows = paginate(
            f'https://graph.facebook.com/v19.0/{account_id}/campaigns',
            {
                'access_token': TOKEN,
                'fields': f'id,name,objective,status,created_time,insights.time_range({tr}){{{INSIGHTS_FIELDS}}}',
                'limit': 200,
            }
        )
        out = []
        for c in rows:
            ins  = (c.get('insights', {}).get('data') or [{}])[0]
            data = parse_insights(ins, c.get('objective', ''))
            ct   = c.get('created_time', '')
            if ct: ct = ct[:19].replace('T', ' ')
            data.update({'id': c['id'], 'name': c['name'], 'status': c.get('status', ''),
                         'created_time': ct, 'objective_raw': c.get('objective', '')})
            out.append(data)
        return sorted(out, key=lambda x: x['spend'], reverse=True)
    except Exception as e:
        print(f'  ! campaigns error for {account_id}: {e}')
        return []

def fetch_adsets(campaign_id, obj_raw):
    tr = f'{{"since":"{SINCE}","until":"{UNTIL}"}}'
    try:
        rows = paginate(
            f'https://graph.facebook.com/v19.0/{campaign_id}/adsets',
            {
                'access_token': TOKEN,
                'fields': f'id,name,status,insights.time_range({tr}){{{INSIGHTS_FIELDS}}}',
                'limit': 200,
            }
        )
        out = []
        for a in rows:
            if not a.get('name', '').strip():
                continue
            ins  = (a.get('insights', {}).get('data') or [{}])[0]
            data = parse_insights(ins, obj_raw)
            data.update({'id': a['id'], 'name': a['name'], 'status': a.get('status', '')})
            out.append(data)
        return sorted(out, key=lambda x: x['spend'], reverse=True)
    except Exception as e:
        print(f'  ! adsets error for {campaign_id}: {e}')
        return []

def fetch_campaigns_daily(account_id):
    try:
        rows = paginate(
            f'https://graph.facebook.com/v19.0/{account_id}/insights',
            {
                'access_token': TOKEN,
                'time_range': f'{{"since":"{SINCE}","until":"{UNTIL}"}}',
                'time_increment': 1,
                'level': 'campaign',
                'fields': f'date_start,campaign_id,campaign_name,objective,{INSIGHTS_FIELDS}',
                'limit': 500,
            }
        )
        out = []
        for row in rows:
            ins = parse_insights(row, row.get('objective', ''))
            out.append({
                'date':          row['date_start'],
                'campaign_id':   row.get('campaign_id', ''),
                'campaign_name': row.get('campaign_name', ''),
                'objective':     ins['objective'],
                'spend':         ins['spend'],        'impressions': ins['impressions'],
                'reach':         ins['reach'],         'clicks':      ins['clicks'],
                'link_clicks':   ins['link_clicks'],   'cpm':         ins['cpm'],
                'results':       ins['result'],         'result_label': ins['result_label'],
                'cpr':           ins['cpr'],            'purchases':   ins['purchases'],
                'messages':      ins['messages'],       'cost_per_message': ins['cost_per_message'],
            })
        return out
    except Exception as e:
        print(f'  ! campaigns_daily error for {account_id}: {e}')
        return []

def fetch_adsets_daily(account_id):
    try:
        rows = paginate(
            f'https://graph.facebook.com/v19.0/{account_id}/insights',
            {
                'access_token': TOKEN,
                'time_range': f'{{"since":"{SINCE}","until":"{UNTIL}"}}',
                'time_increment': 1,
                'level': 'adset',
                'fields': f'date_start,campaign_id,campaign_name,adset_id,adset_name,objective,{INSIGHTS_FIELDS}',
                'limit': 500,
            }
        )
        out = []
        for row in rows:
            if not row.get('adset_name', '').strip():
                continue
            ins = parse_insights(row, row.get('objective', ''))
            out.append({
                'date':          row['date_start'],
                'campaign_id':   row.get('campaign_id', ''),
                'campaign_name': row.get('campaign_name', ''),
                'adset_id':      row.get('adset_id', ''),
                'adset_name':    row.get('adset_name', ''),
                'objective':     ins['objective'],
                'spend':         ins['spend'],        'impressions': ins['impressions'],
                'reach':         ins['reach'],         'clicks':      ins['clicks'],
                'link_clicks':   ins['link_clicks'],   'cpm':         ins['cpm'],
                'results':       ins['result'],         'result_label': ins['result_label'],
                'cpr':           ins['cpr'],            'purchases':   ins['purchases'],
                'messages':      ins['messages'],       'cost_per_message': ins['cost_per_message'],
            })
        return out
    except Exception as e:
        print(f'  ! adsets_daily error for {account_id}: {e}')
        return []

def fetch_ads(adset_id, obj_raw):
    tr = f'{{"since":"{SINCE}","until":"{UNTIL}"}}'
    try:
        rows = paginate(
            f'https://graph.facebook.com/v19.0/{adset_id}/ads',
            {
                'access_token': TOKEN,
                'fields': f'id,name,status,creative{{thumbnail_url,image_url}},insights.time_range({tr}){{{INSIGHTS_FIELDS}}}',
                'limit': 200,
            }
        )
        out = []
        for a in rows:
            ins      = (a.get('insights', {}).get('data') or [{}])[0]
            data     = parse_insights(ins, obj_raw)
            creative = a.get('creative', {})
            thumbnail = creative.get('thumbnail_url') or creative.get('image_url') or ''
            data.update({'id': a['id'], 'name': a['name'],
                         'status': a.get('status', ''), 'thumbnail_url': thumbnail})
            out.append(data)
        return sorted(out, key=lambda x: x['spend'], reverse=True)
    except Exception:
        return []

def fetch_balance(account_id):
    try:
        r = requests.get(
            f'https://graph.facebook.com/v19.0/{account_id}',
            params={'access_token': TOKEN, 'fields': 'funding_source_details,currency'}
        )
        r.raise_for_status()
        d        = r.json()
        currency = d.get('currency', 'EGP')
        display  = d.get('funding_source_details', {}).get('display_string', '')
        match    = re.search(r'[\d,]+\.?\d*', display.replace(',', ''))
        balance  = round(float(match.group().replace(',', '')), 2) if match else 0.0
        return balance, currency, display
    except Exception as e:
        print(f'  ! balance error for {account_id}: {e}')
        return 0.0, 'EGP', ''

def fetch_daily(account_id):
    try:
        rows = paginate(
            f'https://graph.facebook.com/v19.0/{account_id}/insights',
            {
                'access_token': TOKEN,
                'time_range': f'{{"since":"{SINCE}","until":"{UNTIL}"}}',
                'time_increment': 1,
                'fields': 'date_start,spend,impressions,inline_link_clicks,reach,actions',
            }
        )
        out = []
        for row in rows:
            actions   = row.get('actions', [])
            purchases = sum(int(float(a['value'])) for a in actions if a['action_type'] in PURCHASE_ACTIONS)
            msg_act   = next((a for a in actions
                              if a['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), None)
            messages  = int(float(msg_act['value'])) if msg_act else 0
            out.append({
                'date':        row['date_start'],
                'impressions': int(row.get('impressions', 0)),
                'reach':       int(row.get('reach', 0)),
                'link_clicks': int(row.get('inline_link_clicks', 0)),
                'spend':       round(float(row.get('spend', 0)), 2),
                'purchases':   purchases,
                'messages':    messages,
            })
        return sorted(out, key=lambda x: x['date'])
    except Exception as e:
        print(f'  ! daily error for {account_id}: {e}')
        return []

# ── BIGQUERY HELPERS ──────────────────────────────────────────────────────────

def get_bq_client():
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=['https://www.googleapis.com/auth/bigquery']
    )
    return bigquery.Client(project=GCP_PROJECT, credentials=creds)

def ensure_dataset(client):
    dataset_ref = f'{GCP_PROJECT}.{BQ_DATASET}'
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        client.create_dataset(bigquery.Dataset(dataset_ref))
        print(f'  Created dataset {BQ_DATASET}')

def load_table(client, table_name, schema, rows):
    """Batch load rows - free tier compatible, overwrites table each run."""
    if not rows:
        print(f'  SKIP {table_name}: no rows')
        return
    table_ref  = f'{GCP_PROJECT}.{BQ_DATASET}.{table_name}'
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_json(rows, table_ref, job_config=job_config)
    job.result()
    print(f'  OK {table_name}: {len(rows)} rows')

# ── MAIN ──────────────────────────────────────────────────────────────────────

def _unified_row(level, acc_name, row, c=None, a=None, ad=None, status_map=None):
    """Build a unified table row for any level."""
    cid = row.get('campaign_id', c['id'] if c else '')
    base = {
        'date':            row.get('date', TODAY),
        'date_updated':    TODAY,
        'account':         acc_name,
        'level':           level,
        'campaign_id':     cid,
        'campaign_name':   row.get('campaign_name', c['name'] if c else ''),
        'campaign_status': (status_map or {}).get(cid, c['status'] if c else ''),
        'objective':       row.get('objective', c['objective'] if c else ''),
        'adset_id':        row.get('adset_id',   a['id']   if a else ''),
        'adset_name':      row.get('adset_name', a['name'] if a else ''),
        'adset_status':    a['status'] if a else '',
        'ad_id':           ad['id']            if ad else '',
        'ad_name':         ad['name']          if ad else '',
        'ad_status':       ad['status']        if ad else '',
        'thumbnail_url':   ad['thumbnail_url'] if ad else '',
    }
    src = ad or row
    base.update({
        'spend':            src.get('spend', 0),
        'impressions':      src.get('impressions', 0),
        'reach':            src.get('reach', 0),
        'clicks':           src.get('clicks', 0),
        'link_clicks':      src.get('link_clicks', 0),
        'cpm':              src.get('cpm', 0),
        'results':          src.get('results', src.get('result', 0)),
        'result_label':     src.get('result_label', 'Results'),
        'cpr':              src.get('cpr', 0),
        'purchases':        src.get('purchases', 0),
        'messages':         src.get('messages', 0),
        'cost_per_message': src.get('cost_per_message', 0),
        'balance':          0.0,
        'currency':         '',
    })
    return base


def main():
    client = get_bq_client()
    ensure_dataset(client)

    unified_rows = []

    for acc_name, acc_id in ACCOUNTS.items():
        print(f'Fetching {acc_name}...')

        # Campaign list: needed for status map and iterating ads
        campaigns  = fetch_campaigns(acc_id)
        status_map = {c['id']: c['status'] for c in campaigns}
        print(f'  campaigns: {len(campaigns)}')

        # level=account — daily account totals (for trend charts)
        for row in fetch_daily(acc_id):
            unified_rows.append({
                'date': row['date'], 'date_updated': TODAY,
                'account': acc_name, 'level': 'account',
                'campaign_id': '', 'campaign_name': '', 'campaign_status': '',
                'objective': '', 'adset_id': '', 'adset_name': '', 'adset_status': '',
                'ad_id': '', 'ad_name': '', 'ad_status': '', 'thumbnail_url': '',
                'spend': row['spend'], 'impressions': row['impressions'],
                'reach': row['reach'], 'clicks': 0,
                'link_clicks': row['link_clicks'], 'cpm': 0.0,
                'results': 0, 'result_label': '', 'cpr': 0.0,
                'purchases': row['purchases'], 'messages': row['messages'],
                'cost_per_message': 0.0,
                'balance': 0.0, 'currency': '',
            })

        # level=campaign — daily rows (respond to date filter)
        camp_daily = fetch_campaigns_daily(acc_id)
        print(f'  campaigns_daily: {len(camp_daily)} rows')
        for row in camp_daily:
            unified_rows.append(_unified_row('campaign', acc_name, row, status_map=status_map))

        # level=adset — daily rows (respond to date filter)
        adset_daily = fetch_adsets_daily(acc_id)
        print(f'  adsets_daily: {len(adset_daily)} rows')
        for row in adset_daily:
            unified_rows.append(_unified_row('adset', acc_name, row, status_map=status_map))

        # level=ad — aggregated over full SINCE->UNTIL range
        ad_count = 0
        for c in campaigns:
            adsets = fetch_adsets(c['id'], c['objective_raw'])
            for a in adsets:
                for ad in fetch_ads(a['id'], c['objective_raw']):
                    unified_rows.append(_unified_row('ad', acc_name, {'date': TODAY}, c=c, a=a, ad=ad))
                    ad_count += 1
        print(f'  ads: {ad_count}')

        # level=balance — current account balance
        balance, currency, display = fetch_balance(acc_id)
        unified_rows.append({
            'date': TODAY, 'date_updated': TODAY,
            'account': acc_name, 'level': 'balance',
            'campaign_id': '', 'campaign_name': '', 'campaign_status': '',
            'objective': display, 'adset_id': '', 'adset_name': '', 'adset_status': '',
            'ad_id': '', 'ad_name': '', 'ad_status': '', 'thumbnail_url': '',
            'spend': 0.0, 'impressions': 0, 'reach': 0, 'clicks': 0,
            'link_clicks': 0, 'cpm': 0.0, 'results': 0, 'result_label': '',
            'cpr': 0.0, 'purchases': 0, 'messages': 0, 'cost_per_message': 0.0,
            'balance': balance, 'currency': currency,
        })

    load_table(client, 'unified', UNIFIED_SCHEMA, unified_rows)
    print('Done.')

if __name__ == '__main__':
    main()
