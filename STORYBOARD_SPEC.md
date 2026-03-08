# V-Splice Storyboard Specification
## Version 0.1 — March 2026

### Overview

The **storyboard** is the central data structure of V-Splice. It represents the user's creative intent as an ordered sequence of scenes, where each scene can be fulfilled by found footage, generated assets, or a mix of both.

Every operation in V-Splice flows through the storyboard:
- **Phase 1-2 (Search → Cut):** Query generates a storyboard where all scenes are `source: found`
- **Phase 3 (Story → Movie):** User provides a narrative; AI decomposes it into scenes, searches footage, generates what's missing

---

### Storyboard Schema

```json
{
  "schema_version": "0.1",
  "title": "Segway Day",
  "created_at": "2026-03-08T12:00:00",
  "author": "user | ai | hybrid",
  
  "narrative": {
    "summary": "A summer day unboxing and riding a Segway for the first time",
    "tone": "casual, fun, personal",
    "duration_target_sec": 120,
    "music_style": null
  },

  "sources": {
    "footage_folders": ["/path/to/video/library"],
    "generation_backends": ["comfyui", "runway", "dalle"]
  },

  "scenes": [
    {
      "id": "scene_01",
      "order": 1,
      "intent": "Show the Segway box arriving / first look",
      "search_query": "Segway Ninebot box unboxing packaging",
      
      "duration_target_sec": 10,
      "duration_min_sec": 5,
      "duration_max_sec": 20,
      
      "source": "found",
      "assets": [
        {
          "type": "footage",
          "file": "/path/to/IMG_0223.MOV",
          "start_sec": 18,
          "end_sec": 45,
          "description": "Ninebot S-Max box on red dolly in garage workshop",
          "score": 16.0,
          "matched_terms": ["segway", "ninebot", "box"]
        }
      ],
      
      "style": {
        "transition_in": "fade",
        "transition_out": "cut",
        "speed": 1.0,
        "effects": [],
        "text_overlay": null
      },
      
      "generation_prompt": null,
      "generation_params": null,
      "status": "fulfilled"
    },
    {
      "id": "scene_02",
      "order": 2,
      "intent": "Dramatic reveal — Segway emerges from packaging",
      "search_query": "unboxing foam packaging Segway parts",
      
      "duration_target_sec": 8,
      "duration_min_sec": 4,
      "duration_max_sec": 15,
      
      "source": "found",
      "assets": [
        {
          "type": "footage",
          "file": "/path/to/IMG_0225.MOV",
          "start_sec": 0,
          "end_sec": 118,
          "description": "Unboxing scene with foam packing and manual",
          "score": 9.6,
          "matched_terms": ["unboxing", "packaging", "segway"]
        }
      ],
      
      "style": {
        "transition_in": "cut",
        "transition_out": "crossfade",
        "speed": 1.5,
        "effects": ["slight_zoom"],
        "text_overlay": null
      },
      
      "generation_prompt": null,
      "generation_params": null,
      "status": "fulfilled"
    },
    {
      "id": "scene_03",
      "order": 3,
      "intent": "Close-up of assembly — hands working with tools",
      "search_query": "assembly hex bolts wrench Segway hardware",
      
      "duration_target_sec": 12,
      "duration_min_sec": 5,
      "duration_max_sec": 20,
      
      "source": "found",
      "assets": [
        {
          "type": "footage",
          "file": "/path/to/IMG_0231.MOV",
          "start_sec": 0,
          "end_sec": 8,
          "description": "Close-up hex key assembly of device housing",
          "score": 12.0
        },
        {
          "type": "footage",
          "file": "/path/to/IMG_0228.MOV",
          "start_sec": 0,
          "end_sec": 16,
          "description": "Inspecting assembly bracket on garage floor",
          "score": 18.0
        }
      ],
      
      "style": {
        "transition_in": "crossfade",
        "transition_out": "cut",
        "speed": 1.0,
        "effects": [],
        "text_overlay": null
      },
      
      "generation_prompt": null,
      "generation_params": null,
      "status": "fulfilled"
    },
    {
      "id": "scene_04",
      "order": 4,
      "intent": "First step onto the Segway — the moment of truth",
      "search_query": "stepping onto hoverboard testing balance",
      
      "duration_target_sec": 8,
      "duration_min_sec": 3,
      "duration_max_sec": 15,
      
      "source": "found",
      "assets": [
        {
          "type": "footage",
          "file": "/path/to/IMG_0227.MOV",
          "start_sec": 0,
          "end_sec": 16,
          "description": "Person stepping onto hoverboard footpad",
          "score": 27.6
        }
      ],
      
      "style": {
        "transition_in": "cut",
        "transition_out": "crossfade",
        "speed": 0.7,
        "effects": ["slow_motion_build"],
        "text_overlay": null
      },
      
      "generation_prompt": null,
      "generation_params": null,
      "status": "fulfilled"
    },
    {
      "id": "scene_05",
      "order": 5,
      "intent": "Riding the Segway outside — freedom, movement, fun",
      "search_query": "riding scooter outdoor driveway",
      
      "duration_target_sec": 30,
      "duration_min_sec": 15,
      "duration_max_sec": 60,
      
      "source": "found",
      "assets": [
        {
          "type": "footage",
          "file": "/path/to/GH010231.MP4",
          "start_sec": 195,
          "end_sec": 228,
          "description": "Man in helmet riding on driveway near trailer",
          "score": 21.0
        },
        {
          "type": "footage",
          "file": "/path/to/GH010232.MP4",
          "start_sec": 0,
          "end_sec": 532,
          "description": "Riding electric scooter near RV and travel trailer",
          "score": 28.8
        }
      ],
      
      "style": {
        "transition_in": "crossfade",
        "transition_out": "fade_to_black",
        "speed": 1.0,
        "effects": ["dynamic_speed"],
        "text_overlay": null
      },
      
      "generation_prompt": null,
      "generation_params": null,
      "status": "fulfilled"
    },
    {
      "id": "scene_06_example_generated",
      "order": 6,
      "intent": "Aerial shot pulling back to reveal the whole neighborhood",
      "search_query": "aerial drone neighborhood overhead",
      
      "duration_target_sec": 8,
      "duration_min_sec": 5,
      "duration_max_sec": 12,
      
      "source": "generate",
      "assets": [
        {
          "type": "generated_video",
          "file": null,
          "description": "Aerial drone shot pulling back from residential driveway to reveal suburban neighborhood with mountains in background, golden hour lighting",
          "backend": "runway",
          "generation_id": null
        }
      ],
      
      "style": {
        "transition_in": "crossfade",
        "transition_out": "fade_to_black",
        "speed": 0.8,
        "effects": ["cinematic_grade"],
        "text_overlay": "Summer 2023"
      },
      
      "generation_prompt": "Aerial drone shot slowly pulling back from a residential driveway where a man rides an electric scooter. Camera reveals suburban neighborhood with mountains in background. Golden hour, warm cinematic color grading. Smooth continuous motion.",
      "generation_params": {
        "backend": "runway",
        "model": "gen-3",
        "duration_sec": 8,
        "resolution": "1080p",
        "style_reference": "/path/to/GH010231.MP4",
        "style_reference_timestamp": 200
      },
      "status": "pending"
    }
  ],

  "assembly": {
    "output_resolution": "1920x1080",
    "output_fps": 30,
    "output_codec": "h264_nvenc",
    "color_grade": "match_source",
    "audio_track": null,
    "audio_ducking": true
  },

  "metadata": {
    "generated_by": "vsplice_query",
    "query": "Segway day story",
    "footage_clips_searched": 17,
    "scenes_total": 6,
    "scenes_found": 5,
    "scenes_generated": 1,
    "scenes_pending": 1
  }
}
```

