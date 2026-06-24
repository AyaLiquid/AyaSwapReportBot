# AyaSwapReportBot

Telegram-бот: копирует сообщения «фото + текст» из одной группы в другую. Новые — раз в минуту, правки в исходнике — сразу.

[github.com/AyaLiquid/AyaSwapReportBot](https://github.com/AyaLiquid/AyaSwapReportBot)

## Какую задачу решает

Дублирует выписки (фото с подписью) из исходной группы в целевую. Если автор правит сообщение — бот обновляет копию в целевой группе. Сообщения только с текстом или только с фото пропускает.

## Для кого предназначен

Сотрудникам поддержки платёжных сервисов и командам, которым нужно переносить выписки между Telegram-чатами 24/7 без ручной работы.

## Как открыть или запустить проект

**Telegram:** `/newbot` в [@BotFather](https://t.me/BotFather) → токен. Отключить Group Privacy (`/mybots` → Bot Settings → Turn off). Добавить бота в обе группы. ID чатов — [@getidsbot](https://t.me/getidsbot).

**Локально:**

```bash
git clone https://github.com/AyaLiquid/AyaSwapReportBot.git
cd AyaSwapReportBot
pip install -r requirements.txt
cp .env.example .env   # BOT_TOKEN, SOURCE_CHAT_ID, TARGET_CHAT_ID
python bot.py
```

**Railway:** [railway.app](https://railway.app) → Deploy from GitHub → Variables: `BOT_TOKEN`, `SOURCE_CHAT_ID`, `TARGET_CHAT_ID`.

## Как в создании проекта использовался Cursor

В [Cursor](https://cursor.com) описали задачу на обычном языке — агент составил план (с учётом отсутствия прав админа в группах), написал и дорабатывал код (`bot.py`, конфиги деплоя), помог с git и GitHub. Токен, группы и секреты на Railway автор настроил вручную.
