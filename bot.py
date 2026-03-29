import asyncio
import logging
import time
import os
import uuid
import firebase_admin
from firebase_admin import credentials, db as firebase_db
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, 
    InlineKeyboardButton, WebAppInfo, MenuButtonWebApp, Message, CallbackQuery, FSInputFile
)
from aiogram.exceptions import TelegramForbiddenError, TelegramUnauthorizedError, TelegramRetryAfter, TelegramAPIError

# --- ১. Firebase কানেকশন সেটআপ ---
# আপনার দেওয়া vairal-video-18 ডাটাবেস ব্যবহার করা হয়েছে
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://mr-games-club-default-rtdb.firebaseio.com/' 
    })

# --- ২. ট্রাফিক পুলিশ (Rate Limiter) Middleware ---
class TrafficPoliceMiddleware(BaseMiddleware):
    def __init__(self, limit: int = 25):
        self.limit = limit
        self.request_times = []
        super().__init__()

    async def __call__(self, handler, event, data):
        current_time = time.time()
        self.request_times = [t for t in self.request_times if current_time - t < 1.0]
        
        if len(self.request_times) >= self.limit:
            await asyncio.sleep(0.1) 
            return await self.__call__(handler, event, data)
        
        self.request_times.append(current_time)
        return await handler(event, data)

# --- ৩. কনফিগারেশন ও বট সেটআপ ---
TOKEN = "8667547386:AAEKUjJxqR16Ci7mU4ERD-GnBEPv1naU1X4" 
ADMIN_LIST = [6856009995, 5846193023] 
WEB_APP_URL = "https://movibd.pages.dev/" 
CHANNEL_USERNAME = "@bachelor_update"
CHANNEL_LINK = "https://t.me/bachelor_update"

bot = Bot(token=TOKEN)
dp = Dispatcher()

traffic_manager = TrafficPoliceMiddleware(limit=25)
dp.message.outer_middleware(traffic_manager)

# --- ৪. FSM States ---
class VideoUpload(StatesGroup):
    name = State()
    photo = State()
    video_url = State() 

class VideoDelete(StatesGroup):
    waiting_for_search = State()
    confirm_selection = State()

class BotNotice(StatesGroup):
    waiting_for_payload = State()

# --- ৫. কিবোর্ড ফাংশনসমূহ ---
def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Add Video"), KeyboardButton(text="🔕 Delete Video")],
        [KeyboardButton(text="📢 BOT NOTICE"), KeyboardButton(text="📊 Total User")],
        [KeyboardButton(text="🔙 Back to Menu")]
    ], resize_keyboard=True)

def get_back_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Back to Menu")]], resize_keyboard=True)

