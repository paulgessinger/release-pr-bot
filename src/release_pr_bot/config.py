import os

import dotenv

dotenv.load_dotenv()

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
PRIVATE_KEY = os.environ.get("PRIVATE_KEY")
APP_ID = int(os.environ.get("APP_ID"))

PR_GET_RETRIES = 3
PR_GET_SLEEP = 0.2
MAX_COMMIT_NUMBER = 200
