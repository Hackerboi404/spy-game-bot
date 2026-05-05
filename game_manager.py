import random
import time
from pyrogram.types import User
from database import db

class GameState:
    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    VOTING = "VOTING"

class SpyGame:
    def __init__(self, chat_id, creator_id):
        self.chat_id = chat_id
        self.creator_id = creator_id
        self.state = GameState.LOBBY
        self.players = {}  # {user_id: User obj}
        self.location = ""
        self.allowed_locations = [] # Pool for this game (8-12 locations)
        self.spies = []
        self.votes = {}   # {voter_id: target_id}
        self.start_time = 0 # Unix timestamp when game started
        self.guess_attempts = set() # Track who has guessed

    def add_player(self, user: User):
        if user.id not in self.players:
            self.players[user.id] = user
            return True
        return False

    def remove_player(self, user_id):
        if user_id in self.players:
            del self.players[user_id]
            return True
        return False

    def start_game(self, full_locations_list):
        if len(self.players) < 3:
            return False, "Need at least 3 players!"
        
        self.state = GameState.PLAYING
        self.start_time = time.time()
        
        # 1. Create a smaller pool of 8-12 locations for this game
        # This prevents the Spy from having a 1/50 chance by pure luck
        pool_size = random.randint(8, 12)
        self.allowed_locations = random.sample(full_locations_list, pool_size)
        
        # 2. Pick the ACTUAL location from this restricted pool
        self.location = random.choice(self.allowed_locations)
        
        # Determine spy count
        num_spies = max(1, len(self.players) // 5)
        if len(self.players) >= 7: num_spies = 2
        
        player_ids = list(self.players.keys())
        self.spies = random.sample(player_ids, num_spies)
        
        return True, "Game Started! Check your DMs."

    def get_role_message(self, user_id):
        if user_id in self.spies:
            # Show the restricted pool to the Spy so they can reason
            pool_str = "\n".join([f"• {loc}" for loc in self.allowed_locations])
            return (
                f"🕵️‍♂️ **You are the SPY!**\n\n"
                f"The location is one of these:\n{pool_str}\n\n"
                f"You can use /guess <location> to win.\n"
                f"⚠️ You only have **ONE** chance. Wrong guess = Instant Loss."
            )
        else:
            return f"📍 **Location:** {self.location}\n\nThe Spy doesn't know this place. Ask questions to find them!"

    def is_spy(self, user_id):
        return user_id in self.spies

    def can_guess(self, user_id):
        # Rule: Lock for first 2 minutes (120 seconds)
        if time.time() - self.start_time < 120:
            return False, "❌ Guessing is locked for the first 2 minutes!"
        
        # Rule: Only one guess allowed
        if user_id in self.guess_attempts:
            return False, "❌ You have already used your single guess!"
            
        return True, "OK"

    def register_guess(self, user_id):
        self.guess_attempts.add(user_id)

    def cast_vote(self, voter_id, target_id):
        if self.state != GameState.VOTING:
            return False, "Voting is not active."
        if voter_id not in self.players:
            return False, "You are not in the game."
        if target_id not in self.players:
            return False, "Invalid target."
        
        self.votes[voter_id] = target_id
        return True, f"Voted for {self.players[target_id].first_name}"

    def tally_votes(self):
        counts = {}
        for voter, target in self.votes.items():
            counts[target] = counts.get(target, 0) + 1
        
        if not counts: return None 
        
        max_votes = max(counts.values())
        candidates = [pid for pid, count in counts.items() if count == max_votes]
        eliminated_id = random.choice(candidates)
        return eliminated_id

    def calculate_results(self, eliminated_id):
        spy_eliminated = eliminated_id in self.spies
        
        results = {
            "winner_side": None, 
            "eliminated": eliminated_id,
            "spy_eliminated": spy_eliminated
        }

        if spy_eliminated:
            results["winner_side"] = "civilians"
        else:
            results["winner_side"] = "spies"
            
        return results