# --- ৬. চ্যানেল জয়েন চেক ফাংশন ---
async def is_subscribed(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return True 

# --- ৭. স্টার্ট হ্যান্ডলার ---
@dp.message(CommandStart())
@dp.message(F.text == "🔙 Back to Menu")
async def start_handler(message: Message, command: CommandObject = None, state: FSMContext = None):
    if state: await state.clear()
    user_id = str(message.from_user.id)
    
    # ইউজার ডাটাবেসে সেভ করা
    user_ref = firebase_db.reference(f'users/{user_id}')
    if not user_ref.get():
        user_ref.set({'joined_at': time.time()})

    # ওয়েব অ্যাপ মেনু বাটন সেটআপ
    try:
        await bot.set_chat_menu_button(
            chat_id=int(user_id), 
            menu_button=MenuButtonWebApp(text="Watch Now 🎬", web_app=WebAppInfo(url=WEB_APP_URL))
        )
    except: pass

    # স্বাগতম মেসেজ এবং জয়েন করার অনুরোধ
    subscribed = await is_subscribed(int(user_id))
    welcome_text = (
        f"<b>আসসালামুয়ালাইকুম 🥰</b>\n\n"
        f"MOVI TUBE বটে আপনাকে স্বাগতম। নিচের চ্যানেলে জয়েন করুন।\n\n"
        f"নিচের <b>Watch Now</b> বাটনে ক্লিক করে সরাসরি আমাদের ওয়েব অ্যাপে ভিডিও দেখুন। 🥰"
    )

    kb_list = [
        [InlineKeyboardButton(text="📢 Join Our Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton(text="🎬 Watch Now (Web App)", web_app=WebAppInfo(url=WEB_APP_URL))]
    ]
    
    if not subscribed:
        kb_list.insert(0, [InlineKeyboardButton(text="✅ Joined (Check)", callback_data="check_subs")])

    user_kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
    await message.answer(welcome_text, reply_markup=user_kb, parse_mode="HTML")
    
    if int(user_id) in ADMIN_LIST:
        await message.answer("🛠 এডমিন প্যানেল সচল করা হয়েছে:", reply_markup=get_admin_kb())

@dp.callback_query(F.data == "check_subs")
async def check_subs_callback(callback: CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.answer("✅ ধন্যবাদ! আপনি সফলভাবে জয়েন করেছেন।", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Watch Now (Web App)", web_app=WebAppInfo(url=WEB_APP_URL))]
        ]))
    else:
        await callback.answer("❌ আপনি এখনো জয়েন করেননি! দয়া করে জয়েন করুন।", show_alert=True)

# --- ৮. টোটাল ইউজার চেক ---
@dp.message(F.text == "📊 Total User")
async def total_user_handler(message: Message):
    if message.from_user.id in ADMIN_LIST:
        users_ref = firebase_db.reference('users').get()
        if users_ref:
            total_count = len(users_ref.keys())
            await message.answer(f"📊 <b>বটের বর্তমান অবস্থা:</b>\n\nমোট ইউজার সংখ্যা: <code>{total_count}</code> জন।", parse_mode="HTML")
        else:
            await message.answer("❌ ডাটাবেসে কোনো ইউজার পাওয়া যায়নি।")

# --- ৯. ভিডিও অ্যাড করার সেকশন ---
@dp.message(F.text == "➕ Add Video")
async def add_v_start(message: Message, state: FSMContext):
    if message.from_user.id in ADMIN_LIST:
        await state.set_state(VideoUpload.name)
        await message.answer("📝 ভিডিওর টাইটেল লিখুন (যেমন: Episode 01):", reply_markup=get_back_kb())

@dp.message(VideoUpload.name)
async def add_v_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(VideoUpload.photo)
    await message.answer("🖼 থাম্বনেইল পাঠান (লিঙ্ক অথবা ফটো):", reply_markup=get_back_kb())

@dp.message(VideoUpload.photo)
async def add_v_photo(message: Message, state: FSMContext):
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
        await state.update_data(photo=photo_url)
    else:
        await state.update_data(photo=message.text)
    
    await state.set_state(VideoUpload.video_url)
    await message.answer("🔗 ভিডিওর ডাইরেক্ট MP4 লিঙ্কটি দিন (যেমন: https://site.com/video.mp4):", reply_markup=get_back_kb())

@dp.message(VideoUpload.video_url)
async def add_v_final(message: Message, state: FSMContext):
    data = await state.get_data()
    v_id = str(uuid.uuid4())[:8]
    
    firebase_db.reference(f'videos/{v_id}').set({
        'id': v_id,
        'name': data['name'],
        'photo': data['photo'],
        'video_url': message.text 
    })
    
    await message.answer(f"✅ ভিডিও MOVI TUBE ডাটাবেসে সফলভাবে যুক্ত হয়েছে!\nআইডProntubed}`", reply_markup=get_admin_kb())
    await state.clear()

# --- ১০. ভিডিও ডিলিট সেকশন ---
@dp.message(F.text == "🔕 Delete Video")
async def delete_v_init(message: Message, state: FSMContext):
    if message.from_user.id in ADMIN_LIST:
        await state.set_state(VideoDelete.waiting_for_search)
        await message.answer("🔍 ডিলিট করতে চাওয়া ভিডিওর নাম লিখুন:", reply_markup=get_back_kb())

@dp.message(VideoDelete.waiting_for_search)
async def delete_v_search_results(message: Message, state: FSMContext):
    query = message.text.lower()
    videos_ref = firebase_db.reference('videos').get()
    if not videos_ref: return await message.answer("❌ ডাটাবেসে কোনো ভিডিও নেই।")
    
    matches = [v for v in videos_ref.values() if query in v['name'].lower()]
    if not matches: return await message.answer("❌ এই নামে কোনো ভিডিও পাওয়া যায়নি।")

    buttons = [[InlineKeyboardButton(text=f"🗑 {v['name']}", callback_data=f"askdel_{v['id']}")] for v in matches]
    buttons.append([InlineKeyboardButton(text="❌ বাতিল", callback_data="cancel_del")])
    
    await message.answer(f"🔎 {len(matches)}টি ভিডিও পাওয়া গেছে। কোনটি ডিলিট করবেন?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(VideoDelete.confirm_selection)

@dp.callback_query(F.data.startswith("askdel_"))
async def delete_v_ask_confirm(callback: CallbackQuery):
    vid_id = callback.data.split("_")[1]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ নিশ্চিত মুছুন", callback_data=f"dodel_{vid_id}")],
        [InlineKeyboardButton(text="🔙 বাতিল", callback_data="cancel_del")]
    ])
    await callback.message.edit_text("⚠️ আপনি কি নিশ্চিতভাবে ভিডিওটি মুছতে চান?", reply_markup=kb)

@dp.callback_query(F.data.startswith("dodel_"))
async def delete_v_execute(callback: CallbackQuery, state: FSMContext):
    vid_id = callback.data.split("_")[1]
    firebase_db.reference(f'videos/{vid_id}').delete()
    await callback.message.edit_text("✅ ভিডিওটি সফলভাবে মুছে ফেলা হয়েছে।")
    await state.clear()

# --- ১১. ব্রডকাস্ট সিস্টেম (১০ জন/সেকেন্ড লিমিট এবং লাইভ রিপোর্ট) ---
@dp.message(F.text == "📢 BOT NOTICE")
async def notice_init(message: Message, state: FSMContext):
    if message.from_user.id in ADMIN_LIST:
        await state.set_state(BotNotice.waiting_for_payload)
        await message.answer("📢 নোটিশ মেসেজটি দিন (টেক্সট/ছবি/ভিডিও):", reply_markup=get_back_kb())

@dp.message(BotNotice.waiting_for_payload)
async def notice_broadcast(message: Message, state: FSMContext):
    users_ref = firebase_db.reference('users').get()
    if not users_ref:
        await message.answer("❌ কোনো ইউজার পাওয়া যায়নি।")
        await state.clear()
        return

    users = list(users_ref.keys())
    total_users = len(users)
    sent_count = 0
    failed_count = 0
    start_time = time.time()
    
    progress_msg = await message.answer(f"🚀 ব্রডকাস্ট মিশন শুরু হয়েছে...\n📊 টার্গেট ইউজার: `{total_users}`")

    # প্রতি সেকেন্ডে ১০ জনকে পাঠানোর লজিক
    for i in range(0, total_users, 10):
        batch = users[i:i+10]
        batch_start_time = time.time()
        
        for uid in batch:
            try: 
                await message.copy_to(chat_id=int(uid))
                sent_count += 1
            except Exception: 
                failed_count += 1
        
        # লাইভ রিপোর্ট আপডেট
        current_elapsed = time.time() - start_time
        msgs_per_sec = round(sent_count / current_elapsed if current_elapsed > 0 else 0, 1)
        
        try:
            await progress_msg.edit_text(
                f"🛰 <b>ব্রডকাস্ট প্রগ্রেস রিপোর্ট:</b>\n\n"
                f"📊 টার্গেট ইউজার: <code>{total_users}</code>\n"
                f"✅ সফল ডেলিভারি: <code>{sent_count}</code>\n"
                f"❌ ব্যর্থ হয়েছে: <code>{failed_count}</code>\n"
                f"⚡ স্পিড: <code>{msgs_per_sec} msg/sec</code>\n"
                f"⏱ সময় অতিবাহিত: <code>{round(current_elapsed, 1)}s</code>",
                parse_mode="HTML"
            )
        except: pass

        # ১০ জন পাঠানোর পর ১ সেকেন্ড গ্যাপ নিশ্চিত করা (সেফটি)
        await asyncio.sleep(1.0)

    final_time = round(time.time() - start_time, 2)
    await message.answer(
        f"✅ <b>ব্রডকাস্ট সম্পন্ন!</b>\n\n"
        f"🎯 মোট সফল: <code>{sent_count}</code>\n"
        f"🚫 মোট ব্যর্থ: <code>{failed_count}</code>\n"
        f"⏱ মোট সময় লেগেছে: <code>{final_time}s</code>", 
        reply_markup=get_admin_kb(), parse_mode="HTML"
    )
    await state.clear()

# --- ১২. মেইন রানার ---
async def main():
    try:
        print("🤖 MR TUBE Bot is Running with Cloud Database...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): pass
