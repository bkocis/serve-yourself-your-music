import json
import mimetypes
import os
import re
import shutil
import subprocess
import time

import requests
from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory
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


def sanitize_filename(filename, max_length=200):
    """
    Sanitize filename by removing invalid characters and limiting length.

    Args:
        filename (str): Original filename
        max_length (int): Maximum filename length (default: 200)

    Returns:
        str: Sanitized filename
    """
    # Remove invalid characters
    sanitized = re.sub(r'[\\/*?:"<>|#]', "", filename)

    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(" .")

    # Limit length while preserving file extension if present
    if len(sanitized) > max_length:
        # Try to preserve file extension
        name_parts = sanitized.rsplit(".", 1)
        if len(name_parts) == 2 and len(name_parts[1]) <= 10:  # Reasonable extension length
            extension = "." + name_parts[1]
            base_name = name_parts[0]
            max_base_length = max_length - len(extension)
            if max_base_length > 0:
                sanitized = base_name[:max_base_length] + extension
            else:
                sanitized = base_name[:max_length]
        else:
            sanitized = sanitized[:max_length]

    # Ensure we don't return an empty string
    if not sanitized:
        sanitized = "untitled"

    return sanitized


def normalize_username(username):
    """
    Normalize username to lowercase for consistent directory naming
    while preserving original case for display purposes.
    """
    if not username:
        return None
    # Strip whitespace and convert to lowercase for directory naming
    normalized = username.strip().lower()
    # Apply filename sanitization
    return sanitize_filename(normalized)


def check_disk_space(path, required_bytes=1024 * 1024 * 100):  # Default 100MB
    """
    Check if there's enough disk space available.

    Args:
        path (str): Path to check disk space for
        required_bytes (int): Required bytes (default: 100MB)

    Returns:
        bool: True if enough space available, False otherwise
    """
    try:
        stat = shutil.disk_usage(path)
        return stat.free >= required_bytes
    except Exception as e:
        print(f"Warning: Could not check disk space: {e}")
        return True  # Assume enough space if we can't check


