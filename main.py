import os
import re
import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi
from dotenv import load_dotenv

load_dotenv()

# --- 配置區 ---
# 建議使用的免費模型 ID（在 OpenRouter 官網搜尋 "free" 可以找到更多）
# 推薦 1: Google: Gemini 2.0 Flash Experimental (free) (速度快、支援長文本)
# 推薦 2: deepseek/deepseek-chat:free (邏輯強)
FREE_MODEL = "Google: Gemini 2.0 Flash Experimental free"

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

memory = {}

# --- YouTube 處理邏輯 ---
def get_youtube_id(url):
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def get_youtube_transcript(video_id):
    try:
        # 嘗試抓取中文或英文字幕
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['zh-TW', 'zh-CN', 'en'])
        return " ".join([t['text'] for t in transcript_list])
    except Exception as e:
        return None

# --- Brave Search 處理邏輯 ---
async def brave_search(query):
    headers = {"X-Subscription-Token": os.getenv("BRAVE_API_KEY")}
    url = f"https://api.search.brave.com/res/v1/web/search?q={query}"
    try:
        response = requests.get(url, headers=headers)
        results = response.json().get("web", {}).get("results", [])
        return "\n".join([f"{r['title']}: {r['description']}" for r in results[:3]])
    except:
        return "搜尋失敗。"

# --- 核心訊息處理 ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    
    if user_id not in memory:
        memory[user_id] = [{"role": "system", "content": "你是一個有搜尋與影片分析能力的助手，請使用繁體中文回答。"}]

    # A. 處理 YouTube 連結
    if "youtube.com" in user_text or "youtu.be" in user_text:
        video_id = get_youtube_id(user_text)
        if video_id:
            await update.message.reply_text("正在解析影片字幕並生成總結...")
            transcript = get_youtube_transcript(video_id)
            if transcript:
                # 免費模型可能有 Token 限制，我們截取前 10000 字
                user_prompt = f"請詳細總結這部 YouTube 影片的內容：\n\n{transcript[:10000]}"
            else:
                await update.message.reply_text("此影片沒有可用的字幕（作者可能關閉了該功能）。")
                return
        else:
            return

    # B. 處理搜尋請求 (關鍵字觸發)
    elif any(word in user_text for word in ["搜尋", "查一下", "誰是"]):
        search_query = user_text.replace("搜尋", "").strip()
        search_results = await brave_search(search_query)
        user_prompt = f"用戶搜尋：{search_query}\n結果：{search_results}\n請整理並回答。"

    # C. 一般對話
    else:
        user_prompt = user_text

    # 紀錄記憶
    memory[user_id].append({"role": "user", "content": user_prompt})
    
    # 限制記憶長度 (免費模型建議維持在 5-8 輪對話以節省資源)
    if len(memory[user_id]) > 8:
        memory[user_id] = [memory[user_id][0]] + memory[user_id][-7:]

    try:
        completion = client.chat.completions.create(
            model=FREE_MODEL,
            messages=memory[user_id]
        )
        response = completion.choices[0].message.content
        memory[user_id].append({"role": "assistant", "content": response})
        await update.message.reply_text(response)
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            await update.message.reply_text("目前請求太頻繁（免費模型限制），請稍等一分鐘再試。")
        else:
            await update.message.reply_text(f"連線 OpenRouter 發生錯誤：{error_msg}")

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("免費版機器人運行中...")
    app.run_polling()

if __name__ == "__main__":
    main()
