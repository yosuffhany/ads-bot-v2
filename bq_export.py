"""
Meta Ads → BigQuery exporter
Tables: unified | balances | daily
unified has level=campaign/adset/ad rows, all with actual date field.
"""
import os, requests
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

BALANCE_SCHEMA = [
    bigquery.SchemaField('date_updated', 'DATE'),
    bigquery.SchemaField('account',      'STRING'),
    bigquery.SchemaField('balance',      'FLOAT'),
    bigquery.SchemaField('currency',     'STRING'),
    bigquery.SchemaField('display',      'STRING'),
]

DAILY_SCHEMA = [
    bigquery.SchemaField('date',        'DATE'),
    bigquery.SchemaField('account',     'STRING'),
    bigquery.SchemaField('spend',       'FLOAT'),
    bigquery.SchemaField('impressions', 'INTEGER'),
    bigquery.SchemaField('reach',       'INTEGER'),
    bigquery.SchemaField('link_clicks', 'INTEGER'),
    bigquery.SchemaField('purchases',   'INTEGER'),
]

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
]

# ── META API HELPERS ──────────────────────────────────────────────────────────

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

    msg_action = next((a for a in actions if a['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), None)
    messages   = int(float(msg_action['value'])) if msg_action else 0
    msg_cost   = next((c for c in costs if c['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), None)
    cost_per_message = round(float(msg_cost['value']) if msg_cost else (spend / messages if messages else 0), 2)

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

    # Detect actual conversion type from actions
    action_types = {a['action_type'] for a in actions}

    has_messages    = messages > 0
    has_leads       = any(a in action_types for a in ['lead', 'onsite_conversion.lead_grouped'])
    has_purchases   = purchases > 0
    has_page_likes  = 'like' in action_types
    has_video_views = 'video_view' in action_types
    has_post_engage = 'post_engagement' in action_types
    has_app_install = 'app_install' in action_types

    if obj == 'OUTCOME_AWARENESS':
        objective_label = 'Awareness'
    elif obj in ('OUTCOME_REACH', 'REACH'):
        objective_label = 'Reach'
    elif obj == 'OUTCOME_TRAFFIC':
        if has_messages:
            objective_label = 'Messages (Traffic)'
        else:
            objective_label = 'Traffic'
    elif obj == 'OUTCOME_ENGAGEMENT':
        if has_messages:
            objective_label = 'Messages'
        elif has_page_likes:
            objective_label = 'Page Likes'
        elif has_video_views:
            objective_label = 'Video Views'
        elif has_post_engage:
            objective_label = 'Post Engagement'
        else:
            objective_label = 'Engagement'
    elif obj == 'OUTCOME_LEADS':
        if has_messages:
            objective_label = 'Messages (Leads)'
        else:
            objective_label = 'Leads'
    elif obj == 'OUTCOME_SALES':
        if has_messages:
            objective_label = 'Messages (Sales)'
        elif has_purchases:
            objective_label = 'Sales'
        else:
            objective_label = 'Conversions'
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

def fetch_campaigns(account_id):
    tr = f'{{"since":"{SINCE}","until":"{UNTIL}"}}'
    try:
        r  = requests.get(
            f'https://graph.facebook.com/v19.0/{account_id}/campaigns',
            params={
                'access_token': TOKEN,
                'fields': f'id,name,objective,status,created_time,insights.time_range({tr}){{{INSIGHTS_FIELDS}}}',
                'limit': 200,
            }
        )
        r.raise_for_status()
        out = []
        for c in r.json().get('data', []):
            ins  = (c.get('insights', {}).get('data') or [{}])[0]
            data = parse_insights(ins, c.get('objective', ''))
            ct = c.get('created_time', '')
            if ct: ct = ct[:19].replace('T', ' ')
            data.update({'id': c['id'], 'name': c['name'], 'status': c.get('status', ''),
                         'created_time': ct, 'objective_raw': c.get('objective', '')})
            out.append(data)
        return sorted(out, key=lambda x: x['spend'], reverse=True)
    except Exception as e:
        print(f'  ! skipping campaigns for {account_id}: {e}')
        return []

def fetch_adsets(campaign_id, obj_raw):
    tr = f'{{"since":"{SINCE}","until":"{UNTIL}"}}'
    try:
        r  = requests.get(
            f'https://graph.facebook.com/v19.0/{campaign_id}/adsets',
            params={
                'access_token': TOKEN,
                'fields': f'id,name,status,insights.time_range({tr}){{{INSIGHTS_FIELDS}}}',
                'limit': 200,
            }
        )
        r.raise_for_status()
        out = []
        for a in r.json().get('data', []):
            if not a.get('name', '').strip():
                continue
            ins  = (a.get('insights', {}).get('data') or [{}])[0]
            data = parse_insights(ins, obj_raw)
            data.update({'id': a['id'], 'name': a['name'], 'status': a.get('status', '')})
            out.append(data)
        return sorted(out, key=lambda x: x['spend'], reverse=True)
    except Exception as e:
        print(f'  ! skipping adsets for {campaign_id}: {e}')
        return []

def fetch_campaigns_daily(account_id):
    try:
        r = requests.get(
            f'https://graph.facebook.com/v19.0/{account_id}/insights',
            params={
                'access_token': TOKEN,
                'time_range': f'{{"since":"{SINCE}","until":"{UNTIL}"}}',
                'time_increment': 1,
                'level': 'campaign',
                'fields': f'date_start,campaign_id,campaign_name,objective,{INSIGHTS_FIELDS}',
                'limit': 500,
            }
        )
        r.raise_for_status()
        rows = []
        for row in r.json().get('data', []):
            ins  = parse_insights(row, row.get('objective', ''))
            rows.append({
                'date':         row['date_start'],
                'campaign_id':  row.get('campaign_id', ''),
                'campaign_name': row.get('campaign_name', ''),
                'objective':    ins['objective'],
                'status':       '',
                'spend':        ins['spend'], 'impressions': ins['impressions'],
                'reach':        ins['reach'], 'clicks': ins['clicks'],
                'link_clicks':  ins['link_clicks'], 'cpm': ins['cpm'],
                'results':      ins['result'], 'result_label': ins['result_label'],
                'cpr':          ins['cpr'], 'purchases': ins['purchases'],
                'messages':     ins['messages'], 'cost_per_message': ins['cost_per_message'],
            })
        return rows
    except Exception as e:
        print(f'  ! fetch_campaigns_daily error: {e}')
        return []

def fetch_adsets_daily(account_id):
    try:
        r = requests.get(
            f'https://graph.facebook.com/v19.0/{account_id}/insights',
            params={
                'access_token': TOKEN,
                'time_range': f'{{"since":"{SINCE}","until":"{UNTIL}"}}',
                'time_increment': 1,
                'level': 'adset',
                'fields': f'date_start,campaign_id,campaign_name,adset_id,adset_name,objective,{INSIGHTS_FIELDS}',
                'limit': 500,
            }
        )
        r.raise_for_status()
        rows = []
        for row in r.json().get('data', []):
            if not row.get('adset_name', '').strip():
                continue
            ins = parse_insights(row, row.get('objective', ''))
            rows.append({
                'date':          row['date_start'],
                'campaign_id':   row.get('campaign_id', ''),
                'campaign_name': row.get('campaign_name', ''),
                'adset_id':      row.get('adset_id', ''),
                'adset_name':    row.get('adset_name', ''),
                'objective':     ins['objective'],
                'spend':         ins['spend'], 'impressions': ins['impressions'],
                'reach':         ins['reach'], 'clicks': ins['clicks'],
                'link_clicks':   ins['link_clicks'], 'cpm': ins['cpm'],
                'results':       ins['result'], 'result_label': ins['result_label'],
                'cpr':           ins['cpr'], 'purchases': ins['purchases'],
                'messages':      ins['messages'], 'cost_per_message': ins['cost_per_message'],
            })
        return rows
    except Exception as e:
        print(f'  ! fetch_adsets_daily error: {e}')
        return []

def fetch_ads(adset_id, obj_raw):
    tr = f'{{"since":"{SINCE}","until":"{UNTIL}"}}'
    try:
        r = requests.get(
            f'https://graph.facebook.com/v19.0/{adset_id}/ads',
            params={
                'access_token': TOKEN,
                'fields': f'id,name,status,creative{{thumbnail_url,image_url}},insights.time_range({tr}){{{INSIGHTS_FIELDS}}}',
                'limit': 200,
            }
        )
        r.raise_for_status()
        out = []
        for a in r.json().get('data', []):
            ins       = (a.get('insights', {}).get('data') or [{}])[0]
            data      = parse_insights(ins, obj_raw)
            creative  = a.get('creative', {})
            thumbnail = creative.get('thumbnail_url') or creative.get('image_url') or ''
            data.update({'id': a['id'], 'name': a['name'], 'status': a.get('status', ''), 'thumbnail_url': thumbnail})
            out.append(data)
        return sorted(out, key=lambda x: x['spend'], reverse=True)
    except Exception:
        return []

def fetch_balance(account_id):
    import re
    r = requests.get(
        f'https://graph.facebook.com/v19.0/{account_id}',
        params={'access_token': TOKEN, 'fields': 'funding_source_details,currency'}
    )
    d = r.json()
    currency = d.get('currency', 'EGP')
    display  = d.get('funding_source_details', {}).get('display_string', '')
    match    = re.search(r'[\d,]+\.?\d*', display.replace(',', ''))
    balance  = round(float(match.group().replace(',', '')), 2) if match else 0.0
    return balance, currency, display

def fetch_daily(account_id):
    r = requests.get(
        f'https://graph.facebook.com/v19.0/{account_id}/insights',
        params={
            'access_token': TOKEN,
            'time_range': f'{{"since":"{SINCE}","until":"{UNTIL}"}}',
            'time_increment': 1,
            'fields': 'date_start,spend,impressions,inline_link_clicks,reach,actions',
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
            'date': row['date_start'],
            'impressions': int(row.get('impressions', 0)),
            'reach':       int(row.get('reach', 0)),
            'link_clicks': int(row.get('inline_link_clicks', 0)),
            'spend':       round(float(row.get('spend', 0)), 2),
            'purchases':   purchases,
        })
    return sorted(rows, key=lambda x: x['date'])

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
    """Batch load rows — free tier compatible, overwrites table each run."""
    if not rows:
        return
    table_ref = f'{GCP_PROJECT}.{BQ_DATASET}.{table_name}'
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_json(rows, table_ref, job_config=job_config)
    job.result()  # wait for completion

# ── MAIN ──────────────────────────────────────────────────────────────────────

def _unified_row(level, acc_name, row, c=None, a=None, ad=None, status_map=None):
    """Build a unified table row for any level."""
    base = {
        'date': row.get('date', TODAY), 'date_updated': TODAY, 'account': acc_name,
        'level': level,
        'campaign_id':     row.get('campaign_id', c['id'] if c else ''),
        'campaign_name':   row.get('campaign_name', c['name'] if c else ''),
        'campaign_status': (status_map or {}).get(row.get('campaign_id', c['id'] if c else ''), c['status'] if c else ''),
        'objective':       row.get('objective', c['objective'] if c else ''),
        'adset_id':        row.get('adset_id', a['id'] if a else ''),
        'adset_name':      row.get('adset_name', a['name'] if a else ''),
        'adset_status':    a['status'] if a else '',
        'ad_id':           ad['id'] if ad else '',
        'ad_name':         ad['name'] if ad else '',
        'ad_status':       ad['status'] if ad else '',
        'thumbnail_url':   ad['thumbnail_url'] if ad else '',
    }
    src = ad or row
    base.update({
        'spend': src.get('spend', 0), 'impressions': src.get('impressions', 0),
        'reach': src.get('reach', 0), 'clicks': src.get('clicks', 0),
        'link_clicks': src.get('link_clicks', 0), 'cpm': src.get('cpm', 0),
        'results': src.get('results', src.get('result', 0)),
        'result_label': src.get('result_label', 'Results'),
        'cpr': src.get('cpr', 0), 'purchases': src.get('purchases', 0),
        'messages': src.get('messages', 0), 'cost_per_message': src.get('cost_per_message', 0),
    })
    return base


def main():
    client = get_bq_client()
    ensure_dataset(client)

    unified_rows  = []
    balances_rows = []
    daily_rows    = []

    for acc_name, acc_id in ACCOUNTS.items():
        print(f'Fetching {acc_name}...')

        # Need campaign list for status and to iterate adsets→ads
        campaigns  = fetch_campaigns(acc_id)
        status_map = {c['id']: c['status'] for c in campaigns}

        # Campaign rows: daily (date-responsive)
        for row in fetch_campaigns_daily(acc_id):
            unified_rows.append(_unified_row('campaign', acc_name, row, status_map=status_map))

        # Adset rows: daily (date-responsive)
        for row in fetch_adsets_daily(acc_id):
            unified_rows.append(_unified_row('adset', acc_name, row, status_map=status_map))

        # Ad rows: aggregated over SINCE→UNTIL (date=TODAY)
        for c in campaigns:
            adsets = fetch_adsets(c['id'], c['objective_raw'])
            for a in adsets:
                ads = fetch_ads(a['id'], c['objective_raw'])
                for ad in ads:
                    unified_rows.append(_unified_row('ad', acc_name, {'date': TODAY}, c=c, a=a, ad=ad))

        balance, currency, display = fetch_balance(acc_id)
        balances_rows.append({
            'date_updated': TODAY, 'account': acc_name,
            'balance': balance, 'currency': currency, 'display': display,
        })

        for row in fetch_daily(acc_id):
            daily_rows.append({
                'date': row['date'], 'account': acc_name,
                'spend': row['spend'], 'impressions': row['impressions'],
                'reach': row['reach'], 'link_clicks': row['link_clicks'],
                'purchases': row['purchases'],
            })

    load_table(client, 'unified', UNIFIED_SCHEMA, unified_rows)
    print(f'  OK unified: {len(unified_rows)} rows')

    load_table(client, 'balances', BALANCE_SCHEMA, balances_rows)
    print(f'  OK balances: {len(balances_rows)} rows')

    load_table(client, 'daily', DAILY_SCHEMA, daily_rows)
    print(f'  OK daily: {len(daily_rows)} rows')

    print('\nDone! unified=%d balances=%d daily=%d' % (len(unified_rows), len(balances_rows), len(daily_rows)))

if __name__ == '__main__':
    main()
