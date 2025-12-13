"""Media helpers: download remote images, normalize to Instagram-friendly JPEG."""

from __future__ import annotations

import os
import re
import uuid
from typing import Optional, Tuple

import requests
from PIL import Image


def _safe_ext_from_content_type(content_type: str) -> str:
    ct = (content_type or '').lower()
    if 'jpeg' in ct or 'jpg' in ct:
        return '.jpg'
    if 'png' in ct:
        return '.png'
    if 'webp' in ct:
        return '.webp'
    return ''


def download_image(url: str, dest_dir: str, timeout: int = 25) -> str:
    """Download image from URL and return local path."""
    if not url:
        raise ValueError('Empty url')

    os.makedirs(dest_dir, exist_ok=True)

    headers = {
        'User-Agent': 'Mozilla/5.0 (osintgram; +https://example.invalid)'
    }
    resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
    resp.raise_for_status()

    ext = _safe_ext_from_content_type(resp.headers.get('Content-Type', ''))
    if not ext:
        # try from url
        m = re.search(r'\.(jpg|jpeg|png|webp)(\?|$)', url.lower())
        if m:
            ext = '.' + m.group(1).replace('jpeg', 'jpg')
        else:
            ext = '.img'

    path = os.path.join(dest_dir, f'{uuid.uuid4().hex}{ext}')
    with open(path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=1024 * 128):
            if chunk:
                f.write(chunk)
    return path


def normalize_to_jpeg(input_path: str, output_path: str, max_size: Tuple[int, int] = (1080, 1350)) -> str:
    """Convert image to RGB JPEG and resize to fit within max_size."""
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    with Image.open(input_path) as im:
        im = im.convert('RGB')
        im.thumbnail(max_size, Image.LANCZOS)
        im.save(output_path, format='JPEG', quality=92, optimize=True)

    return output_path


def download_and_prepare_instagram_jpeg(url: str, work_dir: str) -> str:
    """Download an image and return a normalized local JPEG path suitable for IG upload."""
    raw_path = download_image(url, work_dir)
    jpg_path = os.path.join(work_dir, f'{uuid.uuid4().hex}.jpg')
    try:
        return normalize_to_jpeg(raw_path, jpg_path)
    finally:
        try:
            os.remove(raw_path)
        except Exception:
            pass
