import os
import asyncio
import random
import json  # <--- ADDED
from threading import Thread
from flask import Flask, request
from pyrogram import Client, filters
from pyrogram.types import Message
from game_manager import SpyGame, GameState
from database import db

# --- CONFIGURATION ---
# Render/Heroku par Environment Variables set karna mat bhoolna
API_ID = int(os.environ.get("API_ID", 1234567))
API_HASH = os.environ.get("API_HASH", "your_api_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://your-app-name.onrender.com")

# --- FLASK APP ---
app = Flask(__name__)

# --- PYROGRAM CLIENT ---
# in_memory=True free tiers ke liye zaroori hai
bot = Client(
    "spy_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    in_memory=True
)

active_games = {}

# --- DATA LOAD ---
def load_locations():
    path = os.path.join(os.path.dirname(__file__), "data", "locations.txt")
    if os.path.exists(path):
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    return ["Hospital", "School"]
LOCATIONS = load_locations()

# --- CONSTANTS (Welcome & Help) ---
WELCOME_TEXT = """
👋 Welcome to the **Spy Game Bot**! 🕵️‍♂️

I am a multiplayer game bot designed for Telegram groups. 
Find the spy before time runs out, or deceive everyone if you are the spy!

Type /help to see how to play.
"""

FEATURES_TEXT = """
🚀 **Bot Features:**

🗺️ **50+ Unique Locations**: From Space Stations to Schools.
🎭 **Role Assignment**: Private messages for spies and civilians.
⏱️ **Timed Rounds**: Discussion and Voting phases.
🎯 **Balanced Guessing**: Spies must reason, not just luck-guess.
🏆 **Rank System**: Earn XP and level up from Rookie to Master Spy.
📊 **Leaderboard**: Compete with your friends.
"""

HOW_TO_PLAY_TEXT = """
📖 **How to Play:**

1️⃣ **Join the Game**: Use /startspy in a group and type /join.
2️⃣ **Roles**:
   • 🕵️ **Spy**: You don't know the location. Blend in and guess correctly!
   • 👱 **Civilian**: You know the location. Ask questions to find the Spy!
3️⃣ **Discussion**: Chat for 5 minutes. Be careful not to reveal too much!
4️⃣ **Voting**: After time runs out, vote to eliminate the suspect using /vote.
5️⃣ **Winning**:
   • Civilians win if they vote out the Spy.
   • Spy wins if they survive the vote OR guess the location correctly.

📌 **Commands List:**
/startspy - Start a new lobby
/join - Join the active game
/begin - Start the game (Host only)
/guess <location> - Spy guesses the location
/vote @username - Vote to eliminate a player
/leaderboard - Top 5 players
/mystats - Check your rank & XP
"""

# --- HELPER FUNCTIONS ---
async def send_role(user_id, text):
    try:
        await bot.send_message(user_id, text)
    except Exception:
        pass

async def start_voting_phase(chat_id):
    game = active_games.get(chat_id)
    if not game: return

    game.state = GameState.VOTING
    game.votes = {}
    
    await bot.send_message(
        chat_id, 
        "🛑 **Time's up!**\n\nDiscussion over. Please vote for the spy using /vote @username.\nYou have 60 seconds."
    )
    
    await asyncio.sleep(60)
    await end_game_voting(chat_id)

async def end_game_voting(chat_id):
    game = active_games.get(chat_id)
    if not game: return

    eliminated_id = game.tally_votes()
    
    if eliminated_id:
        eliminated_user = game.players[eliminated_id]
        role = "SPY 🕵️‍♂️" if game.is_spy(eliminated_id) else "Civilian 👱"
        
        await bot.send_message(
            chat_id,
            f"🗳️ **Voting Results:**\n\n"
            f"Eliminated: {eliminated_user.first_name} ({role})\n\n"
            f"Location was: **{game.location}**"
        )

        # Stats Update
        res = game.calculate_results(eliminated_id)
        for pid, player in game.players.items():
            stats = db.get_user(pid, player.username)
            is_spy = game.is_spy(pid)
            won = False
            if res["winner_side"] == "spies" and is_spy:
                won = True
                db.update_xp(pid, 50)
            elif res["winner_side"] == "civilians" and not is_spy:
                won = True
                db.update_xp(pid, 30)
            if won: db.increment_stat(pid, "wins")
            else: db.increment_stat(pid, "losses")
            db.increment_stat(pid, "games_played")

        if res["winner_side"] == "spies":
            await bot.send_message(chat_id, "🏆 **Spies Win!**")
        else:
            await bot.send_message(chat_id, "🏆 **Civilians Win!**")
    else:
        await bot.send_message(chat_id, "No votes cast. Spies Win by default! 🏆")
    
    del active_games[chat_id]

async def handle_game_over(chat_id, winner_side, text):
    game = active_games.get(chat_id)
    if not game: return
    await bot.send_message(chat_id, text)
    
    # Stats Update
    for pid, player in game.players.items():
        stats = db.get_user(pid, player.username)
        is_spy = game.is_spy(pid)
        won = False
        if winner_side == "spies" and is_spy:
            won = True
            db.update_xp(pid, 50)
        elif winner_side == "civilians" and not is_spy:
            won = True
            db.update_xp(pid, 30)
        if won: db.increment_stat(pid, "wins")
        else: db.increment_stat(pid, "losses")
        db.increment_stat(pid, "games_played")
    del active_games[chat_id]

