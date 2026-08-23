"""
Tests for Media Intelligence (Rule #53).
Validates format detection, metadata extraction, transcript parsing, and processing.
"""

import unittest
import os
import struct
import tempfile
import shutil
from intelligence.media.media_parser import MediaProcessor, MediaInfo, MediaType


class TestMediaProcessor(unittest.TestCase):

    def setUp(self):
        self.processor = MediaProcessor()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_minimal_mp4(self, filename="test.mp4"):
        """Create a minimal MP4 file with ftyp box for format detection."""
        path = os.path.join(self.temp_dir, filename)
        with open(path, "wb") as f:
            # ftyp box (file type box) - required for MP4 detection
            ftyp_data = b"isom" + b"\x00\x00\x00\x01" + b"isomiso2mp41"
            ftyp_size = 8 + len(ftyp_data)
            f.write(struct.pack(">I", ftyp_size))
            f.write(b"ftyp")
            f.write(ftyp_data)
            # moov box with mvhd
            mvhd_data = bytearray(100)
            mvhd_data[0] = 0  # version
            struct.pack_into(">I", mvhd_data, 4, 1000)  # timescale
            struct.pack_into(">I", mvhd_data, 8, 30000)  # duration -> 30 seconds
            moov_size = 8 + len(mvhd_data)
            f.write(struct.pack(">I", moov_size))
            f.write(b"moov")
            f.write(b"mvhd")
            f.write(bytes(mvhd_data))
        return path

    def _create_minimal_png(self, filename="test.png"):
        """Create a minimal PNG file."""
        path = os.path.join(self.temp_dir, filename)
        with open(path, "wb") as f:
            # PNG signature
            f.write(b'\x89PNG\r\n\x1a\n')
            # IHDR chunk
            ihdr_data = struct.pack(">II", 100, 50) + b'\x08\x02\x00\x00\x00'
            ihdr_crc = b'\x00\x00\x00\x00'
            f.write(struct.pack(">I", len(ihdr_data)))
            f.write(b"IHDR")
            f.write(ihdr_data)
            f.write(ihdr_crc)
        return path

    def _create_minimal_jpeg(self, filename="test.jpg"):
        """Create a minimal JPEG file with SOF0 marker."""
        path = os.path.join(self.temp_dir, filename)
        with open(path, "wb") as f:
            f.write(b'\xff\xd8')  # SOI
            # APP0 marker
            f.write(b'\xff\xe0')
            f.write(struct.pack(">H", 16))
            f.write(b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00')
            # SOF0 marker (Start of Frame)
            f.write(b'\xff\xc0')
            sof_data = struct.pack(">B", 8)  # precision
            sof_data += struct.pack(">HH", 200, 300)  # height, width
            sof_data += b'\x01\x00\x00'  # components
            f.write(struct.pack(">H", len(sof_data) + 2))
            f.write(sof_data)
        return path

    def test_process_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.processor.process_file("/nonexistent/file.mp4")

    def test_process_mp4(self):
        path = self._create_minimal_mp4()
        result = self.processor.process_file(path)
        self.assertEqual(result["filename"], "test.mp4")
        self.assertEqual(result["media_type"], "video")
        self.assertEqual(result["format"], "mp4")
        self.assertGreater(result["file_size"], 0)
        self.assertIn("content_hash", result)

    def test_process_png(self):
        path = self._create_minimal_png()
        result = self.processor.process_file(path)
        self.assertEqual(result["filename"], "test.png")
        self.assertEqual(result["media_type"], "image")
        self.assertEqual(result["format"], "png")
        self.assertEqual(result["width"], 100)
        self.assertEqual(result["height"], 50)

    def test_process_jpeg(self):
        path = self._create_minimal_jpeg()
        result = self.processor.process_file(path)
        self.assertEqual(result["filename"], "test.jpg")
        self.assertEqual(result["media_type"], "image")
        self.assertEqual(result["width"], 300)
        self.assertEqual(result["height"], 200)

    def test_compute_hash(self):
        path = self._create_minimal_mp4()
        h = self.processor._compute_hash(path)
        self.assertEqual(len(h), 16)
        # Same file should produce same hash
        h2 = self.processor._compute_hash(path)
        self.assertEqual(h, h2)

    def test_parse_transcript_vtt(self):
        vtt = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello world

00:00:05.000 --> 00:00:08.000
This is a test
"""
        result = self.processor.parse_transcript(vtt, filename="test.vtt")
        self.assertEqual(result["segment_count"], 2)
        self.assertEqual(result["segments"][0]["text"], "Hello world")
        self.assertIn("00:00:01", result["segments"][0]["start"])

    def test_parse_transcript_plain_text(self):
        text = "This is a simple transcript without timestamps. It has multiple sentences. And more content."
        result = self.processor.parse_transcript(text)
        self.assertGreaterEqual(result["segment_count"], 1)
        self.assertGreater(result["total_words"], 0)

    def test_parse_transcript_empty(self):
        result = self.processor.parse_transcript("")
        self.assertEqual(result["segment_count"], 0)

    def test_extract_key_segments(self):
        transcript = {
            "segments": [
                {"start": "00:00", "end": "00:30", "text": "Short."},
                {"start": "00:30", "end": "01:00", "text": "This is a much longer segment with more detailed content about the topic."},
                {"start": "01:00", "end": "01:30", "text": "Another brief one."},
            ]
        }
        key = self.processor.extract_key_segments(transcript, top_k=1)
        self.assertEqual(len(key), 1)
        self.assertGreater(len(key[0]["text"]), len("Short."))

    def test_generate_summary(self):
        transcript = {
            "segments": [
                {"start": "00:00", "text": "Machine learning is transforming data analysis."},
                {"start": "00:30", "text": "Deep learning models can process complex patterns."},
                {"start": "01:00", "text": "Data science combines statistics with computing."},
            ]
        }
        summary = self.processor.generate_summary(transcript)
        self.assertEqual(summary["total_segments"], 3)
        self.assertGreater(summary["total_words"], 0)
        self.assertIn("top_keywords", summary)

    def test_media_info(self):
        info = MediaInfo(
            filename="test.mp4",
            media_type=MediaType.VIDEO,
            format="mp4",
            duration_seconds=125.5,
            file_size=1024000,
        )
        self.assertEqual(info.duration_formatted, "00:02:05")
        d = info.to_dict()
        self.assertEqual(d["file_size_mb"], 0.98)
        self.assertEqual(d["duration_formatted"], "00:02:05")

    def test_format_detection_by_extension(self):
        # Test fallback to extension-based detection for WAV
        path = os.path.join(self.temp_dir, "test.wav")
        with open(path, "wb") as f:
            # Write RIFF header with WAVE format identifier
            f.write(b"RIFF")
            f.write(b"\x00" * 4)  # file size placeholder
            f.write(b"WAVE")
            f.write(b"\x00" * 12)
        result = self.processor.process_file(path)
        self.assertEqual(result["media_type"], "audio")

    def test_media_type_values(self):
        self.assertEqual(MediaType.AUDIO, "audio")
        self.assertEqual(MediaType.VIDEO, "video")
        self.assertEqual(MediaType.IMAGE, "image")
        self.assertEqual(MediaType.UNKNOWN, "unknown")


if __name__ == "__main__":
    unittest.main()
