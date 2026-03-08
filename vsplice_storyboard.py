#!/usr/bin/env python3
"""
vsplice-storyboard: Generate, edit, and render storyboards.

A storyboard is the creative spine of V-Splice — an ordered sequence of
scenes, each fulfilled by found footage, generated assets, or both.

Usage:
    # Generate storyboard from a query (search mode)
    python vsplice_storyboard.py generate <folder> "Segway day" [--output story.json]

    # Generate from a narrative (story mode — Phase 3)
    python vsplice_storyboard.py narrate <folder> "A summer day unboxing and riding a Segway"

    # Render a storyboard to video
    python vsplice_storyboard.py render <storyboard.json> [--style cinematic|clean|montage]

    # List scenes in a storyboard
    python vsplice_storyboard.py show <storyboard.json>
"""

import os
import sys
import json
import argparse
import datetime
import subprocess
import shutil
import tempfile
import re
from pathlib import Path

from vsplice_query import (
    load_clip_metadata, expand_query, auto_search, dense_search,
    coarse_search, get_video_path, fmt_time,
)


# ── Storyboard Generation (from query) ───────────────────────────────────────

def generate_storyboard_from_query(folder, query, results, title=None):
    """Convert search results into a storyboard."""
    # Sort chronologically
    chrono = sorted(results,
                    key=lambda r: r['clip'].get('capture', {}).get('captured_at', ''))

    scenes = []
    scene_num = 0

    for r in chrono:
        clip = r['clip']
        video_path = get_video_path(clip)
        if not video_path:
            continue

        for seg in r['segments']:
            scene_num += 1
            start = seg.get('start_sec', 0)
            end = seg.get('end_sec', clip['file'].get('duration_sec', 0))
            duration = end - start

            scenes.append({
                'id': f'scene_{scene_num:02d}',
                'order': scene_num,
                'intent': seg.get('description', '')[:200],
                'search_query': query,
                'duration_target_sec': round(duration, 1),
                'duration_min_sec': round(max(2, duration * 0.5), 1),
                'duration_max_sec': round(duration * 1.5, 1),
                'source': 'found',
                'assets': [{
                    'type': 'footage',
                    'file': video_path,
                    'start_sec': round(start, 1),
                    'end_sec': round(end, 1),
                    'description': seg.get('description', ''),
                    'score': seg.get('score', r['score']),
                    'matched_terms': seg.get('matched', r['matched_terms']),
                }],
                'style': {
                    'transition_in': 'cut' if scene_num == 1 else 'crossfade',
                    'transition_out': 'crossfade',
                    'transition_duration_sec': 0.5,
                    'speed': 1.0,
                    'effects': [],
                    'text_overlay': None,
                },
                'generation_prompt': None,
                'generation_params': None,
                'status': 'fulfilled',
            })

    # Calculate total duration
    total_dur = sum(s['duration_target_sec'] for s in scenes)

    storyboard = {
        'schema_version': '0.1',
        'title': title or f'V-Splice: {query}',
        'created_at': datetime.datetime.now().isoformat(),
        'author': 'query',
        'narrative': {
            'summary': f'Auto-generated from search: "{query}"',
            'tone': None,
            'duration_target_sec': round(total_dur, 1),
            'music_style': None,
        },
        'sources': {
            'footage_folders': [folder],
            'generation_backends': [],
        },
        'scenes': scenes,
        'assembly': {
            'output_resolution': '1920x1080',
            'output_fps': 30,
            'output_codec': 'h264_nvenc',
            'color_grade': 'match_source',
            'audio_track': None,
            'audio_ducking': True,
        },
        'metadata': {
            'generated_by': 'vsplice_storyboard',
            'query': query,
            'footage_clips_searched': len(set(r['clip']['file']['name'] for r in results)),
            'scenes_total': len(scenes),
            'scenes_found': len(scenes),
            'scenes_generated': 0,
            'scenes_pending': 0,
        },
    }

    return storyboard


# ── Storyboard Rendering ─────────────────────────────────────────────────────

