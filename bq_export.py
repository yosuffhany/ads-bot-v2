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
    'Mall':         'act_2001687506868513',
    'BSQ':          'act_841897980911694',
    'Kemet':        'act_345674018149436',
    'Al Adel':      'act_1392109118185589',
    'Sedra':        'act_1303633554699002',
    'Mas-Pipe':     'act_1774284989787459',
    'ShowPink':     'act_1803969103895553',
    'Belal Khier':  'act_1091777362163635',
    'Mohamed Essam':'act_325431983464353',
}

AWARENESS_OBJECTIVES = {'OUTCOME_AWARENESS', 'OUTCOME_REACH', 'REACH', 'AWARENESS'}
PURCHASE_ACTIONS = {'offsite_conversion.fb_pixel_purchase', 'onsite_conversion.purchase'}
INSIGHTS_FIELDS  = 'spend,cpm,reach,impressions,clicks,inline_link_clicks,actions,cost_per_action_type,results,cost_per_result'

RESULT_INDICATORS = {
    # indicators returned by Meta results field
    'reach':                                                            'Reach',
    'total_profile_visits':                                             'Profile Visits',
    'page_visit_view':                                                  'Page Visits',
    'total_messaging_connection':                                       'Messages',
    'actions:onsite_conversion.messaging_conversation_started_7d':      'Messages',
    'onsite_conversion.messaging_conversation_started_7d':              'Messages',
    'offsite_conversion.fb_pixel_purchase':                             'Purchases',
    'onsite_conversion.purchase':                                       'Purchases',
    'onsite_conversion.lead_grouped':                                   'Leads',
    'lead':                                                             'Leads',
    'like':                                                             'Page Likes',
    'landing_page_view':                                                'Landing Page Views',
    'visit_instagram_profile':                                          'Profile Visits',
    'link_click':                                                       'Link Clicks',
    'video_view':                                                       'Video Views',
    'post_engagement':                                                  'Post Engagement',
    'page_engagement':                                                  'Page Engagement',
    'omni_add_to_cart':                                                 'Add to Cart',
    'omni_initiated_checkout':                                          'Initiated Checkout',
}

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

SINCE = str(date.today() - timedelta(days=90))
UNTIL = str(date.today())
TODAY = str(date.today())

# ── SCHEMAS ───────────────────────────────────────────────────────────────────



UNIFIED_SCHEMA = [
    bigquery.SchemaField('date',               'DATE'),
    bigquery.SchemaField('date_updated',       'DATE'),
    bigquery.SchemaField('account',            'STRING'),
    bigquery.SchemaField('level',              'STRING'),
    bigquery.SchemaField('campaign_id',        'STRING'),
    bigquery.SchemaField('campaign_name',      'STRING'),
    bigquery.SchemaField('campaign_status',    'STRING'),
    bigquery.SchemaField('objective',          'STRING'),
    bigquery.SchemaField('adset_id',           'STRING'),
    bigquery.SchemaField('adset_name',         'STRING'),
    bigquery.SchemaField('adset_status',       'STRING'),
    bigquery.SchemaField('ad_id',              'STRING'),
    bigquery.SchemaField('ad_name',            'STRING'),
    bigquery.SchemaField('ad_status',          'STRING'),
    bigquery.SchemaField('thumbnail_url',      'STRING'),
    # ── metrics ──────────────────────────────
    bigquery.SchemaField('spend',              'FLOAT'),
    bigquery.SchemaField('impressions',        'INTEGER'),
    bigquery.SchemaField('reach',              'INTEGER'),
    bigquery.SchemaField('clicks',             'INTEGER'),
    bigquery.SchemaField('link_clicks',        'INTEGER'),
    bigquery.SchemaField('results',            'INTEGER'),
    bigquery.SchemaField('result_label',       'STRING'),
    bigquery.SchemaField('purchases',          'INTEGER'),
    bigquery.SchemaField('messages',           'INTEGER'),
    bigquery.SchemaField('msg_spend',                'FLOAT'),   # spend attr. to messages (additive per level)
    bigquery.SchemaField('messages_camp',            'INTEGER'), # campaign-level only
    bigquery.SchemaField('msg_campaign_spend',       'FLOAT'),   # campaign-level only
    bigquery.SchemaField('awareness_spend',          'FLOAT'),   # all levels → tables
    bigquery.SchemaField('awareness_reach',          'INTEGER'), # all levels → tables
    bigquery.SchemaField('awareness_campaign_spend', 'FLOAT'),   # campaign-level only
    bigquery.SchemaField('awareness_reach_camp',     'INTEGER'), # campaign-level only
    bigquery.SchemaField('results_camp',             'INTEGER'), # campaign-level only
    bigquery.SchemaField('spend_camp',               'FLOAT'),   # campaign-level only (non-msg, non-awareness)
    bigquery.SchemaField('cost_per_result',          'FLOAT'),   # per-row smart cost
    bigquery.SchemaField('balance',                  'FLOAT'),
    bigquery.SchemaField('currency',                 'STRING'),
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
    msg_spend = round(cost_per_message * messages, 2)  # spend attributable to messages only

    if obj in AWARENESS_OBJECTIVES:
        result, result_label = reach, 'Reach'
        cpr = round(spend / (reach / 1000), 2) if reach else 0.0
    else:
        # Use Meta's results field (matches Ads Manager "Results" column)
        api_results  = ins.get('results', [])
        api_cpr_list = ins.get('cost_per_result', [])
        if api_results:
            r0           = api_results[0]
            raw_val      = r0.get('values', [{}])[0].get('value', 0)
            result       = int(float(raw_val))
            indicator    = r0.get('indicator', '')
            result_label = RESULT_INDICATORS.get(indicator, indicator or 'Results')
            c0           = api_cpr_list[0] if api_cpr_list else {}
            raw_cpr      = c0.get('values', [{}])[0].get('value', 0)
            cpr          = round(float(raw_cpr) if raw_cpr else (spend / result if result else 0), 2)
        else:
            # fallback: objective-based priority
            result, cpr, result_label = 0, 0.0, 'Results'
            priority = OBJECTIVE_PRIORITY.get(obj, list(RESULT_INDICATORS.keys()))
            for at in priority:
                act = next((a for a in actions if a['action_type'] == at), None)
                if act:
                    result = int(float(act['value']))
                    result_label = RESULT_INDICATORS.get(at, at)
                    cost = next((c for c in costs if c['action_type'] == at), None)
                    cpr  = round(float(cost['value']) if cost else (spend / result if result else 0), 2)
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
        'msg_spend': msg_spend,
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
                'msg_spend':     ins['msg_spend'],
            })
        return out
    except Exception as e:
        print(f'  ! campaigns_daily error for {account_id}: {e}')
        return []

