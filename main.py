import os
import time
from utils import fetch_jobs, discord_notif
from dotenv import load_dotenv
load_dotenv(override=True)

# Define your users here
SEARCH_PROFILES = [
    {
        "name": "Ryan",
        "query": "Cybersecurity",
        "user_id": os.getenv('DISCORD_USER_ryan'), 
        "color": 4718505, 
        "country": "Canada"
    },
    {
        "name": "Mik",
        "query": "Front End Developer",
        "user_id": os.getenv('DISCORD_USER_mik'), 
        "color": 11094015, 
        "country": "UK"
    }
]
def run_automation():
    webhook = os.getenv('DISCORD_WEBHOOK_URL')
    if not webhook:
        print('Issue with webhook!')
        return

    for profile in SEARCH_PROFILES:
        try:
            query = profile['query']
            country = profile['country']

            raw_jobs = fetch_jobs(
                country=country,
                q=query,
                max_days_range=30
            )
            if raw_jobs:
                discord_notif(webhook_url=webhook,
                            jobs = raw_jobs,
                            user_id=profile['user_id'],
                            color=profile['color']
                            )
                print(f"Success! Sent jobs for {profile['name']}.")
            else:
                print(f"No new jobs for {profile['query']}.")
        except Exception as e:
            print(f"Error processing job for {profile['name']}.")
        time.sleep(2)
if __name__ == "__main__":
    run_automation()