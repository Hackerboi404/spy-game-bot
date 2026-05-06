from flask import Flask
from threading import Thread
import os

# Flask App setup
app = Flask(__name__)

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Bot is Alive! 🚀"

# Server ko background mein run karne ke liye function
def run():
    # Port environment variable se lena zaroori hai (Render ke liye)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# Jab file run ho, to server start ho
def keep_alive():
    t = Thread(target=run)
    t.start()

if __name__ == "__main__":
    keep_alive()
