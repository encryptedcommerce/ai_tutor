import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class CourseStorage:
    def __init__(self, storage_dir: str = "courses"):
        self.storage_dir = storage_dir
        self._ensure_storage_dir()
    
    def _ensure_storage_dir(self):
        """Ensure the storage directory exists"""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)
    
    def save_course(self, course_data: Dict[str, Any]) -> str:
        """Save course data and return the course ID"""
        try:
            # Validate course data
            if not isinstance(course_data, dict):
                raise ValueError("Course data must be a dictionary")
            
            if 'topic' not in course_data:
                raise ValueError("Course data must contain a 'topic' field")
            
            if not course_data.get('modules'):
                raise ValueError("Course data must contain 'modules'")
            
            # Generate a unique course ID
            course_id = f"{course_data['topic'].lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Create the course file path
            file_path = os.path.join(self.storage_dir, f"{course_id}.json")
            
            # Save the course data
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(course_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Course saved successfully: {course_id}")
            return course_id
            
        except Exception as e:
            logger.error(f"Error saving course: {str(e)}")
            raise

    def load_course(self, course_id: str) -> Optional[Dict[str, Any]]:
        """Load course data by ID"""
        try:
            file_path = os.path.join(self.storage_dir, f"{course_id}.json")
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                course_data = json.load(f)
            
            logger.info(f"Course loaded successfully: {course_id}")
            return course_data
            
        except Exception as e:
            logger.error(f"Error loading course: {str(e)}")
            return None

    def list_courses(self) -> Dict[str, Dict[str, Any]]:
        """List all available courses with their basic info"""
        courses = {}
        for file_name in os.listdir(self.storage_dir):
            if file_name.endswith('.json'):
                course_id = file_name[:-5]  # Remove .json extension
                try:
                    course_data = self.load_course(course_id)
                    if course_data:
                        courses[course_id] = {
                            'topic': course_data['topic'],
                            'language': course_data['language'],
                            'modules': len(course_data.get('modules', [])),
                            'created': course_id.split('_')[-2:]  # Extract date and time
                        }
                except Exception as e:
                    logger.error(f"Error loading course {course_id}: {str(e)}")
        return courses