STYLE_PRESETS = {
    'clean': {
        'description': 'Straight cuts, no effects, original speed',
        'defaults': {
            'speed': 1.0,
            'transition': 'cut',
            'transition_duration': 0.0,
            'effects': [],
        }
    },
    'crossfade': {
        'description': 'Smooth crossfades between scenes',
        'defaults': {
            'speed': 1.0,
            'transition': 'crossfade',
            'transition_duration': 0.5,
            'effects': [],
        }
    },
    'cinematic': {
        'description': 'Crossfades, subtle speed ramps, slight zoom',
        'defaults': {
            'speed': 1.0,
            'transition': 'crossfade',
            'transition_duration': 0.75,
            'effects': ['slight_zoom', 'color_grade'],
        }
    },
    'montage': {
        'description': 'Fast cuts, speed variations, energetic',
        'defaults': {
            'speed': 1.3,
            'transition': 'cut',
            'transition_duration': 0.0,
            'effects': ['speed_ramp'],
        }
    },
}


def render_storyboard(storyboard, output_dir, style='clean', merge_adjacent=True):
    """Render a storyboard to a final video file."""
    scenes = [s for s in storyboard['scenes'] if s['status'] == 'fulfilled']
    if not scenes:
        print("No fulfilled scenes to render.")
        return None

    # Merge adjacent segments from same file
    if merge_adjacent:
        scenes = merge_adjacent_scenes(scenes)

    style_preset = STYLE_PRESETS.get(style, STYLE_PRESETS['clean'])
    assembly = storyboard.get('assembly', {})

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    title_slug = re.sub(r'[^a-zA-Z0-9_-]', '_', storyboard.get('title', 'output'))[:30]
    output_name = f"{title_slug}_{style}_{ts}.mp4"
    output_path = os.path.join(output_dir, output_name)

    temp_dir = tempfile.mkdtemp(prefix='vsplice_render_')
    segment_files = []

    target_res = assembly.get('output_resolution', '1920x1080')
    target_w, target_h = target_res.split('x')

    print(f"\nRendering storyboard: {storyboard.get('title', 'Untitled')}")
    print(f"  Style: {style} — {style_preset['description']}")
    print(f"  Scenes: {len(scenes)}")
    print(f"  Resolution: {target_res}")
    print()

    for i, scene in enumerate(scenes):
        asset = scene['assets'][0]  # Primary asset
        if asset['type'] != 'footage':
            print(f"  [{i+1}] Skipping {scene['id']} — generation not yet supported")
            continue

        seg_file = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
        start = asset.get('start_sec', 0)
        end = asset.get('end_sec', 0)
        duration = end - start
        speed = scene.get('style', {}).get('speed', style_preset['defaults']['speed'])

        # Build ffmpeg command for this segment
        cmd = ['ffmpeg', '-y']

        # Input with seek
        if start > 0:
            cmd.extend(['-ss', str(start)])
        cmd.extend(['-i', asset['file']])
        if duration > 0:
            cmd.extend(['-t', str(duration)])

        # Video filters
        vf_parts = []

        # Scale to target resolution
        vf_parts.append(
            f'scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,'
            f'pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2'
        )

        # Speed adjustment
        if speed != 1.0:
            vf_parts.append(f'setpts={1.0/speed}*PTS')

        # Effects
        effects = scene.get('style', {}).get('effects', style_preset['defaults']['effects'])
        if 'slight_zoom' in effects:
            # Ken Burns style subtle zoom
            vf_parts.append(
                f'scale={int(int(target_w)*1.05)}:{int(int(target_h)*1.05)},'
                f'crop={target_w}:{target_h}'
            )

        vf = ','.join(vf_parts)

        cmd.extend(['-vf', vf])

        # Audio
        af_parts = []
        if speed != 1.0:
            af_parts.append(f'atempo={speed}')
        if af_parts:
            cmd.extend(['-af', ','.join(af_parts)])

        # Encoding
        codec = assembly.get('output_codec', 'h264_nvenc')
        if codec == 'h264_nvenc':
            cmd.extend(['-vcodec', 'h264_nvenc', '-cq', '23', '-preset', 'p4'])
        else:
            cmd.extend(['-vcodec', 'libx264', '-crf', '23', '-preset', 'fast'])

        cmd.extend([
            '-acodec', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-r', str(assembly.get('output_fps', 30)),
            seg_file
        ])

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and os.path.exists(seg_file):
            segment_files.append(seg_file)
            print(f"  [{i+1}/{len(scenes)}] {scene['id']}: "
                  f"{os.path.basename(asset['file'])} "
                  f"[{fmt_time(start)}-{fmt_time(end)}] "
                  f"{'@'+str(speed)+'x ' if speed != 1.0 else ''}"
                  f"✓")
        else:
            stderr = result.stderr.decode(errors='replace')[-300:]
            print(f"  [{i+1}/{len(scenes)}] {scene['id']}: FAILED — {stderr}")

    if not segment_files:
        print("\nNo segments rendered successfully.")
        cleanup_dir(temp_dir)
        return None

    # Concatenate
    print(f"\n  Joining {len(segment_files)} segments...")

    transition = style_preset['defaults']['transition']
    trans_dur = style_preset['defaults']['transition_duration']

    if transition == 'crossfade' and trans_dur > 0 and len(segment_files) > 1:
        output_path = concat_with_crossfade(segment_files, output_path, trans_dur,
                                             assembly)
    else:
        output_path = concat_stream_copy(segment_files, output_path)

    cleanup_dir(temp_dir)

    if output_path and os.path.exists(output_path):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        dur = get_duration(output_path)
        print(f"\n  ✅ Output: {output_path}")
        print(f"     Size: {size_mb:.1f} MB | Duration: {fmt_time(dur or 0)}")
        return output_path

    return None


