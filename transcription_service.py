"""
Smart Office Assistant - Transcription Service
Handles audio/video file transcription using OpenAI Whisper API.
"""
import os
import tempfile
from pathlib import Path
from typing import Optional
from openai import OpenAI
from config import OPENAI_API_KEY, WHISPER_MODEL, MAX_AUDIO_FILE_SIZE_MB, debug_log


client = OpenAI(api_key=OPENAI_API_KEY)

# Supported file formats for Whisper
SUPPORTED_AUDIO_FORMATS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg"}


def is_supported_format(filename: str) -> bool:
    """Check if the file format is supported by Whisper."""
    ext = Path(filename).suffix.lower()
    return ext in SUPPORTED_AUDIO_FORMATS


def check_file_size(file_data: bytes) -> bool:
    """Check if file is within Whisper's size limit (25 MB)."""
    size_mb = len(file_data) / (1024 * 1024)
    return size_mb <= MAX_AUDIO_FILE_SIZE_MB


def transcribe_audio(
    file_data: bytes,
    filename: str,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
) -> dict:
    """
    Transcribe an audio/video file using OpenAI Whisper API.
    
    Args:
        file_data: Raw bytes of the audio/video file
        filename: Original filename (used for format detection)
        language: Optional language code (e.g., 'en', 'hi')
        prompt: Optional prompt to guide transcription
    
    Returns:
        dict with 'success', 'transcript', 'duration', 'language'
    """
    if not is_supported_format(filename):
        return {
            "success": False,
            "error": f"Unsupported format. Supported: {', '.join(SUPPORTED_AUDIO_FORMATS)}"
        }

    if not check_file_size(file_data):
        return {
            "success": False,
            "error": f"File too large. Maximum size: {MAX_AUDIO_FILE_SIZE_MB} MB"
        }

    try:
        # Write to a temporary file (Whisper API needs a file-like object)
        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as audio_file:
                kwargs = {
                    "model": WHISPER_MODEL,
                    "file": audio_file,
                    "response_format": "verbose_json",
                }
                if language:
                    kwargs["language"] = language
                if prompt:
                    kwargs["prompt"] = prompt

                debug_log("[OpenAI Whisper transcribe_audio] Request: model=%s, language=%s, prompt=%s" % (WHISPER_MODEL, language, prompt))
                result = client.audio.transcriptions.create(**kwargs)
                debug_log("[OpenAI Whisper transcribe_audio] Response: transcript_len=%d, text (first 300 chars): %s"
                             % (len(result.text), (result.text[:300] + "..." if len(result.text) > 300 else result.text)))

            return {
                "success": True,
                "transcript": result.text,
                "duration": getattr(result, "duration", None),
                "language": getattr(result, "language", language or "unknown"),
                "segments": [
                    {
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text,
                    }
                    for seg in getattr(result, "segments", [])
                ],
            }

        finally:
            os.unlink(tmp_path)

    except Exception as e:
        return {
            "success": False,
            "error": f"Transcription failed: {str(e)}"
        }


def transcribe_audio_file(filepath: str, language: Optional[str] = None) -> dict:
    """Transcribe an audio file from a file path."""
    path = Path(filepath)
    if not path.exists():
        return {"success": False, "error": f"File not found: {filepath}"}

    with open(path, "rb") as f:
        file_data = f.read()

    return transcribe_audio(file_data, path.name, language)
