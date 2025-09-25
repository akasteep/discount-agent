import os
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import re
import urllib.parse
import urllib.request
import io, requests
from pdf2image import convert_from_bytes
import pytesseract

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
def ocr_pdf_text_from_url(pdf_url: str, dpi: int = 200) -> str:
    """Скачивает PDF, конвертит в изображения и вытаскивает текст через Tesseract (pl+eng)."""
    resp = requests.get(pdf_url, timeout=60)
    resp.raise_for_status()
    images = convert_from_bytes(resp.content, dpi=dpi)  # требует poppler
    text_chunks = []
    for img in images:
        txt = pytesseract.image_to_string(img, lang="pol+eng")
        if txt:
            text_chunks.append(txt)
    return "\n".join(text_chunks)

def biedronka_extract_deals_from_text(text: str) -> List[Dict]:
    """Грубый разбор текста из летучки: находит строки с ценой и рядом с ними имя товара."""
    deals = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        price = parse_price(line)
        if not price:
            continue
        # ищем название рядом (строка до/после)
        name_candidates = []
        if i > 0: name_candidates.append(lines[i-1])
        if i+1 < len(lines): name_candidates.append(lines[i+1])
        # выбираем самую адекватную подпись (не из одних чисел)
        name = None
        for cand in name_candidates:
            if len(cand) >= 4 and not PRICE_RE.fullmatch(cand.replace(",", ".").replace(" ", "")):
                name = cand
                break
        if not name:
            continue
        deals.append({
            "store": "Biedronka",
            "product_name": name[:120],
            "price": price,
            "regular_price": None,
            "discount_pct": None,
            "url": "https://www.biedronka.pl",
        })
    # уникализируем приблизительно по названию+цене
    uniq = {}
    for d in deals:
        key = (normalize(d["product_name"]), d["price"])
        if key not in uniq:
            uniq[key] = d
    return list(uniq.values())
def fetch_biedronka(url: str) -> List[Dict]:
    """
    1) Пытаемся вытащить из HTML (если это обычная страница акций).
    2) Если ноль — пробуем OCR с PDF (летучки иногда только картинками).
    """
    # --- Попытка 1: HTML (как было)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = p.new_page()
            page.goto(url, timeout=90_000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            html = page.content()
            browser.close()
        soup = BeautifulSoup(html, "lxml")
        candidates = soup.find_all(lambda tag: tag.name in ("div","li","article")
                                   and ("zł" in tag.get_text(" ", strip=True)))
        deals = []
        for c in candidates:
            text = c.get_text(" ", strip=True)
            price = parse_price(text)
            if not price or len(text) < 15:
                continue
            name = None
            for sel in ["strong","b","h3","h4","h5"]:
                el = c.find(sel)
                if el and len(el.get_text(strip=True)) >= 5:
                    name = el.get_text(" ", strip=True); break
            if not name:
                name = text.split(" zł")[0][:80]
            deals.append({
                "store": "Biedronka",
                "product_name": name,
                "price": price,
                "regular_price": None,
                "discount_pct": None,
                "url": url
            })
        if deals:
            return deals
    except Exception as e:
        print("[WARN] Biedronka HTML parse failed:", e)

    # --- Попытка 2: PDF-OCR
    try:
        # Если дали прямую ссылку на пресс-PDF — используем её,
        # иначе попробуем найти первую ссылку на .pdf на странице press.
        pdf_url = None
        if url.lower().endswith(".pdf") or "press" in url:
            # или прислали URL страницы press с хешем #page=…
            if url.lower().endswith(".pdf"):
                pdf_url = url
            else:
                # вытащим первую .pdf ссылку с этой страницы
                r = requests.get(url.split("#")[0], timeout=30)
                r.raise_for_status()
                import re
                m = re.search(r'href="([^"]+\.pdf)"', r.text, re.IGNORECASE)
                if m:
                    pdf_url = m.group(1)
                    if pdf_url.startswith("/"):
                        pdf_url = "https://www.biedronka.pl" + pdf_url
        if not pdf_url:
            print("[WARN] Biedronka PDF url not found on page:", url)
            return []

        print("[INFO] Biedronka OCR from PDF:", pdf_url)
        text = ocr_pdf_text_from_url(pdf_url, dpi=220)
        deals = biedronka_extract_deals_from_text(text)
        print(f"[INFO] OCR extracted deals: {len(deals)}")
        return deals
    except Exception as e:
        print("[WARN] Biedronka OCR failed:", e)
        return []

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
    import urllib.parse, urllib.request, urllib.error, os
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[INFO] Telegram secrets are missing; skipping send.")
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=30) as r:
            print("[INFO] Telegram send status:", r.status)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"[WARN] Telegram HTTPError {e.code}: {body}")
    except Exception as e:
        print(f"[WARN] Telegram error: {e}")

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
            print("[DEBUG] всего собрано акций:", len(all_deals))
    for d in all_deals[:10]:
        print("[DEBUG]", d)

    hits = [d for d in all_deals if matches_target(d["product_name"], d.get("price"), d.get("discount_pct"))]

    if hits:
        lines = [f"🔖 {d['store']}: {d['product_name']} — {d.get('price','?')} zł ({d.get('discount_pct','?')}%)\n{d.get('url','')}" for d in hits]
        msg = "Новые акции (" + str(len(hits)) + "):\n\n" + "\n\n".join(lines)
    else:
        msg = "Новых акций по вашим правилам не найдено."

    send_telegram(msg)

if __name__ == "__main__":
    main()
