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
    fid     = match['fixture']['id']
    mn      = f"{match['teams']['home']['name']} vs {match['teams']['away']['name']}"
    info    = f"{match['league']['name']} ({match['league']['country']})"
    score   = match['goals']
    minute  = match['fixture']['status']['elapsed']
    status  = match['fixture']['status']['short']

    state = tracked_matches.setdefault(fid, {
        '36_bet_placed':False,'36_result_checked':False,
        '80_bet_placed':False,'80_result_checked':False,'skip_80':False
    })

    # 36'
    if minute==36 and not state['36_bet_placed']:
        state['score_36']      = f"{score['home']}-{score['away']}"
        state['36_bet_placed']=True
        send_telegram(f"⏱ 36' {mn}\n{info}\nScore: {state['score_36']}\n🎯 First Bet")

    # HT
    if status=='HT' and state['36_bet_placed'] and not state['36_result_checked']:
        curr = f"{score['home']}-{score['away']}"
        if curr==state['score_36']:
            send_telegram(f"✅ HT Win {mn}\nScore: {curr}")
            state['skip_80']=True
        else:
            send_telegram(f"❌ HT Lose {mn}\nScore: {curr}\n🔁 Chase at 80'")
        state['36_result_checked']=True

    # 80'
    if minute==80 and state['36_result_checked'] and not state['skip_80'] and not state['80_bet_placed']:
        state['score_80']= f"{score['home']}-{score['away']}"
        state['80_bet_placed']=True
        send_telegram(f"⏱ 80' {mn}\nScore: {state['score_80']}\n🎯 Chase Bet")

    # FT
    if status=='FT' and state['80_bet_placed'] and not state['80_result_checked']:
        final = f"{score['home']}-{score['away']}"
        if final==state['score_80']:
            send_telegram(f"✅ FT Win {mn}\nScore: {final}")
        else:
            send_telegram(f"❌ FT Lose {mn}\nScore: {final}")
        state['80_result_checked']=True

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
