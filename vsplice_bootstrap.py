#!/usr/bin/env python3
"""
vsplice-bootstrap: Populate visual_observations in JSON metadata using local LLaVA.

Replaces the sub-agent vision call with direct Ollama access. Zero API calls.

Usage:
    python vsplice_bootstrap.py <folder> [--model llava:13b] [--force]

This is idempotent — skips clips that already have visual_observations
unless --force is used.
"""

import os
import sys
import json
import argparse
import base64
import requests
from pathlib import Path


OLLAMA_URL = "http://localhost:11434/api/generate"

VISION_PROMPT = (
    "Analyze these 3 video frames (10%, 50%, 90% through the clip). "
    "For each frame, describe:\n"
    "- Environment: indoor/outdoor, location type, setting\n"
    "- Conditions: lighting, weather, time of day indicators\n"
    "- Activity: what's happening, movement, action\n"
    "- People: count and what they're doing\n"
    "- Vehicles: count and type\n"
    "- Animals: count and type\n\n"
    "Be specific and factual. Output a JSON object with these fields:\n"
    '{"environment": [...], "conditions": [...], "activity": [...], '
    '"people_detected": N, "vehicles_detected": N, "animals_detected": N, '
    '"confidence": "high"|"medium"|"low", "summary": "brief description"}'
)


def analyze_frames_local(frame_paths, model="llava:13b"):
    """Analyze 3 frames with local LLaVA. Returns parsed observations."""
    if len(frame_paths) != 3:
        print(f"  Expected 3 frames, got {len(frame_paths)}")
        return None

    # Load and base64 encode all 3 frames
    images_b64 = []
    for fp in frame_paths:
        try:
            with open(fp, 'rb') as f:
                images_b64.append(base64.b64encode(f.read()).decode())
        except Exception as e:
            print(f"  Failed to load {fp}: {e}")
            return None

    # Call LLaVA with all 3 images
    try:
        resp = requests.post(OLLAMA_URL, json={
            'model': model,
            'prompt': VISION_PROMPT,
            'images': images_b64,
            'stream': False,
            'options': {
                'num_predict': 500,
                'temperature': 0.2,
            }
        }, timeout=120)

        r = resp.json()
        response_text = r.get('response', '').strip()

        if not response_text:
            print(f"  Empty response from {model}")
            return None

        # Try to extract JSON from response
        import re
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                obs = json.loads(json_match.group())
                # Ensure expected fields
                obs.setdefault('environment', [])
                obs.setdefault('conditions', [])
                obs.setdefault('activity', [])
                obs.setdefault('people_detected', 0)
                obs.setdefault('vehicles_detected', 0)
                obs.setdefault('animals_detected', 0)
                obs.setdefault('confidence', 'medium')
                obs.setdefault('summary', response_text[:200])
                return obs
            except json.JSONDecodeError:
                print(f"  Could not parse JSON from response")
                return None
        else:
            print(f"  No JSON found in response")
            return None

    except Exception as e:
        print(f"  Error calling {model}: {e}")
        return None


def bootstrap_clip(json_path, frames_dir, model="llava:13b", force=False):
    """Analyze a single clip's frames and update its JSON."""
    # Load JSON
    try:
        with open(json_path, 'r') as f:
            metadata = json.load(f)
    except Exception as e:
        print(f"  Failed to load {json_path}: {e}")
        return False

    # Skip if already has observations (unless --force)
    if not force and metadata.get('visual_observations', {}).get('environment'):
        return True  # Already done

    # Find frame files
    frame_files = []
    for fname in ['frame_01.jpg', 'frame_02.jpg', 'frame_03.jpg']:
        fpath = os.path.join(frames_dir, fname)
        if os.path.exists(fpath):
            frame_files.append(fpath)

    if len(frame_files) != 3:
        print(f"  Only found {len(frame_files)}/3 frames in {frames_dir}")
        return False

    # Analyze
    obs = analyze_frames_local(frame_files, model=model)
    if not obs:
        print(f"  Analysis failed")
        return False

    # Update JSON
    metadata['visual_observations'] = obs
    metadata['confidence'] = obs.get('confidence', 'medium')

    # Add notes
    summary = obs.get('summary', '')
    if summary:
        metadata['notes'] = summary

    # Write back
    try:
        with open(json_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        return True
    except Exception as e:
        print(f"  Failed to write {json_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Bootstrap visual_observations using local LLaVA.')
    parser.add_argument('folder', help='Folder with video files + JSON metadata')
    parser.add_argument('--model', type=str, default='llava:13b',
                        help='Ollama vision model (default: llava:13b)')
    parser.add_argument('--force', action='store_true',
                        help='Re-analyze even if observations exist')

    args = parser.parse_args()
    folder = os.path.abspath(args.folder)

    if not os.path.isdir(folder):
        print(f"Not a directory: {folder}")
        sys.exit(1)

    # Find video + JSON pairs with frame directories
    video_exts = {'.mp4', '.mov', '.mkv', '.avi', '.webm'}
    clips_to_process = []

    for f in sorted(os.listdir(folder)):
        ext = os.path.splitext(f.lower())[1]
        if ext not in video_exts:
            continue

        name = os.path.splitext(f)[0]
        json_path = os.path.join(folder, f"{name}.json")
        frames_dir = os.path.join(folder, f"{name}.frames")

        if not os.path.exists(json_path):
            continue
        if not os.path.isdir(frames_dir):
            continue

        clips_to_process.append((name, json_path, frames_dir))

    if not clips_to_process:
        print("No clips with frame directories found.")
        sys.exit(0)

    print(f"Bootstrapping {len(clips_to_process)} clips with {args.model}")
    print(f"  (This will take ~10-20s per clip)")
    print()

    success = 0
    for name, json_path, frames_dir in clips_to_process:
        print(f"  {name}...", end=' ', flush=True)
        if bootstrap_clip(json_path, frames_dir, model=args.model, force=args.force):
            print("✓")
            success += 1
        else:
            print("✗")

    print(f"\n{success}/{len(clips_to_process)} clips bootstrapped")


if __name__ == '__main__':
    main()
