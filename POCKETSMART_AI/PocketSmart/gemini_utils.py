"""Gemini prompts, JSON parsing, budget validation, shopping links and fallbacks."""
import json
import os
import re
import urllib.parse

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

from models import HomeBudgetInput, JewelryBudgetInput, PartyBudgetInput

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_client = None

PLATFORMS = {
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "ikea": "https://www.ikea.com/in/en/search/?q={q}",
    "myntra": "https://www.myntra.com/search?q={q}",
    "ajio": "https://www.ajio.com/search/?text={q}",
    "meesho": "https://www.meesho.com/search?q={q}",
    "bigbasket": "https://www.bigbasket.com/ps/?q={q}",
    "swiggy": "https://www.swiggy.com/search?query={q}",
    "zomato": "https://www.zomato.com/search?q={q}",
    "bookmyshow": "https://in.bookmyshow.com/search?q={q}",
    "google": "https://www.google.com/search?q={q}",
    "booking": "https://www.booking.com/searchresults.html?ss={q}",
    "makemytrip": "https://www.makemytrip.com/hotels/hotel-listing/?searchText={q}",
    "oyorooms": "https://www.oyorooms.com/search/?location={q}",
    "nobroker": "https://www.nobroker.in/property/search?searchTerm={q}",
    "bluestone": "https://www.bluestone.com/search.html?query={q}",
    "tanishq": "https://www.tanishq.co.in/search?q={q}",
    "caratlane": "https://www.caratlane.com/search?q={q}",
    "melorra": "https://www.melorra.com/search?q={q}",
}
HOME_PLATFORMS = ["amazon", "flipkart", "ikea", "meesho"]
JEWELRY_PLATFORMS = ["amazon", "flipkart", "bluestone", "tanishq", "caratlane", "melorra", "meesho"]
VENUE_PLATFORMS = ["google", "booking", "makemytrip", "oyorooms", "nobroker"]
PARTY_PLATFORMS = {
    "venue": VENUE_PLATFORMS,
    "catering": ["swiggy", "zomato"],
    "food": ["swiggy", "zomato", "bigbasket"],
    "drinks": ["swiggy", "zomato", "bigbasket"],
    "decoration": ["amazon", "flipkart", "meesho", "myntra"],
    "entertainment": ["bookmyshow", "amazon", "flipkart"],
    "gifts": ["amazon", "flipkart", "myntra", "meesho"],
    "photography": ["google", "amazon"],
    "accommodation": ["oyorooms", "makemytrip", "booking"],
    "contingency": ["google"],
}
DEFAULT_PARTY = ["amazon", "flipkart", "google"]


# ---------- Gemini ----------
def _get_client():
    global _client
    if _client is None:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key or key.startswith("paste_your"):
            raise RuntimeError("GEMINI_API_KEY is not set in the .env file")
        _client = genai.Client(api_key=key)
    return _client


def extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Model response did not contain JSON")
    return json.loads(text[start:end + 1])


def ask_gemini(prompt, image_path=None):
    contents = [prompt]
    if image_path:
        img = Image.open(image_path)
        img.load()
        contents.append(img)
    cfg = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.6)
    last = None
    for _ in range(2):
        try:
            resp = _get_client().models.generate_content(model=MODEL, contents=contents, config=cfg)
            return extract_json(resp.text)
        except Exception as e:  # retry once, then let caller fall back
            last = e
    raise last


# ---------- helpers ----------
def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def add_links(item, platforms):
    q = urllib.parse.quote_plus(str(item.get("search_terms") or item.get("name")
                                    or item.get("item_type") or ""))
    item["shopping_links"] = {p: PLATFORMS[p].format(q=q) for p in platforms if p in PLATFORMS}


def _short(e):
    return (str(e) or type(e).__name__)[:200]


def _normalize(result, total, platform_fn):
    cats = result.get("budget_breakdown")
    if not isinstance(cats, list) or not cats:
        raise ValueError("Model returned an empty plan")
    spent, table = 0.0, []
    for cat in cats:
        cat["category"] = str(cat.get("category") or "misc")
        items = [i for i in (cat.get("items") or []) if isinstance(i, dict)]
        cat["items"], cost = items, 0.0
        for it in items:
            it["estimated_price"] = num(it.get("estimated_price"))
            it["quantity"] = int(num(it.get("quantity"), 1)) or 1
            cost += it["estimated_price"] * it["quantity"]
            add_links(it, platform_fn(cat["category"]))
        cat["allocation"] = num(cat.get("allocation"), cost)
        spent += cost
        table.append({"category": cat["category"], "items_count": len(items),
                      "total_cost": round(cost, 2),
                      "percentage_of_budget": round(cost / total * 100, 1)})
    tips = [str(t) for t in (result.get("additional_suggestions") or [])]
    if spent > total:
        tips.insert(0, f"Estimated cost is Rs {spent - total:,.0f} over budget. Reduce quantities or pick cheaper options.")
    result.update(total_budget=total, remaining_budget=round(total - spent, 2),
                  calculation_table=table, additional_suggestions=tips)
    return result


