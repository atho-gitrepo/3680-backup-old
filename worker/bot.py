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
FIREBASE_CREDENTIALS_JSON_STRING = os.getenv("FIREBASE_CREDENTIALS")

HEADERS = {
    'x-rapidapi-key': API_KEY,
    'x-rapidapi-host': 'v3.football.api-sports.io'
}
BASE_URL = 'https://v3.football.api-sports.io'

# --- CONSTANTS ---
SLEEP_TIME = 90
MINUTES_REGULAR_BET = [35, 36, 37] # Only need the 36' window
BET_TYPE_REGULAR = 'regular' # Only need the regular bet type
STATUS_LIVE = ['LIVE', '1H', '2H', 'ET', 'P']
STATUS_HALFTIME = 'HT'
STATUS_FINISHED = ['FT', 'AET', 'PEN']
# Removed: MINUTES_26_MINUTE_BET, MINUTES_32_MINUTE_BET, MINUTES_80_MINUTE_BET, 
# Removed: BET_TYPE_26_OVER_HT, BET_TYPE_32_OVER, BET_TYPE_80_MINUTE, BET_SCORES_80_MINUTE

class FirebaseManager:
    """Manages all interactions with the Firebase Firestore database."""
    def __init__(self, credentials_json_string):
        try:
            logger.info("Initializing Firebase...")
            if not credentials_json_string:
                logger.warning("FIREBASE_CREDENTIALS_JSON is empty. Skipping Firebase initialization.")
                self.db = None
                return

            cred_dict = json.loads(credentials_json_string)
            cred = credentials.Certificate(cred_dict)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            logger.info("Firebase initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            self.db = None
            raise

    # Note: All Firebase methods should check if self.db is not None
    def get_tracked_match(self, match_id):
        if not self.db: return None
        try:
            doc = self.db.collection('tracked_matches').document(str(match_id)).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Firestore Error during get_tracked_match: {e}")
            return None

    def update_tracked_match(self, match_id, data):
        if not self.db: return
        try:
            self.db.collection('tracked_matches').document(str(match_id)).set(data, merge=True)
        except Exception as e:
            logger.error(f"Firestore Error during update_tracked_match: {e}")
            
    def delete_tracked_match(self, match_id):
        if not self.db: return
        try:
            self.db.collection('tracked_matches').document(str(match_id)).delete()
        except Exception as e:
            logger.error(f"Firestore Error during delete_tracked_match: {e}")

    def get_unresolved_bets(self):
        if not self.db: return {}
        try:
            bets = self.db.collection('unresolved_bets').stream()
            result = {doc.id: doc.to_dict() for doc in bets}
            return result
        except Exception as e:
            logger.error(f"Firestore Error during get_unresolved_bets: {e}")
            return {}
    
    # Removed: get_stale_unresolved_bets as it was only for FT bets (80'/32')

    def add_unresolved_bet(self, match_id, data):
        if not self.db: return
        try:
            # Add a timestamp when the bet was placed
            data['placed_at'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            self.db.collection('unresolved_bets').document(str(match_id)).set(data)
        except Exception as e:
            logger.error(f"Firestore Error during add_unresolved_bet: {e}")

    def move_to_resolved(self, match_id, bet_info, outcome):
        if not self.db: return False
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
        if not self.db: return False
        try:
            resolved_data = {
                **bet_info,
                'outcome': outcome,
                'resolved_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'resolution_timestamp': firestore.SERVER_TIMESTAMP
            }
            # Use a unique ID based on match and timestamp since this is an append operation
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
    if not firebase_manager.db:
        logger.warning("Continuing bot execution with disabled Firebase functionality.")

def send_telegram(msg, max_retries=3):
    """Send Telegram message with retry mechanism"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(f"Telegram credentials missing. Message not sent: {msg}")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg}
    
    for attempt in range(max_retries):
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                return True
            else:
                logger.error(f"Telegram error (attempt {attempt + 1}): {response.status_code} - {response.text}")
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
    if not API_KEY:
        logger.error("API_KEY is not set. Cannot fetch live matches.")
        return []
        
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
    if not API_KEY: return None
    
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
    """Handles placing the 36' correct score bet."""
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

# Removed: place_26_over_ht_bet
# Removed: place_32_over_bet
# Removed: place_80_minute_bet

def check_ht_result(state, fixture_id, score, match_info):
    """Checks the result of the 36' bet at halftime."""
    
    current_score = score
    unresolved_bet_data = firebase_manager.get_unresolved_bets().get(str(fixture_id))

    if unresolved_bet_data and unresolved_bet_data.get('bet_type') == BET_TYPE_REGULAR:
        
        outcome = 'win' if current_score == unresolved_bet_data.get('36_score', '') else 'loss'
        
        message = (
            f"✅ HT Result: {match_info['match_name']}\n"
            f"🏆 {match_info['league_name']} ({match_info['country']})\n"
            f"🔢 Score: {current_score}\n"
            f"🎉 36' Bet WON"
        ) if outcome == 'win' else (
            f"❌ HT Result: {match_info['match_name']}\n"
            f"🏆 {match_info['league_name']} ({match_info['country']})\n"
            f"🔢 Score: {current_score}\n"
            f"🔁 36' Bet LOST"
        )
            
        if outcome:
            firebase_manager.move_to_resolved(fixture_id, unresolved_bet_data, outcome)
            send_telegram(message)
    
    # Delete tracked match state once the 36' bet is resolved or if no bet was placed/found
    firebase_manager.delete_tracked_match(fixture_id)

def process_live_match(match):
    """
    Processes a single live match for the 36' bet.
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
        '36_bet_placed': False,
        '36_score': None,
        # Removed: '32_bet_placed', '26_ht_bet_placed', '80_bet_placed', '80_score'
    }
    
    match_info = {
        'match_name': match_name,
        'league_name': match['league']['name'],
        'country': match['league']['country'],
        'league_id': match['league']['id']
    }

    # 1. 36' Regular Bet Check
    if status.upper() == '1H' and minute in MINUTES_REGULAR_BET and not state.get('36_bet_placed'):
        place_regular_bet(state, fixture_id, score, match_info)
        
    # 2. Halftime Resolution
    elif status.upper() == STATUS_HALFTIME and firebase_manager.get_unresolved_bets().get(str(fixture_id)):
        # Check if the bet is still unresolved
        check_ht_result(state, fixture_id, score, match_info)
    
    # If the match is finished and there are no unresolved bets, delete the tracked match state
    if status in STATUS_FINISHED and not firebase_manager.get_unresolved_bets().get(str(fixture_id)):
        firebase_manager.delete_tracked_match(fixture_id)

# Removed: check_and_resolve_stale_bets (No bets require FT resolution now)

def run_bot_once():
    """Run one complete cycle of the bot"""
    logger.info("Starting bot cycle...")
    
    live_matches = get_live_matches()
    for match in live_matches:
        process_live_match(match)
    
    logger.info("Bot cycle completed.")

if __name__ == "__main__":
    logger.info("Starting Football Betting Bot")
    # Initial startup message
    send_telegram("🚀 Football Betting Bot Started Successfully! Monitoring live games for the 36' bet.")
    
    while True:
        try:
            run_bot_once()
        except Exception as e:
            error_msg = f"❌ CRITICAL ERROR: {str(e)}"
            logger.critical(error_msg, exc_info=True)
            send_telegram(error_msg[:300])
        finally:
            time.sleep(SLEEP_TIME)
