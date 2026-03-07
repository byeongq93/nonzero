import io
from functools import lru_cache

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

try:
    import easyocr  # type: ignore
except Exception:
    easyocr = None

try:
    from paddleocr import PaddleOCR  # type: ignore
except Exception:
    PaddleOCR = None


_RESAMPLE = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
_KEYWORDS = ("유효성분", "유요성분", "성분", "원료약품", "원료 약품", "분량", "USP", "KP", "JP", "EP", "BP")
_STRONG_KEYWORDS = ("유효성분", "유요성분", "원료약품", "원료 약품")
_NOISE_HINTS = (
    "효능", "효과", "용법", "용량", "주의", "RFID",
    "초회용량", "권장 유지", "1일 1회", "1일 최대", "식이요법",
)


@lru_cache(maxsize=1)
def _get_easy_reader():
    if easyocr is None:
        raise RuntimeError("easyocr가 설치되어 있지 않습니다. pip install easyocr")
    return easyocr.Reader(["ko", "en"], gpu=False)


@lru_cache(maxsize=1)
def _get_paddle_reader():
    if PaddleOCR is None:
        return None
    tried = [
        {"use_angle_cls": True, "lang": "korean", "show_log": False},
        {"use_angle_cls": True, "lang": "korean"},
        {"use_angle_cls": True, "lang": "korean", "det": True, "rec": True},
    ]
    for kwargs in tried:
        try:
            return PaddleOCR(**kwargs)
        except Exception:
            continue
    return None


def _resize_for_ocr(image: Image.Image) -> Image.Image:
    base = ImageOps.exif_transpose(image).convert("RGB")
    long_side = max(base.size)
    if long_side > 1900:
        scale = 1900 / long_side
        base = base.resize((max(1, int(base.width * scale)), max(1, int(base.height * scale))), _RESAMPLE)
    elif long_side < 1300:
        scale = 1300 / long_side
        base = base.resize((max(1, int(base.width * scale)), max(1, int(base.height * scale))), _RESAMPLE)
    return base


def _variants(image: Image.Image):
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    strong = ImageEnhance.Contrast(gray).enhance(2.0).filter(ImageFilter.SHARPEN)
    binary = strong.point(lambda p: 255 if p > 170 else 0)
    return [image, strong.convert("RGB"), binary.convert("RGB")]


def _clean_text(text):
    return " ".join(str(text or "").split()).strip()


def _read_easy_lines(reader, image: Image.Image, offset=(0, 0)):
    ox, oy = offset
    try:
        results = reader.readtext(np.array(image), detail=1, paragraph=False)
    except Exception:
        return []

    rows = []
    for entry in results:
        if not entry or len(entry) < 3:
            continue
        box, text, conf = entry
        text = _clean_text(text)
        if not text:
            continue
        xs = [pt[0] for pt in box]
        ys = [pt[1] for pt in box]
        rows.append(
            {
                "text": text,
                "conf": float(conf or 0.0),
                "box": (
                    ox + max(0, int(min(xs))),
                    oy + max(0, int(min(ys))),
                    ox + max(0, int(max(xs))),
                    oy + max(0, int(max(ys))),
                ),
                "engine": "easyocr",
            }
        )
    return rows


def _iter_paddle_items(result):
    if not result:
        return []
    if isinstance(result, tuple):
        result = list(result)
    if isinstance(result, list) and result and isinstance(result[0], dict):
        items = []
        for entry in result:
            rec_texts = entry.get("rec_texts") or []
            rec_scores = entry.get("rec_scores") or []
            rec_boxes = entry.get("rec_boxes") or []
            for idx, text in enumerate(rec_texts):
                box = rec_boxes[idx] if idx < len(rec_boxes) else None
                score = rec_scores[idx] if idx < len(rec_scores) else 0.0
                items.append((box, text, score))
        return items
    if isinstance(result, list) and result and isinstance(result[0], list):
        if result and len(result) == 1 and isinstance(result[0], list):
            result = result[0]
        items = []
        for entry in result:
            if isinstance(entry, list) and len(entry) >= 2:
                box = entry[0]
                rec = entry[1]
                if isinstance(rec, (list, tuple)) and len(rec) >= 2:
                    items.append((box, rec[0], rec[1]))
        return items
    return []


