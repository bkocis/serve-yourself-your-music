import os
import tempfile
import unittest

from webplayer import check_disk_space, download_video_and_description, sanitize_filename, validate_and_create_directory


class TestWebPlayer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_video_path = os.path.join(self.temp_dir, "test_video.mp4")
        self.test_audio_path = os.path.join(self.temp_dir, "test_audio.mp3")

        with open(self.test_video_path, "wb") as f:
            f.write(b"dummy video content")

    def tearDown(self):
        import shutil

        if os.path.exists(self.test_video_path):
            os.remove(self.test_video_path)
        if os.path.exists(self.test_audio_path):
            os.remove(self.test_audio_path)
        # Use shutil.rmtree to remove directory and all contents
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

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

    def test_sanitize_filename_length_limit(self):
        """Test filename sanitization with length limits"""
        long_name = "a" * 300  # Very long filename
        result = sanitize_filename(long_name, max_length=200)
        self.assertLessEqual(len(result), 200)
        self.assertEqual(result, "a" * 200)

    def test_sanitize_filename_with_extension(self):
        """Test filename sanitization preserving extension"""
        long_name = "a" * 300 + ".mp4"
        result = sanitize_filename(long_name, max_length=200)
        self.assertLessEqual(len(result), 200)
        self.assertTrue(result.endswith(".mp4"))

    def test_validate_and_create_directory_success(self):
        """Test directory validation and creation"""
        test_dir = os.path.join(self.temp_dir, "test_subdir")
        success, error_msg = validate_and_create_directory(test_dir)
        self.assertTrue(success)
        self.assertIsNone(error_msg)
        self.assertTrue(os.path.exists(test_dir))

    def test_check_disk_space(self):
        """Test disk space checking"""
        # Test with very small requirement (should pass)
        result = check_disk_space(self.temp_dir, required_bytes=1)
        self.assertTrue(result)

        # Test with extremely large requirement (should fail)
        result = check_disk_space(self.temp_dir, required_bytes=999999999999999)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
