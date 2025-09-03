import requests
import os
import json
import time
import logging
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("FootballBettingBot")

# Load environment variables
API_KEY = os.getenv("API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FIREBASE_CREDENTIALS_JSON_STRING = os.getenv("FIREBASE_CREDENTIALS_JSON")

HEADERS = {
    'x-rapidapi-key': API_KEY,
    'x-rapidapi-host': 'v3.football.api-sports.io'
}
BASE_URL = 'https://v3.football.api-sports.io'

# --- CONSTANTS ---
SLEEP_TIME = 90
MINUTES_REGULAR_BET = [35, 36, 37]
MINUTES_CHASE_BET = [79, 80, 81]
BET_TYPE_REGULAR = 'regular'
BET_TYPE_CHASE = 'chase'
STATUS_LIVE = ['LIVE', '1H', '2H', 'ET', 'P']
STATUS_HALFTIME = 'HT'
STATUS_FINISHED = ['FT', 'AET', 'PEN']

class FirebaseManager:
    """Manages all interactions with the Firebase Firestore database."""
    def __init__(self, credentials_json_string):
        try:
            logger.info("Initializing Firebase...")
            if not credentials_json_string:
                raise ValueError("FIREBASE_CREDENTIALS_JSON is empty. Please set the environment variable.")
            cred_dict = json.loads(credentials_json_string)
            cred = credentials.Certificate(cred_dict)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            logger.info("Firebase initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            raise

    def get_tracked_match(self, match_id):
        try:
            doc = self.db.collection('tracked_matches').document(str(match_id)).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Firestore Error during get_tracked_match: {e}")
            return None

    def update_tracked_match(self, match_id, data):
        try:
            self.db.collection('tracked_matches').document(str(match_id)).set(data, merge=True)
        except Exception as e:
            logger.error(f"Firestore Error during update_tracked_match: {e}")

    def get_unresolved_bets(self):
        try:
            bets = self.db.collection('unresolved_bets').stream()
            result = {doc.id: doc.to_dict() for doc in bets}
            return result
        except Exception as e:
            logger.error(f"Firestore Error during get_unresolved_bets: {e}")
            return {}
    
    def get_stale_unresolved_bets(self, minutes_to_wait=20):
        """
        Retrieves unresolved bets from Firestore that were placed more than `minutes_to_wait` ago.
        These are bets that are likely for a finished match and need a final result check.
        """
        try:
            bets = self.db.collection('unresolved_bets').stream()
            stale_bets = {}
            time_threshold = datetime.utcnow() - timedelta(minutes=minutes_to_wait)
            
            for doc in bets:
                bet_info = doc.to_dict()
                placed_at_str = bet_info.get('placed_at')
                if placed_at_str:
                    try:
                        placed_at_dt = datetime.strptime(placed_at_str, '%Y-%m-%d %H:%M:%S')
                        if placed_at_dt < time_threshold:
                            stale_bets[doc.id] = bet_info
                    except ValueError:
                        logger.warning(f"Could not parse placed_at timestamp for bet {doc.id}")
                        continue
            return stale_bets
        except Exception as e:
            logger.error(f"Firestore Error during get_stale_unresolved_bets: {e}")
            return {}

    def add_unresolved_bet(self, match_id, data):
        try:
            # Add a timestamp when the bet was placed
            data['placed_at'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            self.db.collection('unresolved_bets').document(str(match_id)).set(data)
        except Exception as e:
            logger.error(f"Firestore Error during add_unresolved_bet: {e}")

    def move_to_resolved(self, match_id, bet_info, outcome):
        try:
            resolved_data = {
                **bet_info,
                'outcome': outcome,
                'resolved_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'resolution_timestamp': firestore.SERVER_TIMESTAMP
            } 
            self.db.collection('resolved_bets').document(str(match_id)).set(resolved_data)
            self.db.collection('unresolved_bets').document(str(match_id)).delete()
            return True
        except Exception as e:
            logger.error(f"Firestore Error during move_to_resolved: {e}")
            return False

    def add_to_resolved_bets(self, match_id, bet_info, outcome):
        try:
            resolved_data = {
                **bet_info,
                'outcome': outcome,
                'resolved_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'resolution_timestamp': firestore.SERVER_TIMESTAMP
            }
            doc_id = f"{match_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            self.db.collection('resolved_bets').document(doc_id).set(resolved_data)
            return True
        except Exception as e:
            logger.error(f"Firestore Error during add_to_resolved_bets: {e}")
            return False

# Initialize Firebase
try:
    firebase_manager = FirebaseManager(FIREBASE_CREDENTIALS_JSON_STRING)
except Exception as e:
    logger.critical(f"Critical Firebase initialization error: {e}")
    exit(1)

def send_telegram(msg, max_retries=3):
    """Send Telegram message with retry mechanism"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg}
    
    for attempt in range(max_retries):
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                return True
            else:
                logger.error(f"Telegram error (attempt {attempt + 1}): {response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error sending Telegram message (attempt {attempt + 1}): {e}")
        
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)
    
    return False

def handle_api_rate_limit(response):
    """Handle API rate limiting by adjusting sleep time"""
    if response.status_code == 429:
        retry_after = int(response.headers.get('Retry-After', 60))
        logger.warning(f"Rate limited. Sleeping for {retry_after} seconds")
        time.sleep(retry_after)
        return True
    return False

def get_live_matches():
    """Fetch ONLY live matches from API"""
    url = f"{BASE_URL}/fixtures?live=all"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if handle_api_rate_limit(response):
            return get_live_matches()
        if response.status_code != 200:
            logger.error(f"API ERROR: {response.status_code} - {response.text}")
            return []
        data = response.json()
        return data.get('response', [])
    except Exception as e:
        logger.error(f"API Error: {e}")
        return []

def get_fixture_by_id(fixture_id):
    """Fetch details for a single fixture by its ID."""
    url = f"{BASE_URL}/fixtures"
    params = {'id': fixture_id}
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        if handle_api_rate_limit(response):
            return get_fixture_by_id(fixture_id)
        if response.status_code != 200:
            logger.error(f"API ERROR for fixture {fixture_id}: {response.status_code} - {response.text}")
            return None
        data = response.json()
        return data['response'][0] if data.get('response') else None
    except Exception as e:
        logger.error(f"Error fetching fixture {fixture_id}: {e}")
        return None

def place_regular_bet(state, fixture_id, score, match_info):
    """Handles placing the initial 36' bet."""
    if score in ['1-1', '2-2', '3-3']:
        state['36_bet_placed'] = True
        state['36_score'] = score
        firebase_manager.update_tracked_match(fixture_id, state)
        unresolved_data = {
            'match_name': match_info['match_name'],
            'placed_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'league': match_info['league_name'],
            'country': match_info['country'],
            'league_id': match_info['league_id'],
            'bet_type': BET_TYPE_REGULAR,
            '36_score': score,
            'fixture_id': fixture_id
        }
        firebase_manager.add_unresolved_bet(fixture_id, unresolved_data)
        send_telegram(f"⏱️ 36' - {match_info['match_name']}\n🏆 {match_info['league_name']} ({match_info['country']})\n🔢 Score: {score}\n🎯 Correct Score Bet Placed")
    else:
        state['36_bet_placed'] = True
        firebase_manager.update_tracked_match(fixture_id, state)

def check_ht_result(state, fixture_id, score, match_info):
    """Checks the result of the 36' bet at halftime."""
    current_score = score
    state['ht_score'] = current_score
    unresolved_bet_data = firebase_manager.get_unresolved_bets().get(str(fixture_id))
    
    if not unresolved_bet_data or unresolved_bet_data.get('bet_type') != BET_TYPE_REGULAR:
        state['36_result_checked'] = True
        firebase_manager.update_tracked_match(fixture_id, state)
        return
        
    outcome = 'win' if current_score == state.get('36_score', '') else 'loss'
    message = f"✅ HT Result: {match_info['match_name']}\n🏆 {match_info['league_name']} ({match_info['country']})\n🔢 Score: {current_score}\n🎉 36' Bet WON" if outcome == 'win' else f"❌ HT Result: {match_info['match_name']}\n🏆 {match_info['league_name']} ({match_info['country']})\n🔢 Score: {current_score}\n🔁 36' Bet LOST — eligible for chase"
    send_telegram(message)
    
    if outcome == 'win':
        firebase_manager.move_to_resolved(fixture_id, unresolved_bet_data, outcome)
        state['36_bet_won'] = True
    else:
        firebase_manager.add_to_resolved_bets(fixture_id, unresolved_bet_data, outcome)
        state['36_bet_won'] = False

    state['36_result_checked'] = True
    firebase_manager.update_tracked_match(fixture_id, state)

def place_chase_bet(state, fixture_id, score, match_info):
    """Handles placing the 80' chase bet."""
    if state.get('36_bet_won') is False:
        state['80_score'] = score
        state['80_bet_placed'] = True
        firebase_manager.update_tracked_match(fixture_id, state)
        unresolved_data = {
            'match_name': match_info['match_name'],
            'placed_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'bet_type': BET_TYPE_CHASE,
            '36_score': state.get('36_score'),
            'ht_score': state.get('ht_score'),
            '80_score': score,
            'fixture_id': fixture_id
        }
        firebase_manager.add_unresolved_bet(fixture_id, unresolved_data)
        send_telegram(f"⏱️ 80' CHASE BET: {match_info['match_name']}\n🏆 {match_info['league_name']} ({match_info['country']})\n🔢 Score: {score}\n🎯 Betting for Correct Score\n💡 Covering lost 36' bet ({state.get('36_score')} → {state.get('ht_score')})")

def process_live_match(match):
    """
    Processes a single live match.
    No API calls are made here.
    """
    fixture = match['fixture']
    teams = match['teams']
    goals = match['goals']
    fixture_id = fixture['id']
    match_name = f"{teams['home']['name']} vs {teams['away']['name']}"
    minute = fixture['status']['elapsed']
    status = fixture['status']['short'] 
    home_goals = goals['home'] if goals['home'] is not None else 0
    away_goals = goals['away'] if goals['away'] is not None else 0
    score = f"{home_goals}-{away_goals}"
    
    if status.upper() not in STATUS_LIVE and status.upper() != STATUS_HALFTIME:
        return
    if minute is None and status.upper() not in [STATUS_HALFTIME]:
        return
    
    state = firebase_manager.get_tracked_match(fixture_id) or {
        '36_bet_placed': False, '36_result_checked': False, '36_bet_won': None,
        '80_bet_placed': False, '36_score': None, 'ht_score': None,
    }
    firebase_manager.update_tracked_match(fixture_id, state)

    match_info = {
        'match_name': match_name,
        'league_name': match['league']['name'],
        'country': match['league']['country'],
        'league_id': match['league']['id']
    }

    if status.upper() == '1H' and minute in MINUTES_REGULAR_BET and not state.get('36_bet_placed'):
        place_regular_bet(state, fixture_id, score, match_info)
    elif status.upper() == STATUS_HALFTIME and state.get('36_bet_placed') and not state.get('36_result_checked'):
        check_ht_result(state, fixture_id, score, match_info)
    elif status.upper() == '2H' and minute in MINUTES_CHASE_BET and not state.get('80_bet_placed'):
        place_chase_bet(state, fixture_id, score, match_info)

def check_and_resolve_stale_bets():
    """
    Checks and resolves old, unresolved bets by fetching their final status.
    This function uses a direct API call for each bet and should be called sparingly.
    """
    stale_bets = firebase_manager.get_stale_unresolved_bets()
    if not stale_bets:
        return
    
    for match_id, bet_info in stale_bets.items():
        match_data = get_fixture_by_id(match_id)
        
        if not match_data:
            continue
        
        status = match_data['fixture']['status']['short']
        
        if status in STATUS_FINISHED:
            final_score = f"{match_data['goals']['home'] or 0}-{match_data['goals']['away'] or 0}"
            match_name = bet_info.get('match_name', f"Match {match_id}")
            bet_type = bet_info.get('bet_type', 'unknown')

            if bet_type == BET_TYPE_CHASE:
                bet_score = bet_info.get('80_score')
                outcome = 'win' if final_score == bet_score else 'loss'
                message = f"🏁 FINAL RESULT - Chase Bet\n⚽ {match_name}\n🔢 Final Score: {final_score}\n🎯 Bet on 80' Score: {bet_score}\n📊 Outcome: {'✅ WON' if outcome == 'win' else '❌ LOST'}"
            else: # BET_TYPE_REGULAR
                bet_score = bet_info.get('36_score')
                outcome = 'win' if final_score == bet_score else 'loss'
                message = f"🏁 FINAL RESULT - Regular Bet\n⚽ {match_name}\n🔢 Final Score: {final_score}\n🎯 Bet on 36' Score: {bet_score}\n📊 Outcome: {'✅ WON' if outcome == 'win' else '❌ LOST'}"
                
            if send_telegram(message):
                firebase_manager.move_to_resolved(match_id, bet_info, outcome)
            time.sleep(1)

def run_bot_once():
    """Run one complete cycle of the bot"""
    logger.info("Starting bot cycle...")
    
    # Process all live matches, which uses one API call.
    live_matches = get_live_matches()
    for match in live_matches:
        process_live_match(match)
    
    # Check for stale, unresolved bets and resolve them. This will make API calls, but only
    # for bets that have waited long enough to be considered finished.
    check_and_resolve_stale_bets()
    
    logger.info("Bot cycle completed.")

if __name__ == "__main__":
    logger.info("Starting Football Betting Bot")
    send_telegram("🚀 Football Betting Bot Started Successfully!")
    
    while True:
        try:
            run_bot_once()
        except Exception as e:
            error_msg = f"❌ CRITICAL ERROR: {str(e)}"
            logger.critical(error_msg, exc_info=True)
            send_telegram(error_msg[:300])
        finally:
            time.sleep(SLEEP_TIME)
