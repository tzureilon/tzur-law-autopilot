#!/usr/bin/env python3
"""
Tzur Law — Morning Automation
Runs daily at 07:00 IL via CCR trigger
"""
import base64, json, re, html, requests, pytz
from datetime import datetime, timedelta
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

# ── Config ────────────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = "475857007890-tadc690uhfcv6k48jlhr54sisr9f0ktb.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"
GOOGLE_REFRESH_TOKEN = "1//0992Zecht63WnCgYIARAAGAkSNwF-L9IrBC36DSCb_v8-Z-qZyx2GG46czH_j-2v62_xsZRWvZfZAqsinqCNkimKeXDxSdNTzjM4"
GOOGLE_DEV_TOKEN     = "pDQIf0lW3cTDoB4gwhp58g"
CUSTOMER_ID          = "7704251631"
WP_URL               = "https://tzur-law.co.il/wp-json/wp/v2"
WP_AUTH              = base64.b64encode(b"eylon360:KLqA Km6r m2on Hnzh RXme ldqk").decode()
WA_URL               = "http://72.61.190.120:18899/api/send"
WA_TOKEN             = "MVF9aF8Lj1hDh2GNBmAKgWZOCgVrKOpx"
EILON_PHONE          = "+972547399511"
IL_TZ                = pytz.timezone("Asia/Jerusalem")
TODAY                = datetime.now(IL_TZ).strftime("%Y-%m-%d")

wp_headers = {"Authorization": f"Basic {WP_AUTH}", "Content-Type": "application/json"}

# ── WordPress State ───────────────────────────────────────────────────────────
def read_wp_state():
    try:
        r = requests.get(f"{WP_URL}/posts?slug=autopilot-state&status=private", headers=wp_headers, timeout=15)
        posts = r.json()
        if not posts:
            return {}, None
        post_id = posts[0]["id"]
        raw = posts[0]["content"]["rendered"]
        content = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        return json.loads(content), post_id
    except Exception as e:
        print(f"WP read error: {e}")
        return {}, None

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

# ── WhatsApp ──────────────────────────────────────────────────────────────────
def send_wa(message):
    try:
        r = requests.post(WA_URL,
            headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
            json={"to": EILON_PHONE, "message": message}, timeout=20)
        resp = r.json()
        print(f"WA: {'OK' if resp.get('ok') else 'FAIL'}")
    except Exception as e:
        print(f"WA error: {e}")

# ── Google Ads ────────────────────────────────────────────────────────────────
def get_ads_client():
    return GoogleAdsClient.load_from_dict({
        "developer_token": GOOGLE_DEV_TOKEN,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": GOOGLE_REFRESH_TOKEN,
        "login_customer_id": CUSTOMER_ID,
        "use_proto_plus": True,
    })

def get_search_terms(client):
    """Pull search terms from last 14 days"""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            search_term_view.search_term,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            campaign.name
        FROM search_term_view
        WHERE segments.date DURING LAST_14_DAYS
          AND metrics.impressions > 0
        ORDER BY metrics.cost_micros DESC
        LIMIT 200
    """
    response = ga_service.search(customer_id=CUSTOMER_ID, query=query)
    terms = []
    for row in response:
        terms.append({
            "term": row.search_term_view.search_term,
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "cost_ils": round(row.metrics.cost_micros / 1_000_000 * 3.7, 2),
            "conversions": row.metrics.conversions,
            "campaign": row.campaign.name,
        })
    return terms

def get_campaign_stats(client):
    """Pull today's spend per campaign"""
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            campaign.name,
            metrics.cost_micros,
            metrics.conversions,
            metrics.clicks,
            campaign.status
        FROM campaign
        WHERE segments.date = '{TODAY}'
          AND campaign.status = 'ENABLED'
    """
    response = ga_service.search(customer_id=CUSTOMER_ID, query=query)
    campaigns = []
    for row in response:
        campaigns.append({
            "name": row.campaign.name,
            "spend_ils": round(row.metrics.cost_micros / 1_000_000 * 3.7, 2),
            "conversions": row.metrics.conversions,
            "clicks": row.metrics.clicks,
        })
    return campaigns

def add_negative_keywords(client, negative_terms):
    """Add negative keywords to all campaigns"""
    if not negative_terms:
        return 0
    # Get campaign IDs
    ga_service = client.get_service("GoogleAdsService")
    query = "SELECT campaign.id, campaign.name FROM campaign WHERE campaign.status = 'ENABLED'"
    response = ga_service.search(customer_id=CUSTOMER_ID, query=query)
    campaign_ids = [row.campaign.id for row in response]

    added = 0
    campaign_criterion_service = client.get_service("CampaignCriterionService")
    for campaign_id in campaign_ids:
        ops = []
        for term in negative_terms[:20]:  # max 20 at a time
            op = client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = f"customers/{CUSTOMER_ID}/campaigns/{campaign_id}"
            criterion.negative = True
            criterion.keyword.text = term
            criterion.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD
            ops.append(op)
        if ops:
            try:
                campaign_criterion_service.mutate_campaign_criteria(
                    customer_id=CUSTOMER_ID, operations=ops)
                added += len(ops)
            except Exception as e:
                print(f"Negative add error for campaign {campaign_id}: {e}")
    return added

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"=== Morning Automation {TODAY} ===")
    state, post_id = read_wp_state()
    print(f"WP state loaded, post_id={post_id}")

    try:
        client = get_ads_client()
        print("Google Ads connected")

        # Get stats
        campaigns = get_campaign_stats(client)
        total_spend = sum(c["spend_ils"] for c in campaigns)
        total_conv = sum(c["conversions"] for c in campaigns)
        print(f"Today: ₪{total_spend:.0f} spent, {total_conv:.0f} conversions")

        # Get search terms — find negatives
        terms = get_search_terms(client)
        negative_candidates = []
        for t in terms:
            if t["conversions"] == 0 and t["cost_ils"] >= 150:
                negative_candidates.append(t["term"])
            elif t["conversions"] == 0 and t["impressions"] >= 500 and t["clicks"] == 0:
                # Pure junk terms
                negative_candidates.append(t["term"])

        negative_candidates = list(set(negative_candidates))[:15]
        print(f"Negative candidates: {negative_candidates}")

        added = add_negative_keywords(client, negative_candidates)
        print(f"Added {added} negative keywords")

        # Save to WP state
        state["ads_report"] = {
            "date": TODAY,
            "total_spend_ils": total_spend,
            "total_conversions": total_conv,
            "campaigns": campaigns,
            "negatives_added": added,
            "negatives_terms": negative_candidates,
        }
        write_wp_state(state, post_id)

        # Build summary
        campaign_lines = "\n".join([f"  {c['name']}: ₪{c['spend_ils']:.0f} | {c['conversions']:.0f} המרות" for c in campaigns])
        neg_line = f"\n🚫 {added} מילות שלילה נוספו" if added > 0 else ""
        msg = f"""🌅 *בוקר טוב אילון — דוח יומי {TODAY}*

💰 *Google Ads היום:*
{campaign_lines}
סה״כ: ₪{total_spend:.0f}/₪250 | {total_conv:.0f} המרות{neg_line}

✅ אוטופיילוט רץ תקין"""
        send_wa(msg)

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        state["last_error"] = str(e)
        write_wp_state(state, post_id)
        send_wa(f"⚠️ שגיאה באוטופיילוט הבוקר: {str(e)[:200]}")

if __name__ == "__main__":
    main()
