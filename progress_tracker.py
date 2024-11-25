import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class ProgressTracker:
    def __init__(self, storage_dir: str = "progress"):
        self.storage_dir = storage_dir
        self._ensure_storage_dir()
    
    def _ensure_storage_dir(self):
        """Ensure the storage directory exists"""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)
    
    def _get_progress_file(self, course_id: str) -> str:
        """Get the progress file path for a course"""
        return os.path.join(self.storage_dir, f"{course_id}_progress.json")
    
    def save_progress(self, course_id: str, progress_data: Dict[str, Any]) -> None:
        """Save progress data for a course"""
        try:
            file_path = self._get_progress_file(course_id)
            
            # Add timestamp
            progress_data['last_updated'] = datetime.now().isoformat()
            
            # Save the progress data
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Progress saved for course: {course_id}")
            
        except Exception as e:
            logger.error(f"Error saving progress: {str(e)}")
            raise
    
    def load_progress(self, course_id: str) -> Dict[str, Any]:
        """Load progress data for a course"""
        try:
            file_path = self._get_progress_file(course_id)
            if not os.path.exists(file_path):
                # Return default progress data
                return {
                    'course_id': course_id,
                    'current_module': 0,
                    'current_session': 0,
                    'completed_sessions': [],
                    'assessment_scores': {},
                    'last_updated': datetime.now().isoformat()
                }
            
            with open(file_path, 'r', encoding='utf-8') as f:
                progress_data = json.load(f)
            
            logger.info(f"Progress loaded for course: {course_id}")
            return progress_data
            
        except Exception as e:
            logger.error(f"Error loading progress: {str(e)}")
            return self.create_new_progress(course_id)
    
    def create_new_progress(self, course_id: str) -> Dict[str, Any]:
        """Create new progress data for a course"""
        progress_data = {
            'course_id': course_id,
            'current_module': 0,
            'current_session': 0,
            'completed_sessions': [],
            'assessment_scores': {},
            'last_updated': datetime.now().isoformat()
        }
        self.save_progress(course_id, progress_data)
        return progress_data
    
    def update_session_progress(self, course_id: str, module_idx: int, session_idx: int, 
                              completed: bool = True, score: Optional[float] = None) -> Dict[str, Any]:
        """Update progress for a specific session"""
        progress_data = self.load_progress(course_id)
        
        session_key = f"{module_idx}_{session_idx}"
        if completed:
            if session_key not in progress_data['completed_sessions']:
                progress_data['completed_sessions'].append(session_key)
        
        if score is not None:
            progress_data['assessment_scores'][session_key] = score
        
        progress_data['current_module'] = module_idx
        progress_data['current_session'] = session_idx
        progress_data['last_updated'] = datetime.now().isoformat()
        
        self.save_progress(course_id, progress_data)
        return progress_data
