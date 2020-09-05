import os

import dotenv
dotenv.load_dotenv()

WEBHOOK_SECRET=os.environ.get("WEBHOOK_SECRET")
PRIVATE_KEY=os.environ.get("PRIVATE_KEY")
APP_ID=int(os.environ.get("APP_ID"))