from typing import List, Dict, Optional
from pydantic import BaseModel

class Section(BaseModel):
    title: str
    content: str
    diagram: Optional[str] = None  # Mermaid diagram code

class Question(BaseModel):
    question_text: str
    type: str  # "multiple_choice" or "free_form"
    options: Optional[List[str]] = None  # For multiple choice
    correct_answer: str
    explanation: str

class Assessment(BaseModel):
    questions: List[Question]
    passing_score: float = 0.9  # 90% mastery requirement

class Session(BaseModel):
    title: str
    sections: List[Section]
    assessment: Assessment
    completed: bool = False
    mastery_achieved: bool = False
    attempts: int = 0

class Module(BaseModel):
    title: str
    description: str
    sessions: List[Session]
    module_assessment: Assessment
    completed: bool = False
    mastery_achieved: bool = False

class Course(BaseModel):
    topic: str
    language: str
    modules: List[Module]
    current_module_index: int = 0
    current_session_index: int = 0
    completed: bool = False