def merge_adjacent_scenes(scenes):
    """Merge consecutive scenes from the same source file with adjacent timestamps."""
    if len(scenes) <= 1:
        return scenes

    merged = [scenes[0].copy()]
    for scene in scenes[1:]:
        prev = merged[-1]
        prev_asset = prev['assets'][0]
        curr_asset = scene['assets'][0]

        # Same file and timestamps are close (within 30 seconds gap)?
        same_file = prev_asset.get('file') == curr_asset.get('file')
        gap = curr_asset.get('start_sec', 0) - prev_asset.get('end_sec', 0)
        adjacent = same_file and 0 <= gap <= 30

        if same_file and adjacent:
            # Extend previous scene
            prev_asset['end_sec'] = curr_asset['end_sec']
            new_dur = prev_asset['end_sec'] - prev_asset['start_sec']
            prev['duration_target_sec'] = round(new_dur, 1)
            # Combine descriptions
            if curr_asset.get('description') and curr_asset['description'] != prev_asset.get('description'):
                prev_asset['description'] = (
                    prev_asset.get('description', '') + ' → ' +
                    curr_asset.get('description', '')
                )[:200]
            # Merge matched terms
            prev_terms = set(prev_asset.get('matched_terms', []))
            curr_terms = set(curr_asset.get('matched_terms', []))
            prev_asset['matched_terms'] = sorted(prev_terms | curr_terms)
            prev_asset['score'] = max(prev_asset.get('score', 0), curr_asset.get('score', 0))
        else:
            merged.append(scene.copy())

    # Renumber
    for i, s in enumerate(merged, 1):
        s['order'] = i
        s['id'] = f'scene_{i:02d}'

    return merged


def concat_stream_copy(segment_files, output_path):
    """Simple stream-copy concat."""
    temp_dir = tempfile.mkdtemp()
    concat_path = os.path.join(temp_dir, 'concat.txt')
    with open(concat_path, 'w') as f:
        for sf in segment_files:
            f.write(f"file '{sf}'\n")

    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', concat_path,
        '-c', 'copy',
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    cleanup_dir(temp_dir)

    if result.returncode != 0:
        print(f"  Concat failed: {result.stderr.decode(errors='replace')[-300:]}")
        return None
    return output_path


