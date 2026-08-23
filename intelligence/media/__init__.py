"""
Media intelligence exports (Rule #53).
"""

from .media_parser import MediaProcessor, MediaInfo, MediaType

# Backward compatibility alias
MediaParser = MediaProcessor

__all__ = ["MediaProcessor", "MediaInfo", "MediaType", "MediaParser"]
