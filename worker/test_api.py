import requests
from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables from .env

API_KEY = os.getenv("API_KEY")
HEADERS = {'x-apisports-key': API_KEY}
BASE_URL = 'https://v3.football.api-sports.io'

response = requests.get(f"{BASE_URL}/fixtures?live=all", headers=HEADERS)

print("Status Code:", response.status_code)
print("Response JSON:", response.json())
