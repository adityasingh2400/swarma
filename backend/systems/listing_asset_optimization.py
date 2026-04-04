from __future__ import annotations

import logging
import uuid
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from backend.config import settings
from backend.models.item_card import ItemCard
from backend.models.listing_package import ListingImage

logger = logging.getLogger(__name__)


def _optimized_path_to_url(path: str) -> str:
    return f"/optimized/{Path(path).name}"

MIN_SHARPNESS = 50.0
MAX_IMAGES = 8
DUPLICATE_THRESHOLD = 0.95


class ListingAssetOptimizationSystem:
    def __init__(self) -> None:
        self.output_dir = Path(settings.optimized_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def optimize(self, item: ItemCard) -> list[ListingImage]:
        if not item.hero_frame_paths and not item.all_frame_paths:
            logger.warning("No frame candidates for item %s", item.item_id)
            return []

        # Hero frames first (Gemini-selected frames of THIS item), then fill from all frames
        hero_set = set(item.hero_frame_paths or [])
        hero_scored = []
        for path in (item.hero_frame_paths or []):
            score = self._score_frame(path)
            if score >= MIN_SHARPNESS:
                hero_scored.append((path, score))

        extra_scored = []
        for path in (item.all_frame_paths or []):
            if path in hero_set:
                continue
            score = self._score_frame(path)
            if score >= MIN_SHARPNESS:
                extra_scored.append((path, score))

        hero_scored.sort(key=lambda x: x[1], reverse=True)
        extra_scored.sort(key=lambda x: x[1], reverse=True)

        # Hero frames get priority, extras fill remaining slots
        ordered = [p for p, _ in hero_scored] + [p for p, _ in extra_scored]
        filtered = self._reject_duplicates(ordered)

        results: list[ListingImage] = []
        for i, src_path in enumerate(filtered[:MAX_IMAGES]):
            try:
                img = Image.open(src_path)
                img = self._auto_crop(img)
                img = self._normalize_exposure(img)

                out_name = f"{item.item_id}_{uuid.uuid4().hex[:6]}.jpg"
                out_path = self.output_dir / out_name
                img.save(str(out_path), "JPEG", quality=92)

                role = "hero" if i == 0 else "secondary"
                results.append(ListingImage(
                    path=_optimized_path_to_url(out_path),
                    role=role,
                    original_path=src_path,
                    optimized=True,
                ))
            except Exception:
                logger.exception("Failed to optimize frame %s", src_path)

        return results

    def _score_frame(self, path: str) -> float:
        try:
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return 0.0
            laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()
            brightness = float(np.mean(img))
            brightness_penalty = 0.0
            if brightness < 40 or brightness > 240:
                brightness_penalty = 30.0
            return max(laplacian_var - brightness_penalty, 0.0)
        except Exception:
            logger.exception("Frame scoring failed for %s", path)
            return 0.0

    def _auto_crop(self, image: Image.Image) -> Image.Image:
        try:
            gray = image.convert("L")
            edge = gray.filter(ImageFilter.FIND_EDGES)
            arr = np.array(edge)
            threshold = 30
            rows = np.any(arr > threshold, axis=1)
            cols = np.any(arr > threshold, axis=0)

            if not rows.any() or not cols.any():
                return image

            top = int(np.argmax(rows))
            bottom = int(len(rows) - np.argmax(rows[::-1]))
            left = int(np.argmax(cols))
            right = int(len(cols) - np.argmax(cols[::-1]))

            h, w = arr.shape
            padding = int(min(h, w) * 0.03)
            top = max(0, top - padding)
            left = max(0, left - padding)
            bottom = min(h, bottom + padding)
            right = min(w, right + padding)

            cropped = image.crop((left, top, right, bottom))
            cw, ch = cropped.size
            if cw < w * 0.3 or ch < h * 0.3:
                return image
            return cropped
        except Exception:
            return image

    def _normalize_exposure(self, image: Image.Image) -> Image.Image:
        try:
            arr = np.array(image.convert("L"))
            mean_brightness = float(np.mean(arr))
            target = 128.0

            if abs(mean_brightness - target) < 20:
                return image

            factor = target / max(mean_brightness, 1.0)
            factor = max(0.5, min(factor, 2.0))
            enhancer = ImageEnhance.Brightness(image)
            adjusted = enhancer.enhance(factor)

            contrast = ImageEnhance.Contrast(adjusted)
            return contrast.enhance(1.1)
        except Exception:
            return image

    def _reject_duplicates(self, paths: list[str]) -> list[str]:
        if len(paths) <= 1:
            return paths

        kept: list[str] = []
        histograms: list[np.ndarray] = []

        for path in paths:
            try:
                img = cv2.imread(path)
                if img is None:
                    continue
                small = cv2.resize(img, (64, 64))
                hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
                hist = cv2.normalize(hist, hist).flatten()

                is_dup = False
                for prev_hist in histograms:
                    similarity = cv2.compareHist(hist, prev_hist, cv2.HISTCMP_CORREL)
                    if similarity > DUPLICATE_THRESHOLD:
                        is_dup = True
                        break

                if not is_dup:
                    kept.append(path)
                    histograms.append(hist)
            except Exception:
                kept.append(path)

        return kept
