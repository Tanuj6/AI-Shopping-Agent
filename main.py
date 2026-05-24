from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import httpx
import os
import re
import math
import asyncio

app = FastAPI(title="Product Search AI Agent", version="2.1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Config ──────────────────────────────────────────────────────────────────

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "f260e1461cb4ee03a5f764f33a0ae3fffeeadffa")

TRUSTED_PLATFORMS = [
    "amazon.in", "flipkart.com", "myntra.com", "ajio.com", "snapdeal.com",
    "croma.com", "reliancedigital.com", "tatacliq.com", "meesho.com",
    "nykaa.com", "nykaafashion.com", "vijaysales.com", "shopclues.com",
    "pepperfry.com", 
    "limeroad.com", "bewakoof.com", "firstcry.com", "babyoye.com",
    "healthkart.com", "1mg.com", "bigbasket.com", "blinkit.com",
    "swiggyinstamart.com", "decathlon.in", "sportsuncle.com",
    "boat-lifestyle.com", "noise.com","bajaao.com"
]

PLATFORM_TRUST = {
    "amazon.in":           0.98, "flipkart.com":        0.97,
    "myntra.com":          0.90, "ajio.com":            0.88,
    "croma.com":           0.88, "reliancedigital.com": 0.86,
    "tatacliq.com":        0.85, "nykaa.com":           0.84,
    "nykaafashion.com":    0.83, "vijaysales.com":      0.82,
    "meesho.com":          0.78, "bajaao.com":          0.80,
    "pepperfry.com":       0.77,
    "snapdeal.com":        0.72, "decathlon.in":        0.80,
    "healthkart.com":      0.79, "1mg.com":             0.78,
    "firstcry.com":        0.77, "bigbasket.com":       0.76,
    "boat-lifestyle.com":  0.75, "noise.com":           0.74,
    "bewakoof.com":        0.70, "limeroad.com":        0.68,
    "shopclues.com":       0.65, "blinkit.com":         0.65,
    "swiggyinstamart.com": 0.65, "babyoye.com":         0.65,
    }

COLOUR_WORDS = {
    "black","white","blue","red","green","yellow","pink","purple","gold","silver",
    "grey","gray","orange","violet","titanium","midnight","starlight","coral",
    "lavender","cream","brown","rose","navy","beige","maroon","teal","cyan","magenta","indigo",
}

DEFAULT_WEIGHTS = {
    "price": 0.60, "rating": 0.10, "review_count": 0.12,
    "feature_match": 0.10, "platform_trust": 0.08,
}

OUT_OF_STOCK_SIGNALS = [
    "coming soon","currently unavailable","not available","sold out",
    "temporarily unavailable","notify me","item is unavailable",
    "product is unavailable","out-of-stock","out of stock",
    "currently out of stock","not in stock","no longer available",
    "discontinued","we don't know when or if this item will be back in stock",
    "sign up to be notified",
]

ACCESSORY_KEYWORDS = {
    "cover","case","screen protector","tempered glass","back cover","flip cover",
    "bumper","skin","sticker","charger","cable","adapter","earphone","headphone",
    "stand","holder","mount","strap","band","wallet","pouch","sleeve","shell",
    "guard","film","protector","dock","hub","keyboard","mouse","lens","power bank",
}

# ─── Models ───────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    product_query: str
    budget: Optional[float] = None
    preferences: Optional[str] = None
    num_results: int = 15
    custom_weights: Optional[dict] = None

class AgentResponse(BaseModel):
    query: str
    top_picks: list
    best_overall: dict
    agent_summary: str
    search_count: int

# ─── Helpers ──────────────────────────────────────────────────────────────────

def is_out_of_stock(title: str, snippet: str) -> bool:
    combined = (title + " " + snippet).lower()
    combined = combined.replace("\xa0"," ").replace("\u2013","-").replace("\u2014","-")
    return any(s in combined for s in OUT_OF_STOCK_SIGNALS)

def deduplicate_by_platform(results: list) -> list:
    seen_platforms, seen_base_titles, deduped = set(), set(), []
    for r in results:
        platform = r["platform"]
        base_title = " ".join(
            w for w in r["title"].lower().split()
            if w.strip(",-") not in COLOUR_WORDS
        )[:40]
        if platform in seen_platforms or base_title in seen_base_titles:
            continue
        seen_platforms.add(platform)
        seen_base_titles.add(base_title)
        deduped.append(r)
    return deduped

# ─── Serper Search ─────────────────────────────────────────────────────────────

