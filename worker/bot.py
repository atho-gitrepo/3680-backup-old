import requests
from dotenv import load_dotenv
load_dotenv()
import os
import json
from datetime import datetime

API_KEY = os.getenv("API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {'x-apisports-key': API_KEY}
BASE_URL = 'https://v3.football.api-sports.io'
tracked_matches = {}

STATUS_FILE = os.path.join(os.path.dirname(__file__), "..", "bot_status.json")

# In-memory status to sync with JSON file
bot_status = {
    "last_check": "Not yet run",
    "active_matches": []
}

# Load existing status from file at startup if available
if os.path.exists(STATUS_FILE):
    try:
        with open(STATUS_FILE, "r") as f:
            bot_status = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load bot status on startup: {e}")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg}

    # Log the message you're about to send (can also write to a file)
    print(f"📤 Sending Telegram message:\n{msg}\n")
    response = requests.post(url, data=data)
    # Optional: log Telegram response for success/failure
    if response.status_code == 200:
        print(f"✅ Telegram message sent successfully")
    else:
        print(f"❌ Telegram failed with status {response.status_code}: {response.text}")

    return response

def get_live_matches():
    url = f"{BASE_URL}/fixtures?live=all"
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        print(f"❌ API ERROR: {res.status_code} - {res.text}")
        return []
    try:
        return res.json()['response']
    except Exception as e:
        print(f"❌ JSON Decode Error: {e}")
        return []

def process_match(match):
    fixture_id = match['fixture']['id']
    match_name = f"{match['teams']['home']['name']} vs {match['teams']['away']['name']}"
    league_name = match['league']['name']
    league_country = match['league']['country']
    league_info = f"{league_name} ({league_country})"
    score = match['goals']
    minute = match['fixture']['status']['elapsed']
    status = match['fixture']['status']['short']

    if fixture_id not in tracked_matches:
        tracked_matches[fixture_id] = {
            '36_bet_placed': False,
            '36_result_checked': False,
            '80_bet_placed': False,
            '80_result_checked': False,
            'match_name': match_name
        }

    state = tracked_matches[fixture_id]

    if minute == 36 and not state['36_bet_placed']:
        score_36 = f"{score['home']}-{score['away']}"
        state['score_36'] = score_36
        state['36_bet_placed'] = True
        send_telegram(f"⏱️ 36' - {match_name}\n🏆 {league_info}\n🔢 Score: {score_36}\n🎯 First Bet Placed")

    if status == 'HT' and state['36_bet_placed'] and not state['36_result_checked']:
        current_score = f"{score['home']}-{score['away']}"
        if current_score == state['score_36']:
            send_telegram(f"✅ HT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {current_score}\n🎉 36’ Bet WON")
            state['skip_80'] = True
        else:
            send_telegram(f"❌ HT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {current_score}\n🔁 36’ Bet LOST — chasing at 80’")
        state['36_result_checked'] = True

    if minute == 80 and state['36_result_checked'] and not state.get('skip_80', False) and not state['80_bet_placed']:
        score_80 = f"{score['home']}-{score['away']}"
        state['score_80'] = score_80
        state['80_bet_placed'] = True
        send_telegram(f"⏱️ 80' - {match_name}\n🏆 {league_info}\n🔢 Score: {score_80}\n🎯 Chase Bet Placed")

    if status == 'FT' and state['80_bet_placed'] and not state['80_result_checked']:
        final_score = f"{score['home']}-{score['away']}"
        if final_score == state['score_80']:
            send_telegram(f"✅ FT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {final_score}\n🎉 Chase Bet WON")
        else:
            send_telegram(f"❌ FT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {final_score}\n📉 Chase Bet LOST")
        state['80_result_checked'] = True

def save_bot_status(last_check, matches):
    global bot_status
    try:
        bot_status = {
            "last_check": last_check,
            "active_matches": matches
        }
        with open(STATUS_FILE, "w") as f:
            json.dump(bot_status, f)
    except Exception as e:
        print(f"❌ Failed to save bot status: {e}")

def run_bot_once():
    try:
        print(f"[{datetime.now()}] Checking live matches...")
        live_matches = get_live_matches()

        matches_list = [
            f"{m['teams']['home']['name']} vs {m['teams']['away']['name']} ({m['fixture']['status']['elapsed']}’)" 
            for m in live_matches
        ]

        save_bot_status(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), matches_list)

        for match in live_matches:
            process_match(match)

        return matches_list

    except Exception as e:
        print(f"❌ Error: {e}")
        return []
