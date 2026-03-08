#!/usr/bin/env python3
"""
vsplice-query: Search video clips by content and splice matching segments.

Supports two modes:
  - Coarse: matches whole clips based on visual_observations (always available)
  - Dense:  matches scenes within clips using timeline data (when indexed)

Usage:
    python vsplice_query.py <folder> <query> [--dry-run] [--top N] [--mode coarse|dense|auto]

Examples:
    python vsplice_query.py ./test "Segway riding outdoor"
    python vsplice_query.py ./test "unboxing" --dry-run
    python vsplice_query.py ./test "garage tools" --mode coarse --top 5
"""

import os
import sys
import json
import argparse
import datetime
import subprocess
import re
import shutil
from pathlib import Path


# ── Synonym Expansion ─────────────────────────────────────────────────────────

SYNONYMS = {
    'segway': ['segway', 'ninebot', 'hoverboard', 'scooter', 'self-balancing', 'electric-scooter'],
    'riding': ['riding', 'ride', 'testing', 'stepping', 'driving'],
    'unboxing': ['unboxing', 'unpacking', 'box', 'packaging', 'foam', 'cardboard'],
    'assembly': ['assembly', 'assembling', 'bolts', 'hex', 'bracket', 'hardware', 'wrench'],
    'garage': ['garage', 'workshop', 'indoor', 'workbench'],
    'outdoor': ['outdoor', 'driveway', 'yard', 'outside'],
    'tools': ['tools', 'tool', 'wrench', 'compressor', 'pegboard', 'drill', 'clamp'],
    'car': ['car', 'vehicle', 'suv', 'sedan', 'truck', 'utv'],
    'person': ['person', 'man', 'male', 'adult', 'helmet'],
    'backyard': ['backyard', 'yard', 'lawn', 'garden', 'deck'],
    'trailer': ['trailer', 'rv', 'travel-trailer', 'camper'],
}


def expand_query(query):
    """Expand query terms with synonyms. Returns (original_terms, expanded_terms)."""
    original = re.findall(r'\w+', query.lower())
    expanded = set(original)
    for term in original:
        if term in SYNONYMS:
            expanded.update(SYNONYMS[term])
    return original, list(expanded)


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_text(text, terms):
    """Score a text blob against a list of search terms."""
    text_lower = text.lower()
    score = 0
    matched = set()
    for term in terms:
        count = text_lower.count(term.lower())
        if count > 0:
            score += count
            matched.add(term)
    # Bonus for matching multiple different terms
    if len(matched) > 1:
        score += len(matched) * 2
    return score, matched


# ── Coarse Search (whole clip) ────────────────────────────────────────────────

def coarse_search(clips, terms, min_score=0.5):
    """Search clips at the whole-clip level using visual_observations."""
    results = []
    for clip in clips:
        obs = clip.get('visual_observations', {})
        notes = clip.get('notes', '') or ''

        # Build searchable text
        parts = [notes]
        for field in ['environment', 'conditions', 'activity']:
            vals = obs.get(field, [])
            if isinstance(vals, list):
                parts.extend(vals)
            elif isinstance(vals, str):
                parts.append(vals)

        text = ' '.join(parts)
        score, matched = score_text(text, terms)

        # Confidence multiplier
        conf = clip.get('confidence', 'low')
        if conf == 'high':
            score *= 1.2
        elif conf == 'low':
            score *= 0.5

        if score >= min_score:
            results.append({
                'clip': clip,
                'score': score,
                'matched_terms': sorted(matched),
                'mode': 'coarse',
                'segments': [{
                    'start_sec': 0,
                    'end_sec': clip['file'].get('duration_sec', 0),
                    'description': notes[:120] if notes else '(whole clip)',
                }],
            })

    results.sort(key=lambda r: (-r['score'],
                                 r['clip'].get('capture', {}).get('captured_at', '')))
    return results


# ── Dense Search (scene level) ────────────────────────────────────────────────