async def google_search(query: str, num: int = 15) -> list:
    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    results = []

    for i in range(0, len(TRUSTED_PLATFORMS), 5):
        batch = TRUSTED_PLATFORMS[i:i+5]
        site_filter = " OR ".join([f"site:{p}" for p in batch])
        payload = {"q": f"{query} buy India ({site_filter})", "num": 10, "gl": "in", "hl": "en"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                continue
            data = resp.json()

        for item in data.get("organic", []):
            link    = item.get("link", "")
            snippet = item.get("snippet", "")
            title   = item.get("title", "")
            platform = next((p for p in TRUSTED_PLATFORMS if p in link), None)
            if not platform:
                continue
            results.append({
                "title": title, "link": link, "platform": platform,
                "snippet": snippet, "out_of_stock": is_out_of_stock(title, snippet),
            })

    results = deduplicate_by_platform(results)
    return results[:num]

# ─── HTML Parsing ─────────────────────────────────────────────────────────────

# ── Shared skip patterns used by all ₹-scanning fallbacks ────────────────────
_SKIP_BEFORE = re.compile(
    r'(Save|Savings?|MRP|M\.R\.P\.?|was|original|cashback|off|discount|'
    r'exchange|extra|\+\s*₹|strikethrough|from|upto?|up\s+to|pay)\s*$',
    re.IGNORECASE,
)
_SKIP_AFTER = re.compile(
    r'\s*/mo\b|\s*/month\b|\s*x\s*\d+\s*m\b|\s*EMI',
    re.IGNORECASE,
)
_SKIP_LINE = re.compile(
    r'Save\s+₹|Savings?\s+₹|₹[\d,]+\s*off\b',
    re.IGNORECASE,
)


def _scan_rupee_amounts(html: str, floor: float = 100.0) -> list:
    """
    Generic ₹-amount scanner with shared skip rules.
    Returns sorted list of candidate prices (ascending).
    """
    candidates = []
    for m in re.finditer(r'₹\s*([\d,]+(?:\.\d+)?)', html):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        if val < floor:
            continue
        before = html[max(0, m.start() - 50): m.start()]
        after  = html[m.end(): m.end() + 30]
        line   = html[max(0, m.start() - 60): m.end() + 30]
        if _SKIP_BEFORE.search(before):
            continue
        if _SKIP_AFTER.search(after):
            continue
        if _SKIP_LINE.search(line):
            continue
        candidates.append(val)
    return sorted(candidates)


def parse_html_details(html: str, url: str) -> dict:
    result = {}

    # ── Generic JSON-LD baseline (all platforms) ──────────────────────────────
    m = re.search(r'"ratingValue"\s*:\s*"?([\d.]+)"?', html)
    if m:
        val = float(m.group(1))
        if val >= 2.0 and (val != int(val) or val >= 3.0):
            result["page_rating"] = round(val, 1)

    for pat in (r'"reviewCount"\s*:\s*"?(\d+)"?', r'"ratingCount"\s*:\s*"?(\d+)"?'):
        m = re.search(pat, html)
        if m:
            result["page_reviews"] = int(m.group(1))
            break

    price_candidates = [
        float(m.group(1).replace(",", ""))
        for m in re.finditer(r'"price"\s*:\s*"?([\d,]+(?:\.\d+)?)"?', html)
        if float(m.group(1).replace(",", "")) >= 100
    ]
    if price_candidates:
        result["page_price"] = min(price_candidates)

    # ════════════════════════════════════════════════════════════════════════
    # ── Amazon ──────────────────────────────────────────────────────────────
    # ════════════════════════════════════════════════════════════════════════
    if "amazon.in" in url:
        for pat in (
            r'"priceAmount"\s*:\s*([\d.]+)',
            r'"buyingPrice"\s*:\s*([\d.]+)',
            r'"landingPrice"\s*:\s*([\d.]+)',
            r'<span[^>]*class="[^"]*a-price-whole[^"]*"[^>]*>([\d,]+)',
            r'corePriceDisplay[^}]{0,300}₹\s*([\d,]+)',
            r'[Ww]ithout\s+[Ee]xchange[\s\S]{0,200}?₹\s*([\d,]+)',
            r'-\d+%\s*₹\s*([\d,]+)',
            r'"basisPrice"\s*:\s*\{[^}]*"amount"\s*:\s*([\d.]+)',
            r'"displayPrice"\s*:\s*"₹([\d,]+)"',
        ):
            m = re.search(pat, html, re.DOTALL)
            if m:
                val = float(m.group(1).replace(",", ""))
                if val >= 50:
                    result["page_price"] = val
                    break

        if not result.get("page_price"):
            candidates = _scan_rupee_amounts(html, floor=500)
            if candidates:
                result["page_price"] = candidates[0]

        for pat in (r'([0-9.]+) out of 5 stars', r'"ratingValue"\s*:\s*"?([0-9.]+)"?'):
            m = re.search(pat, html)
            if m:
                val = float(m.group(1))
                if 2.0 <= val <= 5.0:
                    result["page_rating"] = round(val, 1)
                    break

        for pat in (r'"ratingCount"\s*:\s*"?(\d+)"?', r'([\d,]+)\s*global ratings', r'"reviewCount"\s*:\s*"?(\d+)"?'):
            m = re.search(pat, html)
            if m:
                result["page_reviews"] = int(m.group(1).replace(",", ""))
                break

    # ════════════════════════════════════════════════════════════════════════
    # ── Flipkart ────────────────────────────────────────────────────────────
    # ════════════════════════════════════════════════════════════════════════
    elif "flipkart.com" in url:
        for pat in (
            r'"effectivePrice"\s*:\s*([\d.]+)',
            r'"discountedPrice"\s*:\s*([\d.]+)',
            r'"sellingPrice"\s*:\s*([\d.]+)',
            r'"finalPrice"\s*:\s*([\d.]+)',
        ):
            m = re.search(pat, html)
            if m:
                val = float(m.group(1))
                if val >= 100:
                    result["page_price"] = val
                    break

        if not result.get("page_price"):
            candidates = _scan_rupee_amounts(html, floor=500)
            if candidates:
                result["page_price"] = candidates[0]

        m = re.search(r'"avgRating"\s*:\s*"?([0-9.]+)"?', html)
        if m:
            val = float(m.group(1))
            if 2.0 <= val <= 5.0:
                 result["page_rating"] = round(val, 1)

        m = re.search(r'"totalRatings"\s*:\s*(\d+)', html)
        if m:
            result["page_reviews"] = int(m.group(1))

    # ════════════════════════════════════════════════════════════════════════
    # ── Croma  ──────────────────────────────────────────────────────────────
    #
    # ROOT CAUSE of the ₹1,000 bug:
    #   The old code called generic ₹-scan which also matched "Save ₹1,000"
    #   and "(₹259/mo* EMI)".  min() then picked the smallest value.
    #
    # FIX — three-priority extraction:
    #   1. Structured JSON / known API fields  (most reliable, no false positives)
    #   2. "(Incl. all Taxes)" anchor pattern  (Croma's exact selling-price format)
    #   3. Filtered ₹-scan with SAVE/EMI/MRP skip rules + ₹500 floor
    # ════════════════════════════════════════════════════════════════════════
    elif "croma.com" in url:

        # Priority 1 – structured data fields
        for pat in (
            r'"offerPrice"\s*:\s*([\d,]+(?:\.\d+)?)',    # Croma API field
            r'"sellingPrice"\s*:\s*([\d,]+(?:\.\d+)?)',
            r'"priceValue"\s*:\s*([\d,]+(?:\.\d+)?)',
            r'"price"\s*:\s*"([\d,]+(?:\.\d+)?)"',       # JSON-LD string
            r'"price"\s*:\s*([\d]+(?:\.\d+)?)',           # JSON-LD numeric
        ):
            m = re.search(pat, html)
            if m:
                val = float(m.group(1).replace(",", ""))
                # Croma sells nothing under ₹500; reject stray small values
                if val >= 500:
                    result["page_price"] = val
                    break

        # Priority 2 – "(Incl. all Taxes)" anchor: Croma always shows this
        # right after the selling price on the PDP.
        if not result.get("page_price"):
            m = re.search(
                r'₹\s*([\d,]+(?:\.\d+)?)\s*[\n\r\s]*'
                r'\(Incl(?:\.|\b|uding)?\s*(?:all\s+)?[Tt]axes?\)',
                html,
            )
            if m:
                val = float(m.group(1).replace(",", ""))
                if val >= 500:
                    result["page_price"] = val

        # Priority 3 – filtered ₹ scan (floor ₹500, skip Save/EMI/MRP)
        if not result.get("page_price"):
            candidates = _scan_rupee_amounts(html, floor=500)
            if candidates:
                result["page_price"] = candidates[0]

        # Rating ── structured first
        m = re.search(r'"averageRating"\s*:\s*([0-9.]+)', html)
        if m:
            result["page_rating"] = round(float(m.group(1)), 1)

        # Rating ── inline pattern: "3.8 ★ (19 Ratings & 9 Reviews)"
        if not result.get("page_rating"):
            m = re.search(
                r'(\d\.\d)\s*[★\*]\s*\(?\s*(\d[\d,]*)\s*Ratings?\s*'
                r'(?:&amp;|&|and)\s*(\d[\d,]*)\s*Reviews?\)?',
                html, re.IGNORECASE,
            )
            if m:
                result["page_rating"]  = round(float(m.group(1)), 1)
                result["page_reviews"] = (
                    int(m.group(2).replace(",", "")) + int(m.group(3).replace(",", ""))
                )

        # Reviews ── structured
        if not result.get("page_reviews"):
            m = re.search(r'"totalRatingsCount"\s*:\s*(\d+)', html)
            if m:
                result["page_reviews"] = int(m.group(1))

        # Reviews ── inline fallback
        if not result.get("page_reviews"):
            m = re.search(
                r'(\d[\d,]*)\s*Ratings?\s*(?:&amp;|&|and)\s*(\d[\d,]*)\s*Reviews?',
                html, re.IGNORECASE,
            )
            if m:
                result["page_reviews"] = (
                    int(m.group(1).replace(",", "")) + int(m.group(2).replace(",", ""))
                )

    # ════════════════════════════════════════════════════════════════════════
    # ── Myntra ──────────────────────────────────────────────────────────────
    # ════════════════════════════════════════════════════════════════════════
    elif "myntra.com" in url:
        m = re.search(r'"discountedPrice"\s*:\s*([\d.]+)', html)
        if m:
            result["page_price"] = float(m.group(1))
        m = re.search(r'"overallRating"\s*:\s*([0-9.]+)', html)
        if m:
            result["page_rating"] = float(m.group(1))
        m = re.search(r'"totalCount"\s*:\s*(\d+)', html)
        if m:
            result["page_reviews"] = int(m.group(1))

    # ════════════════════════════════════════════════════════════════════════
    # ── TataCliq ────────────────────────────────────────────────────────────
    # ════════════════════════════════════════════════════════════════════════
    elif "tatacliq.com" in url:
        m = re.search(r'"sellingPrice"\s*:\s*([\d.]+)', html)
        if m:
            result["page_price"] = float(m.group(1))
        m = re.search(r'"averageRating"\s*:\s*([0-9.]+)', html)
        if m:
            result["page_rating"] = float(m.group(1))
        m = re.search(r'"numberOfRatings"\s*:\s*(\d+)', html)
        if m:
            result["page_reviews"] = int(m.group(1))

    # ════════════════════════════════════════════════════════════════════════
    # ── Vijay Sales ─────────────────────────────────────────────────────────
    # ════════════════════════════════════════════════════════════════════════
    elif "vijaysales.com" in url:
        m = re.search(
            r'(\d\.\d)\s*\((\d[\d,]*)\s*Ratings?\s*(?:&amp;|&|and)\s*(\d[\d,]*)\s*Reviews?\)',
            html, re.IGNORECASE,
        )
        if m:
            result["page_rating"]  = round(float(m.group(1)), 1)
            result["page_reviews"] = (
                int(m.group(2).replace(",","")) + int(m.group(3).replace(",",""))
            )
        all_prices = [
            float(p.replace(",",""))
            for p in re.findall(r'"price"\s*:\s*"?([\d,]+(?:\.\d+)?)"?', html)
            if float(p.replace(",","")) >= 100
        ]
        if all_prices:
            result["page_price"] = min(all_prices)

    # ════════════════════════════════════════════════════════════════════════
    # ── BigBasket ───────────────────────────────────────────────────────────
    # ════════════════════════════════════════════════════════════════════════
    elif "bigbasket.com" in url:
        for pat in (r'"discounted_price"\s*:\s*([\d.]+)', r'"sp"\s*:\s*([\d.]+)', r'"price"\s*:\s*([\d.]+)'):
            m = re.search(pat, html)
            if m:
                val = float(m.group(1))
                if val >= 50:
                    result["page_price"] = val
                    break
        m = re.search(r'"rating"\s*:\s*([0-9.]+)', html)
        if m:
            result["page_rating"] = float(m.group(1))
        m = re.search(r'"count"\s*:\s*(\d+)', html)
        if m:
            result["page_reviews"] = int(m.group(1))

    # ════════════════════════════════════════════════════════════════════════
    # ── Blinkit ─────────────────────────────────────────────────────────────
    # ════════════════════════════════════════════════════════════════════════
    elif "blinkit.com" in url:
        for pat in (r'"selling_price"\s*:\s*([\d.]+)', r'"price"\s*:\s*([\d.]+)', r'"mrp"\s*:\s*([\d.]+)'):
            m = re.search(pat, html)
            if m:
                val = float(m.group(1))
                if val >= 50:
                    result["page_price"] = val
                    break
        m = re.search(r'"average_rating"\s*:\s*([0-9.]+)', html)
        if m:
            result["page_rating"] = float(m.group(1))
        m = re.search(r'"rating_count"\s*:\s*(\d+)', html)
        if m:
            result["page_reviews"] = int(m.group(1))

        if not result.get("page_rating"):
            m = re.search(r'([0-9]\.[0-9])\s*★', html)
            if m:
                val = float(m.group(1))
                if 2.0 <= val <= 5.0:   # CRITICAL FIX
                    result["page_rating"] = val
    # =======================================================================
    # ---------- 1mg.com ---------------------------------------------------
    # ======================================================================
    elif "1mg.com" in url:
        for pat in (r'"selling_price"\s*:\s*([\d.]+)', r'"discounted_price"\s*:\s*([\d.]+)', r'"price"\s*:\s*"?([\d,]+(?:\.\d+)?)"?', r'"offerPrice"\s*:\s*([\d.]+)', r'"mrp"\s*:\s*([\d.]+)'):
            m = re.search(pat, html)
            if m:
                val = float(m.group(1).replace(",", ""))
                if val >= 10:
                    result["page_price"] = val
                    break

    if not result.get("page_price"):
        nd = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html)
        if nd:
            for pat in (r'"selling_price"\s*:\s*([\d.]+)', r'"discounted_price"\s*:\s*([\d.]+)', r'"price"\s*:\s*([\d.]+)'):
                m = re.search(pat, nd.group(1))
                if m:
                    val = float(m.group(1))
                    if val >= 10:
                        result["page_price"] = val
                        break

    if not result.get("page_price"):
        cands = _scan_rupee_amounts(html, floor=10)
        if cands:
            result["page_price"] = cands[0]

    for pat in (r'"average_rating"\s*:\s*([0-9.]+)', r'"averageRating"\s*:\s*([0-9.]+)', r'"ratingValue"\s*:\s*"?([0-9.]+)"?'):
        m = re.search(pat, html)
        if m:
            val = float(m.group(1))
            if 2.0 <= val <= 5.0:
                result["page_rating"] = round(val, 1)
                break

    if not result.get("page_rating"):
        m = re.search(r'([0-9]\.[0-9])\s*(?:★|out of 5|/5)', html)
        if m:
            val = float(m.group(1))
            if 2.0 <= val <= 5.0:
                result["page_rating"] = round(val, 1)

    for pat in (r'"rating_count"\s*:\s*(\d+)', r'"ratingCount"\s*:\s*(\d+)', r'"reviewCount"\s*:\s*(\d+)', r'"total_ratings"\s*:\s*(\d+)'):
        m = re.search(pat, html)
        if m:
            result["page_reviews"] = int(m.group(1))
            break

    if not result.get("page_reviews"):
        m = re.search(r'([\d,]+)\s*(?:ratings?|reviews?)', html, re.IGNORECASE)
        if m:
            count = _safe_int(m.group(1))
            if count and count >= 1:
                result["page_reviews"] = count
    # ════════════════════════════════════════════════════════════════════════
    # ── Generic SPA fallback (Next.js / Redux state blobs) ──────────────────
    # ════════════════════════════════════════════════════════════════════════
    for json_var_pat in (
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>',
        r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
        r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});',
    ):
        m = re.search(json_var_pat, html, re.DOTALL)
        if m:
            blob = m.group(1)
            if "page_price" not in result:
                pm = re.search(
                    r'"(?:price|sellingPrice|offerPrice|finalPrice|discountedPrice)"\s*:\s*([\d.]+)',
                    blob,
                )
                if pm:
                    result["page_price"] = float(pm.group(1))
            if "page_rating" not in result:
                rm = re.search(
                    r'"(?:ratingValue|avgRating|averageRating|overallRating)"\s*:\s*([0-9.]+)',
                    blob,
                )
                if rm:
                    result["page_rating"] = float(rm.group(1))
            if "page_reviews" not in result:
                rv = re.search(
                    r'"(?:reviewCount|ratingCount|totalRatings|totalCount|numberOfRatings)"\s*:\s*(\d+)',
                    blob,
                )
                if rv:
                    result["page_reviews"] = int(rv.group(1))
            if len(result) >= 3:
                break

    result["page_oos"] = any(s in html.lower() for s in OUT_OF_STOCK_SIGNALS)
    return result


