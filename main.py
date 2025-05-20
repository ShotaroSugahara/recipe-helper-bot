from pathlib import Path

main_py_code = """
import os
import time
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
)
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# ユーザーごとのセッション状態（メモリ上） key: user_id, value: list of recipes
user_sessions = {}

def generate_recipe_prompt(user_msg):
    if "スイーツ" in user_msg or "デザート" in user_msg:
        category = "Japanese desserts"
    elif "ドリンク" in user_msg or "飲み物" in user_msg:
        category = "Japanese drinks"
    else:
        category = "Japanese meals"

    prompt = f\"\"\"
The user says: "{user_msg}"
Please suggest 5 {category} based on this mood.
Each suggestion must include:
- title
- a brief reason why it fits the mood

Respond only in Japanese.
Avoid generic items like coffee, udon, or somen unless user asked.
Avoid drinks or desserts unless requested.
Use common ingredients and simple ideas, but make at least one feel new or clever.
\"\"\"
    return prompt

def generate_detail_prompt(title):
    return f\"\"\"
Please provide a detailed Japanese recipe for the following dish:

{title}

Include:
- estimated cooking time (★1 to 5)
- estimated cost (★1 to 5)
- list of ingredients
- preparation steps
Respond only in Japanese.
\"\"\"

def build_flex_message(recipes):
    contents = {
        "type": "carousel",
        "contents": []
    }

    for i, item in enumerate(recipes):
        contents["contents"].append({
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"{i+1}. {item['title']}", "weight": "bold", "wrap": True},
                    {"type": "text", "text": item['reason'], "size": "sm", "wrap": True, "margin": "md"}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [{
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "これにする",
                        "text": f"{i+1}"
                    },
                    "style": "primary"
                }]
            }
        })

    return FlexSendMessage(alt_text="料理の提案です", contents={"type": "carousel", "contents": contents["contents"]})

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_msg = event.message.text.strip()

    if user_id in user_sessions:
        # ユーザーが料理を選んだと判定
        if user_msg.isdigit():
            index = int(user_msg) - 1
            if 0 <= index < len(user_sessions[user_id]):
                selected = user_sessions[user_id][index]
                detail_prompt = generate_detail_prompt(selected["title"])
                try:
                    reply = openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": detail_prompt}]
                    )
                    detailed_recipe = reply.choices[0].message.content
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"{selected['title']} の作り方です：\n\n{detailed_recipe}")
                    )
                except Exception as e:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="レシピ取得に失敗しました。後でもう一度お試しください。")
                    )
                del user_sessions[user_id]
                return

    # ステータス：受信確認
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="メッセージ受け取りました。考え中です…🤔")
    )

    # GPTへ問い合わせ
    try:
        start = time.time()
        prompt = generate_recipe_prompt(user_msg)
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content.strip()
        elapsed = time.time() - start

        # 応答を5個にパース
        lines = content.split("\\n")
        recipes = []
        for line in lines:
            if line.strip() == "":
                continue
            if line.startswith(tuple("12345")):
                parts = line.split("：", 1) if "：" in line else line.split(":", 1)
                title = parts[1].strip() if len(parts) > 1 else line
                recipes.append({"title": title, "reason": ""})
            elif recipes:
                recipes[-1]["reason"] += line.strip() + " "

        user_sessions[user_id] = recipes[:5]
        flex_msg = build_flex_message(user_sessions[user_id])

        if elapsed > 10:
            status_note = "（少しお待たせしました。Botが寝てたかも…💤）"
        else:
            status_note = ""

        line_bot_api.push_message(
            user_id,
            [TextSendMessage(text=f"気分に合いそうなレシピを5つ提案します！{status_note}"), flex_msg]
        )
    except Exception as e:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="ちょっと調子が悪いみたいです💦 また後で試してみてください🙏")
        )
"""
