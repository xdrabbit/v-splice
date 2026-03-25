#!/usr/bin/env python3
"""vsplice_gentle.py – Video joiner with subtle crossfade and very subtle Ken Burns zoom.

No speed changes, no reverse, no stutter, no audio effects.
Ken Burns: scale up slightly (zoom_max), then slowly pan the crop window across
the clip so the zoom-headroom is used as gentle motion. Default zoom_max=1.04
means you always see ≥96 % of the original frame.
"""
import os
import sys
import shutil
import datetime
import tempfile
import threading
import concurrent.futures

import ffmpeg

# Maximum fraction of the shortest clip's duration used as crossfade to prevent
# negative xfade offsets (e.g. when a clip is only slightly longer than CF).
_CROSSFADE_CAP_RATIO = 0.4


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_video_files(folder_path):
    video_exts = {'.mp4', '.mov', '.mkv', '.avi', '.webm'}
    videos = [
        os.path.join(folder_path, f)
        for f in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, f))
        and os.path.splitext(f.lower())[1] in video_exts
    ]
    videos.sort()
    return videos


def probe_file(path):
    info = ffmpeg.probe(path)
    video_stream = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
    has_audio = any(s['codec_type'] == 'audio' for s in info['streams'])
    return info, video_stream, has_audio


def get_duration(path):
    info = ffmpeg.probe(path)
    dur = float(info.get('format', {}).get('duration', 0) or 0)
    if not dur:
        vs = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
        if vs:
            dur = float(vs.get('duration', 0) or 0)
    return dur or 1.0


# ── Core pipeline ─────────────────────────────────────────────────────────────

