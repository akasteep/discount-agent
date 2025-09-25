import os
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import re
import urllib.parse
import urllib.request

PRICE_RE = re.compile(r"(\d+[.,]\d+)")

TARGETS = [
    {"canonical": "Молоко 3,2% 1л", "synonyms": ["mleko 3,2", "mleko 3.2% 1l", "milk 3.2% 1l"], "max_price": 3.99},
    {"canonical": "Лосось филе", "synonyms": ["łosoś", "losos", "salmon"], "min_discount": 25},
]

def parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    m = PRICE_RE.search(text.replace("\xa0", " ").replace("zł", "").lower())
    if not m:
        return None
    return float(m.group(1).replace(",", "."))

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()

def matches_target(name: str, price: Optional[float], discount: Optional[float]) -> bool:
    n = normalize(name)
    for t in TARGETS:
        syns = [normalize(t["canonical"]), *[normalize(x) for x in t.get("synonyms", [])]]
        if any(s in n for s in syns):
            max_price = t.get("max_price")
            min_discount = t.get("min_discount")
            if max_price is not None and price is not None and price <= max_price:
                return True
            if min_discount is not None and discount is not None and discount >= min_discount:
                return True
            if max_price is None and min_discount is None:
                return True
    return False

def fetch_biedronka(url: str) -> List[Dict]:
    deals: List[Dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(url, timeout=60_000)
        page.wait_for_load_state("networkidle")
        html = page.content()
        browser.close()
    soup = BeautifulSoup(html, "lxml")
    candidates = soup.find_all(lambda tag: tag.name in ("div","li","article") and tag.get_text(strip=True) and ("zł" in tag.get_text() or "zl" in tag.get_text().lower()))
    for c in candidates:
        text = c.get_text(" ", strip=True)
        price = parse_price(text)
        if not price or len(text) < 15:
            continue
        name = None
        for sel in ["strong", "b", "h3", "h4", "h5"]:
            el = c.find(sel)
            if el and len(el.get_text(strip=True)) >= 5:
                name = el.get_text(" ", strip=True)
                break
        if not name:
            name = text.split(" zł")[0][:80]
        old_price = None
        for cls in ["old", "regular", "strike", "przekreslone"]:
            el = c.find(lambda t: t.name in ("span","div") and cls in " ".join(t.get("class", [])))
            if el:
                old_price = parse_price(el.get_text())
                break
        discount_pct = round(100*(1 - price/old_price), 1) if old_price and price else None
        a = c.find("a"); href = a.get("href") if a else url
        deals.append({
            "store": "Biedronka",
            "product_name": name,
            "price": price,
            "regular_price": old_price,
            "discount_pct": discount_pct,
            "url": href if (href and href.startswith("http")) else url
        })
    uniq = {}
    for d in deals:
        key = (d["product_name"].lower(), d["price"])
        if key not in uniq:
            uniq[key] = d
    return list(uniq.values())

def fetch_kaufland(url: str) -> List[Dict]:
    deals: List[Dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(url, timeout=60_000)
        page.wait_for_load_state("networkidle")
        html = page.content()
        browser.close()
    soup = BeautifulSoup(html, "lxml")
    candidates = soup.find_all(lambda tag: tag.name in ("div","li","article") and "zł" in tag.get_text(" ", strip=True))
    for c in candidates:
        text = c.get_text(" ", strip=True)
        price = parse_price(text)
        if not price or len(text) < 15:
            continue
        name = None
        for sel in ["h3","h4",".product__title",".tile__title","strong","b"]:
            el = c.select_one(sel) if sel.startswith(".") else c.find(sel)
            if el and len(el.get_text(strip=True)) >= 5:
                name = el.get_text(" ", strip=True)
                break
        if not name:
            name = text.split(" zł")[0][:80]
        old_price = None
        for sel in [".old-price",".price--old",".regular-price",".price__striked"]:
            el = c.select_one(sel)
            if el:
                old_price = parse_price(el.get_text())
                break
        discount_pct = round(100*(1 - price/old_price), 1) if old_price and price else None
        a = c.find("a"); href = a.get("href") if a else url
        deals.append({
            "store": "Kaufland",
            "product_name": name,
            "price": price,
            "regular_price": old_price,
            "discount_pct": discount_pct,
            "url": href if (href and href.startswith("http")) else url
        })
    uniq = {}
    for d in deals:
        key = (d["product_name"].lower(), d["price"])
        if key not in uniq:
            uniq[key] = d
    return list(uniq.values())

def send_telegram(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[INFO] Telegram secrets are missing; skipping send.")
        return
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        print("[INFO] Telegram send status:", r.status)

def main():
    stores = [
        {"name": "Biedronka", "url": "https://www.biedronka.pl/pl/gazetki"},
        {"name": "Kaufland",  "url": "https://sklep.kaufland.pl/oferta.html"},
    ]
    all_deals: List[Dict] = []
    for s in stores:
        try:
            if s["name"].lower() == "biedronka":
                all_deals += fetch_biedronka(s["url"])
            elif s["name"].lower() == "kaufland":
                all_deals += fetch_kaufland(s["url"])
        except Exception as e:
            print(f"[WARN] {s['name']} failed: {e}")

    hits = [d for d in all_deals if matches_target(d["product_name"], d.get("price"), d.get("discount_pct"))]

    if hits:
        lines = [f"🔖 {d['store']}: {d['product_name']} — {d.get('price','?')} zł ({d.get('discount_pct','?')}%)\n{d.get('url','')}" for d in hits]
        msg = "Новые акции (" + str(len(hits)) + "):\n\n" + "\n\n".join(lines)
    else:
        msg = "Новых акций по вашим правилам не найдено."

    send_telegram(msg)

if __name__ == "__main__":
    main()
