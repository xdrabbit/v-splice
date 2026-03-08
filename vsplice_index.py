#!/usr/bin/env python3
"""
vsplice-index: Dense frame extraction + vision analysis → timeline index.

Extracts a frame every N seconds from each video, analyzes with local LLaVA,
detects scene boundaries, and writes a timeline index per clip.

Usage:
    python vsplice_index.py <folder> [--interval 3] [--model llava:13b] [--workers 2]

Requires: ffmpeg, ollama with a vision model
"""

import os
import sys
import json
import argparse
import base64
import tempfile
import subprocess
import datetime
import concurrent.futures
import threading
from pathlib import Path

import requests


# ── Configuration ─────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/generate"
VISION_PROMPT = (
    "Describe this video frame in ONE concise sentence. "
    "Include: setting/location, main objects, any people (what they're doing), "
    "vehicles, animals. Be specific about actions and objects. "
    "Example: 'Man in helmet riding electric scooter on residential driveway near parked cars.'"
)

# Scene boundary: if consecutive frames share fewer than this fraction of
# key terms, it's a new scene
SCENE_SIMILARITY_THRESHOLD = 0.35
SCENE_MIN_DURATION_SEC = 6  # Merge scenes shorter than this into neighbors


# ── Frame Extraction ──────────────────────────────────────────────────────────

def get_video_duration(video_path):
    """Get video duration in seconds via ffprobe."""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return None
    info = json.loads(result.stdout)
    return float(info['format']['duration'])


def extract_frames(video_path, output_dir, interval_sec=3):
    """Extract frames at regular intervals using ffmpeg with GPU decode."""
    os.makedirs(output_dir, exist_ok=True)

    duration = get_video_duration(video_path)
    if not duration:
        print(f"  Could not get duration for {video_path}")
        return [], 0

    # Calculate expected frame count
    expected = int(duration / interval_sec) + 1

    # Try GPU-accelerated decode first, fall back to CPU
    cmd = [
        'ffmpeg', '-y',
        '-hwaccel', 'cuda',
        '-i', video_path,
        '-vf', f'fps=1/{interval_sec},scale=512:-1',
        '-q:v', '3',
        os.path.join(output_dir, 'dense_%04d.jpg')
    ]

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # Fall back to CPU
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-vf', f'fps=1/{interval_sec},scale=512:-1',
            '-q:v', '3',
            os.path.join(output_dir, 'dense_%04d.jpg')
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            print(f"  ffmpeg failed: {result.stderr.decode(errors='replace')[-200:]}")
            return [], duration

    # Collect extracted frames
    frames = sorted([
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.startswith('dense_') and f.endswith('.jpg')
    ])

    return frames, duration


# ── Vision Analysis ───────────────────────────────────────────────────────────

