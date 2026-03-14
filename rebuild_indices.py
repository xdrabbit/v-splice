#!/usr/bin/env python3
"""
Rebuild V-Splice Phase 1 indices to match final schema
"""
import json
from pathlib import Path

test = Path('test')

# Opus analysis data (already completed)
ANALYSIS = {
    'GH010231.MP4': {
        'summary': 'Man in bike helmet prepares for and discusses a Segway ride. The entire video is mostly pre-ride setup and talking-to-camera from the garage and driveway. He starts inside the garage, mounts the Segway, rolls out through the driveway past vehicles and a Coleman camper trailer, talks extensively outdoors, then returns to the garage at the end. Very little actual riding occurs; this appears to be a vlog-style intro/setup clip.',
        'type': 'riding',
        'duration': 467.776,
        'segments': [
            {'start':0,'end':60,'activity':'talking-to-camera','action':'Garage intro explaining ride plans','events':['intro in garage workshop','helmet on','Segway visible in background'],'interest':0.5,'tags':['intro','garage','explaining']},
            {'start':60,'end':120,'activity':'setup-and-mount','action':'Mounting Segway and maneuvering in garage doorway','events':['grabs Segway handlebars','preparing to roll out of garage'],'interest':0.4,'tags':['setup','mounting','transition']},
            {'start':120,'end':180,'activity':'transition','action':'Rolling out of garage onto driveway','events':['exiting garage','garage door open','brick exterior visible'],'interest':0.3,'tags':['transition','outdoors','driveway']},
            {'start':180,'end':240,'activity':'talking-to-camera','action':'Stationary driveway monologue','events':['standing in driveway','overcast sky','brick house behind'],'interest':0.3,'tags':['explaining','driveway']},
            {'start':240,'end':330,'activity':'talking-to-camera','action':'Extended talking segment on driveway near vehicles','events':['near parked vehicles','white trailer visible','Coleman camper in background'],'interest':0.35,'tags':['explaining','driveway','vehicles']},
            {'start':330,'end':410,'activity':'talking-to-camera','action':'Continued monologue discussing Segway features','events':['Coleman camper prominent','animated speaking','driveway location'],'interest':0.35,'tags':['explaining','features','driveway']},
            {'start':410,'end':467.776,'activity':'riding-successful','action':'Riding Segway back into garage, best moment','events':['riding Segway back','returning home','wrapping up'],'interest':0.6,'tags':['riding','garage','return']},
        ]
    },
    'GH010232.MP4': {
        'summary': 'Stationary camera on driveway/side yard captures a man preparing and practicing on a Segway-style scooter in a tight space between a house, lawn mower, and Coleman travel trailer. A woman briefly appears. Most of the video is setup and repeated test riding attempts in the backyard driveway area.',
        'type': 'riding',
        'duration': 532.011,
        'segments': [
            {'start':0,'end':60,'activity':'camera-setup','action':'Static driveway/garage establishing shot','events':['camera on driveway facing garage','vehicles visible'],'interest':0.2,'tags':['setup','establishing']},
            {'start':60,'end':120,'activity':'camera-setup','action':'Camera being moved or adjusted','events':['low angle on driveway','repositioning'],'interest':0.15,'tags':['setup','technical']},
            {'start':120,'end':180,'activity':'setup-and-mount','action':'Camera positioned for side yard riding','events':['camera in side yard','Segway visible','narrow path between house and trailer'],'interest':0.3,'tags':['setup','preparation']},
            {'start':180,'end':240,'activity':'setup-and-mount','action':'Rider walking to Segway location','events':['helmet on','approaching Segway','navigating narrow path'],'interest':0.5,'tags':['setup','prep','helmet']},
            {'start':240,'end':300,'activity':'testing','action':'Woman arrives, brief interaction','events':['woman appears in yard','possible conversation','Segway parked'],'interest':0.4,'tags':['social','interaction']},
            {'start':300,'end':380,'activity':'riding-attempt','action':'Struggling with mounting or recovery from fall','events':['crouched over Segway','adjustment attempt','getting upright'],'interest':0.6,'tags':['riding','attempt','struggle']},
            {'start':380,'end':440,'activity':'testing','action':'Testing Segway balance on driveway','events':['standing with Segway','balancing','helmet on'],'interest':0.6,'tags':['testing','balance','preparation']},
            {'start':440,'end':490,'activity':'riding-attempt','action':'Practice attempts in narrow corridor','events':['repeated mounting','tight space','persistence'],'interest':0.5,'tags':['riding','attempt','learning']},
            {'start':490,'end':532.011,'activity':'riding-successful','action':'Riding Segway back through narrow path, best moment','events':['riding toward camera','touching trailer for balance','upright','successful'],'interest':0.8,'tags':['riding','success','highlight']},
        ]
    },
    'IMG_0230.MOV': {
        'summary': 'Unpacking and sorting Segway-Ninebot assembly hardware kit including bolts, screws, wrench, bracket, spacers on countertop with instruction card visible.',
        'type': 'assembly',
        'duration': 47.533,
        'segments': [
            {'start':0,'end':16,'activity':'assembly','action':'Displaying unpacked hardware kit','events':['unpacking hardware bag','instruction card visible','red button component','handlebar visible'],'interest':0.5,'tags':['assembly','hardware','unboxing']},
            {'start':16,'end':32,'activity':'assembly','action':'Organizing fasteners and tools','events':['sorting bolts and screws','bracket laid out','spacer tubes','wrench identified'],'interest':0.6,'tags':['assembly','organization','tools']},
            {'start':32,'end':47.533,'activity':'assembly','action':'Inspecting wrench and reviewing parts layout','events':['examining wrench','all hardware arranged','charging port cover','spacer tubes'],'interest':0.6,'tags':['assembly','inspection','review']},
        ]
    }
}

