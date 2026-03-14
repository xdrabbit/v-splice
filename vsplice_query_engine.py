#!/usr/bin/env python3
"""
V-Splice Phase 2 Query Engine

Search across indexed videos by activity, tags, interest, timestamps, or speech.
Returns matched segments ready for Phase 3 assembly.
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class QueryResult:
    """Single matched segment"""
    video_file: str
    segment_id: int
    start_sec: float
    end_sec: float
    duration_sec: float
    activity: str
    primary_action: str
    interest: float
    speech: str
    tags: List[str]
    score: float  # relevance score for ranking

class VSliceQueryEngine:
    """Query engine for V-Splice Phase 1 indices"""
    
    def __init__(self, test_dir: str = './test'):
        self.test_dir = Path(test_dir)
        self.master = None
        self.indices = {}
        self.load_indices()
    
    def load_indices(self):
        """Load master index and all video indices"""
        master_path = self.test_dir / 'v_splice_master_index.json'
        with open(master_path) as f:
            self.master = json.load(f)
        
        # Load each video index
        for video_meta in self.master['videos']:
            idx_path = self.test_dir / video_meta['index']
            with open(idx_path) as f:
                self.indices[video_meta['index']] = json.load(f)
        
        print(f'✓ Loaded {len(self.indices)} video indices')
        print(f'  Total duration: {self.master["total_duration_sec"]:.1f}s')
        print(f'  Activities: {len(self.master["queryable_activities"])}')
        print(f'  Tags: {len(self.master["all_tags"])}')
    
    def query(self, 
              activity: Optional[List[str]] = None,
              tags: Optional[List[str]] = None,
              min_interest: float = 0.0,
              max_interest: float = 1.0,
              speech_contains: Optional[str] = None,
              duration_range: Optional[tuple] = None,
              video_type: Optional[str] = None,
              sort_by: str = 'interest',
              limit: Optional[int] = None) -> List[QueryResult]:
        """
        Query segments across all videos.
        
        Args:
            activity: List of activity types to match (OR logic)
            tags: List of tags to match (AND logic - all must be present)
            min_interest: Minimum interest score (0.0-1.0)
            max_interest: Maximum interest score (0.0-1.0)
            speech_contains: Substring to find in transcript
            duration_range: Tuple of (min_sec, max_sec) for segment duration
            video_type: Filter by video type (riding, assembly, etc.)
            sort_by: 'interest', 'duration', 'timestamp', 'relevance'
            limit: Max results to return
        
        Returns:
            List of QueryResult objects
        """
        results = []
        
        for idx_file, index in self.indices.items():
            # Check video type filter
            if video_type and index['metadata']['type'] != video_type:
                continue
            
            video_file = index['metadata']['file']
            
            for segment in index['segments']:
                # Activity filter (OR: any match)
                if activity:
                    if segment['activity'] not in activity:
                        continue
                
                # Interest filter
                if not (min_interest <= segment['interest'] <= max_interest):
                    continue
                
                # Tags filter (AND: all must match)
                if tags:
                    seg_tags = set(segment['queryable_tags'])
                    if not all(tag in seg_tags for tag in tags):
                        continue
                
                # Speech filter
                if speech_contains:
                    if speech_contains.lower() not in segment['speech']['text'].lower():
                        continue
                
                # Duration filter
                if duration_range:
                    dur = segment['end_sec'] - segment['start_sec']
                    if not (duration_range[0] <= dur <= duration_range[1]):
                        continue
                
                # Calculate relevance score for sorting
                relevance = segment['interest']
                if speech_contains and speech_contains.lower() in segment['speech']['text'].lower():
                    relevance += 0.1  # Boost if speech matches
                
                result = QueryResult(
                    video_file=video_file,
                    segment_id=segment['id'],
                    start_sec=segment['start_sec'],
                    end_sec=segment['end_sec'],
                    duration_sec=segment['duration_sec'],
                    activity=segment['activity'],
                    primary_action=segment['primary_action'],
                    interest=segment['interest'],
                    speech=segment['speech']['text'],
                    tags=segment['queryable_tags'],
                    score=relevance
                )
                results.append(result)
        
        # Sort
        if sort_by == 'interest':
            results.sort(key=lambda r: r.interest, reverse=True)
        elif sort_by == 'duration':
            results.sort(key=lambda r: r.duration_sec, reverse=True)
        elif sort_by == 'timestamp':
            results.sort(key=lambda r: (r.video_file, r.start_sec))
        elif sort_by == 'relevance':
            results.sort(key=lambda r: r.score, reverse=True)
        
        # Limit
        if limit:
            results = results[:limit]
        
        return results
    
    def show_results(self, results: List[QueryResult], show_speech: bool = True):
        """Pretty-print query results"""
        if not results:
            print("No results found.")
            return
        
        print(f"\n{len(results)} segment(s) matched:\n")
        
        for i, r in enumerate(results, 1):
            duration = r.end_sec - r.start_sec
            print(f"{i}. {r.video_file} [{r.start_sec:.0f}s-{r.end_sec:.0f}s] ({duration:.0f}s)")
            print(f"   Activity: {r.activity} | Interest: {r.interest:.1f}")
            print(f"   Action: {r.primary_action}")
            print(f"   Tags: {', '.join(r.tags)}")
            if show_speech and r.speech != '[no speech detected]':
                speech_preview = r.speech[:80] + ('...' if len(r.speech) > 80 else '')
                print(f"   Speech: \"{speech_preview}\"")
            print()
    
    # Convenience methods for common queries
    
    def find_all_riding(self) -> List[QueryResult]:
        """Find all riding segments"""
        return self.query(activity=['riding-attempt', 'riding-successful'])
    
    def find_best_clips(self, min_duration: float = 0) -> List[QueryResult]:
        """Find high-interest clips worth editing"""
        return self.query(
            min_interest=0.6,
            duration_range=(min_duration, 600) if min_duration else (0, 600),
            sort_by='interest'
        )
    
    def find_wipeouts(self) -> List[QueryResult]:
        """Find struggle/fall moments"""
        return self.query(
            tags=['struggle', 'attempt'],
            min_interest=0.5,
            sort_by='interest'
        )
    
    def find_by_location(self, location: str) -> List[QueryResult]:
        """Find segments by location tag"""
        return self.query(tags=[location.lower()])
    
    def find_successful_moments(self) -> List[QueryResult]:
        """Find success/highlight moments"""
        return self.query(
            activity=['riding-successful'],
            min_interest=0.6
        )
    
    def find_assembly_steps(self) -> List[QueryResult]:
        """Find assembly/hardware steps"""
        return self.query(
            activity=['assembly'],
            sort_by='timestamp'
        )
    
    def find_by_speaker_topic(self, speaker: str, topic_words: List[str]) -> List[QueryResult]:
        """Find segments where speaker discusses topic"""
        # Multi-word topic search
        results = []
        for word in topic_words:
            results.extend(self.query(speech_contains=word))
        # Deduplicate
        seen = set()
        unique = []
        for r in results:
            key = (r.video_file, r.segment_id)
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return sorted(unique, key=lambda r: r.interest, reverse=True)
    
    def stats(self):
        """Show index statistics"""
        print("\n=== V-Splice Phase 1 Index Statistics ===\n")
        print(f"Total videos: {len(self.indices)}")
        print(f"Total duration: {self.master['total_duration_sec']:.1f} seconds ({self.master['total_duration_sec']/60:.1f} min)")
        print(f"Total segments: {sum(len(idx['segments']) for idx in self.indices.values())}")
        print()
        print(f"Activities: {', '.join(self.master['queryable_activities'])}")
        print()
        print(f"Tags: {', '.join(self.master['all_tags'][:10])}...")
        print()
        
        # Interest distribution
        all_interests = []
        for idx in self.indices.values():
            for seg in idx['segments']:
                all_interests.append(seg['interest'])
        
        if all_interests:
            avg = sum(all_interests) / len(all_interests)
            print(f"Interest scores: avg={avg:.2f}, min={min(all_interests):.1f}, max={max(all_interests):.1f}")
        print()


def main():
    """Example usage"""
    engine = VSliceQueryEngine()
    
    print("\n" + "="*70)
    print("V-SPLICE QUERY ENGINE")
    print("="*70)
    
    engine.stats()
    
    # Example: Find the wipeout
    print("\n>>> Query: Find all wipeout/struggle moments")
    wipeouts = engine.find_wipeouts()
    engine.show_results(wipeouts)
    
    # Example: Find best clips
    print("\n>>> Query: Find best high-interest clips for montage")
    best = engine.find_best_clips(min_duration=10)
    engine.show_results(best, show_speech=False)
    
    # Example: Find riding
    print("\n>>> Query: Find all riding segments")
    riding = engine.find_all_riding()
    engine.show_results(riding[:3], show_speech=False)  # First 3
    print(f"... and {len(riding) - 3} more" if len(riding) > 3 else "")
    
    # Example: Custom query
    print("\n>>> Query: Assembly sections (for tutorial)")
    assembly = engine.find_assembly_steps()
    engine.show_results(assembly)
    
    # Example: By interest
    print("\n>>> Query: All segments with interest >= 0.6")
    high_value = engine.query(min_interest=0.6)
    engine.show_results(high_value[:5], show_speech=False)
    print(f"... {len(high_value)} total segments" if len(high_value) > 5 else "")


if __name__ == '__main__':
    main()
