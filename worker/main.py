from bot import run_bot_once
import time

if __name__ == "__main__":
    print("🔁 Bot worker started")
    while True:
        run_bot_once()
        time.sleep(180)
