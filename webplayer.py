import json
import mimetypes
import os
import re
import subprocess
import time

import requests
from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from flask_socketio import SocketIO
from moviepy import VideoFileClip
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    import youtube_dl
    import ytsearch  # belongs to youtube_dl package
except ImportError:
    youtube_dl = None
    ytsearch = None

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)
app.secret_key = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*")
PREFIX = os.environ.get("SCRIPT_NAME", "")

MEDIA_FOLDER = "downloads"
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".avi", ".mov", ".mkv"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

if not os.path.exists(MEDIA_FOLDER):
    os.makedirs(MEDIA_FOLDER)

if not os.path.exists("templates"):
    os.makedirs("templates")


def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|#]', "", filename)


def extract_mp3(input_file, output_file):
    """
    Extract audio from video file and save as MP3.
    Requires: moviepy and ffmpeg
    """
    if not output_file.lower().endswith(".mp3"):
        output_file += ".mp3"
    video = VideoFileClip(input_file)
    audio = video.audio
    audio.write_audiofile(output_file, codec="mp3")
    video.close()


def download_video_and_description(url, output_path=None):
    try:
        if output_path is None:
            output_path = MEDIA_FOLDER

        print(f"Starting download process for URL: {url}")
        cmd_info = ["yt-dlp", "--dump-json", url]
        result = subprocess.run(cmd_info, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"Error getting video info: {result.stderr}")
            raise Exception(f"Error getting video info: {result.stderr}")

        video_info = json.loads(result.stdout)
        title = video_info["title"]
        description = video_info["description"]
        thumbnail_url = video_info.get("thumbnail")
        safe_title = sanitize_filename(title)
        output_template = os.path.join(output_path, safe_title)

        print(f"Downloading video: {title}")
        # Command to download video and transcript
        cmd_download = [
            "yt-dlp",
            "-f",
            "best",
            "--progress",
            "--write-auto-sub",  # Download auto-generated transcript if available
            "--write-sub",  # Download manual transcript if available
            "--sub-lang",
            "en",  # Prefer English transcripts
            "--convert-subs",
            "srt",  # Convert subtitles to SRT format
            "-o",
            f"{output_template}.%(ext)s",
            url,
        ]

        process = subprocess.Popen(
            cmd_download, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                print(line.strip())  # Log all output
                # Parse progress information
                if "%" in line:
                    try:
                        progress = float(line.split("%")[0].strip().split()[-1])
                        socketio.emit("download_progress", {"progress": progress})
                    except Exception as e:
                        print(f"Error parsing progress: {str(e)}")

        if process.returncode != 0:
            error_output = process.stderr.read()
            print(f"Error downloading video: {error_output}")
            raise Exception(f"Error downloading video: {error_output}")

        print("Video download completed, processing files...")
        # Extract audio from the downloaded video
        downloaded_video = None
        for file in os.listdir(output_path):
            if file.startswith(safe_title) and any(file.endswith(ext) for ext in ALLOWED_VIDEO_EXTENSIONS):
                downloaded_video = os.path.join(output_path, file)
                print(f"Found downloaded video: {downloaded_video}")
                break

        if downloaded_video:
            try:
                print("Extracting audio to MP3...")
                audio_output = os.path.join(output_path, f"{safe_title}.mp3")
                extract_mp3(downloaded_video, audio_output)
                print(f"Audio extraction completed: {audio_output}")
            except Exception as e:
                print(f"Error extracting audio: {str(e)}")
                raise
        else:
            print("Warning: No video file found after download")

        print("Saving description...")
        description_filename = os.path.join(output_path, f"{safe_title}.txt")
        with open(description_filename, "w", encoding="utf-8") as file:
            file.write(description)
        print(f"Description saved: {description_filename}")

        if thumbnail_url:
            print(f"Downloading thumbnail from: {thumbnail_url}")
            thumbnail_filename = os.path.join(output_path, f"{safe_title}.jpg")
            try:
                response = requests.get(thumbnail_url, stream=True)
                response.raise_for_status()

                with open(thumbnail_filename, "wb") as thumb_file:
                    for chunk in response.iter_content(chunk_size=8192):
                        thumb_file.write(chunk)
                print(f"Thumbnail saved: {thumbnail_filename}")
            except Exception as e:
                print(f"Error downloading thumbnail: {str(e)}")
                raise
        else:
            print("Warning: No thumbnail URL available")

        print("Creating metadata file...")
        # Store download date in a metadata file
        metadata_filename = os.path.join(output_path, f"{safe_title}.meta")
        download_date = time.time()

        # Check if transcript was downloaded and add to metadata
        transcript_path = None
        for file in os.listdir(output_path):
            if file.startswith(safe_title) and file.endswith(".srt"):
                transcript_path = os.path.join(output_path, file)
                print(f"Found transcript: {transcript_path}")
                break

        with open(metadata_filename, "w") as meta_file:
            json.dump({
                "download_date": download_date,
                "has_transcript": transcript_path is not None
            }, meta_file)
        print(f"Metadata saved: {metadata_filename}")

        return {"success": True, "message": f"Successfully downloaded: {title}"}
    except Exception as e:
        print(f"Error in download_video_and_description: {str(e)}")
        return {"success": False, "message": f"Error: {str(e)}"}


def download_soundcloud_track(url, output_path=None):
    if youtube_dl is None:
        return {"success": False, "message": "youtube_dl is not installed"}

    if output_path is None:
        output_path = MEDIA_FOLDER

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "outtmpl": os.path.join(output_path, "%(title)s.%(ext)s"),
    }

    try:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return {"success": True, "message": f"Successfully downloaded: {info['title']}"}
    except Exception as e:
        return {"success": False, "message": f"An error occurred: {str(e)}"}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/download", methods=["GET", "POST"])
