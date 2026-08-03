#!/usr/bin/env python3
"""
convert.py - Convert sailing exam PDFs to questions.json + images/

Usage:
    python convert.py                        # process all PDFs
    python convert.py --resume               # skip already-processed pages
    python convert.py --pdf "Meteorologia.pdf"  # one file only
    python convert.py --reset                # clear checkpoint and start fresh
    python convert.py --out /some/dir        # output directory (default: /tmp/egzamin)

Uses ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL from ~/.claude/settings.json,
or falls back to ANTHROPIC_API_KEY environment variable.
"""

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import anthropic
import fitz  # PyMuPDF
from PIL import Image
import io

# ── Constants ──────────────────────────────────────────────────────────────
PDF_DIR = Path(".")
DEFAULT_OUT_DIR = Path("/tmp/egzamin")

RENDER_DPI = 150
JPEG_QUALITY = 85
MAX_RETRIES = 3
RETRY_DELAY_BASE = 5
ANTHROPIC_MODEL = "claude-opus-5"  # overridden after configure_api() loads settings

PDF_FILES_REAL = [
    ("Budowa jachtów.pdf",                              "Budowa jachtów"),
    ("Manewrowanie.pdf",                                     "Manewrowanie"),
    ("Meteorologia.pdf",                                     "Meteorologia"),
    ("Podstawy locji i pomoce nawigacyjne.pdf",              "Podstawy locji"),
    ("Przepisy prawa drogi, ochrona wód, etykieta.pdf", "Przepisy drogi"),
    ("Ratownictwo wodne.pdf",                                "Ratownictwo wodne"),
    ("Teoria żeglowania.pdf",                           "Teoria żeglowania"),
]


# ── API setup ──────────────────────────────────────────────────────────────

def load_claude_settings() -> dict:
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text(encoding="utf-8")).get("env", {})
    except Exception:
        return {}


def configure_api() -> anthropic.Anthropic:
    global ANTHROPIC_MODEL
    env = load_claude_settings()
    for key, val in env.items():
        if key not in os.environ:
            os.environ[key] = val

    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")

    if not auth_token and not api_key:
        print("ERROR: No API credentials found.")
        sys.exit(1)

    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", ANTHROPIC_MODEL)
    print(f"Using model: {ANTHROPIC_MODEL}")
    if base_url:
        print(f"Using base URL: {base_url}")

    kwargs = {}
    if auth_token:
        kwargs["api_key"] = auth_token
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


# ── PDF rendering ──────────────────────────────────────────────────────────

def render_page(pdf_path: Path, page_num: int) -> bytes:
    doc = fitz.open(str(pdf_path))
    page = doc[page_num]
    mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


def save_question_image(page_png: bytes, question_id: int, images_dir: Path) -> str:
    images_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(page_png)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY)
    img_path = images_dir / f"q_{question_id}.jpg"
    img_path.write_bytes(buf.getvalue())
    return f"images/q_{question_id}.jpg"


# ── JSON repair ────────────────────────────────────────────────────────────

def fix_json(s: str) -> str:
    # Pass 1: replace typographic/curly quotes with escaped double-quote
    for ch in ['„', '“', '”', '»', '«', '‘', '’']:
        s = s.replace(ch, '\\"')

    # Pass 2: state machine - escape bare " that appear inside JSON string values
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            out.append('"')
            i += 1
            while i < n:
                c2 = s[i]
                if c2 == '\\' and i + 1 < n:
                    out.append(c2)
                    out.append(s[i + 1])
                    i += 2
                elif c2 == '"':
                    j = i + 1
                    while j < n and s[j] in ' \t\n\r':
                        j += 1
                    if j >= n or s[j] in ':,}]':
                        out.append('"')
                        i += 1
                        break
                    else:
                        out.append('\\"')
                        i += 1
                else:
                    out.append(c2)
                    i += 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


# ── Claude API ─────────────────────────────────────────────────────────────

def build_extraction_prompt(category: str) -> str:
    return (
        f'This is a page from a Polish sailing license exam question bank. Category: "{category}".\n\n'
        'The page contains multiple-choice questions, each with answers A, B, and C.\n\n'
        'Your task:\n'
        '1. Extract every question visible on this page\n'
        '2. Determine the CORRECT answer based on your knowledge of sailing, maritime law, '
        'meteorology, and seamanship\n'
        '3. Identify whether the question has an associated illustration or diagram\n\n'
        'Return ONLY a JSON array, no other text. Schema:\n'
        '[{\n'
        '  "number": <int>,\n'
        '  "text": "<exact Polish question text>",\n'
        '  "answers": {"A": "...", "B": "...", "C": "..."},\n'
        '  "correct": "<A, B, or C>",\n'
        '  "has_illustration": <true|false>\n'
        '}]\n\n'
        'IMPORTANT: Use only straight ASCII double-quotes in your JSON. '
        'If question text contains quote characters, escape them as \\". '
        'Return empty array [] if page has no questions.'
    )


def call_claude(client: anthropic.Anthropic, png_bytes: bytes, category: str, page_num: int) -> list[dict]:
    b64 = base64.standard_b64encode(png_bytes).decode()
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": build_extraction_prompt(category)},
        ]}],
    )
    raw = response.content[0].text

    match = re.search(r'\[[\s\S]*\]', raw)
    if not match:
        raise ValueError(f"No JSON array in response for page {page_num}")

    json_text = fix_json(match.group())
    raw_list = json.loads(json_text)

    questions = []
    for item in raw_list:
        if not all(k in item for k in ["number", "text", "answers", "correct", "has_illustration"]):
            continue
        if not all(k in item["answers"] for k in ["A", "B", "C"]):
            continue
        if item["correct"] not in ("A", "B", "C"):
            item["correct"] = "A"
        questions.append(item)
    return questions


