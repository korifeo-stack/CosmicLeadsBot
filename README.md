# CosmicLeadsBot

Telegram-бот для лид-магнита с обязательной подпиской на канал и мгновенными уведомлениями владельцу.

## Важно по вашему запросу
- Бот работает **без базы данных**.
- Никакие лиды не пишутся в БД/файлы.
- В память процесса сохраняется только временный state на 1 следующее сообщение (для кнопок «дашборд/демо»).

## Что реализовано
- Deeplink `/start <start_param>`; если параметра нет, используется `organic`.
- Сценарий получения PDF только после подписки на канал `@aicosmicnews`.
- Проверка подписки через `getChatMember`.
- Пост-выдача кнопки: пример дашборда, скрипты фидбека, хочу демо.
- Сбор двух типов заявок (дашборд/демо) в память процесса (без БД/файлов).
- Уведомления владельцу по всем ключевым событиям + событие `error`.

## Быстрый запуск на Windows
1. Установите Python 3.11+.
2. В папке проекта запустите:
   ```bat
   start_windows.bat
   ```
3. При первом запуске создастся `.env` из `.env.example`.
4. Заполните в `.env` минимум:
   - `BOT_TOKEN`
   - `ADMIN_CHAT_ID` (или оставьте пустым и используйте `ADMIN_PASSWORD`)
   - `PDF_PATH` (или `PDF_URL`)
5. Запустите `start_windows.bat` ещё раз.

6. Если хотите без ручного поиска `chat_id`:
   - укажите `ADMIN_PASSWORD` в `.env` (например `1219991`)
   - напишите боту это число отдельным сообщением после `/start`
   - бот запомнит ваш `chat_id` в памяти процесса и начнёт слать вам лиды/контакты

> `.env` подхватывается автоматически, вручную экспортировать переменные не нужно.

## Установка (Linux/macOS)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env`:
- `BOT_TOKEN`
- `CHANNEL_USERNAME` (по ТЗ: `@aicosmicnews`)
- `ADMIN_CHAT_ID` (числовой `chat_id`) **или** `ADMIN_PASSWORD` для автопривязки админа через сообщение в бота
- `PDF_PATH` или `PDF_URL`

## Запуск (Linux/macOS)
```bash
python bot.py
```

## Важно (пререквизиты)
1. Бот должен быть админом канала `@aicosmicnews`, иначе проверка подписки может возвращать ошибку.
2. Дмитрий `@dvshalin` должен один раз написать боту `/start`, после чего нужно взять его `user_id`/`chat_id` и указать в `ADMIN_CHAT_ID`.

## Текст для BotFather (вручную владельцем)
```
✨ Привет! Я бот CosmicMind — контроля сервиса в ресторане: голосовые отзывы → категории → задачи → дашборд.
🎁 Нажми /start 🚀 — выдам PDF «Контроль сервиса за 10 минут в день».
/help ⚙️
```

---

## Site lead integration · POST /api/site-lead

Добавлен HTTP-endpoint, чтобы заявки с лендинга `cosmicmind.ru` прилетали в этот же чат админа в едином формате.

**Endpoint:** `POST http://127.0.0.1:8001/api/site-lead`

**Headers:**
- `Content-Type: application/json`
- `X-Site-Token: <SITE_LEAD_TOKEN>` — должен совпадать с `.env` бота

**Body (JSON):**
```json
{
  "name":    "Иван",
  "phone":   "+7 999 000-00-00",
  "company": "Tokyo-City",
  "size":    "6–15",
  "source":  "hero_primary",
  "page":    "/",
  "ts":      "2026-05-07T18:30:00Z"
}
```

**Ответ:**
- `200 OK` → `{"ok": true}` — заявка ушла в чат админа (форматом «🛎 Заявка с лендинга»)
- `400` — нет name/phone
- `401` — неверный X-Site-Token
- `503` — `ADMIN_CHAT_ID` ещё не настроен (напиши боту пароль через `ADMIN_PASSWORD` или впиши в .env)

### Конфигурация

В `.env`:
```bash
SITE_LEAD_HOST=127.0.0.1   # bind только на localhost — наружу не отдаём
SITE_LEAD_PORT=8001
SITE_LEAD_TOKEN=<openssl rand -hex 32>
```

Тот же `SITE_LEAD_TOKEN` нужно прописать в `.env` лендинга (см. `siteCosmic` репо). Лендинг шлёт сюда → бот шлёт в Telegram → админ.

**Health check:**
```bash
curl http://127.0.0.1:8001/api/health
# {"ok":true,"admin_configured":true,"site_token_set":true}
```
