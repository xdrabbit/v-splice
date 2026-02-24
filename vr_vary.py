#!/usr/bin/env python3
import os
import sys
import random
import shutil
import datetime
import tempfile
import subprocess

import ffmpeg


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
    has_audio    = any(s['codec_type'] == 'audio' for s in info['streams'])
    return info, video_stream, has_audio


def dynamic_perclip_then_concat(
    video_paths, output_dir, output_name,
    crossfade_sec=0.25,
    reverse_prob=0.15,
    min_speed=0.3,
    max_speed=5.0,
    zoom_min=1.00,
    zoom_max=1.15,
    pan_range=0.05,
    brightness_max=0.05,
    contrast_max=0.10,
    effect_prob=0.4,
    pitch_shift_prob=0.15,
    lowpass_prob=0.15,
    wave_amplitude=0.5,
    stutter_prob=0.17,
    progress_callback=None,
):
    temp_dir = tempfile.mkdtemp()
    temp_files     = []
    clip_has_audio = []

    # Detect resolution from first video
    _, first_vs, _ = probe_file(video_paths[0])
    if first_vs:
        orig_w = int(first_vs['width'])
        orig_h = int(first_vs['height'])
        output_size = f'{orig_w}x{orig_h}'
        print(f"Detected source resolution: {output_size}")
    else:
        output_size = '1080x1920'
        print(f"Could not detect resolution, defaulting to {output_size}")

    # ── Phase 1: per-clip effects ─────────────────────────────────────────────
    for i, path in enumerate(video_paths):
        # Only use timestamp-shift styles (fast) — complex per-frame math is a CPU hog
        speed_style = random.choices(
            ['constant', 'constant', 'stutter'],            # weight constant heavier
            weights=[3, 3, max(0.01, stutter_prob * 5)], k=1
        )[0]

        if speed_style == 'constant':
            base_speed = random.uniform(min_speed, max_speed)
            speed_mult = round(1.0 / base_speed, 6)
            speed_expr = f'{speed_mult}*PTS'
            speed_desc = f"constant {base_speed:.2f}x"
        else:  # stutter
            spds = [random.uniform(0.2, 0.5), random.uniform(1.5, 3.0), random.uniform(0.8, 1.2)]
            random.shuffle(spds)
            speed_expr = (f"if(lt(mod(N,90),30),{spds[0]},"
                          f"if(lt(mod(N,90),60),{spds[1]},{spds[2]}))*PTS")
            speed_desc = "stutter"

        # No reverse — buffers entire clip in RAM, causes hangs on large files
        zoom_s     = random.uniform(zoom_min, zoom_max)
        zoom_e     = random.uniform(zoom_min, zoom_max)
        pan_x      = random.uniform(-pan_range, pan_range)
        pan_y      = random.uniform(-pan_range, pan_range)
        brightness = round(random.uniform(-brightness_max, brightness_max), 4)
        contrast   = round(1.0 + random.uniform(-contrast_max, contrast_max), 4)

        temp_out = os.path.join(temp_dir, f"temp_{i:03d}.mp4")

        try:
            _, _, has_audio = probe_file(path)
            inp = ffmpeg.input(path)  # plain CPU decode — hwaccel gains nothing with sw filters
            v   = inp.video
            a   = inp.audio if has_audio else None

            # Speed
            v = v.filter('setpts', speed_expr)

            # Fast zoom: scale up then crop — same visual result as zoompan, much faster
            w, h  = output_size.split('x')
            iw, ih = int(w), int(h)
            zw = int(iw * zoom_e)
            zh = int(ih * zoom_e)
            off_x = max(0, int((zw - iw) / 2 + pan_x * iw))
            off_y = max(0, int((zh - ih) / 2 + pan_y * ih))
            v = v.filter('scale', iw, ih)        # normalise to target res first
            v = v.filter('scale', zw, zh)         # zoom
            v = v.filter('crop', iw, ih, off_x, off_y)  # pan + crop back

            # Static brightness / contrast tweak
            if random.random() < effect_prob:
                v = v.filter('eq', brightness=brightness, contrast=contrast)

            # Optional audio effects
            if a:
                r = random.random()
                if r < pitch_shift_prob:
                    try:
                        a = a.filter('rubberband', pitch=random.uniform(0.9, 1.1))
                    except Exception:
                        pass
                elif r < pitch_shift_prob + lowpass_prob:
                    a = a.filter('lowpass', f=800)

            print(f"  Clip {i+1}/{len(video_paths)}: {speed_desc}, "
                  f"zoom {zoom_s:.2f}→{zoom_e:.2f}, bright={brightness}")

            if a:
                out = ffmpeg.output(v, a, temp_out,
                                    vcodec='h264_nvenc', cq=23, preset='p4',
                                    acodec='aac', audio_bitrate='192k',
                                    pix_fmt='yuv420p')
            else:
                # Add silent audio so all temp clips have identical streams for concat
                silent = ffmpeg.input('anullsrc=r=44100:cl=stereo', format='lavfi')
                out = ffmpeg.output(v, silent, temp_out,
                                    vcodec='h264_nvenc', cq=23, preset='p4',
                                    acodec='aac', audio_bitrate='192k',
                                    pix_fmt='yuv420p',
                                    shortest=None)

            ffmpeg.run(out, overwrite_output=True, quiet=False)
            temp_files.append(temp_out)
            clip_has_audio.append(has_audio)
            if progress_callback:
                progress_callback(len(temp_files), len(video_paths), os.path.basename(path))

        except ffmpeg.Error as ex:
            stderr = ex.stderr.decode(errors='replace') if ex.stderr else str(ex)
            print(f"  FAILED {os.path.basename(path)}: {stderr[-800:]}")
            continue
        except Exception as ex:
            print(f"  FAILED {os.path.basename(path)}: {ex}")
            continue

    if not temp_files:
        raise RuntimeError("No clips processed successfully.")

    # ── Phase 2: concat via demuxer (stream-copy, works for any clip count) ───
    final_output = os.path.join(output_dir, output_name)

    if len(temp_files) == 1:
        shutil.copy(temp_files[0], final_output)
        print(f"Single clip → {final_output}")
    else:
        print(f"Joining {len(temp_files)} clips (stream copy, no re-encode)…")
        concat_list = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list, "w") as fh:
            for tf in temp_files:
                fh.write(f"file '{tf}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            final_output,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode(errors='replace')[-600:])

    # Cleanup
    for f in temp_files:
        try: os.remove(f)
        except Exception: pass
    try: os.rmdir(temp_dir)
    except Exception: pass

    print(f"Done → {final_output}")
    return final_output


def process_folder(
    folder_path,
    crossfade_sec=0.25,
    reverse_prob=0.15,
    min_speed=0.3,
    max_speed=5.0,
    zoom_min=1.00,
    zoom_max=1.15,
    pan_range=0.05,
    brightness_max=0.05,
    contrast_max=0.10,
    effect_prob=0.4,
    pitch_shift_prob=0.15,
    lowpass_prob=0.15,
    wave_amplitude=0.5,
    stutter_prob=0.17,
    progress_callback=None,
):
    """Called from Flask. Returns (success, output_path, message)."""
    videos = get_video_files(folder_path)
    if not videos:
        return False, None, "No video files found in folder"

    ts          = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"combined_dynamic_{ts}.mp4"
    output_path = os.path.join(folder_path, output_name)

    try:
        dynamic_perclip_then_concat(
            videos, folder_path, output_name,
            crossfade_sec=crossfade_sec,
            reverse_prob=reverse_prob,
            min_speed=min_speed,
            max_speed=max_speed,
            zoom_min=zoom_min,
            zoom_max=zoom_max,
            pan_range=pan_range,
            brightness_max=brightness_max,
            contrast_max=contrast_max,
            effect_prob=effect_prob,
            pitch_shift_prob=pitch_shift_prob,
            lowpass_prob=lowpass_prob,
            wave_amplitude=wave_amplitude,
            stutter_prob=stutter_prob,
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


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 vr_vary.py <folder>")
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
    output_name = f"combined_dynamic_{ts}.mp4"
    dynamic_perclip_then_concat(videos, folder, output_name)


if __name__ == "__main__":
    main()
