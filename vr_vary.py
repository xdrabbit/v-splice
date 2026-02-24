#!/usr/bin/env python3
import os
import sys
import random
import shutil
import datetime
import tempfile

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
        # Weight stutter_prob into style selection
        base_styles = ['constant', 'ramp_up', 'ramp_down', 'pulse', 'smooth_wave']
        weights     = [1.0, 1.0, 1.0, 1.0, 1.0]
        base_styles.append('stutter')
        weights.append(max(0.01, stutter_prob * 5))  # scale 0-1 → relative weight
        speed_style = random.choices(base_styles, weights=weights, k=1)[0]

        if speed_style == 'constant':
            base_speed = random.uniform(min_speed, max_speed)
            speed_expr = f'{1/base_speed}*PTS'
            speed_desc = f"constant {base_speed:.2f}x"
        elif speed_style == 'ramp_up':
            s = random.uniform(2.0, 4.0)
            e = random.uniform(0.3, 0.8)
            speed_expr = f'({s} - ({s}-{e})*(N/TB/1000))*PTS'
            speed_desc = f"ramp_up ({1/s:.1f}→{1/e:.1f}x)"
        elif speed_style == 'ramp_down':
            s = random.uniform(0.3, 0.6)
            e = random.uniform(1.5, 3.5)
            speed_expr = f'({s} + ({e}-{s})*(N/TB/1000))*PTS'
            speed_desc = f"ramp_down ({1/s:.1f}→{1/e:.1f}x)"
        elif speed_style == 'pulse':
            base = random.uniform(0.8, 1.2)
            amp  = wave_amplitude * random.uniform(0.3, 0.7)
            freq = random.uniform(0.5, 2.0)
            speed_expr = f'({base} + {amp}*sin(2*PI*{freq}*N/TB/25))*PTS'
            speed_desc = f"pulse ({1/base:.1f}x base, amp={amp:.2f})"
        elif speed_style == 'smooth_wave':
            center = random.uniform(0.6, 1.4)
            swing  = wave_amplitude * random.uniform(0.2, 0.5)
            speed_expr = f'({center} + {swing}*sin(PI*N/TB/500))*PTS'
            speed_desc = f"smooth_wave (swing={swing:.2f})"
        else:  # stutter
            spds = [random.uniform(0.2, 0.5), random.uniform(1.5, 3.0), random.uniform(0.8, 1.2)]
            random.shuffle(spds)
            speed_expr = (f"if(lt(mod(N,90),30),{spds[0]},"
                          f"if(lt(mod(N,90),60),{spds[1]},{spds[2]}))*PTS")
            speed_desc = "stutter"

        reverse    = random.random() < reverse_prob
        zoom_s     = random.uniform(zoom_min, zoom_max)
        zoom_e     = random.uniform(zoom_min, zoom_max)
        pan_x      = random.uniform(-pan_range, pan_range)
        pan_y      = random.uniform(-pan_range, pan_range)
        brightness = round(random.uniform(-brightness_max, brightness_max), 4)
        contrast   = round(1.0 + random.uniform(-contrast_max, contrast_max), 4)

        temp_out = os.path.join(temp_dir, f"temp_{i:03d}.mp4")

        try:
            _, _, has_audio = probe_file(path)
            inp = ffmpeg.input(path)
            v   = inp.video
            a   = inp.audio if has_audio else None

            # Speed
            v = v.filter('setpts', speed_expr)

            # Reverse
            if reverse:
                v = v.filter('reverse')
                if a:
                    a = a.filter('areverse')

            # Zoompan
            v = v.filter('scale', 'iw*2', 'ih*2')
            v = v.filter('zoompan',
                         z=f'zoom+({zoom_e}-{zoom_s})*(on/(duration*25))',
                         x=f'iw/zoom/2+{pan_x}*iw/zoom',
                         y=f'ih/zoom/2+{pan_y}*ih/zoom',
                         d=1, s=output_size)

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

            rev_str = " (rev)" if reverse else ""
            print(f"  Clip {i+1}/{len(video_paths)}: {speed_desc}{rev_str}, "
                  f"zoom {zoom_s:.2f}→{zoom_e:.2f}, bright={brightness}")

            if a:
                out = ffmpeg.output(v, a, temp_out,
                                    vcodec='libx264', crf=23, preset='fast',
                                    acodec='aac', audio_bitrate='192k',
                                    pix_fmt='yuv420p')
            else:
                out = ffmpeg.output(v, temp_out,
                                    vcodec='libx264', crf=23, preset='fast',
                                    pix_fmt='yuv420p')

            ffmpeg.run(out, overwrite_output=True, quiet=True)
            temp_files.append(temp_out)
            clip_has_audio.append(has_audio)
            if progress_callback:
                progress_callback(len(temp_files), len(video_paths), os.path.basename(path))

        except Exception as ex:
            print(f"  FAILED {os.path.basename(path)}: {ex}")
            continue

    if not temp_files:
        raise RuntimeError("No clips processed successfully.")

    # ── Phase 2: crossfade concat ─────────────────────────────────────────────
    final_output   = os.path.join(output_dir, output_name)
    all_have_audio = all(clip_has_audio)

    if len(temp_files) == 1:
        shutil.copy(temp_files[0], final_output)
        print(f"Single clip → {final_output}")
    else:
        print(f"Crossfading {len(temp_files)} clips (audio={'yes' if all_have_audio else 'no'})…")
        durations = []
        for tf in temp_files:
            p = ffmpeg.probe(tf)
            durations.append(float(p['format']['duration']))

        inputs = [ffmpeg.input(tf) for tf in temp_files]
        cur_v  = inputs[0].video
        cur_a  = inputs[0].audio if all_have_audio else None
        cur_d  = durations[0]

        for i in range(1, len(inputs)):
            nxt_v = inputs[i].video
            nxt_a = inputs[i].audio if all_have_audio else None
            nxt_d = durations[i]
            offset = max(cur_d - crossfade_sec, cur_d / 2)

            cur_v = ffmpeg.filter([cur_v, nxt_v], 'xfade',
                                  transition='fade',
                                  duration=crossfade_sec,
                                  offset=offset)
            if all_have_audio:
                cur_a = ffmpeg.filter([cur_a, nxt_a], 'acrossfade',
                                      d=crossfade_sec, c1='tri', c2='tri')
            cur_d = cur_d + nxt_d - crossfade_sec

        if all_have_audio:
            out = ffmpeg.output(cur_v, cur_a, final_output,
                                vcodec='libx264', crf=23, preset='fast',
                                acodec='aac', audio_bitrate='192k',
                                pix_fmt='yuv420p')
        else:
            out = ffmpeg.output(cur_v, final_output,
                                vcodec='libx264', crf=23, preset='fast',
                                pix_fmt='yuv420p')

        ffmpeg.run(out, overwrite_output=True, quiet=True)

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
