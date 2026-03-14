#!/usr/bin/env python3
"""
V-Splice Phase 1 Batch Indexer
Merges Opus activity analysis + Whisper transcription into queryable indices
"""
import json
import os
import glob
from pathlib import Path

TEST_DIR = Path("./test")
BATCH_FRAMES = TEST_DIR / "batch_frames"

VIDEOS = [
    {
        "name": "GH010231.MP4",
        "duration_sec": 467.776,
        "type": "riding"
    },
    {
        "name": "GH010232.MP4", 
        "duration_sec": 532.011,
        "type": "riding"
    },
    {
        "name": "IMG_0230.MOV",
        "duration_sec": 47.533,
        "type": "assembly"
    }
]

def load_whisper(video_name):
    """Load Whisper JSON transcript"""
    base = video_name.replace(".MOV", "").replace(".MP4", "")
    path = TEST_DIR / f"{base}.json"
    if not path.exists():
        return None
    
    with open(path) as f:
        data = json.load(f)
    
    # Convert to list of (start, end, text) tuples
    segments = []
    for seg in data.get('segments', []):
        segments.append({
            'start': seg['start'],
            'end': seg['end'],
            'text': seg['text'].strip()
        })
    return segments

def create_placeholder_opus_analysis(video_name, duration_sec):
    """
    Placeholder for Opus analysis.
    In production, this would be populated by vision model.
    Returns activity segments structured for merging.
    """
    # Estimate segments (30-second chunks)
    num_segments = int(duration_sec / 30) + 1
    
    segments = []
    for i in range(num_segments):
        start = i * 30
        end = min((i + 1) * 30, duration_sec)
        
        segments.append({
            "segment_id": i + 1,
            "start_sec": start,
            "end_sec": end,
            "activity_type": "analyzing...",  # Will be filled by Opus
            "key_events": [],  # Will be filled by Opus
            "interest_score": 0.5,  # Will be filled by Opus
            "notes": f"Segment {i+1} of {num_segments}"
        })
    
    return segments

def merge_activity_and_transcript(video_name, duration_sec, video_type):
    """Merge Opus activity analysis with Whisper transcript"""
    
    # Load transcription
    transcript_segs = load_whisper(video_name) or []
    
    # Load placeholder opus (will be replaced with real analysis)
    opus_segs = create_placeholder_opus_analysis(video_name, duration_sec)
    
    # Merge into combined index
    combined = {
        "metadata": {
            "file": video_name,
            "type": video_type,
            "duration_sec": duration_sec,
            "analysis_date": "2026-03-13",
            "models_used": {
                "activity": "Claude Opus 4.6 (vision) - PENDING",
                "transcription": "Whisper (local)"
            }
        },
        "segments": []
    }
    
    # For each activity segment, find overlapping transcript
    for seg in opus_segs:
        start = seg['start_sec']
        end = seg['end_sec']
        
        # Find all transcript segments that overlap
        transcript_text = []
        for trans in transcript_segs:
            if trans['start'] < end and trans['end'] > start:
                transcript_text.append(trans['text'])
        
        combined['segments'].append({
            "id": seg['segment_id'],
            "timestamp": f"{int(start):02d}:{int(start%60):02d}-{int(end):02d}:{int(end%60):02d}",
            "start_sec": start,
            "end_sec": end,
            "duration_sec": end - start,
            "activity": seg['activity_type'],
            "events": seg['key_events'],
            "interest": seg['interest_score'],
            "transcript": " ".join(transcript_text) if transcript_text else "[no speech detected]",
            "confidence": "pending"
        })
    
    combined['summary'] = {
        "structure": f"{video_type.capitalize()} footage",
        "total_segments": len(combined['segments']),
        "avg_interest": 0.5,  # Will update when Opus runs
        "total_speech_duration_sec": sum(t['end'] - t['start'] for t in transcript_segs),
        "queryable_by": [
            "activity_type",
            "interest_score",
            "speech_content",
            "timestamp",
            "duration"
        ]
    }
    
    return combined

def main():
    print("V-Splice Phase 1 Batch Indexer")
    print("=" * 70)
    print()
    
    indices = []
    
    for video in VIDEOS:
        name = video['name']
        duration = video['duration_sec']
        vtype = video['type']
        
        print(f"Processing: {name}")
        print(f"  Duration: {duration:.1f}s | Type: {vtype}")
        
        # Merge activity + transcript
        index = merge_activity_and_transcript(name, duration, vtype)
        indices.append(index)
        
        # Write individual index
        output = TEST_DIR / f"{name.replace('.MOV', '').replace('.MP4', '')}_index.json"
        with open(output, 'w') as f:
            json.dump(index, f, indent=2)
        
        print(f"  ✓ Created {output.name}")
        print()
    
    # Create master index
    master = {
        "project": "V-Splice Phase 1",
        "batch_date": "2026-03-13",
        "status": "OPUS ANALYSIS PENDING",
        "total_videos": len(indices),
        "total_duration_sec": sum(sum(s['duration_sec'] for s in idx['segments']) 
                                   for idx in indices),
        "videos": indices
    }
    
    master_output = TEST_DIR / "v_splice_master_index.json"
    with open(master_output, 'w') as f:
        json.dump(master, f, indent=2)
    
    print("=" * 70)
    print(f"✓ Created master index: {master_output.name}")
    print(f"✓ Total videos: {len(indices)}")
    print(f"✓ Total duration: {master['total_duration_sec']:.1f} seconds")
    print()
    print("NEXT STEP: Send frames to Opus for activity classification")
    print()

if __name__ == '__main__':
    main()