def dense_search(clips, terms, min_score=1.0):
    """Search within clip timelines at the scene level."""
    results = []

    for clip in clips:
        timeline = clip.get('timeline', {})
        scenes = timeline.get('scenes', [])
        if not scenes:
            continue

        clip_segments = []
        clip_score = 0
        clip_matched = set()

        for scene in scenes:
            # Search against scene description + all_descriptions + key_terms
            text_parts = [scene.get('description', '')]
            text_parts.extend(scene.get('all_descriptions', []))
            text_parts.extend(scene.get('key_terms', []))
            text = ' '.join(text_parts)

            score, matched = score_text(text, terms)

            if score >= min_score:
                clip_segments.append({
                    'start_sec': scene['start_sec'],
                    'end_sec': scene['end_sec'],
                    'duration_sec': scene['duration_sec'],
                    'score': score,
                    'matched': sorted(matched),
                    'description': scene['description'][:120],
                })
                clip_score += score
                clip_matched |= matched

        if clip_segments:
            results.append({
                'clip': clip,
                'score': clip_score,
                'matched_terms': sorted(clip_matched),
                'mode': 'dense',
                'segments': clip_segments,
            })

    # Sort by total score desc, then capture time
    results.sort(key=lambda r: (-r['score'],
                                 r['clip'].get('capture', {}).get('captured_at', '')))
    return results


# ── Auto Mode ─────────────────────────────────────────────────────────────────

def auto_search(clips, terms, min_score=0.5):
    """Use dense search where timeline exists, coarse for the rest."""
    dense_clips = [c for c in clips if c.get('timeline', {}).get('scenes')]
    coarse_clips = [c for c in clips if not c.get('timeline', {}).get('scenes')]

    results = []
    if dense_clips:
        results.extend(dense_search(dense_clips, terms, min_score))
    if coarse_clips:
        results.extend(coarse_search(coarse_clips, terms, min_score))

    results.sort(key=lambda r: (-r['score'],
                                 r['clip'].get('capture', {}).get('captured_at', '')))
    return results


# ── File I/O ──────────────────────────────────────────────────────────────────

def load_clip_metadata(folder):
    """Load all JSON metadata files from a folder."""
    clips = []
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith('.json') or f == 'manifest.json':
            continue
        path = os.path.join(folder, f)
        try:
            with open(path, 'r') as fh:
                data = json.load(fh)
            if 'file' in data:
                data['_json_path'] = path
                data['_folder'] = folder
                clips.append(data)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Skipping {f}: {e}")
    return clips


def get_video_path(clip):
    """Resolve the actual video file path."""
    folder = clip['_folder']
    filename = clip['file']['name']
    path = os.path.join(folder, filename)
    if os.path.exists(path):
        return path
    for f in os.listdir(folder):
        if f.lower() == filename.lower():
            return os.path.join(folder, f)
    return None


# ── Cut List Generation ──────────────────────────────────────────────────────

def generate_cut_list(results):
    """Generate chronologically ordered cut list with segment-level precision."""
    # Sort by capture time
    chrono = sorted(results,
                    key=lambda r: r['clip'].get('capture', {}).get('captured_at', ''))

    cut_list = []
    for r in chrono:
        clip = r['clip']
        video_path = get_video_path(clip)
        if not video_path:
            print(f"  WARNING: Video not found: {clip['file']['name']}")
            continue

        for seg in r['segments']:
            cut_list.append({
                'file': video_path,
                'name': clip['file']['name'],
                'start_sec': seg['start_sec'],
                'end_sec': seg['end_sec'],
                'duration': seg.get('duration_sec', seg['end_sec'] - seg['start_sec']),
                'captured_at': clip.get('capture', {}).get('captured_at', 'unknown'),
                'score': seg.get('score', r['score']),
                'matched': seg.get('matched', r['matched_terms']),
                'description': seg.get('description', ''),
                'mode': r['mode'],
            })

    return cut_list


# ── Splicing ──────────────────────────────────────────────────────────────────