def _safe_int(raw: str) -> Optional[int]:
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


async def fetch_product_details(url: str, platform: str) -> dict:
    PLAYWRIGHT_ONLY = {"amazon.in","flipkart.com"}

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    html = None
    if platform not in PLAYWRIGHT_ONLY:
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=HEADERS) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                html = resp.text
        except Exception:
            pass

    def _is_complete(d: dict) -> bool:
        if platform in PLAYWRIGHT_ONLY:
            return False
        return bool(d.get("page_price") and d.get("page_rating") and d.get("page_reviews"))

    result = {}

    if html:
        result = parse_html_details(html, url)
        if _is_complete(result):
            result["page_oos"] = any(s in html.lower() for s in OUT_OF_STOCK_SIGNALS)
            return result

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            if not result.get("page_price"):
                for sel in ["[class*=price]", "[class*=Price]", "[class*=amount]", "[itemprop=price]", "[class*=offer]"]:
                    el = soup.select_one(sel)
                    if el:
                        raw = re.sub(r"[^\d.]", "", el.get_text())
                        try:
                            val = float(raw)
                            if val >= 100:
                                result["page_price"] = val
                                break
                        except ValueError:
                            pass

            if not result.get("page_rating"):
                for sel in ["[itemprop=ratingValue]", "[class*=rating]", "[class*=Rating]", "[class*=star]"]:
                    el = soup.select_one(sel)
                    if el:
                        raw = el.get("content") or el.get_text()
                        m = re.search(r"([0-9]\.[0-9])", raw)
                        if m:
                            val = float(m.group(1))
                            if 2.0 <= val <= 5.0:
                                result["page_rating"] = round(val, 1)
                                break

            if not result.get("page_reviews"):
                for sel in ["[itemprop=reviewCount]", "[itemprop=ratingCount]", "[class*=review]", "[class*=Review]", "[class*=rating-count]"]:
                    el = soup.select_one(sel)
                    if el:
                        raw = el.get("content") or el.get_text()
                        m = re.search(r"([\d,]+)", raw)
                        if m:
                            count = _safe_int(m.group(1))
                            if count is not None:
                                result["page_reviews"] = count
                                break

        except ImportError:
            pass

        if _is_complete(result):
            result["page_oos"] = any(s in html.lower() for s in OUT_OF_STOCK_SIGNALS)
            return result

        if not result.get("page_price"):
            candidates = _scan_rupee_amounts(html, floor=100)
            if candidates:
                result["page_price"] = candidates[0]

        if not result.get("page_rating"):
            for pat in (r"(\d\.\d)\s*/\s*5", r"(\d\.\d)\s*(?:out of|★|stars?)", r"(\d\.\d)\s*\(\d[\d,]*\s*(?:ratings?|reviews?)"):
                m = re.search(pat, html, re.IGNORECASE)
                if m:
                    val = float(m.group(1))
                    if 2.0 <= val <= 5.0:
                        result["page_rating"] = round(val, 1)
                        break

        if not result.get("page_reviews"):
            m = re.search(r"([\d,]+)\s*(?:ratings?|reviews?|customers?)", html, re.IGNORECASE)
            if m:
                count = _safe_int(m.group(1))
                if count is not None and count >= 5:
                    result["page_reviews"] = count

        result["page_oos"] = any(s in html.lower() for s in OUT_OF_STOCK_SIGNALS)

        if result.get("page_price") or result.get("page_rating"):
            return result

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return result if html else {}

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="en-IN",
                extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
            )
            page = await context.new_page()

            async def block_resources(route):
                if route.request.resource_type in {"image", "media", "font", "stylesheet"}:
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", block_resources)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            rendered_html = await page.content()
            await browser.close()

        pw_result = parse_html_details(rendered_html, url)
        pw_result["page_oos"] = any(s in rendered_html.lower() for s in OUT_OF_STOCK_SIGNALS)
        return pw_result

    except Exception:
        return result if html else {}