def gentle_join(
    video_paths, output_dir, output_name,
    crossfade_sec=0.5,
    zoom_max=1.04,
    progress_callback=None,
):
    """
    Phase 1: Apply Ken Burns (subtle zoom + slow pan) to each clip in parallel.
    Phase 2: Concatenate with xfade (video) + acrossfade (audio) transitions.
    """
    temp_dir = tempfile.mkdtemp()

    # Detect output resolution from first video
    _, first_vs, _ = probe_file(video_paths[0])
    if first_vs:
        orig_w = int(first_vs['width'])
        orig_h = int(first_vs['height'])
    else:
        orig_w, orig_h = 1080, 1920
    print(f"Output resolution: {orig_w}x{orig_h}")

    # Ken Burns headroom (keep even numbers for codec compatibility)
    zoom_w = (int(orig_w * zoom_max) // 2) * 2
    zoom_h = (int(orig_h * zoom_max) // 2) * 2
    extra_x = zoom_w - orig_w
    extra_y = zoom_h - orig_h

    # ── Phase 1: per-clip Ken Burns (parallel) ────────────────────────────────
    done_count = 0
    done_lock  = threading.Lock()
    results    = [None] * len(video_paths)

    def process_clip(i, path):
        nonlocal done_count
        temp_out = os.path.join(temp_dir, f"temp_{i:03d}.mp4")
        try:
            info, vs, has_audio = probe_file(path)
            clip_dur = float(info.get('format', {}).get('duration', 0) or 0)
            if not clip_dur and vs:
                clip_dur = float(vs.get('duration', 0) or 0)
            clip_dur = max(clip_dur, 0.5)

            inp = ffmpeg.input(path)
            v   = inp.video
            a   = inp.audio if has_audio else None

            # Normalise to output resolution
            v = v.filter('scale', orig_w, orig_h)

            # Scale up slightly to create Ken Burns headroom
            if extra_x > 0 or extra_y > 0:
                v = v.filter('scale', zoom_w, zoom_h)

                # Animate the crop window: alternating diagonal pan per clip
                t_ratio = f'min(1,max(0,t/{clip_dur:.4f}))'
                if i % 2 == 0:
                    x_expr = f'{extra_x}*{t_ratio}'
                    y_expr = f'{extra_y}*{t_ratio}'
                else:
                    x_expr = f'{extra_x}*(1-{t_ratio})'
                    y_expr = f'{extra_y}*(1-{t_ratio})'

                v = v.filter('crop', orig_w, orig_h, x_expr, y_expr)

            # Ensure audio track (add silence if needed so xfade audio works)
            if a:
                out = ffmpeg.output(
                    v, a, temp_out,
                    vcodec='h264_nvenc', cq=23, preset='p4',
                    acodec='aac', audio_bitrate='192k',
                    pix_fmt='yuv420p',
                )
            else:
                silent = ffmpeg.input('anullsrc=r=44100:cl=stereo', format='lavfi')
                out = ffmpeg.output(
                    v, silent, temp_out,
                    vcodec='h264_nvenc', cq=23, preset='p4',
                    acodec='aac', audio_bitrate='192k',
                    pix_fmt='yuv420p', shortest=None,
                )

            ffmpeg.run(out, overwrite_output=True, quiet=True)

            with done_lock:
                done_count += 1
                current = done_count
            print(f"  [{current}/{len(video_paths)}] Ken Burns | {os.path.basename(path)}")
            if progress_callback:
                progress_callback(current, len(video_paths), os.path.basename(path))
            return temp_out

        except ffmpeg.Error as ex:
            stderr = ex.stderr.decode(errors='replace') if ex.stderr else str(ex)
            print(f"  FAILED {os.path.basename(path)}: {stderr[-400:]}")
            return None
        except Exception as ex:
            print(f"  FAILED {os.path.basename(path)}: {ex}")
            return None

    workers = min(6, len(video_paths))
    print(f"Applying Ken Burns to {len(video_paths)} clips ({workers} parallel workers)…")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(process_clip, i, p): i for i, p in enumerate(video_paths)}
        for fut in concurrent.futures.as_completed(futs):
            results[futs[fut]] = fut.result()

    temp_files = [r for r in results if r is not None]
    if not temp_files:
        raise RuntimeError("No clips processed successfully.")

    # ── Phase 2: crossfade join ───────────────────────────────────────────────
    final_output = os.path.join(output_dir, output_name)

    if len(temp_files) == 1:
        shutil.copy(temp_files[0], final_output)
        print(f"Single clip → {final_output}")
    else:
        print(f"Joining {len(temp_files)} clips with {crossfade_sec}s crossfade…")

        # Probe processed clip durations
        durations = [get_duration(tf) for tf in temp_files]

        # Cap crossfade at _CROSSFADE_CAP_RATIO of the shortest clip to avoid negative offsets
        cf = min(crossfade_sec, min(durations) * _CROSSFADE_CAP_RATIO)
        if cf != crossfade_sec:
            print(f"  Crossfade capped to {cf:.3f}s (shortest clip: {min(durations):.2f}s)")

        # Build xfade+acrossfade chain using ffmpeg-python
        inputs = [ffmpeg.input(tf) for tf in temp_files]
        current_v    = inputs[0].video
        current_a    = inputs[0].audio
        current_dur  = durations[0]

        for j in range(1, len(inputs)):
            offset = max(0.0, current_dur - cf)

            current_v = ffmpeg.filter(
                [current_v, inputs[j].video],
                'xfade',
                transition='fade',
                duration=cf,
                offset=offset,
            )
            current_a = ffmpeg.filter(
                [current_a, inputs[j].audio],
                'acrossfade',
                d=cf,
                c1='tri',
                c2='tri',
            )
            current_dur = offset + durations[j]

        out = ffmpeg.output(
            current_v, current_a, final_output,
            vcodec='h264_nvenc', cq=23, preset='p4',
            acodec='aac', audio_bitrate='192k',
            pix_fmt='yuv420p',
        )
        ffmpeg.run(out, overwrite_output=True, quiet=True)

    # Cleanup
    for f in temp_files:
        try:
            os.remove(f)
        except Exception:
            pass
    shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"Done → {final_output}")
    return final_output


# ── Flask-facing entry point ──────────────────────────────────────────────────

def process_folder(
    folder_path,
    crossfade_sec=0.5,
    zoom_max=1.04,
    progress_callback=None,
):
    """Called from Flask. Returns (success, output_path, message)."""
    videos = get_video_files(folder_path)
    if not videos:
        return False, None, "No video files found in folder"

    ts          = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"gentle_{ts}.mp4"
    output_path = os.path.join(folder_path, output_name)

    try:
        gentle_join(
            videos, folder_path, output_name,
            crossfade_sec=crossfade_sec,
            zoom_max=zoom_max,
            progress_callback=progress_callback,
        )
        if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
            return True, output_path, f"Done! → {output_name}"
        else:
            return False, None, "Output file missing or suspiciously small"
    except ffmpeg.Error as e:
        stderr = e.stderr.decode(errors='replace') if e.stderr else str(e)
        return False, None, f"Processing failed: {stderr[-600:]}"
    except Exception as e:
        return False, None, f"Processing failed: {e}"


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 vsplice_gentle.py <folder>")
        sys.exit(1)
    folder = os.path.abspath(sys.argv[1])
    if not os.path.isdir(folder):
        print(f"Not a directory: {folder}")
        sys.exit(1)
    videos = get_video_files(folder)
    if not videos:
        print("No videos found.")
        sys.exit(1)
    print(f"Found {len(videos)} videos.")
    ts          = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"gentle_{ts}.mp4"
    gentle_join(videos, folder, output_name)


if __name__ == "__main__":
    main()
