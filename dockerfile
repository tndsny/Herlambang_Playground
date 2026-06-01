FROM node:20-slim

# Install Python3, FFmpeg, wget, dan tools tambahan
RUN apt-get update && apt-get install -y \
    python3 \
    ffmpeg \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Ambil binary yt-dlp terbaru
RUN wget https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -O /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /usr/src/app

COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 3000

CMD [ "node", "server.js" ]