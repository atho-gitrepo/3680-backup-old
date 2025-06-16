import requests
from dotenv import load_dotenv
load_dotenv()
import os, json, time
from datetime import datetime

API_KEY         = os.getenv("API_KEY")
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID= os.getenv("TELEGRAM_CHAT_ID")
HEADERS         = {'x-apisports-key': API_KEY}
BASE_URL        = 'https://v3.football.api-sports.io'

STATUS_FILE     = os.path.join(os.path.dirname(__file__), "..", "bot_status.json")
STATE_FILE      = os.path.join(os.path.dirname(__file__), "..", "tracked_matches.json")

# --- Load bot_status (unchanged) ---
if os.path.exists(STATUS_FILE):
    with open(STATUS_FILE) as f:
        bot_status = json.load(f)
else:
    bot_status = {"last_check":"Not yet run","active_matches":[]}

# --- Load or initialize tracked_matches ---
if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE) as f:
            tracked_matches = json.load(f)
    except:
        tracked_matches = {}
else:
    tracked_matches = {}

def save_tracked_matches():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(tracked_matches, f)
    except Exception as e:
        print(f"❌ Failed to save tracked_matches: {e}")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data= {'chat_id':TELEGRAM_CHAT_ID,'text':msg}
    print(f"📤 {msg}")
    r = requests.post(url,data=data)
    print("✅" if r.status_code==200 else f"❌ {r.status_code} {r.text}")

def get_live_matches():
    res = requests.get(f"{BASE_URL}/fixtures?live=all", headers=HEADERS)
    if res.status_code!=200:
        print("❌ API ERROR",res.status_code)
        return []
    return res.json().get("response",[])

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

    # 36' Bet logic (trigger between 35–37 minutes)
    if 35 <= minute <= 37 and not state['36_bet_placed']:
        score_36 = f"{score['home']}-{score['away']}"
        state['score_36'] = score_36
        state['36_bet_placed'] = True
        send_telegram(f"⏱️ 36' - {match_name}\n🏆 {league_info}\n🔢 Score: {score_36}\n🎯 First Bet Placed")

    # HT check
    if status == 'HT' and state['36_bet_placed'] and not state['36_result_checked']:
        current_score = f"{score['home']}-{score['away']}"
        if current_score == state['score_36']:
            send_telegram(f"✅ HT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {current_score}\n🎉 36’ Bet WON")
            state['skip_80'] = True
        else:
            send_telegram(f"❌ HT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {current_score}\n🔁 36’ Bet LOST — chasing at 80’")
        state['36_result_checked'] = True

    # 80' Chase logic (trigger between 79–81 minutes)
    if 79 <= minute <= 81 and state['36_result_checked'] and not state.get('skip_80', False) and not state['80_bet_placed']:
        score_80 = f"{score['home']}-{score['away']}"
        state['score_80'] = score_80
        state['80_bet_placed'] = True
        send_telegram(f"⏱️ 80' - {match_name}\n🏆 {league_info}\n🔢 Score: {score_80}\n🎯 Chase Bet Placed")

    # FT check for 80' bet
    if status == 'FT' and state['80_bet_placed'] and not state['80_result_checked']:
        final_score = f"{score['home']}-{score['away']}"
        if final_score == state['score_80']:
            send_telegram(f"✅ FT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {final_score}\n🎉 Chase Bet WON")
        else:
            send_telegram(f"❌ FT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {final_score}\n📉 Chase Bet LOST")
        state['80_result_checked'] = True

def save_bot_status(last_check, matches):
    with open(STATUS_FILE,"w") as f:
        json.dump({"last_check":last_check,"active_matches":matches},f)

def run_bot_once():
    print(f"[{datetime.now()}] Checking live matches…")
    lives = get_live_matches()
    save_bot_status(datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    [f"{m['teams']['home']['name']} vs {m['teams']['away']['name']} ({m['fixture']['status']['elapsed']}’)" for m in lives])
    for m in lives:
        process_match(m)
    save_tracked_matches()

def run_continuous_poll(minutes=120, interval=60):
    end = datetime.now().timestamp() + minutes*60
    while datetime.now().timestamp() < end:
        run_bot_once()
        time.sleep(interval)

if __name__=="__main__":
    # Either run once (for cron every minute)
    # run_bot_once()

    # Or keep alive for 2 hours, polling every minute:
    run_continuous_poll(minutes=120, interval=60)
