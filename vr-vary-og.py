#!/usr/bin/env python3
import os
import sys
import random
import datetime
import tempfile

import ffmpeg

def get_video_files(folder_path):
    video_exts = {'.mp4', '.mov', '.mkv', '.avi', '.webm'}
    videos = [
        os.path.join(folder_path, f)
        for f in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, f)) and os.path.splitext(f.lower())[1] in video_exts
    ]
    videos.sort()
    return videos

def fast_concat(video_paths, output_path):
    """Fast stream copy concat - no re-encode"""
    concat_txt = "concat_list.txt"
    with open(concat_txt, "w", encoding="utf-8") as f:
        for path in video_paths:
            escaped = path.replace("\\", "\\\\").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    try:
        stream = ffmpeg.input(concat_txt, format='concat', safe=0)
        stream = ffmpeg.output(stream, output_path, c='copy', map='0', loglevel='info')
        print("Running fast concat command:")
        print(' '.join(ffmpeg.compile(stream)))
        ffmpeg.run(stream, overwrite_output=True)
        print(f"Fast concat success: {output_path}")
        return True
    except ffmpeg.Error as e:
        print("Fast concat failed:")
        if e.stderr:
            print(e.stderr.decode('utf-8', errors='replace'))
        else:
            print("No stderr - check ffmpeg in PATH.")
        return False
    finally:
        if os.path.exists(concat_txt):
            os.remove(concat_txt)