def analyze_frame(frame_path, model="llava:13b", retries=2):
    """Analyze a single frame with local LLaVA via Ollama."""
    with open(frame_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    for attempt in range(retries + 1):
        try:
            resp = requests.post(OLLAMA_URL, json={
                'model': model,
                'prompt': VISION_PROMPT,
                'images': [img_b64],
                'stream': False,
                'options': {
                    'num_predict': 100,  # Keep responses short
                    'temperature': 0.1,  # Factual, not creative
                }
            }, timeout=60)
            r = resp.json()
            description = r.get('response', '').strip()
            if description:
                return description
        except Exception as e:
            if attempt < retries:
                continue
            return f"[analysis failed: {e}]"

    return "[no description]"


# ── Scene Detection ───────────────────────────────────────────────────────────

def extract_key_terms(description):
    """Extract meaningful terms from a frame description for scene comparison."""
    # Simple but effective: split into words, filter stopwords
    stopwords = {
        'a', 'an', 'the', 'in', 'on', 'at', 'of', 'with', 'and', 'or', 'to',
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'this', 'that',
        'it', 'its', 'for', 'from', 'by', 'as', 'into', 'has', 'have',
        'there', 'their', 'they', 'some', 'what', 'which', 'who', 'whom',
        'can', 'could', 'would', 'should', 'may', 'might', 'near', 'appears',
        'visible', 'seen', 'shows', 'image', 'frame', 'video', 'appears',
    }
    words = set()
    for word in description.lower().split():
        # Strip punctuation
        word = ''.join(c for c in word if c.isalnum() or c == '-')
        if word and len(word) > 2 and word not in stopwords:
            words.add(word)
    return words


def similarity(terms_a, terms_b):
    """Jaccard similarity between two term sets."""
    if not terms_a or not terms_b:
        return 0.0
    intersection = terms_a & terms_b
    union = terms_a | terms_b
    return len(intersection) / len(union)


def detect_scenes(frame_analyses, interval_sec, threshold=SCENE_SIMILARITY_THRESHOLD):
    """Group consecutive frames into scenes based on content similarity."""
    if not frame_analyses:
        return []

    scenes = []
    current_scene = {
        'start_sec': 0,
        'end_sec': interval_sec,
        'frames': [frame_analyses[0]],
        'key_terms': extract_key_terms(frame_analyses[0]['description']),
    }

    for i in range(1, len(frame_analyses)):
        fa = frame_analyses[i]
        new_terms = extract_key_terms(fa['description'])
        sim = similarity(current_scene['key_terms'], new_terms)

        if sim >= threshold:
            # Same scene — extend
            current_scene['end_sec'] = fa['timestamp_sec'] + interval_sec
            current_scene['frames'].append(fa)
            # Merge terms
            current_scene['key_terms'] |= new_terms
        else:
            # New scene — save current, start new
            scenes.append(finalize_scene(current_scene))
            current_scene = {
                'start_sec': fa['timestamp_sec'],
                'end_sec': fa['timestamp_sec'] + interval_sec,
                'frames': [fa],
                'key_terms': new_terms,
            }

    # Don't forget the last scene
    scenes.append(finalize_scene(current_scene))

    # Merge short scenes into neighbors
    if len(scenes) > 1:
        merged = [scenes[0]]
        for s in scenes[1:]:
            prev = merged[-1]
            if prev['duration_sec'] < SCENE_MIN_DURATION_SEC or s['duration_sec'] < SCENE_MIN_DURATION_SEC:
                # Merge: extend previous scene
                prev['end_sec'] = s['end_sec']
                prev['duration_sec'] = round(prev['end_sec'] - prev['start_sec'], 1)
                prev['frame_count'] += s['frame_count']
                prev['all_descriptions'].extend(s['all_descriptions'])
                prev['key_terms'] = sorted(set(prev['key_terms']) | set(s['key_terms']))
            else:
                merged.append(s)
        scenes = merged

    return scenes


def finalize_scene(scene_data):
    """Create a clean scene object from accumulated data."""
    # Pick the most representative description (middle frame)
    mid_idx = len(scene_data['frames']) // 2
    representative = scene_data['frames'][mid_idx]['description']

    # Aggregate all descriptions for searchability
    all_descriptions = [f['description'] for f in scene_data['frames']]

    return {
        'start_sec': round(scene_data['start_sec'], 1),
        'end_sec': round(scene_data['end_sec'], 1),
        'duration_sec': round(scene_data['end_sec'] - scene_data['start_sec'], 1),
        'description': representative,
        'all_descriptions': all_descriptions,
        'key_terms': sorted(list(scene_data['key_terms'])),
        'frame_count': len(scene_data['frames']),
    }


# ── Timestamp formatting ─────────────────────────────────────────────────────

def fmt_time(seconds):
    """Format seconds as M:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def index_video(video_path, json_path, interval_sec, model, temp_base):
    """Full pipeline for one video: extract → analyze → scene detect → save."""
    name = os.path.splitext(os.path.basename(video_path))[0]
    print(f"\n{'='*60}")
    print(f"  Indexing: {os.path.basename(video_path)}")
    print(f"{'='*60}")

    # Extract frames
    frame_dir = os.path.join(temp_base, f"{name}_dense")
    frames, duration = extract_frames(video_path, frame_dir, interval_sec)
    if not frames:
        print(f"  No frames extracted.")
        return False

    print(f"  Extracted {len(frames)} frames ({fmt_time(duration)} video, every {interval_sec}s)")

    # Analyze each frame
    frame_analyses = []
    for i, frame_path in enumerate(frames):
        timestamp = i * interval_sec
        desc = analyze_frame(frame_path, model=model)
        frame_analyses.append({
            'frame_index': i,
            'timestamp_sec': timestamp,
            'timestamp_fmt': fmt_time(timestamp),
            'description': desc,
        })
        # Progress
        if (i + 1) % 10 == 0 or i == len(frames) - 1:
            print(f"  Analyzed {i+1}/{len(frames)} frames...")

    # Detect scenes
    scenes = detect_scenes(frame_analyses, interval_sec)
    print(f"  Detected {len(scenes)} scenes:")
    for s in scenes:
        print(f"    [{fmt_time(s['start_sec'])} - {fmt_time(s['end_sec'])}] "
              f"({s['frame_count']} frames) {s['description'][:80]}")

    # Update the JSON metadata
    try:
        with open(json_path, 'r') as f:
            metadata = json.load(f)
    except Exception:
        metadata = {}

    metadata['timeline'] = {
        'indexed_at': datetime.datetime.now().isoformat(),
        'interval_sec': interval_sec,
        'model': model,
        'total_frames_analyzed': len(frame_analyses),
        'scenes': scenes,
        'frame_analyses': frame_analyses,
    }

    with open(json_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved timeline to {os.path.basename(json_path)}")

    # Cleanup dense frames
    for frame in frames:
        try:
            os.remove(frame)
        except Exception:
            pass
    try:
        os.rmdir(frame_dir)
    except Exception:
        pass

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Dense frame indexing for video content search.')
    parser.add_argument('folder', help='Folder containing video files + JSON metadata')
    parser.add_argument('--interval', type=int, default=3,
                        help='Seconds between frame extractions (default: 3)')
    parser.add_argument('--model', type=str, default='llava:13b',
                        help='Ollama vision model (default: llava:13b)')
    parser.add_argument('--clip', type=str, default=None,
                        help='Process only this clip (by name, e.g. IMG_0223)')
    parser.add_argument('--skip-indexed', action='store_true',
                        help='Skip clips that already have timeline data')

    args = parser.parse_args()
    folder = os.path.abspath(args.folder)

    if not os.path.isdir(folder):
        print(f"Not a directory: {folder}")
        sys.exit(1)

    # Find video + JSON pairs
    video_exts = {'.mp4', '.mov', '.mkv', '.avi', '.webm'}
    pairs = []
    for f in sorted(os.listdir(folder)):
        ext = os.path.splitext(f.lower())[1]
        if ext not in video_exts:
            continue
        name = os.path.splitext(f)[0]
        video_path = os.path.join(folder, f)
        json_path = os.path.join(folder, f"{name}.json")

        if args.clip and name != args.clip:
            continue

        if not os.path.exists(json_path):
            print(f"  Skipping {f} (no JSON metadata)")
            continue

        if args.skip_indexed:
            try:
                with open(json_path, 'r') as jf:
                    data = json.load(jf)
                if 'timeline' in data:
                    print(f"  Skipping {f} (already indexed)")
                    continue
            except Exception:
                pass

        pairs.append((video_path, json_path))

    if not pairs:
        print("No videos to index.")
        sys.exit(0)

    # Create temp dir for frame extraction
    temp_base = tempfile.mkdtemp(prefix='vsplice_dense_')

    print(f"Indexing {len(pairs)} videos")
    print(f"  Interval: {args.interval}s")
    print(f"  Model: {args.model}")
    print(f"  Temp dir: {temp_base}")

    start_time = datetime.datetime.now()
    success = 0
    for video_path, json_path in pairs:
        try:
            if index_video(video_path, json_path, args.interval, args.model, temp_base):
                success += 1
        except Exception as e:
            print(f"  ERROR processing {os.path.basename(video_path)}: {e}")

    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    print(f"\n{'='*60}")
    print(f"  COMPLETE: {success}/{len(pairs)} videos indexed in {fmt_time(elapsed)}")
    print(f"{'='*60}")

    # Cleanup temp
    try:
        os.rmdir(temp_base)
    except Exception:
        pass


if __name__ == '__main__':
    main()
