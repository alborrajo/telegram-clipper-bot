#!/usr/bin/env python

import configparser
import logging
import re
import tempfile
import time
from os import remove
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from yt_dlp import YoutubeDL

class RateLimitError(Exception):
    pass

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)

url_regex = re.compile(
        r'^(?:http|ftp)s?://' # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' #domain...
        #r'localhost|' #localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
        r'(?::\d+)?' # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

timestamp_regex = re.compile(r'([0-9]+\:)?([0-9]{1,2}\:)?[0-9]{1,2}')

rate_limit = {}

# Define a few command handlers. These usually take the two arguments update and
# context.
def start(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    update.message.reply_markdown_v2(
        fr'Hi {user.mention_markdown_v2()}\! Send me a YT link and a time range and I\'ll clip it for you\!'
    )
    help(update, context)

def help(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "Usage:\n/clip https://www.youtube.com/watch?v=dQw4w9WgXcQ 00:00:00 00:00:05"
    )

def clip(update: Update, context: CallbackContext) -> None:
    try:
        url = context.args[0]
        start_time = context.args[1]
        end_time = context.args[2]

        if url_regex.fullmatch(url) is None \
        or timestamp_regex.fullmatch(start_time) is None \
        or timestamp_regex.fullmatch(end_time) is None:
            raise ValueError

        if exceeds_rate_limit(update.message.chat_id):
            raise RateLimitError

        update.message.reply_text("Clipping...")
        logger.info(f"For chat {update.message.chat_id}: Clipping {url} from {start_time} to {end_time}")

        ydl_opts = {
            'external_downloader': 'ffmpeg',
            'external_downloader_args': {'ffmpeg_i': ['-ss', start_time, '-to', end_time]},
            'outtmpl': f'{download_directory}/%(id)s.%(ext)s',
            "format": "mp4",
            "noplaylist": True,
            "quiet": True,
        }  
        with YoutubeDL(ydl_opts) as ydl:
            meta = ydl.extract_info(
                url,
                download=True,
            )
            video_id = meta["id"]
            video_ext = meta["ext"]

        with open(f"{download_directory}/{video_id}.{video_ext}", "rb") as file:
            update.message.reply_video(file)
            
        # Clean up
        remove(f"{download_directory}/{video_id}.{video_ext}")

        logger.info(f"For chat {update.message.chat_id}: Done clipping {url} from {start_time} to {end_time}")

    except (IndexError, ValueError):
        help(update, context)

    except RateLimitError:
        update.message.reply_text("Too many requests. Try again later.")
        logger.warning(f"For chat {update.message.chat_id}: Rate limit exceeded")

    except Exception as e:
        update.message.reply_text("Something went wrong somehow, please try again later")
        logger.exception(f"For chat {update.message.chat_id}: Something went wrong", e)


def exceeds_rate_limit(chat_id: int) -> bool:
    global rate_limit
    if chat_id not in rate_limit:
        rate_limit[chat_id] = []

    for timestamp in rate_limit[chat_id]:
        if timestamp + rate_limit_minutes*60 < time.time():
            rate_limit[chat_id].clear()
            break

    rate_limit[chat_id].append(time.time())
    
    return len(rate_limit[chat_id]) > rate_limit_threshold


def main() -> None:
    """Start the bot."""
    # Create the Updater and pass it your bot's token.
    updater = Updater(api_key)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # on different commands - answer in Telegram
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help))
    dispatcher.add_handler(CommandHandler("clip", clip))

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    try:
        config = configparser.ConfigParser()
        config.read('config.ini')
        api_key = config['General']['APIKey']
        rate_limit_threshold = int(config['General']['RateLimitThreshold'])
        rate_limit_minutes = int(config['General']['RateLimitMinutes'])
    except KeyError as e:
        config['General'] = {
            'APIKey': 'Enter your API key here',
            'RateLimitThreshold': '5',
            'RateLimitMinutes': '5',
        }
        with open('config.ini', 'w') as configfile:
            config.write(configfile)
        logger.error("API key not found, please enter it in config.ini")
        exit(1)

    with tempfile.TemporaryDirectory() as download_directory:
        main()