def dynamic_perclip_then_concat(video_paths, output_dir, output_name):
    temp_dir = tempfile.mkdtemp()
    temp_files = []

    # Detect resolution from first video
    probe = ffmpeg.probe(video_paths[0])
    video_stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
    if video_stream:
        orig_width = int(video_stream['width'])
        orig_height = int(video_stream['height'])
        output_size = f'{orig_width}x{orig_height}'
        print(f"Detected source resolution: {output_size}")
    else:
        output_size = '1080x1920'
        print(f"Could not detect resolution, defaulting to {output_size}")

    # Phase 1: Process all clips with random effects
    for i, path in enumerate(video_paths):
        # === DYNAMIC SPEED VARIATIONS ===
        speed_style = random.choice(['constant', 'ramp_up', 'ramp_down', 'pulse', 'smooth_wave', 'stutter'])
        
        if speed_style == 'constant':
            # Classic random constant speed
            base_speed = random.uniform(0.3, 5.0)
            speed_expr = f'{1/base_speed}*PTS'
            speed_desc = f"constant {base_speed:.2f}x"
        
        elif speed_style == 'ramp_up':
            # Start slow, accelerate (dramatic build)
            start_mult = random.uniform(2.0, 4.0)  # start slower
            end_mult = random.uniform(0.3, 0.8)    # end faster
            speed_expr = f'({start_mult} - ({start_mult}-{end_mult})*(N/TB/1000))*PTS'
            speed_desc = f"ramp up ({1/start_mult:.1f}x → {1/end_mult:.1f}x)"
        
        elif speed_style == 'ramp_down':
            # Start fast, decelerate (slow motion landing)
            start_mult = random.uniform(0.3, 0.6)  # start faster
            end_mult = random.uniform(1.5, 3.5)    # end slower
            speed_expr = f'({start_mult} + ({end_mult}-{start_mult})*(N/TB/1000))*PTS'
            speed_desc = f"ramp down ({1/start_mult:.1f}x → {1/end_mult:.1f}x)"
        
        elif speed_style == 'pulse':
            # Oscillating speed (dreamy/hypnotic)
            base = random.uniform(0.8, 1.2)
            amplitude = random.uniform(0.3, 0.7)
            freq = random.uniform(0.5, 2.0)  # cycles per ~second
            speed_expr = f'({base} + {amplitude}*sin(2*PI*{freq}*N/TB/25))*PTS'
            speed_desc = f"pulse (base {1/base:.1f}x ± {amplitude:.1f})"
        
        elif speed_style == 'smooth_wave':
            # Gentle sine wave speed variation
            center = random.uniform(0.6, 1.4)
            swing = random.uniform(0.2, 0.5)
            speed_expr = f'({center} + {swing}*sin(PI*N/TB/500))*PTS'
            speed_desc = f"smooth wave ({1/(center+swing):.1f}x ↔ {1/(center-swing):.1f}x)"
        
        elif speed_style == 'stutter':
            # Quick speed jumps (music video style)
            speeds = [random.uniform(0.2, 0.5), random.uniform(1.5, 3.0), random.uniform(0.8, 1.2)]
            random.shuffle(speeds)
            # Use step function with mod
            speed_expr = f"if(lt(mod(N,90),30),{speeds[0]},if(lt(mod(N,90),60),{speeds[1]},{speeds[2]}))*PTS"
            speed_desc = f"stutter ({1/speeds[0]:.1f}x/{1/speeds[1]:.1f}x/{1/speeds[2]:.1f}x)"

        reverse = random.random() < 0.15  # reduced from 30% to 15%
        
        # Subtle zoom (toned down ranges)
        zoom_start = random.uniform(1.0, 1.1)  # was 1.0-1.4
        zoom_end = random.uniform(1.05, 1.15) if random.random() > 0.5 else random.uniform(0.95, 1.05)  # subtle zoom in/out
        
        # Minimal pan (toned down)
        pan_x = random.uniform(-0.05, 0.05)  # was -0.2 to 0.2
        pan_y = random.uniform(-0.05, 0.05)  # was -0.2 to 0.2
        
        brightness_wave = random.uniform(0.01, 0.03)  # was 0.02-0.08
        contrast_wave = random.uniform(0.02, 0.06)    # was 0.04-0.15

        temp_out = os.path.join(temp_dir, f"temp_{i:03d}.mp4")

        try:
            stream = ffmpeg.input(path)
            v = stream.video
            a = stream.audio

            # Dynamic speed (using computed expression)
            v = v.filter('setpts', speed_expr)

            # Optional reverse (after speed to maintain timing logic)
            if reverse:
                v = v.filter('reverse')
                a = a.filter('areverse')

            # Zoompan
            v = v.filter('scale', 'iw*2', 'ih*2')
            v = v.filter('zoompan',
                         z=f'zoom + (on/(duration*25))*({zoom_end}-{zoom_start})',
                         x=f'(iw/zoom/2) + ({pan_x}*iw/zoom)',
                         y=f'(ih/zoom/2) + ({pan_y}*ih/zoom)',
                         d=1, s=output_size)  # use detected resolution

            # Optional audio effects
            if random.random() < 0.15:
                a = a.filter('rubberband', pitch=random.uniform(0.9, 1.1))
            elif random.random() < 0.15:
                a = a.filter('lowpass', f='800')

            # Optional brightness/contrast pulse
            if random.random() > 0.4:
                v = v.filter('eq',
                             brightness=f'{brightness_wave}*sin(2*PI*t/5)',
                             contrast=f'1 + {contrast_wave}*sin(2*PI*t/3)')

            stream = ffmpeg.output(v, a, temp_out,
                                   vcodec='h264_videotoolbox', q=65,  # Apple hardware encoder (q: 1-100, higher=better)
                                   acodec='aac', audio_bitrate='192k',
                                   pix_fmt='yuv420p', shortest=None)
            rev_str = " (reversed)" if reverse else ""
            print(f"Processing clip {i+1}/{len(video_paths)}: {speed_desc}{rev_str}, zoom {zoom_start:.2f}→{zoom_end:.2f}")
            ffmpeg.run(stream, overwrite_output=True)
            temp_files.append(temp_out)

        except Exception as ex:
            print(f"Failed {os.path.basename(path)}: {ex}")
            continue

    if not temp_files:
        print("No clips processed successfully.")
        return

    # Phase 2: Crossfade all clips together using xfade (video) + acrossfade (audio)
    crossfade_duration = 0.25  # seconds of overlap
    
    final_output = os.path.join(output_dir, output_name)
    
    if len(temp_files) == 1:
        # Only one clip, just copy it
        import shutil
        shutil.copy(temp_files[0], final_output)
        print(f"Single clip copied to {final_output}")
    else:
        # Build crossfade chain
        print(f"Applying crossfades between {len(temp_files)} clips...")
        
        # Get durations for each clip
        durations = []
        for tf in temp_files:
            probe = ffmpeg.probe(tf)
            dur = float(probe['format']['duration'])
            durations.append(dur)
        
        # Build the filter graph iteratively
        # Start with first clip
        inputs = [ffmpeg.input(tf) for tf in temp_files]
        
        current_video = inputs[0].video
        current_audio = inputs[0].audio
        current_duration = durations[0]
        
        for i in range(1, len(inputs)):
            next_video = inputs[i].video
            next_audio = inputs[i].audio
            next_duration = durations[i]
            
            # Calculate offset: where to start the transition
            offset = current_duration - crossfade_duration
            if offset < 0:
                offset = current_duration / 2  # fallback for very short clips
            
            # Video crossfade
            current_video = ffmpeg.filter(
                [current_video, next_video],
                'xfade',
                transition='fade',
                duration=crossfade_duration,
                offset=offset
            )
            
            # Audio crossfade
            current_audio = ffmpeg.filter(
                [current_audio, next_audio],
                'acrossfade',
                d=crossfade_duration,   
                c1='tri',  # fade out curve
                c2='tri'   # fade in curve
            )
            
            # Update running duration (output duration = d1 + d2 - crossfade)
            current_duration = current_duration + next_duration - crossfade_duration
        
        # Output final result
        output = ffmpeg.output(
            current_video, current_audio,
            final_output,
            vcodec='h264_videotoolbox', q=65,  # Apple hardware encoder (q: 1-100, higher=better)
            acodec='aac', audio_bitrate='192k',
            pix_fmt='yuv420p'
        )
        
        print("Running crossfade command:")
        print(' '.join(ffmpeg.compile(output)))
        ffmpeg.run(output, overwrite_output=True)

    # Cleanup temp files
    # for f in temp_files:
    #     if f and os.path.exists(f):
    #         os.remove(f)
    # if os.path.exists(temp_dir):
    #     os.rmdir(temp_dir)
    
    print(f"Crossfade complete: {final_output}")

def main():
    if len(sys.argv) != 2:
        print("Usage: python vr-vary.py <folder>")
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

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"combined_dynamic_{ts}.mp4"
    output_path = os.path.join(folder, output_name)

    # Always use dynamic processing with crossfades
    print("Processing clips with effects + crossfades...")
    dynamic_perclip_then_concat(videos, folder, output_name)

if __name__ == "__main__":
    main()