def validate_and_create_directory(directory_path):
    """
    Validate and create directory if it doesn't exist.

    Args:
        directory_path (str): Path to validate/create

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(directory_path, exist_ok=True)

        # Check if directory is writable
        if not os.access(directory_path, os.W_OK):
            return False, f"Directory {directory_path} is not writable"

        return True, None
    except PermissionError:
        return False, f"Permission denied creating directory: {directory_path}"
    except OSError as e:
        return False, f"Error creating directory {directory_path}: {str(e)}"


def safe_subprocess_run(cmd, **kwargs):
    """
    Run subprocess with better error handling.

    Args:
        cmd (list): Command to run
        **kwargs: Additional arguments for subprocess.run

    Returns:
        subprocess.CompletedProcess: Result of the command
    """
    try:
        # Extract cwd for error message context
        cwd = kwargs.get("cwd", os.getcwd())
        return subprocess.run(cmd, **kwargs)
    except FileNotFoundError:
        raise Exception(f"Command not found: {cmd[0]}. Please ensure it's installed and in PATH.")
    except Exception as e:
        raise Exception(f"Error running command {' '.join(cmd)} in directory {cwd}: {str(e)}")


def extract_mp3(input_file, output_file):
    """
    Extract audio from video file and save as MP3.
    Uses ffmpeg directly for better reliability.
    Falls back to moviepy if ffmpeg direct call fails.
    """
    if not output_file.lower().endswith(".mp3"):
        output_file += ".mp3"

    # Try ffmpeg directly first (more reliable)
    try:
        print(f"Attempting audio extraction with ffmpeg: {input_file} -> {output_file}")
        cmd = [
            "ffmpeg",
            "-i",
            input_file,
            "-vn",  # No video
            "-acodec",
            "libmp3lame",  # MP3 codec
            "-ab",
            "192k",  # 192kbps bitrate
            "-ar",
            "44100",  # 44.1kHz sample rate
            "-y",  # Overwrite output file
            output_file,
        ]

        result = safe_subprocess_run(cmd, capture_output=True, text=True, timeout=300)  # 5 min timeout

        if result.returncode != 0:
            error_msg = result.stderr or "Unknown ffmpeg error"
            print(f"ffmpeg failed: {error_msg}")
            raise Exception(f"ffmpeg extraction failed: {error_msg}")

        print(f"ffmpeg audio extraction successful: {output_file}")
        return

    except Exception as e:
        print(f"ffmpeg extraction failed: {str(e)}, trying moviepy fallback...")

        # Fallback to moviepy
        try:
            video = VideoFileClip(input_file)
            if video.audio is None:
                video.close()
                raise Exception("No audio track found in video file")

            audio = video.audio
            audio.write_audiofile(output_file, codec="mp3", bitrate="192k", verbose=False, logger=None)
            video.close()
            print(f"MoviePy audio extraction successful: {output_file}")

        except Exception as moviepy_error:
            print(f"MoviePy extraction also failed: {str(moviepy_error)}")
            raise Exception(
                f"Both ffmpeg and moviepy audio extraction failed. ffmpeg: {str(e)}, moviepy: {str(moviepy_error)}"
            )


def download_video_and_description(url, output_path=None):
    try:
        if output_path is None:
            output_path = MEDIA_FOLDER

        print(f"Starting download process for URL: {url}")

        # Validate and create output directory
        success, error_msg = validate_and_create_directory(output_path)
        if not success:
            raise Exception(f"Directory validation failed: {error_msg}")

        # Check disk space (require at least 100MB free)
        if not check_disk_space(output_path):
            raise Exception("Insufficient disk space. At least 100MB free space required.")

        print(f"Directory validated: {output_path}")

        # Get video information
        cmd_info = ["yt-dlp", "--dump-json", url]
        result = safe_subprocess_run(cmd_info, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            error_msg = result.stderr or "Unknown error getting video info"
            print(f"Error getting video info: {error_msg}")
            raise Exception(f"Error getting video info: {error_msg}")

        try:
            video_info = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON response from yt-dlp: {e}")

        title = video_info.get("title", "untitled")
        description = video_info.get("description", "")
        thumbnail_url = video_info.get("thumbnail")

        # Sanitize filename with length limits
        safe_title = sanitize_filename(title)

        print(f"Sanitized title: '{title}' -> '{safe_title}'")

        print(f"Downloading video: {title}")

        # Enhanced command to download video and transcript with better error handling
        cmd_download = [
            "yt-dlp",
            "--progress",
            "--no-warnings",  # Reduce noise in logs
            "--write-auto-sub",  # Download auto-generated transcript if available
            "--write-sub",  # Download manual transcript if available
            "--sub-lang",
            "en",  # Prefer English transcripts
            "--convert-subs",
            "srt",  # Convert subtitles to SRT format
            "--no-overwrites",  # Don't overwrite existing files
            "--continue",  # Resume interrupted downloads
            "--retries",
            "3",  # Retry failed downloads
            "--fragment-retries",
            "3",  # Retry failed fragments
            "--format",
            "best[height<=720]/best",  # Prefer 720p or lower to avoid timeouts
            "-o",
            f"{safe_title}.%(ext)s",  # Use relative filename since we set working directory
            url,
        ]

        print(f"Executing download command in directory '{output_path}': {' '.join(cmd_download)}")

        try:
            process = subprocess.Popen(
                cmd_download,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                cwd=output_path,  # Set working directory to output path
            )

            stderr_output = []
            download_timeout = 1800  # 30 minutes timeout for downloads
            start_time = time.time()

            while True:
                # Check for timeout
                if time.time() - start_time > download_timeout:
                    process.kill()
                    process.wait()
                    raise Exception(f"Download timeout - process exceeded {download_timeout} seconds")

                line = process.stdout.readline()
                stderr_line = process.stderr.readline()

                if not line and not stderr_line and process.poll() is not None:
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

                if stderr_line:
                    stderr_output.append(stderr_line.strip())
                    print(f"yt-dlp stderr: {stderr_line.strip()}")

                    # Check for specific error patterns that indicate failure
                    if any(
                        error_pattern in stderr_line.lower()
                        for error_pattern in [
                            "error:",
                            "unable to download",
                            "http error",
                            "network error",
                            "video unavailable",
                            "private video",
                            "age-restricted",
                        ]
                    ):
                        print(f"Detected critical error in stderr: {stderr_line.strip()}")

            # Read any remaining stderr output
            remaining_stderr = process.stderr.read()
            if remaining_stderr:
                stderr_output.append(remaining_stderr.strip())
                print(f"Remaining stderr: {remaining_stderr.strip()}")

            # Wait for process to complete and get final return code
            process.wait()

            if process.returncode != 0:
                error_output = "\n".join(stderr_output) if stderr_output else "Unknown download error"
                print(f"Error downloading video (exit code {process.returncode}): {error_output}")

                # Try audio-only download as fallback
                print("Video download failed, attempting audio-only download as fallback...")
                try:
                    cmd_audio_only = [
                        "yt-dlp",
                        "--progress",
                        "--no-warnings",
                        "--format",
                        "bestaudio/best",
                        "--extract-audio",
                        "--audio-format",
                        "mp3",
                        "--audio-quality",
                        "192K",
                        "--retries",
                        "3",
                        "--fragment-retries",
                        "3",
                        "-o",
                        f"{safe_title}.%(ext)s",  # Use relative filename since we set working directory
                        url,
                    ]

                    print(f"Executing audio-only download in directory '{output_path}': {' '.join(cmd_audio_only)}")
                    audio_result = safe_subprocess_run(
                        cmd_audio_only, capture_output=True, text=True, timeout=600, cwd=output_path
                    )

                    if audio_result.returncode == 0:
                        print("Audio-only download successful!")
                        # Skip video processing since we only have audio
                        downloaded_video = None
                    else:
                        audio_error = audio_result.stderr or "Unknown audio download error"
                        print(f"Audio-only download also failed: {audio_error}")
                        raise Exception(
                            f"Both video and audio-only downloads failed. Video error: "
                            f"{error_output}. Audio error: {audio_error}"
                        )

                except Exception as audio_e:
                    print(f"Audio-only fallback failed: {str(audio_e)}")
                    raise Exception(f"Error downloading video (exit code {process.returncode}): {error_output}")

        except subprocess.TimeoutExpired:
            if "process" in locals():
                process.kill()
                process.wait()
            raise Exception("Download timeout - process took too long")
        except Exception as e:
            if "process" in locals():
                try:
                    process.kill()
                    process.wait()
                except Exception:
                    pass
            raise Exception(f"Download process error: {str(e)}")

        print("Video download completed, processing files...")

        # Verify download completed by checking for files
        try:
            downloaded_files = os.listdir(output_path)
            matching_files = [f for f in downloaded_files if f.startswith(safe_title)]

            if not matching_files:
                raise Exception(f"No files found with expected prefix '{safe_title}' in {output_path}")

            print(f"Found {len(matching_files)} files with matching prefix")

        except OSError as e:
            raise Exception(f"Error accessing output directory: {e}")

        # Extract audio from the downloaded video
        downloaded_video = None
        for file in downloaded_files:
            if file.startswith(safe_title) and any(file.endswith(ext) for ext in ALLOWED_VIDEO_EXTENSIONS):
                downloaded_video = os.path.join(output_path, file)
                print(f"Found downloaded video: {downloaded_video}")
                break

        if downloaded_video and os.path.exists(downloaded_video):
            try:
                print(f"Extracting audio to MP3 from video file: {downloaded_video}")
                audio_output = os.path.join(output_path, f"{safe_title}.mp3")

                # Check if MP3 already exists
                if os.path.exists(audio_output):
                    print(f"MP3 file already exists: {audio_output}")
                else:
                    # Verify the video file is readable and has audio
                    video_size = os.path.getsize(downloaded_video)
                    print(f"Video file size: {video_size / (1024 * 1024):.2f} MB")

                    if video_size < 1024:  # Less than 1KB, probably corrupt
                        raise Exception(f"Video file appears to be corrupt (size: {video_size} bytes)")

                    extract_mp3(downloaded_video, audio_output)

                    # Verify MP3 was created successfully
                    if os.path.exists(audio_output):
                        mp3_size = os.path.getsize(audio_output)
                        print(f"Audio extraction completed: {audio_output} (size: {mp3_size / (1024 * 1024):.2f} MB)")

                        if mp3_size < 1024:  # Less than 1KB, probably failed
                            os.remove(audio_output)  # Remove corrupt file
                            raise Exception("Audio extraction produced corrupt file (too small)")
                    else:
                        raise Exception("Audio extraction completed but no MP3 file was created")

            except Exception as e:
                print(f"Error extracting audio: {str(e)}")
                # Don't raise here - video download was successful even if audio extraction fails
                print("Continuing without audio extraction...")
                print("Note: Video file is still available for manual audio extraction if needed")
        else:
            print(
                f"Warning: No video file found after download. Expected file: "
                f"{downloaded_video if downloaded_video else 'None'}"
            )
            # List all files in the directory for debugging
            try:
                all_files = os.listdir(output_path)
                print(f"Files found in output directory: {all_files}")
                video_files = [f for f in all_files if any(f.endswith(ext) for ext in ALLOWED_VIDEO_EXTENSIONS)]
                print(f"Video files found: {video_files}")
            except Exception as e:
                print(f"Error listing directory contents: {e}")

        print("Saving description...")
        try:
            description_filename = os.path.join(output_path, f"{safe_title}.txt")
            with open(description_filename, "w", encoding="utf-8") as file:
                file.write(description)
            print(f"Description saved: {description_filename}")
        except Exception as e:
            print(f"Warning: Could not save description: {e}")
            # Continue - description save failure shouldn't stop the whole process

        # Download thumbnail (non-critical, continue if it fails)
        if thumbnail_url:
            print(f"Downloading thumbnail from: {thumbnail_url}")
            thumbnail_filename = os.path.join(output_path, f"{safe_title}.jpg")
            try:
                response = requests.get(thumbnail_url, stream=True, timeout=10)
                response.raise_for_status()

                with open(thumbnail_filename, "wb") as thumb_file:
                    for chunk in response.iter_content(chunk_size=8192):
                        thumb_file.write(chunk)
                print(f"Thumbnail saved: {thumbnail_filename}")
            except Exception as e:
                print(f"Warning: Error downloading thumbnail: {str(e)}")
                # Continue - thumbnail download failure shouldn't stop the whole process
        else:
            print("Warning: No thumbnail URL available")

        print("Creating metadata file...")
        try:
            # Store download date in a metadata file
            metadata_filename = os.path.join(output_path, f"{safe_title}.meta")
            download_date = time.time()

            # Check if transcript was downloaded and add to metadata
            transcript_path = None
            try:
                current_files = os.listdir(output_path)
                for file in current_files:
                    if file.startswith(safe_title) and file.endswith(".srt"):
                        transcript_path = os.path.join(output_path, file)
                        print(f"Found transcript: {transcript_path}")
                        break
            except Exception as e:
                print(f"Warning: Error checking for transcript files: {e}")

            metadata = {
                "download_date": download_date,
                "has_transcript": transcript_path is not None,
                "original_title": title,
                "sanitized_title": safe_title,
                "source_url": url,
            }

            with open(metadata_filename, "w", encoding="utf-8") as meta_file:
                json.dump(metadata, meta_file, indent=2)
            print(f"Metadata saved: {metadata_filename}")

        except Exception as e:
            print(f"Warning: Could not save metadata: {e}")
            # Continue - metadata save failure shouldn't stop the whole process

        print(f"Download process completed successfully for: {title}")
        return {"success": True, "message": f"Successfully downloaded: {title}"}

    except Exception as e:
        error_msg = str(e)
        print(f"Error in download_video_and_description: {error_msg}")

        # Provide more specific error guidance
        if "disk space" in error_msg.lower():
            error_msg += " Please free up some disk space and try again."
        elif "permission" in error_msg.lower():
            error_msg += " Please check file permissions for the download directory."
        elif "directory" in error_msg.lower():
            error_msg += " Please ensure the download directory is accessible."
        elif "command not found" in error_msg.lower():
            error_msg += " Please ensure yt-dlp is installed and accessible."

        return {"success": False, "message": f"Download failed: {error_msg}"}


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


@app.route("/dmca_policy")
def dmca_policy():
    return render_template("dmca_policy.html")


@app.route("/download", methods=["GET", "POST"])
def download_page():
    if request.method == "POST":
        url = request.form.get("url")
        source = request.form.get("source")
        user = request.form.get("user")
        legal_acknowledgment = request.form.get("legal_acknowledgment")

        if not url:
            return jsonify({"success": False, "message": "No URL provided"})
        if not user:
            return jsonify({"success": False, "message": "No user provided"})
        if not legal_acknowledgment:
            return jsonify({"success": False, "message": "Must acknowledge legal terms before downloading"})

        user = normalize_username(user)
        if not user:
            return jsonify({"success": False, "message": "Invalid username"})
        user_dir = os.path.join(MEDIA_FOLDER, user)

        # Use improved directory validation
        success, error_msg = validate_and_create_directory(user_dir)
        if not success:
            return jsonify({"success": False, "message": f"Directory error: {error_msg}"})
        if source == "youtube":
            result = download_video_and_description(url, output_path=user_dir)
        elif source == "soundcloud":
            result = download_soundcloud_track(url, output_path=user_dir)
        else:
            result = {"success": False, "message": "Invalid source selected"}
        return jsonify(result)
    return render_template("download.html")


@app.route("/media")
def list_media():
    """List all media files in the user's media directory."""
    user, user_dir = get_user_from_request()
    media_files = []
    sort_by = request.args.get("sort", "date_downloaded")  # Default sort by date downloaded
    sort_order = request.args.get("order", "desc")  # Default descending order

    for root, dirs, files in os.walk(user_dir):
        for file in files:
            file_path = os.path.join(root, file)
            _, extension = os.path.splitext(file)

            if extension.lower() in ALLOWED_AUDIO_EXTENSIONS or extension.lower() in ALLOWED_VIDEO_EXTENSIONS:
                rel_path = os.path.relpath(file_path, user_dir)
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
                        thumbnail_rel_path = os.path.relpath(potential_thumbnail, user_dir)
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
    user, user_dir = get_user_from_request()
    file_path = os.path.join(user_dir, filename)

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
        return send_from_directory(user_dir, filename)


