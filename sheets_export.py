"""
Meta Ads → Google Sheets exporter
Tabs: Campaigns | AdSets | Balances | Daily
Run manually or schedule via Task Scheduler.
"""
import os, json, requests
from datetime import date, timedelta
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

TOKEN              = os.getenv('LONG_LIVED_TOKEN')
SHEETS_ID          = os.getenv('GOOGLE_SHEETS_ID')
CREDENTIALS_FILE   = os.getenv('GOOGLE_CREDENTIALS_FILE', 'google_credentials.json')

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

SINCE = str(date.today() - timedelta(days=30))
UNTIL = str(date.today())
TODAY = str(date.today())

# ── GOOGLE SHEETS AUTH ────────────────────────────────────────────────────────

def get_gc():
    scopes = ['https://spreadsheets.google.com/feeds',
              'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return gspread.authorize(creds)

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
        'objective':     obj.replace('OUTCOME_', '').title(),
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
    currency    = d.get('currency', 'USD')
    display     = d.get('funding_source_details', {}).get('display_string', '')
    return balance_usd, currency, display

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
            'date':        row['date_start'],
            'impressions': int(row.get('impressions', 0)),
            'reach':       int(row.get('reach', 0)),
            'link_clicks': int(row.get('inline_link_clicks', 0)),
            'spend':       round(float(row.get('spend', 0)), 2),
            'purchases':   purchases,
        })
    return sorted(rows, key=lambda x: x['date'])

# ── BUILD DATA ────────────────────────────────────────────────────────────────

def build_data():
    campaigns_rows = []
    adsets_rows    = []
    balances_rows  = []
    daily_rows     = []

    for acc_name, acc_id in ACCOUNTS.items():
        print(f"Fetching {acc_name}...")

        # Campaigns + AdSets
        campaigns = fetch_campaigns(acc_id)
        for c in campaigns:
            campaigns_rows.append([
                TODAY, acc_name,
                c['id'], c['name'], c['objective'], c['status'],
                c['spend'], c['impressions'], c['reach'], c['clicks'],
                c['link_clicks'], c['cpm'],
                c['result'], c['result_label'], c['cpr'], c['purchases'],
            ])

            adsets = fetch_adsets(c['id'], c['objective'])
            for a in adsets:
                adsets_rows.append([
                    TODAY, acc_name,
                    c['name'], c['id'],
                    a['id'], a['name'], a['status'],
                    a['spend'], a['impressions'], a['reach'], a['clicks'],
                    a['link_clicks'], a['cpm'],
                    a['result'], a['result_label'], a['cpr'], a['purchases'],
                ])

        # Balance
        balance, currency, display = fetch_balance(acc_id)
        balances_rows.append([TODAY, acc_name, balance, currency, display])

        # Daily
        for row in fetch_daily(acc_id):
            daily_rows.append([
                row['date'], acc_name,
                row['spend'], row['impressions'], row['reach'],
                row['link_clicks'], row['purchases'],
            ])

    return campaigns_rows, adsets_rows, balances_rows, daily_rows

# ── WRITE TO SHEETS ───────────────────────────────────────────────────────────

CAMPAIGN_HEADERS = [
    'date_updated', 'account',
    'campaign_id', 'campaign_name', 'objective', 'status',
    'spend', 'impressions', 'reach', 'clicks', 'link_clicks', 'cpm',
    'results', 'result_label', 'cpr', 'purchases',
]

ADSET_HEADERS = [
    'date_updated', 'account',
    'campaign_name', 'campaign_id',
    'adset_id', 'adset_name', 'status',
    'spend', 'impressions', 'reach', 'clicks', 'link_clicks', 'cpm',
    'results', 'result_label', 'cpr', 'purchases',
]

BALANCE_HEADERS = ['date_updated', 'account', 'balance', 'currency', 'display']

DAILY_HEADERS   = ['date', 'account', 'spend', 'impressions', 'reach', 'link_clicks', 'purchases']


def write_sheet(ws, headers, rows):
    ws.clear()
    ws.update('A1', [headers] + rows)
    # Bold the header row
    ws.format('1:1', {'textFormat': {'bold': True}})


def ensure_tab(sh, name):
    try:
        return sh.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=name, rows=5000, cols=30)


def main():
    campaigns_rows, adsets_rows, balances_rows, daily_rows = build_data()

    print("Connecting to Google Sheets...")
    gc = get_gc()
    sh = gc.open_by_key(SHEETS_ID)

    write_sheet(ensure_tab(sh, 'Campaigns'), CAMPAIGN_HEADERS, campaigns_rows)
    print(f"  ✓ Campaigns: {len(campaigns_rows)} rows")

    write_sheet(ensure_tab(sh, 'AdSets'), ADSET_HEADERS, adsets_rows)
    print(f"  ✓ AdSets: {len(adsets_rows)} rows")

    write_sheet(ensure_tab(sh, 'Balances'), BALANCE_HEADERS, balances_rows)
    print(f"  ✓ Balances: {len(balances_rows)} rows")

    write_sheet(ensure_tab(sh, 'Daily'), DAILY_HEADERS, daily_rows)
    print(f"  ✓ Daily: {len(daily_rows)} rows")

    print("\nDone! Open Looker Studio and connect to your Google Sheet.")


if __name__ == '__main__':
    main()