def download_page():
    if request.method == "POST":
        url = request.form.get("url")
        source = request.form.get("source")

        if not url:
            return jsonify({"success": False, "message": "No URL provided"})
        if source == "youtube":
            result = download_video_and_description(url)
        elif source == "soundcloud":
            result = download_soundcloud_track(url)
        else:
            result = {"success": False, "message": "Invalid source selected"}
        return jsonify(result)
    return render_template("download.html")


@app.route("/media")
def list_media():
    """List all media files in the media directory."""
    media_files = []
    sort_by = request.args.get("sort", "date_downloaded")  # Default sort by date downloaded
    sort_order = request.args.get("order", "desc")  # Default descending order

    for root, dirs, files in os.walk(MEDIA_FOLDER):
        for file in files:
            file_path = os.path.join(root, file)
            _, extension = os.path.splitext(file)

            if extension.lower() in ALLOWED_AUDIO_EXTENSIONS or extension.lower() in ALLOWED_VIDEO_EXTENSIONS:
                rel_path = os.path.relpath(file_path, MEDIA_FOLDER)
                filename_without_ext = os.path.splitext(file)[0]

                media_type = "audio" if extension.lower() in ALLOWED_AUDIO_EXTENSIONS else "video"

                stats = os.stat(file_path)
                size_mb = stats.st_size / (1024 * 1024)
                date_modified = stats.st_mtime  # Get modification time

                # Try to get download date from metadata file
                metadata_path = os.path.join(root, f"{filename_without_ext}.meta")
                date_downloaded = date_modified  # Default to modification date if no metadata
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, "r") as meta_file:
                            metadata = json.load(meta_file)
                            date_downloaded = metadata.get("download_date", date_modified)
                    except Exception:
                        pass

                # Look for matching thumbnail in the same directory
                thumbnail_found = False
                for img_ext in ALLOWED_IMAGE_EXTENSIONS:
                    potential_thumbnail = os.path.join(root, filename_without_ext + img_ext)
                    if os.path.exists(potential_thumbnail):
                        thumbnail_rel_path = os.path.relpath(potential_thumbnail, MEDIA_FOLDER)
                        thumbnail_found = True
                        break

                # If no matching thumbnail found, use default
                if not thumbnail_found:
                    if media_type == "audio":
                        thumbnail_rel_path = "default_audio_thumbnail.jpg"
                    else:
                        thumbnail_rel_path = "default_video_thumbnail.jpg"

                # Fix thumbnail path for display
                if not thumbnail_rel_path.startswith(PREFIX):
                    thumbnail_rel_path = thumbnail_rel_path

                media_files.append(
                    {
                        "id": rel_path,
                        "name": os.path.basename(file),
                        "path": rel_path,
                        "type": media_type,
                        "size": size_mb,  # Store as float for sorting
                        "size_display": f"{size_mb:.2f} MB",
                        "date_modified": date_modified,
                        "date_downloaded": date_downloaded,
                        "thumbnail": thumbnail_rel_path,
                    }
                )

    # Sort the media files based on the specified criteria
    reverse = sort_order == "desc"
    if sort_by == "name":
        media_files.sort(key=lambda x: x["name"].lower(), reverse=reverse)
    elif sort_by == "date":
        media_files.sort(key=lambda x: x["date_modified"], reverse=reverse)
    elif sort_by == "date_downloaded":
        media_files.sort(key=lambda x: x["date_downloaded"], reverse=reverse)
    elif sort_by == "size":
        media_files.sort(key=lambda x: x["size"], reverse=reverse)

    # Convert size back to string for display
    for file in media_files:
        file["size"] = file["size_display"]
        del file["size_display"]

    return jsonify(media_files)


@app.route("/stream/<path:filename>")
def stream_file(filename):
    """Stream a media file."""
    file_path = os.path.join(MEDIA_FOLDER, filename)

    if not os.path.exists(file_path):
        return "File not found", 404

    file_size = os.path.getsize(file_path)

    range_header = request.headers.get("Range", None)

    if range_header:
        byte_start, byte_end = 0, None
        if range_header:
            ranges = range_header.strip().replace("bytes=", "").split("-")
            if ranges[0]:
                byte_start = int(ranges[0])
            if ranges[1]:
                byte_end = int(ranges[1])

        if byte_end is None:
            byte_end = file_size - 1

        content_length = byte_end - byte_start + 1

        headers = {
            "Content-Range": f"bytes {byte_start}-{byte_end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": content_length,
            "Content-Type": mimetypes.guess_type(file_path)[0],
        }

        with open(file_path, "rb") as f:
            f.seek(byte_start)
            data = f.read(content_length)

        return Response(data, 206, headers)
    else:
        return send_from_directory(MEDIA_FOLDER, filename)