# --- HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_private_cmd(_, message: Message):
    await message.reply(WELCOME_TEXT)

@bot.on_message(filters.command("help"))
async def help_cmd(_, message: Message):
    full_text = f"{FEATURES_TEXT}\n\n{HOW_TO_PLAY_TEXT}"
    await message.reply(full_text, disable_web_page_preview=True)

@bot.on_message(filters.command("startspy") & filters.group)
async def start_game_cmd(_, message: Message):
    if message.chat.id not in active_games:
        active_games[message.chat.id] = SpyGame(message.chat.id, message.from_user.id)
        await message.reply(
            "🕵️‍♂️ **Spy Game Lobby Created!**\n\n"
            "Type /join to join the game.\n"
            f"Host: {message.from_user.first_name}\n"
            "Waiting for players..."
        )

@bot.on_message(filters.command("join") & filters.group)
async def join_game(_, message: Message):
    game = active_games.get(message.chat.id)
    if game and game.state == GameState.LOBBY:
        if game.add_player(message.from_user):
            await message.reply(f"✅ {message.from_user.first_name} joined!")

@bot.on_message(filters.command("begin") & filters.group)
async def begin_game(_, message: Message):
    game = active_games.get(message.chat.id)
    if game and game.creator_id == message.from_user.id:
        success, msg = game.start_game(LOCATIONS)
        if success:
            await message.reply(msg)
            for pid, p in game.players.items():
                await send_role(pid, game.get_role_message(pid))
            asyncio.create_task(start_voting_phase(message.chat.id))
        else:
            await message.reply(msg)

@bot.on_message(filters.command("guess") & filters.group)
async def guess_game(_, message: Message):
    game = active_games.get(message.chat.id)
    if not game or game.state != GameState.PLAYING: return
    if not game.is_spy(message.from_user.id):
        await message.reply("Only Spy!")
        return
    
    can_guess, reason = game.can_guess(message.from_user.id)
    if not can_guess:
        await message.reply(reason)
        return
    
    guess = " ".join(message.command[1:]).strip()
    game.register_guess(message.from_user.id)
    
    await message.reply(f"🎲 Guessing...")
    await asyncio.sleep(3)
    
    if guess.title() == game.location:
        await handle_game_over(message.chat.id, "spies", "🎉 Spy Guessed Correct! Spy Wins!")
    else:
        await handle_game_over(message.chat.id, "civilians", "💥 Spy Wrong! Civilians Win!")

@bot.on_message(filters.command("vote") & filters.group)
async def vote_game(_, message: Message):
    game = active_games.get(message.chat.id)
    if game and game.state == GameState.VOTING:
        if message.reply_to_message:
            target = message.reply_to_message.from_user
            game.cast_vote(message.from_user.id, target.id)
            await message.reply(f"Voted {target.first_name}")

@bot.on_message(filters.command("mystats") & filters.private)
async def mystats_cmd(_, message: Message):
    user_id = message.from_user.id
    stats = db.get_user(user_id, message.from_user.username)
    rank = db.get_rank(stats['xp'])
    await message.reply(f"👤 **Stats**\n🏆 Rank: {rank}\n⭐ XP: {stats['xp']}")

@bot.on_message(filters.command("leaderboard") & filters.group)
async def leaderboard_cmd(_, message: Message):
    top = db.get_leaderboard(5)
    text = "🏆 **Leaderboard**\n\n"
    for i, (name, xp) in enumerate(top, 1):
        text += f"{i}. {name} - {xp} XP\n"
    await message.reply(text)

# --- FLASK ROUTES ---

@app.route("/", methods=["GET", "POST"])
def webhook():
    # Telegram POST request yahan aayega
    if request.method == "GET":
        return "Spy Game Bot is Running via Webhook! 🚀"
    
    # 1. Raw JSON data lo
    str_data = request.get_data(as_text=True)
    data = json.loads(str_data)
    
    # 2. Thread-Safe tareeke se Pyrogram ke loop mein update daalo
    # dispatcher.handle_update direct use nahi karte, put queue use karte hain
    asyncio.run_coroutine_threadsafe(
        bot.update_queue.put(data),
        bot.loop
    )
    
    return "OK", 200

# --- BOOTSTRAP ---

def run_pyrogram():
    """Runs the bot client in a separate thread to keep Flask running"""
    print("Setting Webhook...")
    
    # Async function create karke run karenge
    async def start_and_set_webhook():
        await bot.start()
        await bot.delete_webhook()
        # URL set karo
        await bot.set_webhook(url=f"{WEBHOOK_URL}/")
        print(f"Webhook set to: {WEBHOOK_URL}/")
        # Idly rukho taaki loop band na ho
        await asyncio.Event().wait()

    # New Event Loop banayein
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Async function chalayein
    loop.run_until_complete(start_and_set_webhook())
    
    # Loop ko idle mein rakhein (yeh line kabhi hit nahi hogi kyunki upar wait() laga hai)
    # Lekin safety ke liye loop close karna zaroori nahi hai kyunki idle mein chalna chahiye
    loop.run_forever()

if __name__ == "__main__":
    # 1. Start Pyrogram in background
    t = Thread(target=run_pyrogram, daemon=True)
    t.start()
    
    # 2. Start Flask Server
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