def concat_with_crossfade(segment_files, output_path, crossfade_sec, assembly):
    """Concat with crossfade transitions between segments."""
    # For crossfade we need to re-encode through a filter chain
    # Build complex filter graph
    if len(segment_files) <= 1:
        return concat_stream_copy(segment_files, output_path)

    # Get durations
    durations = []
    for sf in segment_files:
        dur = get_duration(sf)
        if dur:
            durations.append(dur)
        else:
            durations.append(10)  # fallback

    # Build xfade filter chain
    inputs = []
    for sf in segment_files:
        inputs.extend(['-i', sf])

    # Video xfade chain
    filter_parts = []
    current_label = '[0:v]'
    current_duration = durations[0]

    for i in range(1, len(segment_files)):
        next_label = f'[{i}:v]'
        offset = max(0, current_duration - crossfade_sec)
        out_label = f'[v{i}]' if i < len(segment_files) - 1 else '[vout]'

        filter_parts.append(
            f'{current_label}{next_label}xfade=transition=fade:'
            f'duration={crossfade_sec}:offset={offset}{out_label}'
        )
        current_label = out_label
        current_duration = current_duration + durations[i] - crossfade_sec

    # Audio crossfade chain
    current_alabel = '[0:a]'
    for i in range(1, len(segment_files)):
        next_alabel = f'[{i}:a]'
        out_alabel = f'[a{i}]' if i < len(segment_files) - 1 else '[aout]'

        filter_parts.append(
            f'{current_alabel}{next_alabel}acrossfade=d={crossfade_sec}:'
            f'c1=tri:c2=tri{out_alabel}'
        )
        current_alabel = out_alabel

    filter_graph = ';'.join(filter_parts)

    cmd = ['ffmpeg', '-y'] + inputs + [
        '-filter_complex', filter_graph,
        '-map', '[vout]', '-map', '[aout]',
        '-vcodec', 'h264_nvenc', '-cq', '23', '-preset', 'p4',
        '-acodec', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # Fall back to stream copy
        print(f"  Crossfade failed, falling back to clean cuts...")
        return concat_stream_copy(segment_files, output_path)

    return output_path


def get_duration(video_path):
    """Get video duration via ffprobe."""
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
           '-show_format', video_path]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return None
    try:
        info = json.loads(result.stdout)
        return float(info['format']['duration'])
    except (json.JSONDecodeError, KeyError):
        return None


def cleanup_dir(d):
    try:
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        os.rmdir(d)
    except Exception:
        pass


# ── Display ───────────────────────────────────────────────────────────────────

def show_storyboard(storyboard):
    """Pretty-print a storyboard."""
    title = storyboard.get('title', 'Untitled')
    narrative = storyboard.get('narrative', {})
    meta = storyboard.get('metadata', {})
    scenes = storyboard.get('scenes', [])

    total_dur = sum(s.get('duration_target_sec', 0) for s in scenes)
    found = sum(1 for s in scenes if s.get('source') == 'found')
    gen = sum(1 for s in scenes if s.get('source') == 'generate')
    pending = sum(1 for s in scenes if s.get('status') == 'pending')

    print(f"\n{'='*70}")
    print(f"  📽️  {title}")
    print(f"{'='*70}")
    if narrative.get('summary'):
        print(f"  {narrative['summary']}")
    print(f"  Duration: ~{fmt_time(total_dur)} | "
          f"Scenes: {len(scenes)} ({found} found, {gen} generated, {pending} pending)")
    print(f"{'='*70}")

    for s in scenes:
        asset = s['assets'][0] if s.get('assets') else {}
        source_icon = '🎬' if s.get('source') == 'found' else '🎨'
        status_icon = {'fulfilled': '✅', 'pending': '⏳', 'failed': '❌',
                       'searching': '🔍', 'generating': '⚙️'}.get(s.get('status'), '❓')

        print(f"\n  {s.get('order', '?')}. {source_icon} {s.get('id', '?')} {status_icon}")
        print(f"     Intent:   {s.get('intent', '')[:80]}")

        if asset.get('file'):
            fname = os.path.basename(asset['file'])
            start = asset.get('start_sec', 0)
            end = asset.get('end_sec', 0)
            print(f"     Source:   {fname} [{fmt_time(start)}-{fmt_time(end)}]")
            print(f"     Score:    {asset.get('score', 0):.1f} | "
                  f"Matched: {', '.join(asset.get('matched_terms', []))}")

        style = s.get('style', {})
        style_parts = []
        if style.get('speed', 1.0) != 1.0:
            style_parts.append(f"{style['speed']}x speed")
        if style.get('transition_in') and style['transition_in'] != 'cut':
            style_parts.append(f"↦ {style['transition_in']}")
        if style.get('effects'):
            style_parts.append(f"fx: {', '.join(style['effects'])}")
        if style_parts:
            print(f"     Style:    {' | '.join(style_parts)}")

        if s.get('generation_prompt'):
            print(f"     GenPrompt: {s['generation_prompt'][:80]}...")

    print(f"\n{'='*70}\n")


