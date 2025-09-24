import os
import requests
from bs4 import BeautifulSoup
import json

# --- Конфигурация ---
# Список интересующих продуктов (ключевые слова для поиска)
PRODUCTS_TO_TRACK = ["mleko", "masło", "chleb", "jajka", "ser żółty", "kurczak"]

# --- Функции для скрейпинга ---

def scrape_biedronka():
    """
    Функция для скрейпинга акций с сайта Biedronka.
    Примечание: Структура сайта может меняться, что потребует обновления этого кода.
    """
    found_products = {}
    try:
        # Biedronka часто использует динамическую загрузку, прямой скрейпинг может быть затруднен.
        # Этот пример демонстрирует базовый подход.
        # Для более надежного решения может потребоваться анализ сетевых запросов сайта.
        # В данном примере мы будем использовать условный поиск по главной странице.
        url = "https://www.biedronka.pl/pl"
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Поиск по текстовому содержимому на странице
        page_text = soup.get_text().lower()
        for product in PRODUCTS_TO_TRACK:
            if product.lower() in page_text:
                # Нашли упоминание, но без деталей о цене.
                # Для более точной информации нужен более сложный скрейпинг.
                if "Biedronka" not in found_products:
                    found_products["Biedronka"] = []
                found_products["Biedronka"].append(f"Znaleziono wzmiankę o produkcie: {product.capitalize()}")

    except requests.exceptions.RequestException as e:
        print(f"Błąd podczas парсинга Biedronka: {e}")
    return found_products

def scrape_kaufland():
    """
    Функция для скрейпинга акций с сайта Kaufland.
    Примечание: Структура сайта может меняться, что потребует обновления этого кода.
    """
    found_products = {}
    try:
        # Аналогично Biedronka, Kaufland может использовать сложную структуру.
        # Этот пример демонстрирует общий подход.
        url = "https://www.kaufland.pl/oferta.html"
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        page_text = soup.get_text().lower()
        for product in PRODUCTS_TO_TRACK:
            if product.lower() in page_text:
                if "Kaufland" not in found_products:
                    found_products["Kaufland"] = []
                found_products["Kaufland"].append(f"Znaleziono wzmiankę o produkcie: {product.capitalize()}")

    except requests.exceptions.RequestException as e:
        print(f"Błąd podczas парсинга Kaufland: {e}")
    return found_products


# --- Функция для отправки уведомлений в Telegram ---

def send_telegram_message(message):
    """
    Отправляет сообщение в Telegram чат.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Ошибка: Переменные окружения TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID не установлены.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Сообщение успешно отправлено в Telegram.")
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при отправке сообщения в Telegram: {e}")
        print(response.json())

# --- Основная логика ---

if __name__ == "__main__":
    all_found_products = {}
    all_found_products.update(scrape_biedronka())
    all_found_products.update(scrape_kaufland())

    if not all_found_products:
        print("Не найдено скидок на отслеживаемые продукты.")
        # Для отладки можно раскомментировать следующую строку, чтобы всегда получать уведомление
        # send_telegram_message("Не найдено скидок на отслеживаемые продукты.")
    else:
        message_body = "🔥 *Найдены скидки на интересующие вас товары:*\n\n"
        for store, products in all_found_products.items():
            message_body += f"🛒 *{store}*\n"
            for product_info in products:
                message_body += f"- {product_info}\n"
            message_body += "\n"

        send_telegram_message(message_body)