def splice_segments(cut_list, output_dir, query_slug):
    """Splice cut list segments together using ffmpeg."""
    if not cut_list:
        print("Nothing to splice.")
        return None

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '_', query_slug)[:30]
    output_name = f"query_{safe_slug}_{ts}.mp4"
    output_path = os.path.join(output_dir, output_name)

    # Check if we have segment-level cuts (not just whole clips)
    has_segments = any(
        item['start_sec'] > 0 or
        item['end_sec'] < item.get('_full_duration', float('inf'))
        for item in cut_list
    )

    # For dense mode with segments: extract each segment first, then concat
    # For coarse mode (whole clips): direct concat
    is_dense = any(item['mode'] == 'dense' for item in cut_list)

    if is_dense:
        return splice_with_segments(cut_list, output_path)
    else:
        return splice_whole_clips(cut_list, output_path)


def splice_with_segments(cut_list, output_path):
    """Extract specific segments from clips, then concat."""
    import tempfile
    temp_dir = tempfile.mkdtemp(prefix='vsplice_cut_')
    segment_files = []

    print(f"Extracting {len(cut_list)} segments...")
    for i, item in enumerate(cut_list):
        seg_file = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
        start = item['start_sec']
        duration = item['end_sec'] - item['start_sec']

        # Use ffmpeg to extract segment (stream copy for speed)
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(start),
            '-i', item['file'],
            '-t', str(duration),
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            seg_file
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and os.path.exists(seg_file):
            segment_files.append(seg_file)
            print(f"  [{i+1}/{len(cut_list)}] {item['name']} "
                  f"[{fmt_time(start)}-{fmt_time(item['end_sec'])}]")
        else:
            print(f"  FAILED: {item['name']} segment {fmt_time(start)}-{fmt_time(item['end_sec'])}")

    if not segment_files:
        print("No segments extracted successfully.")
        return None

    # Concat all segments
    if len(segment_files) == 1:
        shutil.copy(segment_files[0], output_path)
    else:
        concat_path = os.path.join(temp_dir, 'concat.txt')
        with open(concat_path, 'w') as f:
            for sf in segment_files:
                f.write(f"file '{sf}'\n")

        # Try stream copy first
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', concat_path,
            '-c', 'copy',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True)

        if result.returncode != 0:
            # Re-encode if mixed formats
            print("  Stream copy failed, re-encoding...")
            cmd = [
                'ffmpeg', '-y',
                '-f', 'concat', '-safe', '0',
                '-i', concat_path,
                '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,'
                       'pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
                '-vcodec', 'h264_nvenc', '-cq', '23', '-preset', 'p4',
                '-acodec', 'aac', '-b:a', '192k',
                '-pix_fmt', 'yuv420p',
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                stderr = result.stderr.decode(errors='replace')[-500:]
                print(f"  Splice failed: {stderr}")
                cleanup_temp(temp_dir, segment_files)
                return None

    cleanup_temp(temp_dir, segment_files)
    print(f"Done → {output_path}")
    return output_path


def splice_whole_clips(cut_list, output_path):
    """Concat whole clips (coarse mode)."""
    import tempfile
    temp_dir = tempfile.mkdtemp(prefix='vsplice_cut_')

    if len(cut_list) == 1:
        shutil.copy(cut_list[0]['file'], output_path)
        print(f"Single clip → {output_path}")
        return output_path

    concat_path = os.path.join(temp_dir, 'concat.txt')
    with open(concat_path, 'w') as f:
        for item in cut_list:
            escaped = item['file'].replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    print(f"Splicing {len(cut_list)} clips...")
    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', concat_path,
        '-c', 'copy',
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True)

    if result.returncode != 0:
        print("  Stream copy failed, re-encoding...")
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', concat_path,
            '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,'
                   'pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
            '-vcodec', 'h264_nvenc', '-cq', '23', '-preset', 'p4',
            '-acodec', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            stderr = result.stderr.decode(errors='replace')[-500:]
            print(f"  Splice failed: {stderr}")
            cleanup_temp(temp_dir, [])
            return None

    cleanup_temp(temp_dir, [])
    print(f"Done → {output_path}")
    return output_path


def cleanup_temp(temp_dir, files):
    for f in files:
        try:
            os.remove(f)
        except Exception:
            pass
    try:
        # Remove any remaining files
        for f in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, f))
            except Exception:
                pass
        os.rmdir(temp_dir)
    except Exception:
        pass


