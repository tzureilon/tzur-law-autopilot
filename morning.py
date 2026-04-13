#!/usr/bin/env python3
"""Tzur Law — Morning Automation. Reads credentials from environment variables."""
import os, base64, json, re, html, requests, pytz
from datetime import datetime
from google.ads.googleads.client import GoogleAdsClient

GOOGLE_CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
GOOGLE_DEV_TOKEN     = os.environ["GOOGLE_DEV_TOKEN"]
CUSTOMER_ID          = os.environ["CUSTOMER_ID"]
WP_URL               = "https://tzur-law.co.il/wp-json/wp/v2"
WP_AUTH              = base64.b64encode(f"{os.environ['WP_USER']}:{os.environ['WP_PASS']}".encode()).decode()
WA_URL               = os.environ["WA_URL"]
WA_TOKEN             = os.environ["WA_TOKEN"]
EILON_PHONE          = os.environ["EILON_PHONE"]
IL_TZ                = pytz.timezone("Asia/Jerusalem")
TODAY                = datetime.now(IL_TZ).strftime("%Y-%m-%d")
wp_headers           = {"Authorization": f"Basic {WP_AUTH}", "Content-Type": "application/json"}

def read_wp_state():
    try:
        r = requests.get(f"{WP_URL}/posts?slug=autopilot-state&status=private", headers=wp_headers, timeout=15)
        posts = r.json()
        if not posts: return {}, None
        post_id = posts[0]["id"]
        raw = posts[0]["content"]["rendered"]
        content = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        return json.loads(content), post_id
    except Exception as e:
        print(f"WP read error: {e}"); return {}, None

def write_wp_state(state, post_id):
    try:
        body = {"content": json.dumps(state, ensure_ascii=False)}
        if post_id:
            requests.post(f"{WP_URL}/posts/{post_id}", json=body, headers=wp_headers, timeout=15)
        else:
            body.update({"title": "autopilot-state", "slug": "autopilot-state", "status": "private"})
            requests.post(f"{WP_URL}/posts", json=body, headers=wp_headers, timeout=15)
        print("WP state saved")
    except Exception as e:
        print(f"WP write error: {e}")

def send_wa(message):
    try:
        r = requests.post(WA_URL,
            headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
            json={"to": EILON_PHONE, "message": message}, timeout=20)
        print(f"WA: {r.json()}")
    except Exception as e:
        print(f"WA error: {e}")

def main():
    print(f"=== Morning Automation {TODAY} ===")
    state, post_id = read_wp_state()
    print(f"WP state loaded, post_id={post_id}")

    client = GoogleAdsClient.load_from_dict({
        "developer_token": GOOGLE_DEV_TOKEN,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": GOOGLE_REFRESH_TOKEN,
        "login_customer_id": CUSTOMER_ID,
        "use_proto_plus": True,
    })
    print("Google Ads connected")

    ga_service = client.get_service("GoogleAdsService")

    # Today's stats
    query = f"SELECT campaign.name, metrics.cost_micros, metrics.conversions, metrics.clicks FROM campaign WHERE segments.date = '{TODAY}' AND campaign.status = 'ENABLED'"
    campaigns = []
    for row in ga_service.search(customer_id=CUSTOMER_ID, query=query):
        campaigns.append({
            "name": row.campaign.name,
            "spend_ils": round(row.metrics.cost_micros / 1_000_000 * 3.7, 2),
            "conversions": row.metrics.conversions,
            "clicks": row.metrics.clicks,
        })
    total_spend = sum(c["spend_ils"] for c in campaigns)
    total_conv = sum(c["conversions"] for c in campaigns)
    print(f"Today: ₪{total_spend:.0f} spent, {total_conv:.0f} conversions")

    # Search terms for negatives
    query2 = "SELECT search_term_view.search_term, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions FROM search_term_view WHERE segments.date DURING LAST_14_DAYS AND metrics.impressions > 0 ORDER BY metrics.cost_micros DESC LIMIT 200"
    negative_candidates = []
    for row in ga_service.search(customer_id=CUSTOMER_ID, query=query2):
        cost = row.metrics.cost_micros / 1_000_000 * 3.7
        if row.metrics.conversions == 0 and cost >= 150:
            negative_candidates.append(row.search_term_view.search_term)

    negative_candidates = list(set(negative_candidates))[:15]
    added = 0
    if negative_candidates:
        # Get campaign IDs
        campaign_ids = [row.campaign.id for row in ga_service.search(customer_id=CUSTOMER_ID, query="SELECT campaign.id FROM campaign WHERE campaign.status = 'ENABLED'")]
        svc = client.get_service("CampaignCriterionService")
        for cid in campaign_ids:
            ops = []
            for term in negative_candidates:
                op = client.get_type("CampaignCriterionOperation")
                cr = op.create
                cr.campaign = f"customers/{CUSTOMER_ID}/campaigns/{cid}"
                cr.negative = True
                cr.keyword.text = term
                cr.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD
                ops.append(op)
            if ops:
                try:
                    svc.mutate_campaign_criteria(customer_id=CUSTOMER_ID, operations=ops)
                    added += len(ops)
                except Exception as e:
                    print(f"Negative error: {e}")

    print(f"Negatives added: {added}, terms: {negative_candidates}")

    state["ads_report"] = {
        "date": TODAY, "total_spend_ils": total_spend, "total_conversions": total_conv,
        "campaigns": campaigns, "negatives_added": added, "negatives_terms": negative_candidates,
    }
    write_wp_state(state, post_id)

    campaign_lines = "\n".join([f"  {c['name']}: ₪{c['spend_ils']:.0f} | {c['conversions']:.0f} המרות" for c in campaigns])
    neg_line = f"\n🚫 {added} מילות שלילה נוספו" if added else ""
    send_wa(f"""🌅 *בוקר טוב אילון — {TODAY}*

💰 *Google Ads:*
{campaign_lines}
סה״כ: ₪{total_spend:.0f}/₪250 | {total_conv:.0f} המרות{neg_line}

✅ אוטופיילוט רץ תקין""")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"CRITICAL: {e}")
        requests.post(os.environ.get("WA_URL",""), 
            headers={"Authorization": f"Bearer {os.environ.get('WA_TOKEN','')}","Content-Type":"application/json"},
            json={"to": os.environ.get("EILON_PHONE",""), "message": f"⚠️ שגיאה: {str(e)[:200]}"}, timeout=20)
