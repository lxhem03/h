FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libtorrent-rasterbar-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY bot.py .

# Ensure directories exist
RUN mkdir -p /app/downloads /app/torrents /app/thumbnails

# Run the bot
CMD gunicorn app:app && python bot.py