# ---------- Home ----------
def _home_prompt(b: HomeBudgetInput):
    rooms = [n for n, f in (("Living room", b.has_living_room), ("Kitchen", b.has_kitchen),
                            ("Bedroom", b.has_bedroom)) if f]
    return f"""You are an interior shopping budget planner for the Indian market.
Total budget: Rs {b.total_budget:,.0f}. Rooms: {', '.join(rooms) or 'not specified'}.
Needs: {b.num_lights} lights, {b.num_fans} ceiling fans, {b.num_furniture} furniture pieces, {b.num_dining_tables} dining tables.
Extra requirements: {b.additional_requirements or 'None'}.
Only include categories whose count is above zero. Recommend products and brands sold in India (Amazon India, Flipkart, IKEA India) with realistic INR prices, balancing function, style and price.
estimated_price is the price of ONE unit; the sum of price x quantity over all items must stay within the budget.
Return ONLY JSON:
{{"budget_breakdown":[{{"category":"lighting|ceiling_fans|furniture|dining_tables","allocation":0,"items":[{{"name":"","description":"","estimated_price":0,"quantity":1,"search_terms":""}}]}}],"additional_suggestions":["tip"]}}"""


def _home_fallback(b):
    spec = [("lighting", "LED light fixture", "Energy-efficient LED light", b.num_lights, .2),
            ("ceiling_fans", "Ceiling fan", "BEE 5-star energy saving ceiling fan", b.num_fans, .3),
            ("furniture", "Furniture piece", "Basic sofa, chair or storage unit", b.num_furniture, .3),
            ("dining_tables", "Dining table", "Compact dining table with chairs", b.num_dining_tables, .2)]
    spec = [s for s in spec if s[3] > 0] or [("furniture", "Furniture piece", "Basic furniture", 1, 1)]
    wsum = sum(s[4] for s in spec)
    cats = []
    for cat, name, desc, qty, w in spec:
        alloc = b.total_budget * 0.9 * w / wsum
        cats.append({"category": cat, "allocation": round(alloc, 2), "items": [
            {"name": name, "description": desc, "estimated_price": round(alloc / qty, 2),
             "quantity": qty, "search_terms": name}]})
    return {"budget_breakdown": cats,
            "additional_suggestions": ["Compare prices across platforms before buying."]}


def get_home_recommendations(b: HomeBudgetInput):
    try:
        return _normalize(ask_gemini(_home_prompt(b)), b.total_budget, lambda c: HOME_PLATFORMS)
    except Exception as e:
        r = _normalize(_home_fallback(b), b.total_budget, lambda c: HOME_PLATFORMS)
        r["notice"] = f"AI unavailable, showing default suggestions ({_short(e)})"
        return r


# ---------- Party ----------
def _party_prompt(b: PartyBudgetInput):
    needs = [n for n, f in (("catering", b.needs_catering), ("decoration", b.needs_decoration),
                            ("entertainment", b.needs_entertainment)) if f]
    return f"""You are a party budget planner for the Indian market.
Total budget: Rs {b.total_budget:,.0f}. Event: {b.party_type}. Guests: {b.num_guests}. Venue: {b.venue_type or 'not specified'}.
Needed services: {', '.join(needs) or 'venue only'}. Extra requirements: {b.additional_requirements or 'None'}.
Split the budget proportionally across venue, {', '.join(needs)} and a small contingency. Use realistic INR prices for India (vendors on Swiggy, Zomato, Amazon, Flipkart, BookMyShow, OYO).
estimated_price is the price of ONE unit (for example per plate); the sum of price x quantity over all items must not exceed the budget.
Return ONLY JSON:
{{"budget_breakdown":[{{"category":"venue|catering|decoration|entertainment|contingency","allocation":0,"items":[{{"name":"","description":"","estimated_price":0,"quantity":1,"search_terms":""}}]}}],"venue_suggestions":[{{"name":"","type":"","capacity":0,"estimated_cost":0,"search_terms":""}}],"additional_suggestions":["tip"]}}"""


