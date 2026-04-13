#!/usr/bin/env python3
"""
Tzur Law — Evening Summary
Runs daily at 20:00 IL via CCR trigger
"""
import base64, json, re, html, requests, pytz
from datetime import datetime

IL_TZ       = pytz.timezone("Asia/Jerusalem")
TODAY       = datetime.now(IL_TZ).strftime("%Y-%m-%d")
WP_URL      = "https://tzur-law.co.il/wp-json/wp/v2"
WP_AUTH     = base64.b64encode(b"eylon360:KLqA Km6r m2on Hnzh RXme ldqk").decode()
WA_URL      = "http://72.61.190.120:18899/api/send"
WA_TOKEN    = "MVF9aF8Lj1hDh2GNBmAKgWZOCgVrKOpx"
EILON_PHONE = "+972547399511"
wp_headers  = {"Authorization": f"Basic {WP_AUTH}"}

def read_wp_state():
    try:
        r = requests.get(f"{WP_URL}/posts?slug=autopilot-state&status=private", headers=wp_headers, timeout=15)
        posts = r.json()
        if not posts:
            return {}
        raw = posts[0]["content"]["rendered"]
        content = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}

def send_wa(message):
    r = requests.post(WA_URL,
        headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
        json={"to": EILON_PHONE, "message": message}, timeout=20)
    print(f"WA: {r.json()}")

def main():
    state = read_wp_state()
    ads = state.get("ads_report", {})
    seo = state.get("seo_report", {})
    content = state.get("content_report", {})

    # Build summary
    ads_line = ""
    if ads:
        spend = ads.get("total_spend_ils", 0)
        conv  = ads.get("total_conversions", 0)
        neg   = ads.get("negatives_added", 0)
        cpa   = round(spend / conv, 0) if conv > 0 else "∞"
        ads_line = f"💰 Ads: ₪{spend:.0f} הוצאה | {conv:.0f} המרות | CPA ₪{cpa}"
        if neg:
            ads_line += f" | 🚫 {neg} שליליות"

    seo_line = ""
    if seo:
        wins = seo.get("quick_wins_updated", 0)
        seo_line = f"📈 SEO: {wins} עמודים עודכנו"

    content_line = ""
    if content.get("published"):
        content_line = f"📝 מאמר פורסם: {content.get('title', '')}"

    lines = [l for l in [ads_line, seo_line, content_line] if l]
    body = "\n".join(lines) if lines else "אין פעולות לדווח היום"

    msg = f"""🌙 *סיכום יומי {TODAY}*

{body}

🤖 אוטופיילוט — tzur-law.co.il"""
    send_wa(msg)
    print("Summary sent")

if __name__ == "__main__":
    main()
