"""Video generation utilities.

Creates a simple Ken Burns (zoom) animation from a still image and optionally
embeds a user-provided audio track.

Note: requires ffmpeg available via moviepy/imageio-ffmpeg.
"""

from __future__ import annotations

import os
from typing import Optional


def _require_moviepy():
    try:
        from moviepy.editor import ImageClip, AudioFileClip  # noqa: F401
        from moviepy.audio.fx.all import audio_loop  # noqa: F401
        from moviepy.video.fx.resize import resize  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "moviepy is required for animation. Install dependencies from requirements.txt"
        ) from e


def animate_photo_to_mp4(
    image_path: str,
    output_path: str,
    duration_seconds: int = 8,
    fps: int = 30,
    audio_path: Optional[str] = None,
    target_size: tuple[int, int] = (1080, 1920),
) -> str:
    """Create an MP4 animation from a still image.

    - Video duration is always `duration_seconds`.
    - If audio is shorter than the duration, it is looped.
    - If audio is longer, it is trimmed.

    Returns output_path.
    """

    _require_moviepy()
    from moviepy.editor import ImageClip, AudioFileClip
    from moviepy.audio.fx.all import audio_loop

    duration_seconds = int(duration_seconds or 0)
    if duration_seconds <= 0:
        duration_seconds = 8

    fps = int(fps or 0)
    if fps <= 0:
        fps = 30

    w, h = target_size

    clip = ImageClip(image_path).set_duration(duration_seconds)

    # Resize to cover the target frame, then center-crop.
    iw, ih = clip.size
    if iw == 0 or ih == 0:
        raise RuntimeError("Invalid image dimensions")

    scale = max(w / iw, h / ih)
    clip = clip.resize(scale)

    # Center-crop to exact target size.
    x1 = int((clip.w - w) / 2)
    y1 = int((clip.h - h) / 2)
    clip = clip.crop(x1=x1, y1=y1, width=w, height=h)

    # Simple Ken Burns zoom-in effect.
    zoom_max = 1.08

    def _zoom(t: float) -> float:
        if duration_seconds <= 0:
            return 1.0
        return 1.0 + (zoom_max - 1.0) * (t / duration_seconds)

    clip = clip.resize(_zoom)

    if audio_path:
        audio_path = os.path.abspath(audio_path)
        if os.path.exists(audio_path):
            audio = AudioFileClip(audio_path)
            if audio.duration <= 0:
                pass
            elif audio.duration < duration_seconds:
                audio = audio_loop(audio, duration=duration_seconds)
            else:
                audio = audio.subclip(0, duration_seconds)
            clip = clip.set_audio(audio)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    clip.write_videofile(
        output_path,
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        bitrate="5000k",
        preset="medium",
        threads=2,
        verbose=False,
        logger=None,
    )

    clip.close()
    return output_path