def fetch_adsets_daily(account_id, since=None, until=None):
    since = since or SINCE
    until = until or UNTIL
    try:
        rows = paginate(
            f'https://graph.facebook.com/v19.0/{account_id}/insights',
            {
                'access_token': TOKEN,
                'time_range': f'{{"since":"{since}","until":"{until}"}}',
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
                'msg_spend':     ins['msg_spend'],
            })
        return out
    except Exception as e:
        err = str(e)
        if '500' in err or '400' in err:
            since_30 = str(date.today() - timedelta(days=30))
            since_7  = str(date.today() - timedelta(days=7))
            if since == SINCE:
                print(f'  ! adsets_daily retrying with 30 days for {account_id}')
                return fetch_adsets_daily(account_id, since=since_30, until=until)
            elif since == since_30:
                print(f'  ! adsets_daily retrying with 7 days for {account_id}')
                return fetch_adsets_daily(account_id, since=since_7, until=until)
        print(f'  ! adsets_daily error for {account_id}: {e}')
        return []

def fetch_ads_daily(account_id, since=None, until=None):
    """Daily ad-level metrics — responds to date filter like campaigns/adsets."""
    since = since or SINCE
    until = until or UNTIL
    try:
        rows = paginate(
            f'https://graph.facebook.com/v19.0/{account_id}/insights',
            {
                'access_token': TOKEN,
                'time_range': f'{{"since":"{since}","until":"{until}"}}',
                'time_increment': 1,
                'level': 'ad',
                'fields': f'date_start,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,objective,{INSIGHTS_FIELDS}',
                'limit': 500,
            }
        )
        out = []
        for row in rows:
            if not row.get('ad_name', '').strip():
                continue
            ins = parse_insights(row, row.get('objective', ''))
            out.append({
                'date':          row['date_start'],
                'campaign_id':   row.get('campaign_id', ''),
                'campaign_name': row.get('campaign_name', ''),
                'adset_id':      row.get('adset_id', ''),
                'adset_name':    row.get('adset_name', ''),
                'ad_id':         row.get('ad_id', ''),
                'ad_name':       row.get('ad_name', ''),
                'objective':     ins['objective'],
                'spend':         ins['spend'],        'impressions': ins['impressions'],
                'reach':         ins['reach'],         'clicks':      ins['clicks'],
                'link_clicks':   ins['link_clicks'],   'cpm':         ins['cpm'],
                'results':       ins['result'],         'result_label': ins['result_label'],
                'cpr':           ins['cpr'],            'purchases':   ins['purchases'],
                'messages':      ins['messages'],       'cost_per_message': ins['cost_per_message'],
                'msg_spend':     ins['msg_spend'],
            })
        return out
    except Exception as e:
        if since == SINCE and ('500' in str(e) or '400' in str(e)):
            since_30 = str(date.today() - timedelta(days=30))
            print(f'  ! ads_daily retrying with 30 days for {account_id}')
            return fetch_ads_daily(account_id, since=since_30, until=until)
        print(f'  ! ads_daily error for {account_id}: {e}')
        return []