# ── Display ───────────────────────────────────────────────────────────────────

def fmt_time(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def print_cut_list(cut_list, query):
    """Pretty-print the cut list."""
    total_duration = sum(item['duration'] for item in cut_list)
    dense_count = sum(1 for item in cut_list if item['mode'] == 'dense')
    coarse_count = sum(1 for item in cut_list if item['mode'] == 'coarse')

    print(f"\n{'='*70}")
    print(f"  QUERY: \"{query}\"")
    print(f"  RESULTS: {len(cut_list)} segments "
          f"({dense_count} precise, {coarse_count} whole-clip)")
    print(f"{'='*70}")

    for i, item in enumerate(cut_list, 1):
        dur = item['duration']
        is_segment = item['mode'] == 'dense'
        time_range = (f"[{fmt_time(item['start_sec'])}-{fmt_time(item['end_sec'])}]"
                      if is_segment else "[full]")

        print(f"\n  {i}. {item['name']} {time_range}")
        print(f"     Captured: {item['captured_at']}")
        print(f"     Duration: {fmt_time(dur)} | Score: {item['score']:.1f} | "
              f"Mode: {item['mode']}")
        print(f"     Matched:  {', '.join(item['matched'])}")
        if item['description']:
            print(f"     Content:  {item['description'][:100]}")

    print(f"\n{'='*70}")
    print(f"  TOTAL: {len(cut_list)} segments, {fmt_time(total_duration)}")
    print(f"{'='*70}\n")


# ── Stats ─────────────────────────────────────────────────────────────────────

def print_index_stats(clips):
    """Show how many clips have dense vs coarse metadata."""
    dense = sum(1 for c in clips if c.get('timeline', {}).get('scenes'))
    coarse = sum(1 for c in clips if c.get('visual_observations') and not c.get('timeline', {}).get('scenes'))
    empty = len(clips) - dense - coarse
    print(f"  Index: {dense} dense, {coarse} coarse-only, {empty} no metadata")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Search video clips by content and splice matches.')
    parser.add_argument('folder', help='Folder with video files + JSON metadata')
    parser.add_argument('query', help='Natural language search query')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show cut list without splicing')
    parser.add_argument('--top', type=int, default=None,
                        help='Limit to top N results')
    parser.add_argument('--min-score', type=float, default=0.5,
                        help='Minimum relevance score (default: 0.5)')
    parser.add_argument('--mode', choices=['coarse', 'dense', 'auto'],
                        default='auto',
                        help='Search mode (default: auto)')

    args = parser.parse_args()
    folder = os.path.abspath(args.folder)

    if not os.path.isdir(folder):
        print(f"Not a directory: {folder}")
        sys.exit(1)

    # Load
    print(f"Loading metadata from {folder}...")
    clips = load_clip_metadata(folder)
    if not clips:
        print("No clip metadata found.")
        sys.exit(1)
    print(f"Found {len(clips)} clips.")
    print_index_stats(clips)

    # Expand query
    original_terms, expanded_terms = expand_query(args.query)
    print(f"Searching: \"{args.query}\"")
    if len(expanded_terms) > len(original_terms):
        extra = set(expanded_terms) - set(original_terms)
        print(f"  + synonyms: {', '.join(sorted(extra))}")

    # Search
    if args.mode == 'coarse':
        results = coarse_search(clips, expanded_terms, args.min_score)
    elif args.mode == 'dense':
        results = dense_search(clips, expanded_terms, args.min_score)
    else:
        results = auto_search(clips, expanded_terms, args.min_score)

    if not results:
        print("No matching clips found.")
        sys.exit(0)

    if args.top:
        results = results[:args.top]

    # Cut list
    cut_list = generate_cut_list(results)
    print_cut_list(cut_list, args.query)

    if args.dry_run:
        print("(Dry run — no video output)")
        return

    # Splice
    output = splice_segments(cut_list, folder, args.query)
    if output:
        size_mb = os.path.getsize(output) / (1024 * 1024)
        print(f"\nOutput: {output} ({size_mb:.1f} MB)")


if __name__ == '__main__':
    main()
