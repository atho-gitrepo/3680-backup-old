from flask import Flask, render_template_string
from datetime import datetime
from bot import run_bot_once

app = Flask(__name__)
bot_status = {
    "active_matches": [],
    "last_check": "Not yet run"
}

@app.route('/')
def index():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Betting Strategy Tracker</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
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
                <ul class="list-group">
                    {% for match in active_matches %}
                        <li class="list-group-item match-item">{{ match }}</li>
                    {% endfor %}
                </ul>
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

@app.route('/ping')
def ping():
    run_bot_once()
    bot_status["last_check"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return f"✅ Bot triggered at {bot_status['last_check']}", 200

def start_web():
    app.run(host='0.0.0.0', port=8080)
