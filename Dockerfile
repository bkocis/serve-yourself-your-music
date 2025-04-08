FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && \
    apt-get install -y \
    autoconf \
    automake \
    build-essential \
    cmake \
    git-core \
    libass-dev \
    libfreetype6-dev \
    libsdl2-dev \
    libtool \
    libva-dev \
    libvdpau-dev \
    libvorbis-dev \
    libxcb1-dev \
    libxcb-shm0-dev \
    libxcb-xfixes0-dev \
    pkg-config \
    texinfo \
    wget \
    zlib1g-dev && \
    apt install ffmpeg -y
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -U yt-dlp # take always the latest version of this package

COPY . .

RUN mkdir -p downloads
RUN mkdir -p templates

EXPOSE 5000

VOLUME ["/app/downloads"]

CMD ["python", "webplayer.py"]