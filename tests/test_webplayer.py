import os
import tempfile
import unittest

from webplayer import download_video_and_description, sanitize_filename


class TestWebPlayer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_video_path = os.path.join(self.temp_dir, "test_video.mp4")
        self.test_audio_path = os.path.join(self.temp_dir, "test_audio.mp3")

        with open(self.test_video_path, "wb") as f:
            f.write(b"dummy video content")

    def tearDown(self):
        if os.path.exists(self.test_video_path):
            os.remove(self.test_video_path)
        if os.path.exists(self.test_audio_path):
            os.remove(self.test_audio_path)
        os.rmdir(self.temp_dir)

    def test_sanitize_filename(self):
        """Test the filename sanitization function"""
        test_cases = [
            ("file/with/slashes.txt", "filewithslashes.txt"),
            ("file*with*asterisks.txt", "filewithasterisks.txt"),
            ("file?with?question.txt", "filewithquestion.txt"),
            ("file:with:colons.txt", "filewithcolons.txt"),
            ('file"with"quotes.txt', "filewithquotes.txt"),
            ("file<with>brackets.txt", "filewithbrackets.txt"),
            ("file|with|pipe.txt", "filewithpipe.txt"),
            ("file#with#hash.txt", "filewithhash.txt"),
        ]

        for input_name, expected in test_cases:
            with self.subTest(input_name=input_name):
                result = sanitize_filename(input_name)
                self.assertEqual(result, expected)

    def test_download_video_and_description_invalid_url(self):
        """Test video download with an invalid URL"""
        result = download_video_and_description("invalid_url")
        self.assertFalse(result["success"])
        self.assertIn("Error", result["message"])

    def test_download_video_and_description_no_url(self):
        """Test video download with no URL"""
        result = download_video_and_description("")
        self.assertFalse(result["success"])
        self.assertIn("Error", result["message"])


if __name__ == "__main__":
    unittest.main()
