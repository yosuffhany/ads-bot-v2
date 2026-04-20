"""
Meta Ads → BigQuery exporter
Tables: campaigns | adsets | balances | daily
Data is APPENDED daily (full history preserved).
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

CAMPAIGN_SCHEMA = [
    bigquery.SchemaField('date_updated',  'DATE'),
    bigquery.SchemaField('account',       'STRING'),
    bigquery.SchemaField('campaign_id',   'STRING'),
    bigquery.SchemaField('campaign_name', 'STRING'),
    bigquery.SchemaField('objective',     'STRING'),
    bigquery.SchemaField('status',        'STRING'),
    bigquery.SchemaField('spend',         'FLOAT'),
    bigquery.SchemaField('impressions',   'INTEGER'),
    bigquery.SchemaField('reach',         'INTEGER'),
    bigquery.SchemaField('clicks',        'INTEGER'),
    bigquery.SchemaField('link_clicks',   'INTEGER'),
    bigquery.SchemaField('cpm',           'FLOAT'),
    bigquery.SchemaField('results',       'INTEGER'),
    bigquery.SchemaField('result_label',  'STRING'),
    bigquery.SchemaField('cpr',           'FLOAT'),
    bigquery.SchemaField('purchases',     'INTEGER'),
]

ADSET_SCHEMA = [
    bigquery.SchemaField('date_updated',  'DATE'),
    bigquery.SchemaField('account',       'STRING'),
    bigquery.SchemaField('campaign_name', 'STRING'),
    bigquery.SchemaField('campaign_id',   'STRING'),
    bigquery.SchemaField('adset_id',      'STRING'),
    bigquery.SchemaField('adset_name',    'STRING'),
    bigquery.SchemaField('status',        'STRING'),
    bigquery.SchemaField('spend',         'FLOAT'),
    bigquery.SchemaField('impressions',   'INTEGER'),
    bigquery.SchemaField('reach',         'INTEGER'),
    bigquery.SchemaField('clicks',        'INTEGER'),
    bigquery.SchemaField('link_clicks',   'INTEGER'),
    bigquery.SchemaField('cpm',           'FLOAT'),
    bigquery.SchemaField('results',       'INTEGER'),
    bigquery.SchemaField('result_label',  'STRING'),
    bigquery.SchemaField('cpr',           'FLOAT'),
    bigquery.SchemaField('purchases',     'INTEGER'),
]

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
        'objective': obj.replace('OUTCOME_', '').title(),
        'result': result, 'result_label': result_label, 'cpr': cpr,
        'spend': spend, 'cpm': cpm, 'impressions': impressions,
        'clicks': clicks, 'reach': reach, 'link_clicks': link_clicks,
        'purchases': purchases,
    }

def fetch_campaigns(account_id):
    tr = f'{{"since":"{SINCE}","until":"{UNTIL}"}}'
    r  = requests.get(
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

def fetch_adsets(campaign_id, obj_raw):
    tr = f'{{"since":"{SINCE}","until":"{UNTIL}"}}'
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
        ins  = (a.get('insights', {}).get('data') or [{}])[0]
        data = parse_insights(ins, obj_raw)
        data.update({'id': a['id'], 'name': a['name'], 'status': a.get('status', '')})
        out.append(data)
    return sorted(out, key=lambda x: x['spend'], reverse=True)

def fetch_balance(account_id):
    r = requests.get(
        f'https://graph.facebook.com/v19.0/{account_id}',
        params={'access_token': TOKEN, 'fields': 'funding_source_details,currency,balance'}
    )
    d = r.json()
    raw_balance = d.get('balance', 0)
    balance_usd = round(int(raw_balance) / 100, 2) if raw_balance else 0.0
    return balance_usd, d.get('currency', 'USD'), d.get('funding_source_details', {}).get('display_string', '')

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

def main():
    client = get_bq_client()
    ensure_dataset(client)

    campaigns_rows = []
    adsets_rows    = []
    balances_rows  = []
    daily_rows     = []

    for acc_name, acc_id in ACCOUNTS.items():
        print(f'Fetching {acc_name}...')

        campaigns = fetch_campaigns(acc_id)
        for c in campaigns:
            campaigns_rows.append({
                'date_updated': TODAY, 'account': acc_name,
                'campaign_id': c['id'], 'campaign_name': c['name'],
                'objective': c['objective'], 'status': c['status'],
                'spend': c['spend'], 'impressions': c['impressions'],
                'reach': c['reach'], 'clicks': c['clicks'],
                'link_clicks': c['link_clicks'], 'cpm': c['cpm'],
                'results': c['result'], 'result_label': c['result_label'],
                'cpr': c['cpr'], 'purchases': c['purchases'],
            })

            adsets = fetch_adsets(c['id'], c['objective'])
            for a in adsets:
                adsets_rows.append({
                    'date_updated': TODAY, 'account': acc_name,
                    'campaign_name': c['name'], 'campaign_id': c['id'],
                    'adset_id': a['id'], 'adset_name': a['name'],
                    'status': a['status'],
                    'spend': a['spend'], 'impressions': a['impressions'],
                    'reach': a['reach'], 'clicks': a['clicks'],
                    'link_clicks': a['link_clicks'], 'cpm': a['cpm'],
                    'results': a['result'], 'result_label': a['result_label'],
                    'cpr': a['cpr'], 'purchases': a['purchases'],
                })

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

    load_table(client, 'campaigns', CAMPAIGN_SCHEMA, campaigns_rows)
    print(f'  ✓ campaigns: {len(campaigns_rows)} rows')

    load_table(client, 'adsets', ADSET_SCHEMA, adsets_rows)
    print(f'  ✓ adsets: {len(adsets_rows)} rows')

    load_table(client, 'balances', BALANCE_SCHEMA, balances_rows)
    print(f'  ✓ balances: {len(balances_rows)} rows')

    load_table(client, 'daily', DAILY_SCHEMA, daily_rows)
    print(f'  ✓ daily: {len(daily_rows)} rows')

    print('\nDone! Connect Looker Studio → BigQuery → meta_ads dataset.')

if __name__ == '__main__':
    main()