def call_with_retry(client: anthropic.Anthropic, png_bytes: bytes, category: str, page_num: int) -> list[dict]:
    delay = RETRY_DELAY_BASE
    for attempt in range(MAX_RETRIES):
        try:
            return call_claude(client, png_bytes, category, page_num)
        except anthropic.RateLimitError as e:
            wait = int(getattr(getattr(e, "response", None), "headers", {}).get("retry-after", delay))
            print(f"\n    Rate limited, waiting {wait}s...", end=" ", flush=True)
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                print(f"\n    Server error ({e.status_code}), retry {attempt+1}/{MAX_RETRIES}", end=" ", flush=True)
                time.sleep(delay)
                delay *= 2
            else:
                raise
        except (json.JSONDecodeError, ValueError) as e:
            print(f"\n    Parse error attempt {attempt+1}/{MAX_RETRIES}: {e}", end=" ", flush=True)
            if attempt == MAX_RETRIES - 1:
                print(f"\n    GIVING UP on page {page_num}")
                return []
            time.sleep(delay)
            delay *= 2
    return []


# ── Checkpoint ─────────────────────────────────────────────────────────────

def checkpoint_load(out_dir: Path) -> dict:
    f = out_dir / "checkpoint.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"pages": {}, "next_id": 1}


def checkpoint_save(checkpoint: dict, out_dir: Path):
    (out_dir / "checkpoint.json").write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── PDF processing ──────────────────────────────────────────────────────────

def process_pdf(pdf_path: Path, category: str, checkpoint: dict,
                client: anthropic.Anthropic, out_dir: Path) -> list[dict]:
    doc = fitz.open(str(pdf_path))
    page_count = len(doc)
    doc.close()

    images_dir = out_dir / "images"
    all_questions = []

    for page_num in range(page_count):
        ck_key = f"{pdf_path.name}::{page_num}"

        if ck_key in checkpoint["pages"]:
            cached = checkpoint["pages"][ck_key]
            print(f"  [SKIP] page {page_num+1}/{page_count} ({len(cached)} questions, cached)")
            all_questions.extend(cached)
            continue

        print(f"  [API]  page {page_num+1}/{page_count}...", end=" ", flush=True)
        png_bytes = render_page(pdf_path, page_num)
        raw_qs = call_with_retry(client, png_bytes, category, page_num)

        page_questions = []
        for q in raw_qs:
            qid = checkpoint["next_id"]
            checkpoint["next_id"] += 1
            has_img = q.pop("has_illustration", False)
            orig_number = q.pop("number", None)
            entry = {
                "id": qid,
                "orig_number": orig_number,
                "category": category,
                "text": q["text"],
                "answers": q["answers"],
                "correct": q["correct"],
                "image": save_question_image(png_bytes, qid, images_dir) if has_img else None,
            }
            page_questions.append(entry)

        print(f"{len(page_questions)} questions")
        checkpoint["pages"][ck_key] = page_questions
        checkpoint_save(checkpoint, out_dir)
        all_questions.extend(page_questions)
        time.sleep(1.0)

    return all_questions


# ── Main ───────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Convert sailing exam PDFs to questions.json")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.add_argument("--pdf", metavar="NAME")
    p.add_argument("--out", metavar="DIR", default=str(DEFAULT_OUT_DIR))
    return p.parse_args()


def main():
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = configure_api()
    checkpoint = checkpoint_load(out_dir)

    if args.reset:
        print("Resetting checkpoint...")
        checkpoint = {"pages": {}, "next_id": 1}
        checkpoint_save(checkpoint, out_dir)

    pdf_list = PDF_FILES_REAL
    if args.pdf:
        matches = [(Path(n), c) for n, c in PDF_FILES_REAL if n == args.pdf]
        if not matches:
            print(f"ERROR: '{args.pdf}' not found. Available:")
            for n, _ in PDF_FILES_REAL:
                print(f"  {n}")
            sys.exit(1)
        pdf_list = [(Path(matches[0][0]), matches[0][1])]

    all_questions = []
    for pdf_name, category in pdf_list:
        full_path = PDF_DIR / pdf_name
        if not full_path.exists():
            print(f"WARNING: {pdf_name} not found, skipping")
            continue
        print(f"\nProcessing: {pdf_name} ({category})")
        questions = process_pdf(full_path, category, checkpoint, client, out_dir)
        all_questions.extend(questions)

    if not all_questions:
        print("\nNo questions extracted.")
        return

    out_file = out_dir / "questions.json"
    out_file.write_text(
        json.dumps({"questions": all_questions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with_images = sum(1 for q in all_questions if q["image"])
    print(f"\nDone! {len(all_questions)} questions -> {out_file}")
    print(f"Images: {with_images} in {out_dir}/images/")
    print("\nBy category:")
    by_cat: dict[str, int] = {}
    for q in all_questions:
        by_cat[q["category"]] = by_cat.get(q["category"], 0) + 1
    for cat, count in sorted(by_cat.items()):
        print(f"  {cat}: {count}")
    print(f"\nCopy to project directory when done:")
    print(f"  cp {out_file} .")
    print(f"  cp -r {out_dir}/images .")


if __name__ == "__main__":
    main()
