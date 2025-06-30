import os
import time
import logging
import feedparser
import requests
import magic
import subprocess
import yt_dlp
import libtorrent as lt
from pyrogram import Client, filters
from pyrogram.types import InputMediaVideo
from urllib.parse import urlparse
from pathlib import Path

# Configuration
API_ID = "27394279"  # Replace with your API ID
API_HASH = "90a9aa4c31afa3750da5fd686c410851"  # Replace with your API Hash
BOT_TOKEN = "7721902522:AAFnaEw9JuYmmfqPybFkgX60mGqO-fk9bJE"  # Replace with your Bot Token
CHANNEL_ID = -1002288135729  # Replace with your Telegram channel ID
RSS_FEEDS = [
    "https://nyaa.si/?page=rss",  # SubsPlease 1080p
    "https://subsplease.org/rss"  # Nyaa 1080p
]
DOWNLOAD_DIR = "/app/downloads/"  # Koyeb volume or temp directory
TORRENT_DIR = "/app/torrents/"  # Koyeb volume or temp directory
THUMBNAIL_DIR = "/app/thumbnails/"  # Koyeb volume or temp directory
CHECK_INTERVAL = 30  # Check RSS every 5 minutes
PROCESSED_TORRENTS_FILE = "/app/processed_torrents.txt"  # Track processed torrents
SEEDING_TIME = 60  # Seed for 1 hour after download (adjust as needed)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("/app/bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize Pyrogram client
app = Client("rss_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Ensure directories exist
for dir_path in [DOWNLOAD_DIR, TORRENT_DIR, THUMBNAIL_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# Load processed torrent IDs
def load_processed_torrents():
    if os.path.exists(PROCESSED_TORRENTS_FILE):
        with open(PROCESSED_TORRENTS_FILE, "r") as f:
            return set(f.read().splitlines())
    return set()

# Save processed torrent ID
def save_processed_torrent(torrent_id):
    with open(PROCESSED_TORRENTS_FILE, "a") as f:
        f.write(torrent_id + "\n")

# Get video duration using ffprobe
def get_video_duration(file_path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True
        )
        duration = int(float(result.stdout.strip()))
        return duration
    except Exception as e:
        logger.error(f"Error getting duration for {file_path}: {e}")
        return None

# Generate thumbnail using ffmpeg
def generate_thumbnail(file_path):
    thumbnail_path = os.path.join(THUMBNAIL_DIR, f"{os.path.basename(file_path)}.jpg")
    try:
        subprocess.run(
            ["ffmpeg", "-i", file_path, "-ss", "00:00:05", "-vframes", "1", thumbnail_path, "-y"],
            capture_output=True, text=True
        )
        if os.path.exists(thumbnail_path):
            return thumbnail_path
        logger.error(f"Thumbnail not generated for {file_path}")
        return None
    except Exception as e:
        logger.error(f"Error generating thumbnail for {file_path}: {e}")
        return None

# Check if file is a video
def is_video_file(file_path):
    mime = magic.Magic(mime=True)
    file_type = mime.from_file(file_path)
    return file_type.startswith("video/")

# Download .torrent file using yt-dlp
def download_torrent(torrent_url, torrent_title):
    torrent_path = os.path.join(TORRENT_DIR, f"{torrent_title}.torrent")
    try:
        ydl_opts = {
            "outtmpl": torrent_path,
            "quiet": True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([torrent_url])
        if os.path.exists(torrent_path):
            logger.info(f"Downloaded torrent: {torrent_path}")
            return torrent_path
        return None
    except Exception as e:
        logger.error(f"Error downloading torrent {torrent_url}: {e}")
        return None

# Download and seed torrent using libtorrent
def download_and_seed_torrent(torrent_path=None, magnet_link=None, torrent_title=None):
    ses = lt.session()
    ses.listen_on(6881, 6891)  # Default torrent ports
    params = {
        "save_path": DOWNLOAD_DIR,
        "storage_mode": lt.storage_mode_t.storage_mode_sparse
    }

    if torrent_path:
        with open(torrent_path, "rb") as f:
            torrent_info = lt.torrent_info(lt.bdecode(f.read()))
        handle = ses.add_torrent({"ti": torrent_info, **params})
    elif magnet_link:
        handle = lt.add_magnet_uri(ses, magnet_link, params)

    logger.info(f"Starting download: {torrent_title}")
    while not handle.status().is_seeding:
        s = handle.status()
        logger.info(f"Download progress: {s.progress * 100:.2f}% ({torrent_title})")
        time.sleep(5)

    logger.info(f"Download complete: {torrent_title}")
    # Seed for SEEDING_TIME seconds
    seeding_start = time.time()
    while time.time() - seeding_start < SEEDING_TIME:
        logger.info(f"Seeding: {torrent_title} ({int(time.time() - seeding_start)}s/{SEEDING_TIME}s)")
        time.sleep(10)

    # Return downloaded files
    torrent_info = handle.torrent_file()
    files = []
    for file in torrent_info.files():
        file_path = os.path.join(DOWNLOAD_DIR, file.path)
        if os.path.exists(file_path):
            files.append(file_path)
    ses.remove_torrent(handle)
    return files

# Process RSS feeds
def process_rss_feeds():
    logger.info("Checking RSS feeds...")
    processed_torrents = load_processed_torrents()

    for rss_url in RSS_FEEDS:
        logger.info(f"Processing RSS feed: {rss_url}")
        feed = feedparser.parse(rss_url)

        for entry in feed.entries:
            torrent_id = entry.id
            if torrent_id in processed_torrents:
                continue

            torrent_url = entry.link
            torrent_title = entry.title.replace("/", "_").replace("\\", "_")
            logger.info(f"Found new torrent: {torrent_title}")

            # Handle magnet link or .torrent file
            torrent_path = None
            magnet_link = None
            if torrent_url.startswith("magnet:"):
                magnet_link = torrent_url
            elif torrent_url.endswith(".torrent"):
                torrent_path = download_torrent(torrent_url, torrent_title)
                if not torrent_path:
                    continue

            # Download and seed torrent
            try:
                downloaded_files = download_and_seed_torrent(torrent_path, magnet_link, torrent_title)
            except Exception as e:
                logger.error(f"Error downloading/seeding {torrent_title}: {e}")
                continue

            # Process downloaded video files
            for file_path in downloaded_files:
                if is_video_file(file_path):
                    try:
                        # Get video duration
                        duration = get_video_duration(file_path)
                        if duration is None:
                            logger.error(f"Skipping {file_path}: Could not determine duration")
                            continue

                        # Generate thumbnail
                        thumbnail_path = generate_thumbnail(file_path)
                        if thumbnail_path is None:
                            logger.warning(f"No thumbnail for {file_path}, uploading without")

                        # Prepare caption
                        caption = f"{torrent_title}\nDuration: {duration // 60} min {duration % 60} sec"

                        # Upload video to Telegram
                        logger.info(f"Uploading {file_path} to channel {CHANNEL_ID}")
                        with open(file_path, "rb") as video_file:
                            app.send_video(
                                chat_id=CHANNEL_ID,
                                video=video_file,
                                caption=caption[:1024],
                                duration=duration,
                                thumb=thumbnail_path if thumbnail_path else None,
                                supports_streaming=True
                            )
                        logger.info(f"Successfully uploaded {torrent_title}")

                        # Mark torrent as processed
                        save_processed_torrent(torrent_id)

                        # Clean up
                        os.remove(file_path)
                        logger.info(f"Deleted video: {file_path}")
                        if thumbnail_path and os.path.exists(thumbnail_path):
                            os.remove(thumbnail_path)
                            logger.info(f"Deleted thumbnail: {thumbnail_path}")
                        if torrent_path and os.path.exists(torrent_path):
                            os.remove(torrent_path)
                            logger.info(f"Deleted torrent file: {torrent_path}")

                    except Exception as e:
                        logger.error(f"Error processing {file_path}: {e}")

# Command to start the bot
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("RSS Video Bot started! Monitoring RSS feeds, downloading, seeding, and uploading.")
    while True:
        try:
            process_rss_feeds()
        except Exception as e:
            logger.error(f"Error in RSS processing loop: {e}")
        time.sleep(CHECK_INTERVAL)

# Main function
def main():
    logger.info("Starting bot...")
    app.run()

if __name__ == "__main__":
    main()
