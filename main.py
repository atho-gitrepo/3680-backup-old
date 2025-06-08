# main.py
from threading import Thread
from web import app  # ← This exposes the Flask app object
from bot import run_bot_once
import time

def launch_web():
    from web import start_web
    start_web()

if __name__ == "__main__":
    web_thread = Thread(target=launch_web)
    web_thread.daemon = True
    web_thread.start()

    try:
        while True:
            from bot import run_bot_once
            run_bot_once()
            time.sleep(60)
    except KeyboardInterrupt:
        print("🔴 Shutting down...")
