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

HEADERS = {'x-apisports-key': API_KEY}
BASE_URL = 'https://v3.football.api-sports.io'

# --- CONSTANTS ---
SLEEP_TIME = 90
HEALTH_CHECK_INTERVAL_MIN = 30
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
        doc_ref = self.db.collection('tracked_matches').document(str(match_id))
        try:
            doc = doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Firestore Error during get_tracked_match: {e}")
            return None

    def update_tracked_match(self, match_id, data):
        doc_ref = self.db.collection('tracked_matches').document(str(match_id))
        try:
            doc_ref.set(data, merge=True)
            logger.debug(f"Updated tracked match {match_id} with data: {data}")
        except Exception as e:
            logger.error(f"Firestore Error during update_tracked_match: {e}")

    def get_unresolved_bets(self, bet_type=None):
        try:
            col_ref = self.db.collection('unresolved_bets')
            if bet_type:
                query = col_ref.where('bet_type', '==', bet_type)
            else:
                query = col_ref
            bets = query.stream()
            result = {doc.id: doc.to_dict() for doc in bets}
            logger.info(f"Retrieved {len(result)} unresolved bets")
            return result
        except Exception as e:
            logger.error(f"Firestore Error during get_unresolved_bets: {e}")
            return {}
    
    def add_unresolved_bet(self, match_id, data):
        try:
            self.db.collection('unresolved_bets').document(str(match_id)).set(data)
            logger.info(f"Added unresolved bet for match {match_id}")
        except Exception as e:
            logger.error(f"Firestore Error during add_unresolved_bet: {e}")

    def move_to_resolved(self, match_id, bet_info, outcome):
        resolved_bet_ref = self.db.collection('resolved_bets').document(str(match_id))
        try:
            resolved_data = {
                **bet_info,
                'outcome': outcome,
                'resolved_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            } 
            resolved_bet_ref.set(resolved_data)
            self.db.collection('unresolved_bets').document(str(match_id)).delete()
            logger.info(f"Moved match {match_id} to resolved bets with outcome: {outcome}")
        except Exception as e:
            logger.error(f"Firestore Error during move_to_resolved: {e}")

    def add_to_resolved_bets(self, match_id, bet_info, outcome):
        resolved_bet_ref = self.db.collection('resolved_bets').document(f"{match_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
        try:
            resolved_data = {
                **bet_info,
                'outcome': outcome,
                'resolved_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }
            resolved_bet_ref.set(resolved_data)
            logger.info(f"Added bet for match {match_id} to resolved bets with outcome: {outcome}")
        except Exception as e:
            logger.error(f"Firestore Error during add_to_resolved_bets: {e}")

# Initialize Firebase
try:
    firebase_manager = FirebaseManager(FIREBASE_CREDENTIALS_JSON_STRING)
except Exception as e:
    logger.critical(f"Critical Firebase initialization error: {e}")
    exit(1)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg}
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code != 200:
            logger.error(f"Telegram error: {response.text}")
        else:
            logger.info("Telegram message sent successfully")
        return response
    except requests.exceptions.RequestException as e:
        logger.error(f"Network Error sending Telegram message: {e}")
        return None

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
    logger.info("Fetching live matches...")
    url = f"{BASE_URL}/fixtures?live=all"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        
        if handle_api_rate_limit(response):
            return get_live_matches()  # Retry after sleep
        
        if response.status_code != 200:
            logger.error(f"API ERROR: {response.status_code} - {response.text}")
            return []
            
        data = response.json()
        matches = data.get('response', [])
        logger.info(f"Found {len(matches)} live matches")
        return matches
    except Exception as e:
        logger.error(f"API Error: {e}")
        return []

def get_finished_matches_by_league(league_id):
    """Fetch all finished matches for a specific league from yesterday and today."""
    logger.info(f"Fetching finished matches for league ID: {league_id}")
    
    all_finished_fixtures = {}
    today_str = datetime.utcnow().date().isoformat()
    yesterday_str = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
    
    for date_str in [today_str, yesterday_str]:
        url = f"{BASE_URL}/fixtures?league={league_id}&season=2024&date={date_str}" # Assuming 2024 season
        try:
            response = requests.get(url, headers=HEADERS, timeout=25)
            
            if handle_api_rate_limit(response):
                time.sleep(60)
                response = requests.get(url, headers=HEADERS, timeout=25)
            
            if response.status_code != 200:
                logger.error(f"API ERROR for league {league_id}, date {date_str}: {response.status_code} - {response.text}")
                continue
            
            data = response.json()
            response_fixtures = data.get('response', [])
            
            for f in response_fixtures:
                if f['fixture']['status']['short'] in STATUS_FINISHED:
                    fixture_id = str(f['fixture']['id'])
                    all_finished_fixtures[fixture_id] = f
            
        except Exception as e:
            logger.error(f"Fixture Lookup Error for league {league_id}, date {date_str}: {e}")
    
    return all_finished_fixtures

def place_regular_bet(state, fixture_id, score, match_info):
    """Handles placing the initial 36' bet."""
    if score in ['0-0', '1-1', '2-2', '3-3']:
        logger.info(f"Placing Regular bet {match_info['match_name']} - score {score}")
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
        }
        firebase_manager.add_unresolved_bet(fixture_id, unresolved_data)
        
        send_telegram(
            f"⏱️ 36' - {match_info['match_name']}\n"
            f"🏆 {match_info['league_name']} ({match_info['country']})\n"
            f"🔢 Score: {score}\n"
            f"🎯 Correct Score Bet Placed"
        )
    else:
        logger.info(f"No 36' bet for {match_info['match_name']} - score {score} not in strategy")
        state['36_bet_placed'] = True
        firebase_manager.update_tracked_match(fixture_id, state)

def check_ht_result(state, fixture_id, score, match_info):
    """Checks the result of the 36' bet at halftime."""
    current_score = score
    state['ht_score'] = current_score
    unresolved_bet_data = firebase_manager.get_unresolved_bets(BET_TYPE_REGULAR).get(str(fixture_id))
    
    if not unresolved_bet_data:
        logger.warning(f"No unresolved regular bet found for {match_info['match_name']} at HT")
        state['36_result_checked'] = True
        firebase_manager.update_tracked_match(fixture_id, state)
        return
        
    if current_score == state.get('36_score', ''):
        logger.info(f"HT Result WIN: {match_info['match_name']} - Score: {current_score}")
        send_telegram(
            f"✅ HT Result: {match_info['match_name']}\n"
            f"🏆 {match_info['league_name']} ({match_info['country']})\n"
            f"🔢 Score: {current_score}\n"
            f"🎉 36' Bet WON"
        )
        state['36_bet_won'] = True
        firebase_manager.move_to_resolved(fixture_id, unresolved_bet_data, 'win')
    else:
        logger.info(f"HT Result LOSS: {match_info['match_name']} - Score: {current_score} (was {state.get('36_score', '')} at 36')")
        send_telegram(
            f"❌ HT Result: {match_info['match_name']}\n"
            f"🏆 {match_info['league_name']} ({match_info['country']})\n"
            f"🔢 Score: {current_score}\n"
            f"🔁 36' Bet LOST — eligible for chase"
        )
        state['36_bet_won'] = False
        # Add a record to resolved_bets for the loss, but keep the original in unresolved for the chase bet.
        firebase_manager.add_to_resolved_bets(fixture_id, unresolved_bet_data, 'loss')
    
    state['36_result_checked'] = True
    firebase_manager.update_tracked_match(fixture_id, state)

def place_chase_bet(state, fixture_id, score, match_info):
    """Handles placing the 80' chase bet."""
    if state.get('36_bet_won') is False:
        logger.info(f"Placing 80' chase bet for {match_info['match_name']}")
        state['80_score'] = score
        state['80_bet_placed'] = True
        firebase_manager.update_tracked_match(fixture_id, state)
        
        unresolved_data = {
            'match_name': match_info['match_name'],
            'placed_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'league': match_info['league_name'],
            'country': match_info['country'],
            'league_id': match_info['league_id'],
            'bet_type': BET_TYPE_CHASE,
            '36_score': state.get('36_score'),
            'ht_score': state.get('ht_score'),
            '80_score': score
        }
        firebase_manager.add_unresolved_bet(fixture_id, unresolved_data)
        
        send_telegram(
            f"⏱️ 80' CHASE BET: {match_info['match_name']}\n"
            f"🏆 {match_info['league_name']} ({match_info['country']})\n"
            f"🔢 Score: {score}\n"
            f"🎯 Betting for Correct Score\n"
            f"💡 Covering lost 36' bet ({state.get('36_score')} -> {state.get('ht_score')})"
        )

def process_match(match):
    fixture = match['fixture']
    teams = match['teams']
    league = match['league']
    goals = match['goals']
    
    fixture_id = fixture['id']
    match_name = f"{teams['home']['name']} vs {teams['away']['name']}"
    league_name = league['name']
    league_id = league['id']
    country = league.get('country', 'N/A')
    minute = fixture['status']['elapsed']
    status = fixture['status']['short'] 
    
    home_goals = goals['home'] if goals['home'] is not None else 0
    away_goals = goals['away'] if goals['away'] is not None else 0
    score = f"{home_goals}-{away_goals}"
    
    if status.upper() not in STATUS_LIVE and status.upper() != STATUS_HALFTIME:
        return
        
    if minute is None and status.upper() not in [STATUS_HALFTIME]:
        logger.info(f"Skipping {match_name} - no minute data (status: {status})")
        return
    
    logger.debug(f"Processing: {match_name} ({minute}' {score}) [ID: {fixture_id}]")
    
    state = firebase_manager.get_tracked_match(fixture_id) or {
        '36_bet_placed': False,
        '36_result_checked': False,
        '36_bet_won': None,
        '80_bet_placed': False,
        '36_score': None,
        'ht_score': None,
    }
    firebase_manager.update_tracked_match(fixture_id, state)

    match_info = {
        'match_name': match_name, 'league_name': league_name,
        'country': country, 'league_id': league_id
    }

    if status.upper() == '1H' and minute in MINUTES_REGULAR_BET and not state.get('36_bet_placed'):
        place_regular_bet(state, fixture_id, score, match_info)

    if status.upper() == STATUS_HALFTIME and state.get('36_bet_placed') and not state.get('36_result_checked'):
        check_ht_result(state, fixture_id, score, match_info)

    if status.upper() == '2H' and minute in MINUTES_CHASE_BET and not state.get('80_bet_placed'):
        place_chase_bet(state, fixture_id, score, match_info)

def check_unresolved_bets():
    """Check ONLY unresolved CHASE bets by fetching finished matches for specific leagues."""
    logger.info("Checking unresolved CHASE bets...")
    unresolved_bets = firebase_manager.get_unresolved_bets(BET_TYPE_CHASE)
    if not unresolved_bets:
        logger.info("No unresolved CHASE bets found")
        return
        
    unresolved_finished_fixtures = {}
    leagues_to_check = {bet_info.get('league_id') for bet_info in unresolved_bets.values() if bet_info.get('league_id')}

    for league_id in leagues_to_check:
        unresolved_finished_fixtures.update(get_finished_matches_by_league(league_id))
    
    logger.info(f"Found {len(unresolved_finished_fixtures)} finished fixtures relevant to unresolved bets")
    
    for match_id, bet_info in unresolved_bets.items():
        if match_id not in unresolved_finished_fixtures:
            logger.info(f"Fixture {match_id} not found in recently finished matches. Waiting for result.")
            continue
            
        match_data = unresolved_finished_fixtures[match_id]
        fixture = match_data['fixture']
        
        fixture_date = datetime.fromisoformat(fixture['date'].replace('Z', '+00:00'))
        if (datetime.utcnow() - fixture_date) < timedelta(minutes=30):
            logger.info(f"Match {match_id} finished very recently, waiting for data stabilization")
            continue
            
        home_goals_ft = match_data['goals']['home'] or 0
        away_goals_ft = match_data['goals']['away'] or 0
        final_score = f"{home_goals_ft}-{away_goals_ft}"
        
        match_name = bet_info.get('match_name', f"Match {match_id}")
        league_name = bet_info.get('league', 'Unknown League')
        bet_type = bet_info['bet_type']
        country = bet_info.get('country', 'N/A')
        
        logger.info(f"Resolving chase bet for finished match {match_id}: {match_name} - Final: {final_score}")
        
        outcome = None
        message = ""
        
        if bet_type == BET_TYPE_CHASE:
            chase_score = bet_info.get('80_score', '')
            if final_score == chase_score:
                outcome = 'win'
                message = (
                    f"✅ CHASE BET WON: {match_name}\n"
                    f"🏆 {league_name} ({country})\n"
                    f"🔢 Final Score: {final_score}\n"
                    f"🎉 Same as 80' score\n"
                    f"💡 Covered 36' loss ({bet_info.get('36_score')} -> {bet_info.get('ht_score')})"
                )
                logger.info(f"Chase bet WON for {match_id}: Final score {final_score} matches 80' score")
            else:
                outcome = 'loss'
                message = (
                    f"❌ CHASE BET LOST: {match_name}\n"
                    f"🏆 {league_name} ({country})\n"
                    f"🔢 Final Score: {final_score} (was {chase_score} at 80')\n"
                    f"📉 Score changed after 80'\n"
                    f"💡 Failed to cover 36' loss ({bet_info.get('36_score')} -> {bet_info.get('ht_score')})"
                )
                logger.info(f"Chase bet LOST for {match_id}: Final score {final_score} differs from 80' score {chase_score}")
                
        else:
            outcome = 'error'
            message = f"⚠️ FT Result: {match_name}\n🏆 {league_name} ({country})\n🔢 Score: {final_score}\n❓ Unknown bet type: {bet_type}"
            logger.error(f"Unknown bet type {bet_type} for match {match_id}")
        
        if outcome:
            send_telegram(message)
            firebase_manager.move_to_resolved(match_id, bet_info, outcome)

def run_bot_once():
    """Run one complete cycle of the bot"""
    logger.info(f"Starting new cycle")
    
    live_matches = get_live_matches()
    logger.info(f"Processing {len(live_matches)} live matches")
    for match in live_matches:
        process_match(match)
    
    check_unresolved_bets()
    
    logger.info(f"Cycle completed")

def health_check():
    """Periodic health check notification"""
    if datetime.now().minute % HEALTH_CHECK_INTERVAL_MIN == 0:
        logger.info("Sending health check")
        send_telegram(f"🤖 Bot is active | Last cycle: {datetime.now().strftime('%H:%M:%S')}")

if __name__ == "__main__":
    logger.info("Starting Football Betting Bot")
    cycle_count = 0
    
    while True:
        try:
            cycle_count += 1
            logger.info(f"=== Cycle #{cycle_count} ===")
            run_bot_once()
            health_check()
        except Exception as e:
            error_msg = f"CRITICAL ERROR: {str(e)}"
            logger.critical(error_msg, exc_info=True)
            send_telegram(error_msg[:300])
            sleep_time = min(300, 5 * 2 ** cycle_count)
            logger.info(f"Sleeping for {sleep_time} seconds due to error")
            time.sleep(sleep_time)
        finally:
            logger.info(f"Sleeping for {SLEEP_TIME} seconds...")
            time.sleep(SLEEP_TIME)
