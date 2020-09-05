#!/usr/bin/env python3

import release_pr_bot

from release_pr_bot.web import create_app

app = create_app()
app.run(host="0.0.0.0", port=8000, debug=True)