def _party_fallback(b):
    parts = [("venue", "Venue booking", "Home setup or local community hall", .15, 1)]
    if b.needs_catering:
        parts.append(("catering", "Catering per guest", "Meal per plate", .40, b.num_guests))
    if b.needs_decoration:
        parts.append(("decoration", "Theme decoration kit", "Balloons, banners and lights", .20, 1))
    if b.needs_entertainment:
        parts.append(("entertainment", "Music and games", "Speaker rental and party games", .15, 1))
    parts.append(("contingency", "Contingency buffer", "Unexpected expenses", .10, 1))
    wsum = sum(p[3] for p in parts)
    cats = []
    for cat, name, desc, w, qty in parts:
        alloc = b.total_budget * 0.95 * w / wsum
        cats.append({"category": cat, "allocation": round(alloc, 2), "items": [
            {"name": name, "description": desc, "estimated_price": round(alloc / qty, 2),
             "quantity": qty, "search_terms": f"{b.party_type} {name}"}]})
    return {"budget_breakdown": cats, "venue_suggestions": [],
            "additional_suggestions": ["Consider a potluck style meal to reduce catering costs."]}


def get_party_recommendations(b: PartyBudgetInput):
    fn = lambda c: PARTY_PLATFORMS.get(c.lower().strip(), DEFAULT_PARTY)
    try:
        r = _normalize(ask_gemini(_party_prompt(b)), b.total_budget, fn)
    except Exception as e:
        r = _normalize(_party_fallback(b), b.total_budget, fn)
        r["notice"] = f"AI unavailable, showing default suggestions ({_short(e)})"
    venues = [v for v in (r.get("venue_suggestions") or []) if isinstance(v, dict)]
    for v in venues:
        v["estimated_cost"] = num(v.get("estimated_cost"))
        add_links(v, VENUE_PLATFORMS)
    r["venue_suggestions"] = venues
    return r


# ---------- Jewelry ----------
def _jewelry_prompt(b: JewelryBudgetInput, has_image):
    outfit = ('An outfit image is attached. Analyse its colors, style and formality and suggest jewelry that complements it.\n'
              '"outfit_analysis":{"colors":[],"style":"","formality":""},') if has_image else ""
    return f"""You are a jewelry stylist for the Indian market.
Total budget: Rs {b.total_budget:,.0f}. Occasion: {b.occasion}. Style preferences: {b.preferences or 'Not specified'}.
Suggest 3 to 5 pieces available in India with realistic INR prices; the total of all estimated_price values must stay within the budget.
Return ONLY JSON like:
{{{outfit}"jewelry_recommendations":[{{"item_type":"","description":"","style":"","estimated_price":0,"search_terms":""}}],"styling_tips":["tip"]}}"""


def _jewelry_fallback(b):
    spec = [("earrings", "Elegant earrings", .35), ("necklace", "Matching necklace or pendant", .35),
            ("bracelet", "Simple bracelet or ring", .20)]
    return {"jewelry_recommendations": [
        {"item_type": t, "description": d, "style": b.preferences or "classic",
         "estimated_price": round(b.total_budget * w, 2), "search_terms": f"{b.occasion} {t}"}
        for t, d, w in spec],
        "styling_tips": ["Keep metal tones consistent across pieces."]}


def get_jewelry_recommendations(b: JewelryBudgetInput, image_path=None):
    notice = None
    try:
        r = ask_gemini(_jewelry_prompt(b, bool(image_path)), image_path)
        if not isinstance(r.get("jewelry_recommendations"), list) or not r["jewelry_recommendations"]:
            raise ValueError("Model returned no jewelry items")
    except Exception as e:
        r = _jewelry_fallback(b)
        notice = f"AI unavailable, showing default suggestions ({_short(e)})"
    spent = 0.0
    r["jewelry_recommendations"] = [i for i in r["jewelry_recommendations"] if isinstance(i, dict)]
    for it in r["jewelry_recommendations"]:
        it["estimated_price"] = num(it.get("estimated_price"))
        spent += it["estimated_price"]
        add_links(it, JEWELRY_PLATFORMS)
    r["total_budget"] = b.total_budget
    r["remaining_budget"] = round(b.total_budget - spent, 2)
    r["styling_tips"] = [str(t) for t in (r.get("styling_tips") or [])]
    if spent > b.total_budget:
        r["styling_tips"].insert(0, f"Estimated cost is Rs {spent - b.total_budget:,.0f} over budget; choose fewer pieces.")
    if notice:
        r["notice"] = notice
    return r