def _read_paddle_lines(reader, image: Image.Image, offset=(0, 0)):
    if reader is None:
        return []
    ox, oy = offset
    try:
        result = reader.ocr(np.array(image), cls=True)
    except Exception:
        return []

    rows = []
    for box, text, conf in _iter_paddle_items(result):
        text = _clean_text(text)
        if not text or box is None:
            continue
        try:
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
        except Exception:
            continue
        rows.append(
            {
                "text": text,
                "conf": float(conf or 0.0),
                "box": (
                    ox + max(0, int(min(xs))),
                    oy + max(0, int(min(ys))),
                    ox + max(0, int(max(xs))),
                    oy + max(0, int(max(ys))),
                ),
                "engine": "paddleocr",
            }
        )
    return rows


def _line_score(text: str, conf: float) -> float:
    score = float(conf or 0.0)
    t = str(text or "")
    if any(k in t for k in _STRONG_KEYWORDS):
        score += 0.65
    elif any(k in t for k in _KEYWORDS):
        score += 0.25
    if any(u in t for u in ("USP", "KP", "JP", "EP", "BP")):
        score += 0.25
    if any(u in t for u in ("mg", "mL", "ml", "㎎")):
        score += 0.12
    if any(n in t for n in _NOISE_HINTS):
        score -= 0.18
    if len(t) > 90:
        score -= 0.15
    return score


def _merge_lines(rows):
    best = {}
    for row in rows:
        text = _clean_text(row.get("text"))
        if not text:
            continue
        x1, y1, x2, y2 = row.get("box", (0, 0, 0, 0))
        key = text.lower()
        score = _line_score(text, row.get("conf", 0.0))
        current = best.get(key)
        payload = {
            "text": text,
            "score": score,
            "conf": float(row.get("conf", 0.0)),
            "x": x1,
            "y": y1,
            "box": (x1, y1, x2, y2),
        }
        if current is None:
            best[key] = payload
        else:
            if (y1, x1) < (current["y"], current["x"]):
                current["x"], current["y"] = x1, y1
            if score > current["score"]:
                current.update(payload)
    ordered = sorted(best.values(), key=lambda item: (item["y"], item["x"], -item["score"]))
    return [item["text"] for item in ordered[:60]]


def _context_crop(base: Image.Image, box):
    x1, y1, x2, y2 = box
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    pad_x = max(36, int(bw * 0.18))
    pad_y = max(24, int(bh * 0.8))
    left = max(0, x1 - pad_x)
    right = min(base.size[0], x2 + pad_x)
    top = max(0, y1 - pad_y)
    bottom = min(base.size[1], y2 + int(pad_y * 4.0))
    return base.crop((left, top, right, bottom)), (left, top)


def _title_crop(base: Image.Image):
    w, h = base.size
    if w >= h:
        box = (0, 0, int(w * 0.62), int(h * 0.46))
    else:
        box = (0, 0, w, int(h * 0.4))
    return base.crop(box), (box[0], box[1])


def _lower_left_crop(base: Image.Image):
    w, h = base.size
    box = (0, int(h * 0.18), int(w * 0.75), min(h, int(h * 0.78)))
    return base.crop(box), (box[0], box[1])


async def extract_text_from_image(image):
    contents = await image.read()
    base = _resize_for_ocr(Image.open(io.BytesIO(contents)))
    easy_reader = _get_easy_reader()
    paddle_reader = _get_paddle_reader()

    seed_rows = []
    for variant in _variants(base)[:2]:
        seed_rows.extend(_read_easy_lines(easy_reader, variant))

    keyword_rows = [row for row in seed_rows if any(k in row.get("text", "") for k in _KEYWORDS)]
    keyword_rows = sorted(keyword_rows, key=lambda r: _line_score(r.get("text", ""), r.get("conf", 0.0)), reverse=True)

    extra_rows = []
    seen_regions = set()
    regions = []
    for row in keyword_rows[:2]:
        crop, offset = _context_crop(base, row["box"])
        sig = (*offset, *crop.size)
        if sig not in seen_regions:
            seen_regions.add(sig)
            regions.append((crop, offset, True))

    if not regions:
        regions.extend([
            (*_title_crop(base), False),
            (*_lower_left_crop(base), False),
        ])

    for crop, offset, prefer_binary in regions[:2]:
        variants = _variants(crop)
        for variant in variants[:2]:
            extra_rows.extend(_read_easy_lines(easy_reader, variant, offset=offset))
        if paddle_reader is not None:
            extra_rows.extend(_read_paddle_lines(paddle_reader, variants[0], offset=offset))
            if prefer_binary:
                extra_rows.extend(_read_paddle_lines(paddle_reader, variants[2], offset=offset))

    merged = _merge_lines(seed_rows + extra_rows)
    return "\n".join(merged).strip()
