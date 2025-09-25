# discount-agent

Собирает акции из Biedronka и Kaufland и шлёт дайджест в Telegram.
Запуск — ежедневно 09:00 Europe/Warsaw через GitHub Actions.

## Быстрый старт
1) В Settings → Secrets → Actions добавьте `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
2) Откройте вкладку **Actions** → включите и запустите **Deals Agent** (Run workflow).
3) Сообщение “✅ GitHub Actions: бот жив.” должно прийти в Telegram.
