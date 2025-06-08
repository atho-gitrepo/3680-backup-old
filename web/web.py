from flask import Flask, render_template_string
from datetime import datetime
import sys
import os

# Adjust Python path if needed (adjust folder name accordingly)
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from worker.bot import bot_status, run_bot_once# Assuming bot.py is one level above web.py


app = Flask(__name__)

@app.route('/')
def index():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Betting Strategy Tracker</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
        <style>
            body {
                background-color: #f8f9fa;
                padding-top: 40px;
            }
            .container {
                max-width: 700px;
            }
            .match-item {
                font-size: 1.1rem;
            }
        </style>
    </head>
    <body>
        <div class="container shadow p-4 bg-white rounded">
            <h2 class="mb-4 text-center text-primary">⚽ Betting Strategy Tracker</h2>
            <p class="text-muted text-end"><strong>Last Checked:</strong> {{ last_check }}</p>
            <hr>
            {% if active_matches %}
                <ol class="list-group">
                    {% for match in active_matches %}
                        <li class="list-group-item match-item">{{ match }}</li>
                    {% endfor %}
                </ol>
            {% else %}
                <div class="alert alert-info text-center" role="alert">
                    No active matches right now.
                </div>
            {% endif %}
        </div>
    </body>
    </html>
    """
    return render_template_string(html, **bot_status)

@app.route('/health')
def health():
    return "OK", 200

@app.route('/run-bot')
def run_bot():
    try:
        matches = run_bot_once()
        return f"Bot run successfully. Active matches: {len(matches)}", 200
    except Exception as e:
        return f"Bot run failed: {str(e)}", 500

if __name__ == "__main__":
    app.run(debug=True)
