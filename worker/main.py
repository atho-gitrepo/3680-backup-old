from bot import run_bot_once
import time
from datetime import datetime, timedelta, timezone
import json
import os

# Configuration
TARGET_HOUR = 21  # 9:00 PM in 24-hour format (Myanmar Time)
TARGET_MINUTE = 0
CHECK_INTERVAL = 120  # Check every 2 minutes (120 seconds)
STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "tracked_matches.json")

def initialize_tracked_matches():
    """Initialize or repair the tracked_matches file"""
    default_data = {}
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(default_data, f)
        print(f"Initialized new tracked_matches file at {STATE_FILE}")
    except Exception as e:
        print(f"Failed to initialize tracked_matches file: {e}")

def get_next_run_time():
    """Calculate the next run time at 9:00 PM MMT (UTC+6:30)"""
    now = datetime.now(timezone(timedelta(hours=6, minutes=30)))  # MMT is UTC+6:30
    
    # Today's target time
    target_datetime = now.replace(
        hour=TARGET_HOUR,
        minute=TARGET_MINUTE,
        second=0,
        microsecond=0
    )
    
    # If today's target time has passed, schedule for tomorrow
    if now > target_datetime:
        target_datetime += timedelta(days=1)
    
    return target_datetime

def main():
    print(f"🚀 Bot worker started (will run daily at {TARGET_HOUR:02d}:{TARGET_MINUTE:02d} MMT)")
    
    # Initialize tracked_matches file if it doesn't exist or is corrupted
    if not os.path.exists(STATE_FILE):
        initialize_tracked_matches()
    else:
        try:
            with open(STATE_FILE) as f:
                json.load(f)  # Test if file is valid JSON
        except json.JSONDecodeError:
            print("⚠️ tracked_matches.json is corrupted, reinitializing...")
            initialize_tracked_matches()
    
    while True:
        try:
            mmt = timezone(timedelta(hours=6, minutes=30))  # Myanmar Time (UTC+6:30)
            now = datetime.now(mmt)
            next_run = get_next_run_time()
            time_until_run = (next_run - now).total_seconds()
            
            print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S %Z')}] Current status:")
            print(f"Next scheduled run at: {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"Time until next run: {timedelta(seconds=time_until_run)}")
            
            # If it's time to run (within check interval window)
            if time_until_run <= CHECK_INTERVAL:
                print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S %Z')}] ⏳ Running bot cycle...")
                run_bot_once()
                print(f"[{datetime.now(mmt).strftime('%Y-%m-%d %H:%M:%S %Z')}] ✅ Bot cycle completed")
                
                # Skip ahead to avoid multiple runs in the same window
                time.sleep(CHECK_INTERVAL)
                continue
            
            # Otherwise sleep until next check interval or run time
            sleep_time = min(CHECK_INTERVAL, time_until_run)
            print(f"[{now.strftime('%Y-%m-%d %H:%M:%S %Z')}] 💤 Sleeping for {sleep_time} seconds...")
            time.sleep(sleep_time)
            
        except KeyboardInterrupt:
            print("\n🛑 Bot worker stopped by user")
            break
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Unexpected error in main loop: {e}")
            print("💤 Sleeping for 2 minutes before retrying...")
            time.sleep(120)

if __name__ == "__main__":
    main()