# ─── Extraction Helpers (snippet fallback) ────────────────────────────────────

def extract_price(text: str) -> Optional[float]:
    DIRECT_EMI  = re.compile(r'^[\s*\.]*(/mo\b|/month\b)', re.IGNORECASE)
    INSTALMENT  = re.compile(r'\s*x\s*\d+\s*m|\s*for\s*\d+\s*months?', re.IGNORECASE)
    PREFIX_SKIP = re.compile(
        r'(\+|pay|up\s+to|upto|save|\d+%\s*off|discount|exchange|cashback|extra|from|mrp)\s*$',
        re.IGNORECASE,
    )
    candidates = []
    for m in re.finditer(r"(?:₹|Rs\.?|\$|USD|INR)\s?([\d,]+(?:\.\d+)?)", text, re.IGNORECASE):
        price_val = float(m.group(1).replace(",", ""))
        if price_val < 50:
            continue
        before  = text[max(0, m.start()-20): m.start()]
        after10 = text[m.end(): m.end()+10]
        after25 = text[m.end(): m.end()+25]
        if DIRECT_EMI.search(after10): continue
        if INSTALMENT.search(after25): continue
        if PREFIX_SKIP.search(before): continue
        candidates.append(price_val)
    return min(candidates) if candidates else None

def extract_budget(budget_input) -> Optional[float]:
    if not budget_input:
        return None

    # ✅ If already a number (THIS FIXES YOUR ERROR)
    if isinstance(budget_input, (int, float)):
        return float(budget_input)

    # ✅ Otherwise treat as string
    budget_str = str(budget_input)

    nums = re.findall(r"[\d,]+(?:\.\d+)?", budget_str.replace(",", ""))
    return float(nums[0]) if nums else None

