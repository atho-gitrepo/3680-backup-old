from bot import run_bot_once
import time
from datetime import datetime, timedelta
import pytz

# Configuration
TARGET_TIME = "21:00"  # 9:00 PM in 24-hour format
TIMEZONE = "Asia/Yangon"  # Myanmar Time (MMT)
CHECK_INTERVAL = 120  # Check every 2 minutes (120 seconds)

def get_next_run_time():
    """Calculate the next run time at 9:00 PM MMT"""
    mmt = pytz.timezone(TIMEZONE)
    now = datetime.now(mmt)
    
    # Today's target time
    target = datetime.strptime(TARGET_TIME, "%H:%M").time()
    target_datetime = datetime.combine(now.date(), target)
    target_datetime = mmt.localize(target_datetime)
    
    # If today's target time has passed, schedule for tomorrow
    if now > target_datetime:
        target_datetime += timedelta(days=1)
    
    return target_datetime

def main():
    print(f"🚀 Bot worker started (will run daily at {TARGET_TIME} {TIMEZONE})")
    mmt = pytz.timezone(TIMEZONE)
    
    while True:
        try:
            now = datetime.now(mmt)
            next_run = get_next_run_time()
            time_until_run = (next_run - now).total_seconds()
            
            print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S %Z')}] Current status:")
            print(f"Next scheduled run at: {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"Time until next run: {timedelta(seconds=time_until_run)}")
            
            # If it's time to run (within 5 minutes of target time)
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
            print(f"[{datetime.now(mmt).strftime('%Y-%m-%d %H:%M:%S %Z')}] ❌ Unexpected error in main loop: {e}")
            print("💤 Sleeping for 5 minutes before retrying...")
            time.sleep(300)

if __name__ == "__main__":
    main()
