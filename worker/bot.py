
import requests
from dotenv import load_dotenv
load_dotenv()
import os, json, time
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

API_KEY = os.getenv("API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HEADERS = {'x-apisports-key': API_KEY}
BASE_URL = 'https://v3.football.api-sports.io'

STATUS_FILE = os.path.join(os.path.dirname(__file__), "..", "bot_status.json")
STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "tracked_matches.json")

def log_environment():
    """Log critical environment variables (masking sensitive info)"""
    logger.info("Environment check:")
    logger.info(f"API_KEY present: {'Yes' if API_KEY else 'No'}")
    logger.info(f"TELEGRAM_TOKEN present: {'Yes' if TELEGRAM_TOKEN else 'No'}")
    logger.info(f"TELEGRAM_CHAT_ID present: {'Yes' if TELEGRAM_CHAT_ID else 'No'}")
    logger.info(f"STATUS_FILE path: {STATUS_FILE}")
    logger.info(f"STATE_FILE path: {STATE_FILE}")

# --- Load bot_status ---
try:
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            bot_status = json.load(f)
        logger.info(f"Loaded bot_status from {STATUS_FILE}")
    else:
        bot_status = {"last_check": "Not yet run", "active_matches": []}
        logger.warning(f"No status file found at {STATUS_FILE}, using defaults")
except Exception as e:
    bot_status = {"last_check": "Not yet run", "active_matches": []}
    logger.error(f"Error loading bot_status: {e}, using defaults")

# --- Load or initialize tracked_matches ---
try:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            tracked_matches = json.load(f)
        logger.info(f"Loaded tracked_matches from {STATE_FILE} ({len(tracked_matches)} matches)")
    else:
        tracked_matches = {}
        logger.warning(f"No state file found at {STATE_FILE}, initializing empty")
except Exception as e:
    tracked_matches = {}
    logger.error(f"Error loading tracked_matches: {e}, initializing empty")

def save_tracked_matches():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(tracked_matches, f)
        logger.info(f"Saved tracked_matches to {STATE_FILE}")
    except Exception as e:
        logger.error(f"Failed to save tracked_matches: {e}")

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg}
        logger.info(f"Sending Telegram message: {msg[:100]}...")  # Log first 100 chars
        r = requests.post(url, data=data)
        if r.status_code == 200:
            logger.info("Telegram message sent successfully")
        else:
            logger.error(f"Telegram API error: {r.status_code} - {r.text}")
    except Exception as e:
        logger.error(f"Exception in send_telegram: {e}")

def get_live_matches():
    try:
        logger.info("Fetching live matches from API")
        res = requests.get(f"{BASE_URL}/fixtures?live=all", headers=HEADERS)
        if res.status_code != 200:
            logger.error(f"API ERROR: Status {res.status_code}, Response: {res.text}")
            return []
        
        matches = res.json().get("response", [])
        logger.info(f"Found {len(matches)} live matches")
        return matches
    except Exception as e:
        logger.error(f"Exception in get_live_matches: {e}")
        return []

def get_match_details(fixture_id):
    try:
        logger.info(f"Fetching details for fixture {fixture_id}")
        res = requests.get(f"{BASE_URL}/fixtures?id={fixture_id}", headers=HEADERS)
        if res.status_code != 200:
            logger.error(f"API ERROR for fixture {fixture_id}: {res.status_code}")
            return None
        
        match_data = res.json().get('response', [])
        if not match_data:
            logger.warning(f"No data for fixture {fixture_id}")
            return None
            
        return match_data[0]
    except Exception as e:
        logger.error(f"Exception getting match details: {e}")
        return None

def process_match(match):
    try:
        fixture_id = match['fixture']['id']
        match_name = f"{match['teams']['home']['name']} vs {match['teams']['away']['name']}"
        league_name = match['league']['name']
        league_country = match['league']['country']
        league_info = f"{league_name} ({league_country})"
        score = match['goals']
        minute = match['fixture']['status']['elapsed']
        status = match['fixture']['status']['short']

        logger.info(f"Processing match: {match_name} (ID: {fixture_id}, {minute}', Status: {status})")

        if fixture_id not in tracked_matches:
            tracked_matches[fixture_id] = {
                '36_bet_placed': False,
                '36_result_checked': False,
                '80_bet_placed': False,
                '80_result_checked': False,
                'match_name': match_name,
                'league_info': league_info,
                'last_seen': datetime.now().isoformat(),
                'last_status': status,
                'last_minute': minute
            }
            logger.info(f"New match added to tracking: {match_name}")
        else:
            # Update last seen time and status
            tracked_matches[fixture_id]['last_seen'] = datetime.now().isoformat()
            tracked_matches[fixture_id]['last_status'] = status
            tracked_matches[fixture_id]['last_minute'] = minute

        state = tracked_matches[fixture_id]
        logger.debug(f"Current state for {match_name}: {state}")

        # 36' Bet logic
        if 35 <= minute <= 37 and not state['36_bet_placed']:
            score_36 = f"{score['home']}-{score['away']}"
            state['score_36'] = score_36
            state['36_bet_placed'] = True
            state['36_bet_time'] = datetime.now().isoformat()
            logger.info(f"36' bet condition met for {match_name}, score: {score_36}")
            send_telegram(f"⏱️ 36' - {match_name}\n🏆 {league_info}\n🔢 Score: {score_36}\n🎯 First Bet Placed")

        # HT check
        if status == 'HT' and state['36_bet_placed'] and not state['36_result_checked']:
            current_score = f"{score['home']}-{score['away']}"
            state['ht_score'] = current_score
            if current_score == state['score_36']:
                logger.info(f"36' bet WON for {match_name}")
                send_telegram(f"✅ HT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {current_score}\n🎉 36' Bet WON")
                state['skip_80'] = True
            else:
                logger.info(f"36' bet LOST for {match_name}")
                send_telegram(f"❌ HT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {current_score}\n🔁 36' Bet LOST — chasing at 80'")
            state['36_result_checked'] = True

        # 80' Chase logic
        if 79 <= minute <= 81 and state['36_result_checked'] and not state.get('skip_80', False) and not state['80_bet_placed']:
            score_80 = f"{score['home']}-{score['away']}"
            state['score_80'] = score_80
            state['80_bet_placed'] = True
            state['80_bet_time'] = datetime.now().isoformat()
            logger.info(f"80' bet condition met for {match_name}, score: {score_80}")
            send_telegram(f"⏱️ 80' - {match_name}\n🏆 {league_info}\n🔢 Score: {score_80}\n🎯 Chase Bet Placed")

        # FT check for 80' bet (immediate if match is FT)
        if status == 'FT' and state['80_bet_placed'] and not state['80_result_checked']:
            final_score = f"{score['home']}-{score['away']}"
            state['final_score'] = final_score
            if final_score == state['score_80']:
                logger.info(f"80' chase bet WON for {match_name}")
                send_telegram(f"✅ FT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {final_score}\n🎉 Chase Bet WON")
            else:
                logger.info(f"80' chase bet LOST for {match_name}")
                send_telegram(f"❌ FT Result: {match_name}\n🏆 {league_info}\n🔢 Score: {final_score}\n📉 Chase Bet LOST")
            state['80_result_checked'] = True

    except Exception as e:
        logger.error(f"Error processing match {match.get('fixture', {}).get('id', 'unknown')}: {e}")