def load_whisper_speech(base):
    """Load Whisper transcript and extract clean speech with confidence"""
    try:
        with open(test / f'{base}.json') as f:
            data = json.load(f)
        segs = data.get('segments', [])
        
        # Filter out repetitive/noisy segments
        clean = []
        for s in segs:
            text = s['text'].strip()
            # Skip obvious artifacts
            if text and text not in ['', 'okay', 'I don\'t know', 'yeah'] and 'PHONE RINGS' not in text:
                clean.append({'start':s['start'], 'end':s['end'], 'text':text})
        
        return clean
    except:
        return []

def get_speech_for_segment(transcripts, start, end):
    """Extract speech and confidence for a segment"""
    segment_texts = [t['text'] for t in transcripts if t['start'] < end and t['end'] > start]
    
    if not segment_texts:
        return {'text': '[no speech detected]', 'confidence': 'none', 'speaker': 'Tom', 'duration_sec': 0}
    
    # Determine confidence
    if all(len(t) > 5 for t in segment_texts):
        confidence = 'high'
    elif len(segment_texts) >= 2:
        confidence = 'medium'
    else:
        confidence = 'low'
    
    return {
        'text': ' '.join(segment_texts),
        'confidence': confidence,
        'speaker': 'Tom',
        'duration_sec': int(end - start)
    }

def build_index(base, metadata):
    """Build full index for one video"""
    whisper = load_whisper_speech(base)
    
    index = {
        'metadata': {
            'file': metadata['type'] if isinstance(metadata.get('type'), str) else base,
            'duration_sec': metadata['duration'],
            'type': metadata['type'],
            'analysis_date': '2026-03-13',
            'models': {
                'activity_analysis': 'Claude Opus 4.6',
                'transcription': 'Whisper local',
                'transcript_confidence': 'medium'
            }
        },
        'summary': {
            'title': metadata['summary'],
            'primary_activity': metadata['segments'][0]['activity'] if metadata['segments'] else 'unknown',
            'peak_interest_moment': f"{max(s['interest'] for s in metadata['segments']):.2f}",
            'best_segment_for_editing': max(metadata['segments'], key=lambda s: s['interest'])['activity'],
            'estimated_useful_content_sec': int(sum(s['end']-s['start'] for s in metadata['segments'] if s['interest'] >= 0.5)),
            'activities': sorted(set(s['activity'] for s in metadata['segments'])),
            'tags': sorted(set(tag for s in metadata['segments'] for tag in s['tags']))
        },
        'segments': []
    }
    
    # Build segments
    for i, seg in enumerate(metadata['segments'], start=1):
        speech = get_speech_for_segment(whisper, seg['start'], seg['end'])
        
        index['segments'].append({
            'id': i,
            'start_sec': seg['start'],
            'end_sec': seg['end'],
            'duration_sec': round(seg['end'] - seg['start'], 2),
            'activity': seg['activity'],
            'primary_action': seg['action'],
            'key_events': seg['events'],
            'interest': seg['interest'],
            'speech': speech,
            'queryable_tags': seg['tags'],
            'useful_for_editing': seg['interest'] >= 0.5
        })
    
    # Build master queries
    index['master_queries'] = {
        'all_riding': [i for i, s in enumerate(index['segments'], 1) if 'riding' in s['activity']],
        'all_explaining': [i for i, s in enumerate(index['segments'], 1) if s['activity'] == 'talking-to-camera'],
        'all_setup': [i for i, s in enumerate(index['segments'], 1) if 'setup' in s['activity'] or 'assembly' in s['activity']],
        'high_interest': [i for i, s in enumerate(index['segments'], 1) if s['interest'] >= 0.6],
        'best_clips_for_montage': [i for i, s in enumerate(index['segments'], 1) if s['interest'] >= 0.6 and s['useful_for_editing']]
    }
    
    return index

# Build indices
VIDEOS = {
    'GH010231': ANALYSIS['GH010231.MP4'],
    'GH010232': ANALYSIS['GH010232.MP4'],
    'IMG_0230': ANALYSIS['IMG_0230.MOV'],
}

master = {
    'project': 'V-Splice Phase 1',
    'videos': [],
    'total_duration_sec': 0,
    'queryable_activities': set(),
    'all_tags': set(),
    'last_updated': '2026-03-13T10:19:00Z'
}

for base, meta in VIDEOS.items():
    idx = build_index(base, meta)
    
    # Write individual index
    output = test / f'{base}_index.json'
    with open(output, 'w') as f:
        json.dump(idx, f, indent=2)
    print(f'✓ {output.name}')
    
    # Accumulate master index data
    master['videos'].append({
        'file': idx['metadata']['file'],
        'type': idx['metadata']['type'],
        'duration_sec': idx['metadata']['duration_sec'],
        'peak_interest': max(s['interest'] for s in idx['segments']),
        'index': f'{base}_index.json'
    })
    master['total_duration_sec'] += idx['metadata']['duration_sec']
    master['queryable_activities'].update(idx['summary']['activities'])
    master['all_tags'].update(idx['summary']['tags'])

# Write master index
master['queryable_activities'] = sorted(list(master['queryable_activities']))
master['all_tags'] = sorted(list(master['all_tags']))

with open(test / 'v_splice_master_index.json', 'w') as f:
    json.dump(master, f, indent=2)
print(f'✓ v_splice_master_index.json')
print()
print(f'Phase 1 complete: {len(master["videos"])} videos indexed')

EOF
