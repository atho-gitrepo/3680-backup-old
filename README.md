# ⚽ Live Betting Bot with Telegram Alerts

This bot monitors live football matches using the [API-Football v3](https://www.api-football.com/documentation-v3) and sends Telegram alerts for correct score bets at the 36' and 80' minute.

## 🧠 Strategy
- 🔹 Bet on the correct score at 36'
- 🔹 If that bet wins at HT, stop.
- 🔹 If it loses, chase the correct score at 80'
- 🔹 Telegram alerts sent at each stage

## 🔧 Features
- Live match tracking (via API-Football)
- Telegram integration
- Flask web server for uptime pings & status
- UptimeRobot-compatible /ping endpoint

---

## 🚀 Deploy in Cloud (Render or Railway)

### 1. Push Code to GitHub
Make sure your files are structured like this:

/
├── web/                  # Web dashboard service
│   ├── web.py
│   ├── __init__.py
│   └── templates/        # (Optional, not used if rendering from string)
├── worker/               # Bot loop service
│   └── main.py
│   └── bot.py
├── .env                  # API keys & secrets (NOT committed)
├── requirements.txt
├── render.yaml           # Deploy config
└── README.md