def check_pending_80_bets():
    logger.info("Checking pending 80' bets...")
    now = datetime.now()
    pending_bets = 0
    resolved_bets = 0
    
    for fixture_id, state in list(tracked_matches.items()):
        # Skip if no 80' bet placed or already resolved
        if not state.get('80_bet_placed') or state.get('80_result_checked'):
            continue
            
        # Skip if bet was placed recently (within 15 minutes)
        if '80_bet_time' in state:
            bet_time = datetime.fromisoformat(state['80_bet_time'])
            if (now - bet_time).total_seconds() < 900:  # 15 minutes
                continue
                
        pending_bets += 1
        match_name = state.get('match_name', f"Fixture {fixture_id}")
        
        # Get updated match data
        match = get_match_details(fixture_id)
        if not match:
            logger.warning(f"Couldn't get updated data for {match_name}")
            continue
            
        status = match['fixture']['status']['short']
        
        # If match is finished, resolve the bet
        if status == 'FT':
            final_score = f"{match['goals']['home']}-{match['goals']['away']}"
            state['final_score'] = final_score
            state['80_result_checked'] = True
            resolved_bets += 1
            
            if final_score == state['score_80']:
                logger.info(f"80' chase bet WON for {match_name}")
                send_telegram(f"✅ FT Result: {match_name}\n🏆 {state.get('league_info', '')}\n🔢 Score: {final_score}\n🎉 Chase Bet WON")
            else:
                logger.info(f"80' chase bet LOST for {match_name}")
                send_telegram(f"❌ FT Result: {match_name}\n🏆 {state.get('league_info', '')}\n🔢 Score: {final_score}\n📉 Chase Bet LOST")
        else:
            logger.info(f"Match {match_name} still in progress (Status: {status})")
    
    logger.info(f"Checked {pending_bets} pending bets, resolved {resolved_bets}")

def save_bot_status(last_check, matches):
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump({"last_check": last_check, "active_matches": matches}, f)
        logger.info(f"Saved bot status with {len(matches)} active matches")
    except Exception as e:
        logger.error(f"Error saving bot status: {e}")

def run_bot_once():
    try:
        logger.info("--- Starting bot cycle ---")
        log_environment()
        
        logger.info("Fetching live matches")
        lives = get_live_matches()
        
        match_list = [f"{m['teams']['home']['name']} vs {m['teams']['away']['name']} ({m['fixture']['status']['elapsed']}')" 
                     for m in lives]
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_bot_status(timestamp, match_list)
        logger.info(f"Tracking {len(lives)} matches: {', '.join(match_list[:3])}{'...' if len(match_list) > 3 else ''}")

        for idx, m in enumerate(lives, 1):
            logger.info(f"Processing match {idx}/{len(lives)}")
            process_match(m)
        
        # Check for any pending 80' bets that need resolution
        check_pending_80_bets()
        
        save_tracked_matches()
        logger.info("--- Completed bot cycle ---\n")
    except Exception as e:
        logger.error(f"Fatal error in run_bot_once: {e}")

def run_continuous_poll(minutes=120, interval=60):
    logger.info(f"Starting continuous polling for {minutes} minutes with {interval} second interval")
    end = datetime.now().timestamp() + minutes * 60
    cycle = 0
    
    while datetime.now().timestamp() < end:
        cycle += 1
        logger.info(f"\n=== Polling cycle {cycle} ===")
        try:
            run_bot_once()
        except Exception as e:
            logger.error(f"Error in polling cycle {cycle}: {e}")
        
        logger.info(f"Sleeping for {interval} seconds")
        time.sleep(interval)
    
    logger.info("Polling completed")

if __name__ == "__main__":
    logger.info("===== Bot Starting =====")
    log_environment()
    
    try:
        # Either run once (for cron every minute)
        # run_bot_once()

        # Or keep alive for 2 hours, polling every minute:
        run_continuous_poll(minutes=120, interval=60)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
    finally:
        logger.info("===== Bot Shutting Down =====")