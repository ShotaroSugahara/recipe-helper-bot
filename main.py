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

user_sessions = {}

def generate_recipe_prompt(user_msg):
    if "スイーツ" in user_msg or "デザート" in user_msg:
        category = "Japanese desserts"
    elif "ドリンク" in user_msg or "飲み物" in user_msg:
        category = "Japanese drinks"
    else:
        category = "Japanese meals"

    prompt = f"""
The user says: "{user_msg}"
Please suggest 5 {category} based on this mood.
Each suggestion must include:
- title
- a brief reason why it fits the mood

Respond only in Japanese.
Avoid generic items like coffee, udon, or somen unless user asked.
Avoid drinks or desserts unless requested.
Use common ingredients and simple ideas, but make at least one feel new or clever.
"""
    return prompt

def generate_detail_prompt(title):
    return f"""
You are a Japanese cooking expert. Please write a full Japanese-language recipe for the following dish:

【Dish】{title}

Please include the following:

1. How many servings the recipe makes (e.g., 2〜3人前)
2. List of ingredients using simple units (e.g., "a little", "1 handful", "1 piece" — avoid grams/ml)
3. Step-by-step instructions
   - For each step, explain briefly **why** it's done (e.g., "Start with the skin side to make it crispy")
4. At the end, add a short bonus section with a fun or useful fact about the dish.
   - Use a casual, modern tone
   - Start with a catchy phrase like one of the following (pick randomly):
     「料理の小ネタ」, 「知ってると話したくなる話」, 「この料理、実は…」, 「ちょこっと豆知識」, 「豆メモ」

Important:
- Output must be entirely in Japanese.
- Keep the tone friendly, easy, and suitable for home cooks.
"""

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

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="メッセージ受け取りました。考え中です…🤔")
    )

    try:
        start = time.time()
        prompt = generate_recipe_prompt(user_msg)
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content.strip()
        elapsed = time.time() - start

        lines = content.split("\n")
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

        status_note = "（少しお待たせしました。Botが寝てたかも…💤）" if elapsed > 10 else ""

        line_bot_api.push_message(
            user_id,
            [TextSendMessage(text=f"気分に合いそうなレシピを5つ提案します！{status_note}"), flex_msg]
        )
    except Exception as e:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="ちょっと調子が悪いみたいです💦 また後で試してみてください🙏")
        )
