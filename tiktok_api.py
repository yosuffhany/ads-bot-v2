"""
TikTok Marketing API helper
"""
import os, json, requests, logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL     = "https://business-api.tiktok.com/open_api/v1.3"
ACCESS_TOKEN = os.getenv('TIKTOK_ACCESS_TOKEN', '')

TIKTOK_ACCOUNTS = [
    {'key': 'tt_mall',  'id': '7477170011656896529', 'label': 'Mall (TikTok)',      'platform': 'tiktok', 'ar': ['مول تيك', 'mall tiktok']},
    {'key': 'tt_safaa', 'id': '7647455477714042881', 'label': 'Dr.Safaa (TikTok)', 'platform': 'tiktok', 'ar': ['صفاء', 'دكتوره صفاء', 'safaa']},
]

OBJECTIVE_LABELS = {
    'WEB_CONVERSIONS':   'Conversions',
    'LANDING_PAGE':      'LP Views',
    'APP_INSTALL':       'App Installs',
    'VIDEO_VIEWS':       'Video Views',
    'REACH':             'Reach',
    'TRAFFIC':           'Clicks',
    'LEAD_GENERATION':   'Leads',
    'SHOP_PURCHASES':    'Purchases',
    'PRODUCT_SALES':     'Purchases',
    'ENGAGEMENT':        'Engagement',
    'FOLLOWERS':         'Followers',
    'RF_REACH':          'Reach',
    'CATALOG_SALES':     'Purchases',
}

def _headers():
    return {'Access-Token': ACCESS_TOKEN}

def get_campaigns_list(advertiser_id):
    """Returns list of {id, name, status, objective_type}."""
    try:
        r = requests.get(
            f"{BASE_URL}/campaign/get/",
            headers=_headers(),
            params={'advertiser_id': advertiser_id, 'page_size': 50},
            timeout=20
        )
        d = r.json()
        if d.get('code') != 0:
            logger.warning(f"TikTok campaigns error: {d.get('message')}")
            return []
        camps = d['data']['list']
        # return both active and paused (ENABLE/DISABLE)
        result = []
        for c in camps:
            result.append({
                'id':            str(c['campaign_id']),
                'name':          c['campaign_name'],
                'status':        'ACTIVE' if c.get('secondary_status','').endswith('ENABLE') else 'PAUSED',
                'objective_type': c.get('objective_type', ''),
            })
        return result
    except Exception as e:
        logger.error(f"TikTok campaigns_list exception {advertiser_id}: {e}")
        return []

def get_campaign_report(advertiser_id, campaign_id, date_start, date_end):
    """Returns raw metrics dict or None."""
    try:
        r = requests.get(
            f"{BASE_URL}/report/integrated/get/",
            headers=_headers(),
            params={
                'advertiser_id': advertiser_id,
                'report_type':   'BASIC',
                'data_level':    'AUCTION_CAMPAIGN',
                'dimensions':    json.dumps(['campaign_id']),
                'metrics':       json.dumps(['campaign_name', 'spend', 'impressions', 'reach',
                                             'result', 'cost_per_result', 'clicks', 'cpm']),
                'start_date':    date_start,
                'end_date':      date_end,
                'page_size':     50,
            },
            timeout=20
        )
        d = r.json()
        if d.get('code') != 0:
            logger.warning(f"TikTok report error: {d.get('message')}")
            return None
        for row in d['data']['list']:
            if str(row['dimensions']['campaign_id']) == str(campaign_id):
                return row['metrics']
        # not found → 0-spend
        return None
    except Exception as e:
        logger.error(f"TikTok campaign_report exception: {e}")
        return None

def get_adgroup_report(advertiser_id, campaign_id, date_start, date_end):
    """Returns list of adgroup metrics rows."""
    try:
        r = requests.get(
            f"{BASE_URL}/report/integrated/get/",
            headers=_headers(),
            params={
                'advertiser_id': advertiser_id,
                'report_type':   'BASIC',
                'data_level':    'AUCTION_ADGROUP',
                'dimensions':    json.dumps(['adgroup_id']),
                'metrics':       json.dumps(['adgroup_name', 'spend', 'impressions', 'reach',
                                             'result', 'cost_per_result']),
                'filters':       json.dumps([{'field_name': 'campaign_id', 'filter_type': 'IN',
                                              'filter_value': json.dumps([str(campaign_id)])}]),
                'start_date':    date_start,
                'end_date':      date_end,
                'page_size':     50,
            },
            timeout=20
        )
        d = r.json()
        if d.get('code') != 0:
            return []
        return [row['metrics'] for row in d['data']['list']]
    except Exception as e:
        logger.error(f"TikTok adgroup_report exception: {e}")
        return []

def parse_campaign_insights(metrics, objective_type=''):
    """Convert raw TikTok metrics dict to same shape as Meta parse_insights output."""
    if not metrics:
        return None
    spend   = round(float(metrics.get('spend', 0)), 2)
    impr    = int(metrics.get('impressions', 0))
    reach   = int(metrics.get('reach', 0))
    clicks  = int(metrics.get('clicks', 0))
    results = int(float(metrics.get('result', 0)))
    cpr_raw = metrics.get('cost_per_result', '0')
    cpr     = round(float(cpr_raw) if cpr_raw and cpr_raw != '--' else (spend / results if results else 0), 2)
    cpm_raw = metrics.get('cpm', '0')
    cpm     = round(float(cpm_raw) if cpm_raw and cpm_raw != '--' else (spend / impr * 1000 if impr else 0), 2)

    result_label = OBJECTIVE_LABELS.get(objective_type, 'Results')

    return dict(
        spend=spend, impr=impr, reach=reach, clicks=clicks, lc=0,
        cpm=cpm, messages=0, cpm_msg=0,
        results=results, result_label=result_label, cpr=cpr,
        obj=objective_type, currency='USD',
        platform='tiktok',
    )