@app.route("/thumbnail/<path:filename>")
def serve_thumbnail(filename):
    """Serve thumbnail images from the media folder."""
    return send_from_directory(MEDIA_FOLDER, filename)


@app.route("/templates/<path:filename>")
def serve_static(filename):
    """Serve static files from templates directory."""
    return send_from_directory("templates", filename)


@app.route("/description/<path:filename>")
def serve_description(filename):
    """Serve description files from the media folder."""
    # Convert the media filename to the corresponding description filename
    base_name = os.path.splitext(filename)[0]
    description_path = os.path.join(MEDIA_FOLDER, f"{base_name}.txt")

    if os.path.exists(description_path):
        try:
            with open(description_path, "r", encoding="utf-8") as f:
                description = f.read()
            return jsonify({"success": True, "description": description})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})
    else:
        return jsonify({"success": False, "message": "Description file not found"})


@app.route("/delete", methods=["POST"])
def delete_files():
    """Delete selected media files and their associated files."""
    try:
        files = request.json.get("files", [])
        if not files:
            return jsonify({"success": False, "message": "No files selected"})

        deleted_files = []
        errors = []

        for file_path in files:
            try:
                # Get the base name without extension
                base_name = os.path.splitext(file_path)[0]

                # Delete the main media file
                media_path = os.path.join(MEDIA_FOLDER, file_path)
                if os.path.exists(media_path):
                    os.remove(media_path)
                    deleted_files.append(file_path)

                # Delete associated files (description, thumbnail, metadata)
                associated_files = [
                    f"{base_name}.txt",  # description
                    f"{base_name}.jpg",  # thumbnail
                    f"{base_name}.meta",  # metadata
                ]

                for assoc_file in associated_files:
                    assoc_path = os.path.join(MEDIA_FOLDER, assoc_file)
                    if os.path.exists(assoc_path):
                        os.remove(assoc_path)

            except Exception as e:
                errors.append(f"Error deleting {file_path}: {str(e)}")

        if errors:
            return jsonify(
                {
                    "success": True,
                    "message": f"Deleted {len(deleted_files)} files with {len(errors)} errors",
                    "deleted_files": deleted_files,
                    "errors": errors,
                }
            )
        else:
            return jsonify(
                {
                    "success": True,
                    "message": f"Successfully deleted {len(deleted_files)} files",
                    "deleted_files": deleted_files,
                }
            )

    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"})


# Create default thumbnails
def create_default_thumbnails():
    """Create default thumbnail images if they don't exist."""
    try:
        from PIL import Image

        default_audio_path = os.path.join(MEDIA_FOLDER, "default_audio_thumbnail.jpg")
        default_video_path = os.path.join(MEDIA_FOLDER, "default_video_thumbnail.jpg")

        if not os.path.exists(default_audio_path):
            img = Image.new("RGB", (200, 200), color=(73, 109, 137))
            img.save(default_audio_path)

        if not os.path.exists(default_video_path):
            img = Image.new("RGB", (200, 200), color=(120, 80, 100))
            img.save(default_video_path)
    except ImportError:
        print("PIL not installed. Default thumbnails will not be created.")
        print("Please install Pillow with: pip install Pillow")
        return


@app.route("/search", methods=["POST"])
def search_youtube():
    """Search YouTube for videos."""
    if ytsearch is None:
        return jsonify({"success": False, "message": "youtube_dl is not installed"})

    query = request.form.get("query")
    max_results = 50  # int(request.form.get('max_results', 50))

    if not query:
        return jsonify({"success": False, "message": "No search query provided"})

    try:
        yts = ytsearch.YTSearch()
        search_results = yts.search_by_term(term=query, max_results=max_results)

        # Format results for frontend
        formatted_results = []
        for result in search_results:
            video_id = result.get("id")
            # Try hq720 first, fall back to hqdefault if not available
            thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hq720.jpg" if video_id else None
            if thumbnail_url:
                try:
                    response = requests.head(thumbnail_url)
                    if response.status_code != 200:
                        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                except Exception:
                    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

            formatted_results.append(
                {
                    "id": video_id,
                    "title": result.get("title"),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnail": thumbnail_url,
                    "duration": result.get("duration", ""),
                    "views": result.get("views", ""),
                }
            )

        return jsonify({"success": True, "results": formatted_results})
    except Exception as e:
        print(f"Search error: {str(e)}")  # Add debug logging
        return jsonify({"success": False, "message": f"Error searching YouTube: {str(e)}"})


if __name__ == "__main__":
    create_default_thumbnails()
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
