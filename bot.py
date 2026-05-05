import os
import time
import random
import asyncio
from datetime import datetime
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from game_manager import SpyGame, GameState
from database import db

# --- CONFIGURATION ---
API_ID = 1234567  
API_HASH = "your_api_hash_here"
BOT_TOKEN = "your_bot_token_here"

# Load Locations
def load_locations():
    path = os.path.join(os.path.dirname(__file__), "data", "locations.txt")
    if os.path.exists(path):
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    return ["Hospital", "School"] 

LOCATIONS = load_locations()

# --- BOT SETUP ---
app = Client("spy_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
active_games = {}

# --- HELPER FUNCTIONS ---
async def send_role(client, user_id, text):
    try:
        await client.send_message(user_id, text)
    except Exception:
        pass 

async def start_voting_phase(chat_id, client):
    game = active_games.get(chat_id)
    if not game: return

    game.state = GameState.VOTING
    game.votes = {}
    
    await client.send_message(
        chat_id, 
        "🛑 **Time's up!**\n\nDiscussion over. Please vote for the spy using /vote @username.\nYou have 60 seconds."
    )
    
    await asyncio.sleep(60) 
    await end_game_voting(chat_id, client)

async def end_game_voting(chat_id, client):
    game = active_games.get(chat_id)
    if not game: return

    eliminated_id = game.tally_votes()
    
    if eliminated_id:
        eliminated_user = game.players[eliminated_id]
        role = "SPY 🕵️‍♂️" if game.is_spy(eliminated_id) else "Civilian 👱"
        
        await client.send_message(
            chat_id,
            f"🗳️ **Voting Results:**\n\n"
            f"Eliminated: {eliminated_user.mention} ({role})\n\n"
            f"Location was: **{game.location}**"
        )

        res = game.calculate_results(eliminated_id)
        
        # Update Stats
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
            await client.send_message(chat_id, "🏆 **Spies Win!**")
        else:
            await client.send_message(chat_id, "🏆 **Civilians Win!**")

    else:
        await client.send_message(chat_id, "No votes cast. Spies Win by default! 🏆")
    
    del active_games[chat_id]

async def handle_game_over(chat_id, client, winner_side, message_text):
    """Generic function to end game and update stats based on result"""
    game = active_games.get(chat_id)
    if not game: return

    await client.send_message(chat_id, message_text)
    
    # Update Stats
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

# --- COMMANDS ---

@app.on_message(filters.command("startspy") & filters.group)
async def start_game_cmd(client, message: Message):
    chat_id = message.chat.id
    
    if chat_id in active_games:
        await message.reply("A game is already running in this group!")
        return

    new_game = SpyGame(chat_id, message.from_user.id)
    active_games[chat_id] = new_game
    
    await message.reply(
        "🕵️‍♂️ **Spy Game Lobby Created!**\n\n"
        "Type /join to join the game.\n"
        f"Host: {message.from_user.mention}\n"
        "Waiting for players..."
    )

@app.on_message(filters.command("join") & filters.group)
async def join_cmd(client, message: Message):
    chat_id = message.chat.id
    user = message.from_user

    if chat_id not in active_games:
        await message.reply("No game lobby. Use /startspy to create one.")
        return

    game = active_games[chat_id]
    if game.state != GameState.LOBBY:
        await message.reply("Game already started!")
        return

    if game.add_player(user):
        await message.reply(f"✅ {user.mention} joined! ({len(game.players)})")
    else:
        await message.reply("You are already in the game.")

@app.on_message(filters.command("leave") & filters.group)
async def leave_cmd(client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id in active_games:
        game = active_games[chat_id]
        if game.remove_player(user_id):
            await message.reply(f"❌ You left the game.")
            if len(game.players) == 0:
                del active_games[chat_id]
        else:
            await message.reply("You are not in the game.")

@app.on_message(filters.command("begin") & filters.group)
async def begin_cmd(client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id not in active_games: return
    game = active_games[chat_id]
    
    if user_id != game.creator_id:
        await message.reply("Only the game host can start.")
        return

    success, msg = game.start_game(LOCATIONS)
    if not success:
        await message.reply(msg)
        return

    await message.reply(f"🚀 **Game Started!** \n\n{msg}\nDiscussion Phase: 5 Minutes!")

    for pid, player in game.players.items():
        role_msg = game.get_role_message(pid)
        await send_role(client, pid, role_msg)

    asyncio.create_task(start_voting_phase(chat_id, client))

@app.on_message(filters.command("vote") & filters.group)
async def vote_cmd(client, message: Message):
    chat_id = message.chat.id
    user = message.from_user
    
    if chat_id not in active_games: return
    game = active_games[chat_id]
    
    # Simplified parsing: prefer reply, fallback to command arg
    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif len(message.command) > 1:
        username = message.command[1].replace("@", "").lower()
        for p in game.players.values():
            if p.username and p.username.lower() == username:
                target_user = p
                break

    if not target_user:
        await message.reply("Please reply to the player or use @username to vote.")
        return
    
    success, msg = game.cast_vote(user.id, target_user.id)
    if success:
        await message.reply(f"✅ {msg}", reply_to_message_id=message.id)
    else:
        await message.reply(f"❌ {msg}")

@app.on_message(filters.command("guess") & filters.group)
async def guess_cmd(client, message: Message):
    chat_id = message.chat.id
    user = message.from_user
    
    if chat_id not in active_games: return
    game = active_games[chat_id]
    
    if game.state != GameState.PLAYING:
        await message.reply("You can only guess during the discussion phase!")
        return
    
    if not game.is_spy(user.id):
        await message.reply("Only the Spy can guess!")
        return
    
    # Check Constraints (Time & Attempts)
    can_guess, reason = game.can_guess(user.id)
    if not can_guess:
        await message.reply(reason)
        return
    
    guess_text = " ".join(message.command[1:]).strip()
    if not guess_text:
        await message.reply("Usage: /guess <location>")
        return

    # Lock the guess immediately (prevent spam guessing)
    game.register_guess(user.id)

    # Suspense Delay (3 seconds)
    await message.reply(f"🎲 {user.mention} is making a guess...")
    await asyncio.sleep(3)

    # Normalize for comparison (Title Case)
    formatted_guess = guess_text.title()
    
    if formatted_guess == game.location:
        # Spy Wins
        msg = (
            f"🎉 **GUESS CORRECT!**\n\n"
            f"The Spy ({user.mention}) correctly identified the location: **{game.location}**\n\n"
            f"**SPY WINS!** 🏆"
        )
        await handle_game_over(chat_id, client, "spies", msg)
    else:
        # Spy Loses (Civilians Win)
        msg = (
            f"💥 **GUESS FAILED!**\n\n"
            f"The Spy ({user.mention}) guessed: **{formatted_guess}**\n"
            f"But the location was: **{game.location}**\n\n"
            f"**CIVILIANS WIN!** 🏆"
        )
        await handle_game_over(chat_id, client, "civilians", msg)

@app.on_message(filters.command("mystats") & filters.private)
async def mystats_cmd(client, message: Message):
    user_id = message.from_user.id
    stats = db.get_user(user_id, message.from_user.username)
    rank = db.get_rank(stats['xp'])
    text = f"👤 **Stats**\n🏆 Rank: {rank}\n⭐ XP: {stats['xp']}\n✅ Wins: {stats['wins']}"
    await message.reply(text)

@app.on_message(filters.command("leaderboard") & filters.group)
async def leaderboard_cmd(client, message: Message):
    top = db.get_leaderboard(5)
    text = "🏆 **Leaderboard**\n\n"
    for i, (name, xp) in enumerate(top, 1):
        text += f"{i}. {name} - {xp} XP\n"
    await message.reply(text)

if __name__ == "__main__":
    print("Bot Started...")
    app.run()