def extract_rating(text: str) -> Optional[float]:
    patterns = [
        r"(\d\.\d)\s*\(\d[\d,]*\s*Ratings?\s*(?:&|and)\s*\d[\d,]*\s*Reviews?\)",
        r"(\d\.\d)\s*\(\d[\d,]*\s*Ratings?",
        r"(\d\.\d)\s*★",
        r"(\d\.\d)\s*(?:out of|/)\s*5",
        r"rated\s+(\d\.\d)",
        r"(\d\.\d)\s*stars?",
        r"(?:rating|score)\s*[:\-]\s*(\d\.\d)",
        r"([1-5]\.\d)\s*★",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 1.0 <= val <= 5.0:
                return round(val, 1)
    return None

def extract_review_count(text: str) -> Optional[int]:
    for m in re.finditer(r"([\d,]+)\s*(?:ratings?|reviews?)", text, re.IGNORECASE):
        raw = m.group(1).replace(",", "").strip()

        if not raw:
            continue

        try:
            val = int(raw)
        except ValueError:
            continue

        if val > 0:
            return val

    return None
# ─── Scoring Functions ────────────────────────────────────────────────────────

def score_price(price: Optional[float], budget: Optional[float], min_price: Optional[float] = None) -> float:
    if price is None:
        return 3.5 if budget else 4.0
    if budget:
        ratio = price / budget
        if ratio <= 0.40: return 10.0
        if ratio <= 0.60: return 9.5
        if ratio <= 0.75: return 9.0
        if ratio <= 0.85: return 8.2
        if ratio <= 0.95: return 7.5
        if ratio <= 1.00: return 7.0
        if ratio <= 1.10: return 4.5
        if ratio <= 1.25: return 2.5
        if ratio <= 1.50: return 1.0
        return 0.0
    if min_price and min_price > 0:
        ratio = price / min_price
        if ratio <= 1.00: return 9.0
        if ratio <= 1.05: return 7.0
        if ratio <= 1.10: return 5.5
        if ratio <= 1.20: return 4.0
        return 3.0
    return 5.0

def score_rating(rating: Optional[float]) -> float:
    if rating is None: return 5.0
    if rating >= 4.8: return 10.0
    if rating >= 4.5: return 9.0
    if rating >= 4.2: return 8.0
    if rating >= 4.0: return 7.0
    if rating >= 3.7: return 6.0
    if rating >= 3.5: return 5.0
    if rating >= 3.0: return 3.5
    if rating >= 2.5: return 2.0
    return 1.0

def score_review_count(count: Optional[int]) -> float:
    if count is None: return 4.0
    if count == 0:    return 0.0
    return round(min(math.log10(count + 1) * 2.5, 10.0), 1)

def score_platform_trust(platform: str) -> float:
    return round(PLATFORM_TRUST.get(platform, 0.60) * 10, 1)

def score_feature_match(text: str, query: str, preferences: str) -> float:
    STOPWORDS = {
        "a","an","the","for","and","or","in","with","of","to","is","i","me",
        "my","under","good","best","buy","online","india","price","latest","new","top","get",
    }
    combined_query = (query + " " + (preferences or "")).lower()
    text_lower = text.lower()
    keywords = [k for k in re.findall(r"\w+", combined_query) if k not in STOPWORDS and len(k) > 2]
    if not keywords:
        return 5.0
    hits = sum(1 for k in keywords if k in text_lower)
    ratio = hits / len(keywords)
    phrase_bonus = 0.0
    qwords = [k for k in combined_query.split() if k not in STOPWORDS and len(k) > 2]
    for i in range(len(qwords) - 1):
        if (qwords[i] + " " + qwords[i+1]) in text_lower:
            phrase_bonus += 0.5
    return round(min((ratio * 8.0) + min(phrase_bonus, 2.0), 10.0), 1)

def composite_score(scores: dict, weights: dict) -> float:
    return round(sum(scores[k] * weights.get(k, 0) for k in scores) * 10, 1)

# ─── Recommendation Builder ────────────────────────────────────────────────────

def build_recommendation(scores, price, rating, reviews, budget, out_of_stock) -> str:
    parts = []
    if price:
        tag = f"₹{price:,.0f}"
        if budget:
            tag += " (within budget)" if price <= budget else " (over budget)"
        parts.append(f"priced at {tag}")
    if rating:
        parts.append(f"rated {rating}/5")
    if reviews:
        parts.append(f"{reviews:,} reviews")
    if scores["feature_match"] >= 8:
        parts.append("strong feature match")
    elif scores["feature_match"] <= 3:
        parts.append("partial feature match")
    if out_of_stock:
        parts.append("⚠️ currently out of stock")
    if not parts:
        return "Limited details in snippet — verify on the platform."
    return ", ".join(parts).capitalize() + "."

def filter_price_outliers(products: list, threshold: float = 0.5) -> list:
    prices = [p["price"] for p in products if p.get("price") is not None]

    if len(prices) < 3:
        return products

    prices_sorted = sorted(prices)
    n = len(prices_sorted)

    median = (
        prices_sorted[n // 2]
        if n % 2 == 1
        else (prices_sorted[n // 2 - 1] + prices_sorted[n // 2]) / 2
    )

    filtered = []

    for p in products:
        price = p.get("price")

        # ✅ KEEP products with no price (your requirement)
        if price is None:
            filtered.append(p)
            continue

        deviation = abs(price - median) / median

        if deviation <= threshold:
            filtered.append(p)

    return filtered
# ─── Score Products ────────────────────────────────────────────────────────────

async def score_products(products, query, budget_str, preferences, weights):
    try:
        budget = float(budget_str) if budget_str else None
    except:
        budget = None

    STOPWORDS = {
        "a","an","the","for","and","or","in","with","of","to","is","i","me",
        "my","under","good","best","buy","online","india","price","latest","new","top","get",
    }
    query_keywords = [k for k in re.findall(r"\w+", query.lower()) if k not in STOPWORDS and len(k) > 2]
    query_is_device = not any(acc in query.lower() for acc in ACCESSORY_KEYWORDS)

    filtered = []
    for p in products:
        text = (p["title"] + " " + p["snippet"]).lower()
        if query_keywords and sum(1 for k in query_keywords if k in text) == 0:
            continue
        if query_is_device and any(acc in text for acc in ACCESSORY_KEYWORDS):
            continue
        filtered.append(p)

    products = filtered
    if not products:
        return []

    page_details = await asyncio.gather(
        *[fetch_product_details(p["link"], p["platform"]) for p in products]
    )

    all_prices = []
    for product, page in zip(products, page_details):
        text = product["title"] + " " + product["snippet"]

        price = page.get("page_price")
        if price is None:
            price = extract_price(text)

        if price is not None and price >= 50:
            all_prices.append(price)

    min_price = min(all_prices) if all_prices else None

    result = []

    for product, page in zip(products, page_details):
        text = product["title"] + " " + product["snippet"]

        price   = page.get("page_price")   or extract_price(text)
        rating = page.get("page_rating")

        if rating is None:
            fallback_rating = extract_rating(text)
            if fallback_rating and fallback_rating >= 2.0:
                rating = fallback_rating
        reviews = page.get("page_reviews") or extract_review_count(text)

        out_of_stock = product.get("out_of_stock") or page.get("page_oos", False)
        is_unavailable = (price is None) or out_of_stock

        scores = {
            "price":          score_price(price, budget),
            "rating":         score_rating(rating),
            "review_count":   score_review_count(reviews),
            "feature_match":  score_feature_match(text, query, preferences),
            "platform_trust": score_platform_trust(product["platform"]),
        }

        final = composite_score(scores, weights)

        
        if is_unavailable:
            final = max(0.0, final - 20.0)

        p = product.copy()
        p["available"]       = not is_unavailable
        p["score"]           = final
        p["score_breakdown"] = {k: round(v, 1) for k, v in scores.items()}
        p["price"]           = price
        p["rating"]          = rating
        p["num_reviews"]     = reviews
        p["out_of_stock"]    = out_of_stock
        p["recommendation"]  = build_recommendation(
            scores, price, rating, reviews, budget, out_of_stock
        )

        result.append(p)

    result = filter_price_outliers(result)
    return sorted(result, key=lambda x: x["score"], reverse=True)
# ─── Summary ──────────────────────────────────────────────────────────────────

def generate_summary(top_products, query, budget, preferences) -> str:
    if not top_products:
        return "No results found for your query."

    best        = top_products[0]
    in_stock    = [p for p in top_products if not p.get("out_of_stock")]
    best_is_oos = best.get("out_of_stock", False)

    budget_val = extract_budget(budget) if budget else None
    budget_display = f" under ₹{budget_val:,.0f}" if budget_val else ""
    lines = [f"Looking for {query}{budget_display}."]

    if best_is_oos and in_stock:
        nb = in_stock[0]
        lines.append(f"Top result '{best['title'][:55]}' on {best['platform']} is out of stock.")
        lines.append(f"Best in-stock: '{nb['title'][:55]}' on {nb['platform']} (score {nb['score']}/100) — {nb['recommendation']}")
    else:
        lines.append(f"Best pick: '{best['title'][:55]}' on {best['platform']} (score {best['score']}/100) — {best['recommendation']}")

    if len(top_products) >= 2:
        runner = top_products[1] if not best_is_oos else (in_stock[1] if len(in_stock) > 1 else None)
        if runner:
            lines.append(f"Runner-up: '{runner['title'][:55]}' on {runner['platform']} (score {runner['score']}/100).")

    best_rated = max((p for p in top_products if p.get("rating") is not None), key=lambda x: x["rating"], default=None)
    if best_rated and best_rated != best:
        rev = f" ({best_rated['num_reviews']:,} reviews)" if best_rated.get("num_reviews") else ""
        lines.append(f"Highest rated: '{best_rated['title'][:45]}' on {best_rated['platform']} — {best_rated['rating']}/5{rev}")

    return " ".join(lines)

# ─── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Product Search Agent 🚀 v2.1.1 — Croma price fix, Playwright scraping, Serper.dev"}

@app.get("/platforms")
def get_platforms():
    return {"trusted_platforms": TRUSTED_PLATFORMS, "total": len(TRUSTED_PLATFORMS)}

@app.get("/scoring-aspects")
def get_scoring_aspects():
    return {
        "scoring_weights": DEFAULT_WEIGHTS,
        "extraction": "Playwright headless browser (snippet fallback if page fetch fails)",
        "croma_fix": "Three-priority price extraction: structured JSON → (Incl. Taxes) anchor → filtered ₹-scan with Save/EMI/MRP skip",
        "method": "rule-based",
        "search_provider": "serper.dev",
    }

@app.post("/search", response_model=AgentResponse)
async def search_products(request: SearchRequest):
    weights = DEFAULT_WEIGHTS.copy()
    if request.custom_weights:
        weights.update(request.custom_weights)
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}

    raw_results = await google_search(request.product_query, request.num_results)
    if not raw_results:
        raise HTTPException(status_code=404, detail="No products found. Try a different query.")

    scored = await score_products(
        products=raw_results,
        query=request.product_query,
        budget_str=str(request.budget) if request.budget else "",
        preferences=request.preferences or "",
        weights=weights,
    )

    summary = generate_summary(
        top_products=scored,
        query=request.product_query,
        budget=request.budget or "",
        preferences=request.preferences or "",
    )

    return AgentResponse(
        query=request.product_query,
        top_picks=scored[:12],
        best_overall=scored[0] if scored else {},
        agent_summary=summary,
        search_count=len(raw_results),
    )

@app.post("/quick-search")
async def quick_search(request: SearchRequest):
    results = await google_search(request.product_query, request.num_results)
    return {"results": results, "count": len(results)}