def fetch_all_ad_thumbnails(account_id):
    """Fetch ad_id -> thumbnail_url map in one account-level call."""
    try:
        rows = paginate(
            f'https://graph.facebook.com/v19.0/{account_id}/ads',
            {
                'access_token': TOKEN,
                'fields': 'id,creative{thumbnail_url,image_url}',
                'limit': 500,
            }
        )
        return {
            a['id']: (a.get('creative', {}).get('thumbnail_url') or
                      a.get('creative', {}).get('image_url') or '')
            for a in rows
        }
    except Exception as e:
        print(f'  ! thumbnails error for {account_id}: {e}')
        return {}

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
                'fields': 'date_start,spend,impressions,inline_link_clicks,reach,cpm,actions,cost_per_action_type',
            }
        )
        out = []
        for row in rows:
            actions   = row.get('actions', [])
            costs     = row.get('cost_per_action_type', [])
            purchases = sum(int(float(a['value'])) for a in actions if a['action_type'] in PURCHASE_ACTIONS)
            msg_act   = next((a for a in actions
                              if a['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), None)
            messages  = int(float(msg_act['value'])) if msg_act else 0
            msg_cost  = next((c for c in costs
                              if c['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), None)
            spend     = round(float(row.get('spend', 0)), 2)
            cost_per_message = round(
                float(msg_cost['value']) if msg_cost else (spend / messages if messages else 0), 2
            )
            out.append({
                'date':             row['date_start'],
                'impressions':      int(row.get('impressions', 0)),
                'reach':            int(row.get('reach', 0)),
                'link_clicks':      int(row.get('inline_link_clicks', 0)),
                'spend':            spend,
                'cpm':              round(float(row.get('cpm', 0)), 2),
                'purchases':        purchases,
                'messages':         messages,
                'cost_per_message': cost_per_message,
                'msg_spend':        round(cost_per_message * messages, 2),
            })
        return sorted(out, key=lambda x: x['date'])
    except Exception as e:
        print(f'  ! daily error for {account_id}: {e}')
        return []

# ── BIGQUERY HELPERS ──────────────────────────────────────────────────────────

def get_bq_client():
    import json as _json
    # Support credentials as JSON string in env var (for Railway)
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if creds_json:
        info = _json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/bigquery']
        )
    else:
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

def _unified_row(level, acc_name, row, status_map=None):
    """Build a unified table row for any level."""
    cid       = row.get('campaign_id', '')
    objective = row.get('objective', '')
    spend     = row.get('spend', 0)
    reach     = row.get('reach', 0)
    obj_lower = objective.lower()

    is_messages  = 'message' in obj_lower
    is_awareness = objective in ('Awareness', 'Reach')
    is_camp      = level == 'campaign'   # objective-split fields only at campaign level

    return {
        'date':               row.get('date', None),
        'date_updated':       TODAY,
        'account':            acc_name,
        'level':              level,
        'campaign_id':        cid,
        'campaign_name':      row.get('campaign_name', ''),
        'campaign_status':    (status_map or {}).get(cid, ''),
        'objective':          objective,
        'adset_id':           row.get('adset_id', ''),
        'adset_name':         row.get('adset_name', ''),
        'adset_status':       row.get('adset_status', ''),
        'ad_id':              row.get('ad_id', ''),
        'ad_name':            row.get('ad_name', ''),
        'ad_status':          row.get('ad_status', ''),
        'thumbnail_url':      row.get('thumbnail_url', ''),
        'spend':              spend,
        'impressions':        row.get('impressions', 0),
        'reach':              reach,
        'clicks':             row.get('clicks', 0),
        'link_clicks':        row.get('link_clicks', 0),
        'results':            row.get('results', row.get('result', 0)),
        'result_label':       row.get('result_label', 'Results'),
        'purchases':          row.get('purchases', 0),
        'messages':           row.get('messages', 0),
        'msg_spend':          row.get('msg_spend', 0.0),
        # campaign-level only → scorecard totals صح بدون فلتر
        'messages_camp':            row.get('messages', 0)                    if is_camp else 0,
        'msg_campaign_spend':       (spend if is_messages  else 0.0)          if is_camp else 0.0,
        'awareness_campaign_spend': (spend if is_awareness else 0.0)          if is_camp else 0.0,
        'awareness_reach_camp':     (reach if is_awareness else 0)            if is_camp else 0,
        'results_camp':             row.get('results', row.get('result', 0))  if is_camp else 0,
        'spend_camp':               (spend if (not is_messages and not is_awareness) else 0.0) if is_camp else 0.0,
        # all levels → CPR formula في الجداول صح
        'awareness_spend':    spend if is_awareness else 0.0,
        'awareness_reach':    reach if is_awareness else 0,
        # cost per result — use cpr from parse_insights directly
        # awareness → spend/(reach/1000), messages → spend/messages, others → spend/results
        'cost_per_result':    round(float(row.get('cpr', 0.0)), 2),
        'balance':            row.get('balance', 0.0),
        'currency':           row.get('currency', ''),
    }


def table_name(acc_name):
    return 'unified_' + acc_name.lower().replace(' ', '_').replace('-', '_')


def main():
    client = get_bq_client()
    ensure_dataset(client)

    # Clean up old unused tables
    old_tables = ['unified', 'balances', 'daily', 'campaigns', 'adsets', 'ads']
    for t in old_tables:
        try:
            client.delete_table(f'{GCP_PROJECT}.{BQ_DATASET}.{t}')
            print(f'Deleted: {t}')
        except Exception:
            pass

    for acc_name, acc_id in ACCOUNTS.items():
        print(f'\nFetching {acc_name}...')
        rows = []

        campaigns     = fetch_campaigns(acc_id)
        status_map    = {c['id']: c['status']    for c in campaigns}
        obj_label_map = {c['id']: c['objective'] for c in campaigns}
        print(f'  campaigns: {len(campaigns)}')

        # level=account — daily totals
        for row in fetch_daily(acc_id):
            rows.append(_unified_row('account', acc_name, {
                'date':        row['date'],
                'spend':       row['spend'],
                'impressions': row['impressions'],
                'reach':       row['reach'],
                'link_clicks': row['link_clicks'],
                'messages':    row['messages'],
                'msg_spend':   row['msg_spend'],
                'purchases':   row['purchases'],
            }, status_map=status_map))

        # level=campaign_total — aggregate rows, one per campaign, correct deduplicated reach
        for c in campaigns:
            rows.append(_unified_row('campaign_total', acc_name, {
                'date':          UNTIL,
                'campaign_id':   c['id'],
                'campaign_name': c['name'],
                'objective':     c['objective'],
                'spend':         c['spend'],
                'impressions':   c['impressions'],
                'reach':         c['reach'],
                'clicks':        c['clicks'],
                'link_clicks':   c['link_clicks'],
                'results':       c['result'],
                'result_label':  c['result_label'],
                'purchases':     c['purchases'],
                'messages':      c['messages'],
                'msg_spend':     c['msg_spend'],
            }, status_map=status_map))

        # level=campaign — daily rows for time series
        camp_daily = fetch_campaigns_daily(acc_id)
        print(f'  campaigns_daily: {len(camp_daily)} rows')
        for row in camp_daily:
            row['objective'] = obj_label_map.get(row['campaign_id'], row['objective'])
            rows.append(_unified_row('campaign', acc_name, row, status_map=status_map))

        # level=adset
        adset_daily = fetch_adsets_daily(acc_id)
        print(f'  adsets_daily: {len(adset_daily)} rows')
        for row in adset_daily:
            row['objective'] = obj_label_map.get(row['campaign_id'], row['objective'])
            rows.append(_unified_row('adset', acc_name, row, status_map=status_map))

        # level=ad + thumbnails
        thumbnail_map = fetch_all_ad_thumbnails(acc_id)
        ads_daily = fetch_ads_daily(acc_id)
        print(f'  ads_daily: {len(ads_daily)} rows')
        for row in ads_daily:
            row['objective']     = obj_label_map.get(row['campaign_id'], row['objective'])
            row['thumbnail_url'] = thumbnail_map.get(row.get('ad_id', ''), '')
            rows.append(_unified_row('ad', acc_name, row, status_map=status_map))

        # level=balance
        balance, currency, display = fetch_balance(acc_id)
        rows.append(_unified_row('balance', acc_name, {
            'date': TODAY, 'objective': display,
            'balance': balance, 'currency': currency,
        }, status_map=status_map))

        load_table(client, table_name(acc_name), UNIFIED_SCHEMA, rows)

    print('\nDone.')

if __name__ == '__main__':
    main()
