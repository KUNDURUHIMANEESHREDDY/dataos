"""
Enhanced Media Intelligence Parser for DataOS (Rule #53).
Extracts metadata, segments, transcripts, and provenance from audio/video binary files.
Supports format detection, duration extraction, and timestamp-level tracking.
"""

from __future__ import annotations
import os
import hashlib
import struct
import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import timedelta


class MediaType(str):
    AUDIO = "audio"
    VIDEO = "video"
    IMAGE = "image"
    UNKNOWN = "unknown"


class MediaInfo:
    """Container for extracted media metadata."""

    def __init__(
        self,
        filename: str,
        media_type: str = MediaType.UNKNOWN,
        format: str = "",
        duration_seconds: float = 0.0,
        file_size: int = 0,
        content_hash: str = "",
        codec: str = "",
        bitrate: int = 0,
        sample_rate: int = 0,
        channels: int = 0,
        width: int = 0,
        height: int = 0,
        fps: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.filename = filename
        self.media_type = media_type
        self.format = format
        self.duration_seconds = duration_seconds
        self.file_size = file_size
        self.content_hash = content_hash
        self.codec = codec
        self.bitrate = bitrate
        self.sample_rate = sample_rate
        self.channels = channels
        self.width = width
        self.height = height
        self.fps = fps
        self.metadata = metadata or {}

    @property
    def duration_formatted(self) -> str:
        """Format duration as HH:MM:SS."""
        td = timedelta(seconds=self.duration_seconds)
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation of the media info."""
        return {
            "filename": self.filename,
            "media_type": self.media_type,
            "format": self.format,
            "duration_seconds": round(self.duration_seconds, 2),
            "duration_formatted": self.duration_formatted,
            "file_size": self.file_size,
            "file_size_mb": round(self.file_size / (1024 * 1024), 2),
            "content_hash": self.content_hash,
            "codec": self.codec,
            "bitrate": self.bitrate,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "metadata": self.metadata,
        }


class MediaProcessor:
    """
    Processes audio/video/image binary files:
    - Format detection via magic bytes
    - File size and hash computation
    - Duration extraction (MP4/MOV/AVI via box parsing)
    - Metadata extraction
    - Transcript parsing (VTT/SRT format)
    """

    # Magic byte signatures for format detection
    MAGIC_BYTES = {
        b'\x00\x00\x00\x1c\x66\x74\x79\x70': ("mp4", MediaType.VIDEO),
        b'\x00\x00\x00\x20\x66\x74\x79\x70': ("mp4", MediaType.VIDEO),
        b'\x00\x00\x00\x18\x66\x74\x79\x70': ("mp4", MediaType.VIDEO),
        b'\x66\x74\x79\x70': ("mp4/mov", MediaType.VIDEO),
        b'\x52\x49\x46\x46': ("wav/avi", MediaType.UNKNOWN),  # RIFF - need further detection
        b'\x1a\x45\xdf\xa3': ("mkv/webm", MediaType.VIDEO),
        b'\x4f\x67\x67\x53': ("ogg", MediaType.AUDIO),
        b'\x49\x44\x33': ("mp3", MediaType.AUDIO),
        b'\xff\xfb': ("mp3", MediaType.AUDIO),
        b'\xff\xf3': ("mp3", MediaType.AUDIO),
        b'\xff\xf2': ("mp3", MediaType.AUDIO),
        b'\x66\x4c\x61\x43': ("flac", MediaType.AUDIO),
        b'\x89\x50\x4e\x47': ("png", MediaType.IMAGE),
        b'\xff\xd8\xff': ("jpeg", MediaType.IMAGE),
        b'\x47\x49\x46\x38': ("gif", MediaType.IMAGE),
    }

    def __init__(self):
        pass

    def process_file(self, file_path: str) -> Dict[str, Any]:
        """
        Process a media file and extract all available metadata.
        Returns a structured dict with media info.
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        # Compute content hash
        content_hash = self._compute_hash(file_path)

        # Detect format
        media_type, fmt = self._detect_format(file_path)

        # Extract format-specific metadata
        metadata = {}
        duration = 0.0
        codec = ""
        bitrate = 0
        sample_rate = 0
        channels = 0
        width = 0
        height = 0
        fps = 0.0

        if fmt in ("mp4", "mp4/mov"):
            mp4_info = self._parse_mp4(file_path)
            duration = mp4_info.get("duration", 0.0)
            metadata = mp4_info.get("metadata", {})
            codec = mp4_info.get("codec", "")
            width = mp4_info.get("width", 0)
            height = mp4_info.get("height", 0)
            # MP4 files are typically video; override only if width/height present
            if width > 0 and height > 0:
                media_type = MediaType.VIDEO
            elif media_type != MediaType.VIDEO:
                media_type = MediaType.VIDEO

        elif fmt == "mp3":
            mp3_info = self._parse_mp3(file_path)
            duration = mp3_info.get("duration", 0.0)
            metadata = mp3_info.get("tags", {})
            bitrate = mp3_info.get("bitrate", 0)
            sample_rate = mp3_info.get("sample_rate", 0)

        elif fmt in ("png", "jpeg", "gif"):
            img_info = self._parse_image(file_path)
            width = img_info.get("width", 0)
            height = img_info.get("height", 0)
            metadata = img_info.get("metadata", {})
            media_type = MediaType.IMAGE

        info = MediaInfo(
            filename=filename,
            media_type=media_type,
            format=fmt or "unknown",
            duration_seconds=duration,
            file_size=file_size,
            content_hash=content_hash,
            codec=codec,
            bitrate=bitrate,
            sample_rate=sample_rate,
            channels=channels,
            width=width,
            height=height,
            fps=fps,
            metadata=metadata,
        )

        return info.to_dict()

    def parse_transcript(self, transcript_text: str, filename: str = "media.vtt") -> Dict[str, Any]:
        """Parse structured transcript (VTT/SRT or timestamped text)."""
        lines = transcript_text.splitlines()
        segments: List[Dict[str, Any]] = []
        current_segment = {"start": "00:00:00", "end": "00:00:00", "text": ""}
        in_header = True  # Skip VTT/SRT header lines

        for line in lines:
            line = line.strip()
            # Skip header (WEBVTT, BOM, empty lines at start)
            if in_header:
                if line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("Kind:") or line.startswith("Language:"):
                    continue
                if not line:
                    continue
                in_header = False
            if "-->" in line:
                parts = line.split("-->")
                current_segment = {
                    "start": parts[0].strip(),
                    "end": parts[1].strip(),
                    "text": ""
                }
            elif line and not line.isdigit() and "-->" not in line:
                if current_segment["text"]:
                    current_segment["text"] += " " + line
                else:
                    current_segment["text"] = line
                if current_segment not in segments:
                    segments.append(current_segment)

        if not segments:
            words = transcript_text.split()
            chunk_size = 50
            for i in range(0, len(words), chunk_size):
                start_sec = (i // chunk_size) * 30
                end_sec = start_sec + 30
                segments.append({
                    "start": f"{start_sec // 60:02d}:{start_sec % 60:02d}",
                    "end": f"{end_sec // 60:02d}:{end_sec % 60:02d}",
                    "text": " ".join(words[i:i + chunk_size])
                })

        return {
            "format": "media_transcript",
            "filename": filename,
            "segment_count": len(segments),
            "segments": segments,
            "total_words": len(transcript_text.split()),
            "preview": transcript_text[:500],
        }

    def extract_key_segments(self, transcript: Dict[str, Any], top_k: int = 5) -> List[Dict[str, Any]]:
        """Extract the most content-dense segments from a transcript."""
        segments = transcript.get("segments", [])
        scored = []
        for seg in segments:
            text = seg.get("text", "")
            word_count = len(text.split())
            # Score by word density and sentence completeness
            has_period = 1.0 if text.rstrip().endswith((".", "!", "?")) else 0.5
            score = word_count * has_period
            scored.append((score, seg))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [seg for _, seg in scored[:top_k]]

    def generate_summary(self, transcript: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a basic summary from transcript segments."""
        segments = transcript.get("segments", [])
        all_text = " ".join(s.get("text", "") for s in segments)
        words = all_text.split()
        word_freq = {}
        for w in words:
            w_lower = w.lower().strip(".,!?;:")
            if len(w_lower) > 3:
                word_freq[w_lower] = word_freq.get(w_lower, 0) + 1

        top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_segments": len(segments),
            "total_words": len(words),
            "estimated_duration_minutes": round(len(segments) * 0.5, 1),
            "top_keywords": [{"word": w, "count": c} for w, c in top_words],
            "preview": all_text[:300],
        }

    def _compute_hash(self, file_path: str, chunk_size: int = 8192) -> str:
        """Compute SHA-256 hash of file content."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()[:16]

    def _detect_format(self, file_path: str) -> Tuple[str, str]:
        """Detect media format from magic bytes."""
        try:
            with open(file_path, "rb") as f:
                header = f.read(12)
            for magic, (fmt, mtype) in self.MAGIC_BYTES.items():
                if header[:len(magic)] == magic:
                    # Special handling for RIFF (WAV vs AVI)
                    if magic == b'\x52\x49\x46\x46' and len(header) >= 12:
                        if header[8:12] == b'WAVE':
                            return MediaType.AUDIO, "wav"
                        elif header[8:12] == b'AVI ':
                            return MediaType.VIDEO, "avi"
                        return MediaType.UNKNOWN, "riff"
                    return mtype, fmt
        except (IOError, OSError):
            pass

        ext = os.path.splitext(file_path)[1].lower()
        ext_map = {
            ".mp4": ("mp4", MediaType.VIDEO),
            ".mov": ("mov", MediaType.VIDEO),
            ".avi": ("avi", MediaType.VIDEO),
            ".mkv": ("mkv", MediaType.VIDEO),
            ".webm": ("webm", MediaType.VIDEO),
            ".mp3": ("mp3", MediaType.AUDIO),
            ".wav": ("wav", MediaType.AUDIO),
            ".flac": ("flac", MediaType.AUDIO),
            ".ogg": ("ogg", MediaType.AUDIO),
            ".aac": ("aac", MediaType.AUDIO),
            ".m4a": ("m4a", MediaType.AUDIO),
            ".png": ("png", MediaType.IMAGE),
            ".jpg": ("jpeg", MediaType.IMAGE),
            ".jpeg": ("jpeg", MediaType.IMAGE),
            ".gif": ("gif", MediaType.IMAGE),
        }
        if ext in ext_map:
            return ext_map[ext]
        return ("unknown", MediaType.UNKNOWN)

    def _parse_mp4(self, file_path: str) -> Dict[str, Any]:
        """Parse MP4/MOV container for duration and metadata."""
        info = {"duration": 0.0, "metadata": {}, "codec": "", "width": 0, "height": 0}
        try:
            with open(file_path, "rb") as f:
                while True:
                    box_header = f.read(8)
                    if len(box_header) < 8:
                        break
                    box_size = struct.unpack(">I", box_header[:4])[0]
                    box_type = box_header[4:8].decode("ascii", errors="ignore")

                    if box_size < 8:
                        break

                    if box_type == "mvhd":
                        version = struct.unpack("B", f.read(1))[0]
                        f.read(3)  # flags
                        if version == 0:
                            timescale = struct.unpack(">I", f.read(4))[0]
                            duration = struct.unpack(">I", f.read(4))[0]
                        else:
                            f.read(4)  # reserved
                            timescale = struct.unpack(">I", f.read(4))[0]
                            duration = struct.unpack(">Q", f.read(8))[0]
                        if timescale > 0:
                            info["duration"] = duration / timescale
                        break
                    else:
                        f.seek(box_size - 8, 1)
        except (struct.error, IOError, OSError):
            pass
        return info

    def _parse_mp3(self, file_path: str) -> Dict[str, Any]:
        """Parse MP3 file for duration and basic tags."""
        info = {"duration": 0.0, "bitrate": 0, "sample_rate": 0, "tags": {}}
        try:
            file_size = os.path.getsize(file_path)
            with open(file_path, "rb") as f:
                header = f.read(4)
                if len(header) < 4:
                    return info

                # Check for ID3v2 tag
                if header[:3] == b'ID3':
                    f.seek(0, 2)
                    info["tags"]["has_id3v2"] = True

                # Try to read first frame header
                f.seek(0)
                data = f.read(min(file_size, 65536))

                # Find first sync frame
                for i in range(len(data) - 4):
                    if data[i] == 0xFF and (data[i+1] & 0xE0) == 0xE0:
                        # Parse frame header
                        header_val = struct.unpack(">I", data[i:i+4])[0]
                        version_bits = (header_val >> 19) & 3
                        layer_bits = (header_val >> 17) & 3
                        bitrate_idx = (header_val >> 12) & 0xF
                        sample_rate_idx = (header_val >> 10) & 3

                        # Bitrate table for MPEG1 Layer III
                        bitrate_table = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
                        if 1 <= bitrate_idx <= 14:
                            info["bitrate"] = bitrate_table[bitrate_idx] * 1000

                        sample_rates = [44100, 48000, 32000]
                        if 0 <= sample_rate_idx <= 2:
                            info["sample_rate"] = sample_rates[sample_rate_idx]

                        if info["bitrate"] > 0 and info["sample_rate"] > 0:
                            info["duration"] = (file_size * 8) / info["bitrate"]
                        break
        except (struct.error, IOError, OSError):
            pass
        return info

    def _parse_image(self, file_path: str) -> Dict[str, Any]:
        """Parse image file for dimensions and metadata."""
        info = {"width": 0, "height": 0, "metadata": {}}
        try:
            with open(file_path, "rb") as f:
                header = f.read(32)
                if header[:8] == b'\x89PNG\r\n\x1a\n':
                    # PNG
                    f.seek(16)
                    width, height = struct.unpack(">II", f.read(8))
                    info["width"] = width
                    info["height"] = height
                elif header[:2] == b'\xff\xd8':
                    # JPEG - find SOF marker
                    f.seek(2)
                    while True:
                        marker = f.read(2)
                        if len(marker) < 2:
                            break
                        if marker[0] != 0xFF:
                            break
                        if marker[1] in (0xC0, 0xC1, 0xC2):
                            f.read(3)  # length + precision
                            height, width = struct.unpack(">HH", f.read(4))
                            info["width"] = width
                            info["height"] = height
                            break
                        else:
                            length = struct.unpack(">H", f.read(2))[0]
                            f.seek(length - 2, 1)
                elif header[:6] == b'GIF89a' or header[:6] == b'GIF87a':
                    # GIF
                    info["width"] = struct.unpack("<H", header[6:8])[0]
                    info["height"] = struct.unpack("<H", header[8:10])[0]
        except (struct.error, IOError, OSError):
            pass
        return info
