import os
import re
import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi
from dotenv import load_dotenv

load_dotenv()

# 初始化 OpenRouter 客戶端
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

memory = {}

# --- 工具函數：YouTube 提取總結 ---
def get_youtube_id(url):
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def get_youtube_transcript(video_id):
    try:
        # 優先嘗試中文，後嘗試英文
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['zh-TW', 'zh-CN', 'en'])
        return " ".join([t['text'] for t in transcript_list])
    except Exception as e:
        return f"無法獲取字幕：{str(e)}"

# --- 工具函數：Brave Search ---
async def brave_search(query):
    headers = {"X-Subscription-Token": os.getenv("BRAVE_API_KEY")}
    url = f"https://api.search.brave.com/res/v1/web/search?q={query}"
    try:
        response = requests.get(url, headers=headers)
        results = response.json().get("web", {}).get("results", [])
        return "\n".join([f"{r['title']}: {r['description']}" for r in results[:3]])
    except:
        return "搜尋暫時不可用。"

# --- 核心邏輯：處理訊息 ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    
    if user_id not in memory:
        memory[user_id] = [{"role": "system", "content": "你是一個全能助手，能上網搜尋並總結 YouTube 影片。"}]

    # 1. 檢測是否為 YouTube 連結
    if "youtube.com" in user_text or "youtu.be" in user_text:
        await update.message.reply_text("正在讀取 YouTube 影片內容並生成總結，請稍候...")
        video_id = get_youtube_id(user_text)
        if video_id:
            transcript = get_youtube_transcript(video_id)
            user_prompt = f"請根據以下 YouTube 影片的字幕內容進行詳細總結：\n\n{transcript[:8000]}" # 限制長度防止溢出
        else:
            await update.message.reply_text("抱歉，無法解析該 YouTube 連結。")
            return
    
    # 2. 檢測是否需要搜尋 (包含關鍵字觸發)
    elif any(word in user_text for word in ["搜尋", "查一下", "誰是", "是什麼"]):
        search_results = await brave_search(user_text)
        user_prompt = f"用戶問題：{user_text}\n網路搜尋結果：\n{search_results}\n請結合以上資訊回答。"
    
    # 3. 普通對話
    else:
        user_prompt = user_text

    # 更新記憶並請求 LLM
    memory[user_id].append({"role": "user", "content": user_prompt})
    if len(memory[user_id]) > 10: memory[user_id] = [memory[user_id][0]] + memory[user_id][-9:]

    try:
        completion = client.chat.completions.create(
            model="google/gemini-2.0-flash-001",
            messages=memory[user_id]
        )
        response = completion.choices[0].message.content
        memory[user_id].append({"role": "assistant", "content": response})
        await update.message.reply_text(response)
    except Exception as e:
        await update.message.reply_text(f"發生錯誤：{str(e)}")

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("機器人已啟動...")
    app.run_polling()

if __name__ == "__main__":
    main()