---

### Key Design Decisions

#### 1. Scene Intent is King
Every scene starts with `intent` — a human-readable description of what this moment should convey. This drives both search AND generation. The search query is derived from intent but optimized for matching. The generation prompt is derived from intent but optimized for creation.

#### 2. Assets are Polymorphic
An asset can be:
- `footage` — found in user's library (file + start/end timestamps)
- `generated_image` — created by image gen (Stable Diffusion, DALL-E)
- `generated_video` — created by video gen (Runway, Sora, local)
- `generated_image_to_video` — image gen → video gen pipeline (img2vid)
- `audio` — generated or sourced music/SFX

Multiple assets per scene allows compositing (e.g., footage + overlay).

#### 3. Source Waterfall
When building a storyboard from a narrative:
1. **Search** footage library first
2. **Score** matches against scene intent
3. If score >= threshold → `source: found`
4. If score < threshold → `source: generate`, create generation prompt from intent
5. User can override any scene: force found, force generate, swap assets

#### 4. Style is Per-Scene
Each scene carries its own style block. This allows the storyboard to specify pacing, transitions, and effects at the creative level. The assembly engine reads these when building the final output.

#### 5. Status Lifecycle
```
pending → searching → fulfilled | generating → fulfilled | failed | skipped
```

#### 6. Storyboard as Checkpoint
A storyboard is saveable, resumable, editable. You can:
- Generate a storyboard, review it, tweak scenes, then render
- Re-render with different style settings
- Swap a found asset for a generated one (or vice versa)
- Share storyboards (they're just JSON)

---

### Phase Integration

| Phase | Storyboard Usage |
|-------|-----------------|
| **Phase 1** (Coarse query) | Auto-generated storyboard, all `source: found`, whole clips |
| **Phase 2** (Dense query) | Auto-generated storyboard, all `source: found`, precise segments |
| **Phase 3** (Story → Movie) | User narrative → AI decomposition → search + generate |

---

### What to Build Now (Phase 1-2 Compatibility)

1. **Storyboard generator** — takes query results (from vsplice_query) and wraps them in storyboard format
2. **Storyboard renderer** — takes a storyboard and produces the output video (replaces current splice functions)
3. **Storyboard save/load** — JSON file I/O
4. **Scene description quality** — ensure dense index descriptions are detailed enough to serve as generation prompts later

### What to Build Later (Phase 3)

1. **Narrative decomposer** — LLM breaks a story into scenes with intent + search queries
2. **Generation backends** — ComfyUI, Runway, DALL-E adapters
3. **Style consistency engine** — color matching, resolution normalization
4. **Audio layer** — music generation/selection, SFX, voice-over
5. **Storyboard editor UI** — drag/drop scenes, preview, edit intent, swap assets

---

### File Conventions

- Storyboards: `<folder>/storyboards/<name>.storyboard.json`
- Generated assets: `<folder>/generated/<scene_id>_<timestamp>.<ext>`
- Rendered output: `<folder>/output/<storyboard_name>_<timestamp>.mp4`