# ── Save / Load ───────────────────────────────────────────────────────────────

def save_storyboard(storyboard, path):
    """Save storyboard to JSON file."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as f:
        json.dump(storyboard, f, indent=2)
    print(f"Saved storyboard → {path}")


def load_storyboard(path):
    """Load storyboard from JSON file."""
    with open(path, 'r') as f:
        return json.load(f)


# ── Main CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='V-Splice Storyboard Engine')
    sub = parser.add_subparsers(dest='command', required=True)

    # generate
    gen_p = sub.add_parser('generate', help='Generate storyboard from search query')
    gen_p.add_argument('folder', help='Folder with video files + JSON metadata')
    gen_p.add_argument('query', help='Search query')
    gen_p.add_argument('--title', type=str, default=None)
    gen_p.add_argument('--output', '-o', type=str, default=None,
                       help='Output storyboard path')
    gen_p.add_argument('--min-score', type=float, default=1.0)
    gen_p.add_argument('--top', type=int, default=None)
    gen_p.add_argument('--mode', choices=['coarse', 'dense', 'auto'], default='auto')
    gen_p.add_argument('--merge', action='store_true', default=True,
                       help='Merge adjacent segments (default: on)')

    # show
    show_p = sub.add_parser('show', help='Display storyboard contents')
    show_p.add_argument('storyboard', help='Path to storyboard JSON')

    # render
    render_p = sub.add_parser('render', help='Render storyboard to video')
    render_p.add_argument('storyboard', help='Path to storyboard JSON')
    render_p.add_argument('--style', choices=list(STYLE_PRESETS.keys()),
                          default='crossfade',
                          help='Render style preset')
    render_p.add_argument('--output-dir', '-o', type=str, default=None)
    render_p.add_argument('--no-merge', action='store_true',
                          help='Don\'t merge adjacent segments')

    args = parser.parse_args()

    if args.command == 'generate':
        folder = os.path.abspath(args.folder)
        clips = load_clip_metadata(folder)
        if not clips:
            print("No clip metadata found.")
            sys.exit(1)

        original_terms, expanded_terms = expand_query(args.query)
        print(f"Searching {len(clips)} clips for: \"{args.query}\"")

        if args.mode == 'coarse':
            results = coarse_search(clips, expanded_terms, args.min_score)
        elif args.mode == 'dense':
            results = dense_search(clips, expanded_terms, args.min_score)
        else:
            results = auto_search(clips, expanded_terms, args.min_score)

        if args.top:
            results = results[:args.top]

        if not results:
            print("No matches found.")
            sys.exit(0)

        storyboard = generate_storyboard_from_query(folder, args.query, results,
                                                     title=args.title)

        # Merge adjacent if requested
        if args.merge:
            storyboard['scenes'] = merge_adjacent_scenes(storyboard['scenes'])
            storyboard['metadata']['scenes_total'] = len(storyboard['scenes'])
            storyboard['metadata']['scenes_found'] = len(storyboard['scenes'])

        show_storyboard(storyboard)

        # Save
        if args.output:
            save_storyboard(storyboard, args.output)
        else:
            sb_dir = os.path.join(folder, 'storyboards')
            os.makedirs(sb_dir, exist_ok=True)
            safe_q = re.sub(r'[^a-zA-Z0-9_-]', '_', args.query)[:30]
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            sb_path = os.path.join(sb_dir, f"{safe_q}_{ts}.storyboard.json")
            save_storyboard(storyboard, sb_path)

    elif args.command == 'show':
        storyboard = load_storyboard(args.storyboard)
        show_storyboard(storyboard)

    elif args.command == 'render':
        storyboard = load_storyboard(args.storyboard)
        show_storyboard(storyboard)

        output_dir = args.output_dir or os.path.dirname(args.storyboard) or '.'
        merge = not args.no_merge
        render_storyboard(storyboard, output_dir, style=args.style,
                          merge_adjacent=merge)


if __name__ == '__main__':
    main()
