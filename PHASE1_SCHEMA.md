# V-Splice Phase 1 Index Schema

## Final Format (v1.0)

Each video gets a clean, queryable index file: `{VIDEO_BASE}_index.json`

```json
{
  "metadata": {
    "file": "GH010231.MP4",
    "duration_sec": 467.776,
    "type": "riding",
    "analysis_date": "2026-03-13",
    "models": {
      "activity_analysis": "Claude Opus 4.6",
      "transcription": "Whisper local",
      "transcript_confidence": "medium"
    }
  },
  
  "summary": {
    "title": "Garage setup and outdoor monologue with minimal actual riding",
    "primary_activity": "explaining/setup",
    "peak_interest_moment": "0-60s (garage intro) and 410-468s (riding back in)",
    "best_segment_for_editing": "410-468s",
    "estimated_useful_content_sec": 120,
    "activities": ["talking-to-camera", "setup-and-mount", "riding"],
    "tags": ["garage", "driveway", "monologue", "minimal-riding", "intro-style"]
  },
  
  "segments": [
    {
      "id": 1,
      "start_sec": 0,
      "end_sec": 60,
      "duration_sec": 60,
      "activity": "talking-to-camera",
      "primary_action": "Garage intro explaining ride plans",
      "key_events": [
        "helmet on",
        "Segway visible in background",
        "garage workshop setting"
      ],
      "interest": 0.5,
      "speech": {
        "text": "[monologue about Segway ride plans]",
        "confidence": "high",
        "speaker": "Tom",
        "duration_sec": 45
      },
      "queryable_tags": ["intro", "garage", "explaining"],
      "useful_for_editing": true
    },
    {
      "id": 2,
      "start_sec": 60,
      "end_sec": 120,
      "duration_sec": 60,
      "activity": "setup-and-mount",
      "primary_action": "Mounting Segway and maneuvering in garage doorway",
      "key_events": ["grabs Segway handlebars", "preparing to roll out of garage"],
      "interest": 0.4,
      "speech": {
        "text": "[mounting instructions/commentary]",
        "confidence": "medium",
        "speaker": "Tom",
        "duration_sec": 30
      },
      "queryable_tags": ["setup", "mounting", "transition"],
      "useful_for_editing": false
    },
    {
      "id": 3,
      "start_sec": 120,
      "end_sec": 180,
      "duration_sec": 60,
      "activity": "transition",
      "primary_action": "Rolling out of garage onto driveway",
      "key_events": ["exiting garage", "garage door open", "brick exterior visible"],
      "interest": 0.3,
      "speech": {
        "text": "[continuing monologue outdoors]",
        "confidence": "medium",
        "speaker": "Tom",
        "duration_sec": 45
      },
      "queryable_tags": ["transition", "outdoors", "driveway"],
      "useful_for_editing": false
    }
  ],
  
  "master_queries": {
    "all_riding": [],
    "all_explaining": [1, 2, 3],
    "all_setup": [2],
    "high_interest": [1],
    "best_clips_for_montage": []
  }
}
```

## Key Design Decisions

### Activity Types (Controlled Vocabulary)
- `talking-to-camera` — monologue/explaining
- `setup-and-mount` — preparing equipment
- `transition` — moving between locations
- `riding-attempt` — trying to ride, may fail
- `riding-successful` — smooth, confident riding
- `assembly` — building/installing hardware
- `testing` — feature testing, not full riding
- `explaining` — pointing out features/techniques
- `camera-setup` — repositioning camera or technical setup

### Interest Score (0.0-1.0)
- 0.0–0.2: Background/filler
- 0.2–0.4: Setup/necessary context
- 0.4–0.6: Active but not climactic
- 0.6–0.8: Good edit-worthy content
- 0.8–1.0: Peak moments, must-include

### Speech Confidence
- `high`: clear dialogue, no artifacts
- `medium`: some noise or unclear parts
- `low`: heavy artifacts, unreliable
- Filter transcripts by confidence when querying

### Queryable Tags
User-facing keywords for search:
- Locations: `garage`, `driveway`, `grass`, `concrete`
- Activities: `riding`, `explaining`, `setup`, `assembly`
- Emotional/narrative: `intro`, `climax`, `comedy`, `struggle`
- Technical: `close-up`, `wide-shot`, `helmet-cam`, `stationary-camera`

### Master Queries
Pre-computed query results for common searches:
- `all_riding`: segment IDs where actual riding occurs
- `all_explaining`: IDs with monologue/explanation
- `all_setup`: IDs with assembly/preparation
- `high_interest`: IDs with interest >= 0.6
- `best_clips_for_montage`: hand-curated best moments

## Why This Schema Works for Phase 2 & 3

**Phase 2 (Query):**
```
User: "Show me just the riding"
→ Lookup master_queries.all_riding → segments [7, 9]
→ Render those 2 segments + transcripts
```

**Phase 3 (Generation):**
```
User: "Create a 30-second clip of setup then riding"
→ Query: activity in ["setup", "riding"] + interest >= 0.5
→ Results: [seg 2 (setup), seg 7 (riding)]
→ Stitch: 2 + 7 = clean narrative flow
→ Generate: fill any gaps or extend
```

## Master Index (v_splice_master_index.json)

Links all videos:
```json
{
  "project": "V-Splice Phase 1",
  "videos": [
    { "file": "GH010231.MP4", "type": "riding", "duration_sec": 467.8, "peak_interest": 0.5, "index": "GH010231_index.json" },
    { "file": "GH010232.MP4", "type": "riding", "duration_sec": 532.0, "peak_interest": 0.8, "index": "GH010232_index.json" },
    { "file": "IMG_0230.MOV", "type": "assembly", "duration_sec": 47.5, "peak_interest": 0.6, "index": "IMG_0230_index.json" }
  ],
  "total_duration_sec": 1047.3,
  "queryable_activities": ["talking-to-camera", "setup", "riding", "assembly"],
  "all_tags": ["garage", "driveway", "grass", "riding", "explaining", "setup", "intro"],
  "last_updated": "2026-03-13T10:19:00Z"
}
```