@app.route("/thumbnail/<path:filename>")
def serve_thumbnail(filename):
    """Serve thumbnail images from the user's media folder or default thumbnails."""
    user, user_dir = get_user_from_request()

    # Check if file exists in user directory first
    user_file_path = os.path.join(user_dir, filename)
    if os.path.exists(user_file_path):
        return send_from_directory(user_dir, filename)

    # If not found in user directory, check for default thumbnails in main downloads folder
    if filename in ["default_audio_thumbnail.jpg", "default_video_thumbnail.jpg"]:
        default_file_path = os.path.join(MEDIA_FOLDER, filename)
        if os.path.exists(default_file_path):
            return send_from_directory(MEDIA_FOLDER, filename)

    # If file not found anywhere, return 404
    abort(404)


@app.route("/templates/<path:filename>")
def serve_static(filename):
    """Serve static files from templates directory."""
    return send_from_directory("templates", filename)


@app.route("/description/<path:filename>")
def serve_description(filename):
    """Serve description files from the user's media folder."""
    user, user_dir = get_user_from_request()
    base_name = os.path.splitext(filename)[0]
    description_path = os.path.join(user_dir, f"{base_name}.txt")

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
        data = request.get_json(force=True)
        files = data.get("files", [])
        user = data.get("user")
        if not files:
            return jsonify({"success": False, "message": "No files selected"})
        if not user:
            return jsonify({"success": False, "message": "No user provided"})
        user = normalize_username(user)
        if not user:
            return jsonify({"success": False, "message": "Invalid username"})
        user_dir = os.path.join(MEDIA_FOLDER, user)
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
        deleted_files = []
        errors = []
        for file_path in files:
            try:
                base_name = os.path.splitext(file_path)[0]
                media_path = os.path.join(user_dir, file_path)
                if os.path.exists(media_path):
                    os.remove(media_path)
                    deleted_files.append(file_path)
                associated_files = [
                    f"{base_name}.txt",
                    f"{base_name}.jpg",
                    f"{base_name}.meta",
                ]
                for assoc_file in associated_files:
                    assoc_path = os.path.join(user_dir, assoc_file)
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


# Helper to get user directory
def get_user_from_request():
    user = (
        request.args.get("user") or request.form.get("user") or (request.json.get("user") if request.is_json else None)
    )
    if not user:
        abort(400, description="User not specified")
    user = normalize_username(user)
    if not user:
        abort(400, description="Invalid user")
    user_dir = os.path.join(MEDIA_FOLDER, user)
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user, user_dir


if __name__ == "__main__":
    create_default_thumbnails()
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
