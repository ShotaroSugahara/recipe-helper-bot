from datetime import datetime
from collections import defaultdict

# user_id -> [日付, 回数]
usage_log = defaultdict(lambda: ["", 0])

def check_usage(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    last_date, count = usage_log[user_id]

    if last_date != today:
        usage_log[user_id] = [today, 0]

    return usage_log[user_id][1] < 5

def increment_usage(user_id):
    usage_log[user_id][1] += 1
