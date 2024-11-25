import json
import logging
import os
import re
from typing import Dict, List, TypedDict, Annotated, Optional, Union, AsyncIterator, Any, AsyncGenerator
from dotenv import load_dotenv
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field, ValidationError, validator

from models import Course, Module, Session, Section, Assessment, Question

load_dotenv()

# Configure logging with more detail
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('course_generator.log')
    ]
)

logger = logging.getLogger(__name__)

# Initialize LLM with specific model settings
try:
    llm = ChatOllama(
        model="llama3.2",
        temperature=0.7,
        top_k=50,
        top_p=0.9,
    )
    logger.info("Successfully initialized LLM")
except Exception as e:
    logger.error(f"Error initializing LLM: {str(e)}", exc_info=True)
    raise

class CourseState(TypedDict):
    """Represents the current state of course generation"""
    topic: str
    language: str
    current_stage: str
    course_plan: Dict
    current_module: Dict
    current_session: Dict
    total_modules: int
    current_module_number: int
    total_sessions: int
    current_session_number: int
    errors: List[str]
    status: str  # Add status field for progress updates

class AgentState(TypedDict):
    """State type for the course generation workflow"""
    topic: str
    language: str
    current_stage: str
    status: str
    error: Optional[str]
    retries: int
    completed: bool
    course_outline: Optional[Dict]
    modules: Optional[List[Dict]]
    course: Optional[Dict]

# Global state management
_current_state = None

def get_current_state() -> Dict:
    """Get the current state of course generation"""
    global _current_state
    if _current_state is None:
        _current_state = {
            "topic": "",
            "language": "",
            "current_stage": "init",
            "course_plan": {},
            "current_module": {},
            "current_session": {},
            "total_modules": 0,
            "current_module_number": 0,
            "total_sessions": 0,
            "current_session_number": 0,
            "errors": [],
            "status": "Initializing"
        }
    return _current_state

def update_state(new_state: Dict):
    """Update the current state"""
    global _current_state
    _current_state = new_state

def reset_state():
    """Reset the state to initial values"""
    global _current_state
    _current_state = None

# Define Pydantic models for validation
class Section(BaseModel):
    section_number: str
    title: str
    content: str

    @validator('content')
    def validate_content(cls, v):
        if not v or len(v.split()) < 100:  # Rough estimate for "several paragraphs"
            raise ValueError('Content must contain several paragraphs of instructional text')
        return v

class Question(BaseModel):
    type: str
    text: str
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    correct_answers: Optional[List[str]] = None

class Assessment(BaseModel):
    questions: List[Question]

    @validator('questions')
    def validate_questions(cls, v):
        if len(v) != 10:
            raise ValueError('Each assessment must have exactly 10 questions')
        # Ensure we have a mix of multiple choice and free form
        question_types = [q.type for q in v]
        if 'multiple_choice' not in question_types or 'free_form' not in question_types:
            raise ValueError('Assessment must include both multiple choice and free form questions')
        return v

class Session(BaseModel):
    session_number: str
    title: str
    description: str
    learning_objectives: List[str]
    sections: List[Section]
    assessment: Assessment

    @validator('learning_objectives')
    def validate_learning_objectives(cls, v):
        if not v or len(v) < 1:
            raise ValueError('At least one learning objective is required')
        return v

    @validator('sections')
    def validate_sections(cls, v):
        if not v or len(v) < 1:
            raise ValueError('At least one section is required')
        return v

    @validator('assessment')
    def validate_assessment(cls, v):
        if not v.questions or len(v.questions) < 10:
            raise ValueError('At least 10 assessment questions are required')
        return v

class Module(BaseModel):
    module_number: str
    title: str
    description: str
    objectives: List[str]
    exercises: List[str]
    sessions: List[Session]

    @validator('sessions')
    def validate_sessions(cls, v):
        if not v or len(v) < 1:
            raise ValueError('At least one session is required')
        return v

class CoursePlan(BaseModel):
    title: str
    description: str
    modules: List[Module]

    @validator('modules')
    def validate_modules(cls, v):
        if not v or len(v) < 1:
            raise ValueError('At least one module is required')
        return v

def validate_course_plan(plan_dict: dict) -> dict:
    """Validate the course plan structure using Pydantic models"""
    try:
        course_plan = CoursePlan(**plan_dict)
        return course_plan.dict()
    except ValidationError as e:
        logger.error(f"Course plan validation failed: {str(e)}")
        raise ValueError(f"Invalid course plan structure: {str(e)}")

def parse_module_outline(outline: str) -> List[Dict]:
    """Parse the module outline into a structured format."""
    modules = []
    current_module = None
    current_section = None  # Track current section (Title, Description, etc.)
    
    for line in outline.split('\n'):
        line = line.strip()
        if not line or line.startswith('**') or line.startswith('---'):
            continue
            
        # Match module headers (e.g., "### Module 1: Introduction to Async Programming")
        module_match = re.match(r'^#{1,3}\s*Module\s+(\d+)[:\.]\s*(.+)$', line)
        if module_match:
            if current_module:
                modules.append(current_module)
            current_module = {
                "number": module_match.group(1),
                "title": module_match.group(2).strip(),
                "description": "",
                "objectives": [],
                "exercises": []
            }
            current_section = None
            continue
        
        # Match section headers (e.g., "#### Title:", "#### Description and Key Points:")
        if line.startswith('####'):
            section_name = line.replace('#', '').strip().lower()
            if 'title:' in section_name:
                current_section = 'title'
            elif 'description' in section_name:
                current_section = 'description'
            elif 'learning objectives' in section_name or 'objectives' in section_name:
                current_section = 'objectives'
            elif 'hands-on exercise' in section_name or 'exercise' in section_name:
                current_section = 'exercises'
            continue
        
        # Process content based on current section
        if current_module and current_section:
            # Clean up bullet points and other markdown
            content = line.lstrip('*+-• \t')
            if content:
                if current_section == 'description':
                    if current_module["description"]:
                        current_module["description"] += " "
                    current_module["description"] += content
                elif current_section == 'objectives':
                    if content.startswith('Learning Objectives:'):
                        continue
                    current_module["objectives"].append(content)
                elif current_section == 'exercises':
                    current_module["exercises"].append(content)
    
    # Add the last module
    if current_module:
        modules.append(current_module)
    
    logger.debug(f"Parsed {len(modules)} modules")
    for module in modules:
        logger.debug(f"Module {module['number']}: {module['title']}")
        logger.debug(f"Description: {module['description']}")
        logger.debug(f"Objectives: {module['objectives']}")
        logger.debug(f"Exercises: {module['exercises']}")
    
    return modules

async def create_course_outline(topic: str, language: str = "English") -> Dict[str, Any]:
    """Create a high-level course outline with modules and prerequisites"""
    try:
        # Create the outline prompt
        outline_prompt = f"""
        Create a focused course outline for the topic: {topic}.
        Language: {language}
        
        Create exactly 2-3 modules that cover the essential concepts.
        For each module, use this exact markdown format:
        
        ### Module [number]: [Title]
        #### Title: [Descriptive Title]
        #### Description and Key Points:
        [Detailed description of the module's content and purpose]
        
        * Learning Objectives:
            + [Objective 1]
            + [Objective 2]
            + [Objective 3]
        
        #### Hands-on Exercise:
        [Description of a practical exercise that applies the module's concepts]
        
        Make sure each module includes:
        1. A clear, numbered title (1-5 only)
        2. A descriptive subtitle
        3. A comprehensive description
        4. 3-5 specific learning objectives
        5. A hands-on exercise
        
        Important: Create no more than 5 modules total.
        """
        
        # Get response from LLM
        messages = [
            SystemMessage(content="""You are an expert curriculum designer specializing in creating focused, structured learning content.
            Always create between 3-5 modules total, no more and no less."""),
            HumanMessage(content=outline_prompt)
        ]
        
        response = await llm.ainvoke(messages)
        logger.debug(f"LLM Response for course outline: {response.content}")
        
        # Parse the outline into a structured format
        modules = parse_module_outline(response.content)
        
        if len(modules) > 5:
            logger.warning(f"Got {len(modules)} modules, truncating to 5")
            modules = modules[:5]
        
        # Create the course outline
        course_outline = {
            "topic": topic,
            "language": language,
            "description": f"A comprehensive course on {topic}",
            "prerequisites": [],  # Can be enhanced later
            "modules": modules
        }
        
        return course_outline
        
    except Exception as e:
        logger.error(f"Error creating course outline: {str(e)}", exc_info=True)
        raise

async def create_course_plan(topic: str, language: str = "English") -> Dict[str, Any]:
    """Create a detailed course plan with modules and sessions"""
    try:
        logger.info(f"Creating course plan for topic: {topic}")
        
        # Get the course outline
        course_outline = await create_course_outline(topic, language)
        logger.debug(f"Course outline: {course_outline}")
        
        # Initialize course structure
        course_plan = {
            "topic": topic,
            "language": language,
            "description": course_outline.get("description", ""),
            "prerequisites": course_outline.get("prerequisites", []),
            "modules": []
        }
        
        # Process each module
        for module in course_outline.get("modules", []):
            logger.debug(f"Processing module: {module}")
            
            # Generate detailed module content
            module_content = await create_module_content(
                module_info=module,
                language=language
            )
            
            # Add module to course plan
            course_plan["modules"].append(module_content)
            
            logger.debug(f"Added module {module['number']} to course plan")
        
        return course_plan
        
    except Exception as e:
        logger.error(f"Error in create_course_plan: {str(e)}", exc_info=True)
        raise

async def create_module_content(module_info: Dict[str, Any], language: str) -> Dict[str, Any]:
    """Generate detailed content for a module"""
    try:
        logger.debug(f"Creating content for module: {module_info.get('title', '')}")
        
        # Create the module prompt
        module_prompt = f"""
        Create detailed content for Module: {module_info['title']}
        Language: {language}
        
        Description: {module_info['description']}
        
        Learning Objectives:
        {chr(10).join(f"- {obj}" for obj in module_info['objectives'])}
        
        Create the following:
        1. Detailed module overview
        2. Key concepts (3-5 main points)
        3. Learning path recommendations
        4. Session breakdown (2-3 sessions)
        5. Practical exercises
        
        For each session, include:
        - Clear title that reflects the content
        - Brief description of what will be covered
        - Learning objectives for that session
        
        Format the content using markdown with clear section headers.
        Make the content engaging, clear, and focused on practical understanding.
        """
        
        # Get response from LLM
        messages = [
            SystemMessage(content="""You are an expert educator creating focused, practical learning content.
            Create content that is clear, engaging, and builds understanding step by step.
            Use markdown formatting for better readability."""),
            HumanMessage(content=module_prompt)
        ]
        
        response = await llm.ainvoke(messages)
        logger.debug(f"LLM Response for module content: {response.content}")
        
        # Parse the content
        sections = parse_section_content(response.content)
        
        # Create session outlines
        session_prompt = f"""
        Create 2-3 focused sessions for the module: {module_info['title']}
        Language: {language}
        
        For each session, provide:
        1. Session number and title
        2. Clear description of content
        3. Learning objectives (2-3 specific objectives)
        4. Estimated duration
        
        Format as a structured list that can be easily parsed.
        """
        
        messages = [
            SystemMessage(content="""You are an expert in curriculum design.
            Create focused, achievable learning sessions that build on each other.
            Keep the content practical and engaging."""),
            HumanMessage(content=session_prompt)
        ]
        
        session_response = await llm.ainvoke(messages)
        logger.debug(f"LLM Response for session outline: {session_response.content}")
        
        # Parse session outlines
        sessions = parse_session_outline(session_response.content)
        
        # Format the module content
        module_content = {
            "module_number": module_info.get("number", "1"),
            "title": module_info["title"],
            "description": module_info["description"],
            "objectives": module_info["objectives"],
            "sections": sections,
            "sessions": sessions
        }
        
        return module_content
        
    except Exception as e:
        logger.error(f"Error creating module content: {str(e)}", exc_info=True)
        raise

async def create_session_content(module_number: str, session_number: str, title: str, language: str) -> Dict:
    """Generate content for a session"""
    try:
        # Update state to indicate session generation
        state = get_current_state()
        state["current_stage"] = "session_generation"
        update_state(state)
        
        logger.debug(f"Requesting content for session {session_number} in module {module_number}")
        
        # Create the session prompt
        session_prompt = f"""
        Create detailed content for Session {session_number} of Module {module_number}: {title}
        Language: {language}
        
        Include the following sections:
        1. Introduction and Overview
        2. Key Concepts (3-5 main points)
        3. Detailed Explanations
        4. Examples (if relevant)
        5. Practice Exercises (2-3 exercises)
        6. Additional Resources
        
        Format the content using markdown with clear section headers.
        Make the content engaging, clear, and focused on practical understanding.
        """
        
        # Get response from LLM
        messages = [
            SystemMessage(content="""You are an expert educator creating focused, practical learning content.
            Create content that is clear, engaging, and builds understanding step by step.
            Use markdown formatting for better readability."""),
            HumanMessage(content=session_prompt)
        ]
        
        response = await llm.ainvoke(messages)
        logger.debug(f"LLM Response for session content: {response.content}")
        
        # Parse the content
        sections = parse_section_content(response.content)
        
        # Create assessment for the session
        assessment_prompt = f"""
        Create an assessment for Session {session_number} of Module {module_number}: {title}
        Language: {language}
        
        Create 5 questions that test understanding of the key concepts.
        Include a mix of:
        - Multiple choice questions
        - Short answer questions
        - Practical application questions
        
        For each question, provide:
        1. The question text
        2. The correct answer
        3. Explanation of why it's correct

        Do not include any other content other than the questions and answers.
        """
        
        messages = [
            SystemMessage(content="""You are an expert in creating effective assessments.
            Create questions that test both understanding and practical application.
            Make questions clear and unambiguous."""),
            HumanMessage(content=assessment_prompt)
        ]
        
        assessment_response = await llm.ainvoke(messages)
        logger.debug(f"LLM Response for assessment: {assessment_response.content}")
        
        # Format the session content
        session_content = {
            "session_number": session_number,
            "title": title,
            "module_number": module_number,
            "language": language,
            "sections": sections,
            "assessment": {
                "questions": parse_assessment_content(assessment_response.content)
            }
        }
        
        return session_content
        
    except Exception as e:
        logger.error(f"Error creating session content: {str(e)}", exc_info=True)
        raise

def parse_section_content(content: str) -> List[Dict[str, Any]]:
    """Parse section content from LLM response"""
    try:
        sections = []
        current_section = None
        current_list = []
        
        for line in content.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Check for section headers (markdown style)
            if line.startswith('#'):
                if current_section:
                    current_section['content'] = '\n'.join(current_list)
                    sections.append(current_section)
                    current_list = []
                
                # Create new section
                current_section = {
                    'title': line.lstrip('#').strip(),
                    'content': '',
                    'subsections': []
                }
            
            # Check for subsection headers
            elif line.startswith('##'):
                if current_list:
                    if current_section:
                        current_section['subsections'].append({
                            'title': line.lstrip('#').strip(),
                            'content': '\n'.join(current_list)
                        })
                    current_list = []
            
            # Add line to current content
            else:
                current_list.append(line)
        
        # Add the last section
        if current_section and current_list:
            current_section['content'] = '\n'.join(current_list)
            sections.append(current_section)
        
        logger.debug(f"Parsed {len(sections)} sections")
        return sections
        
    except Exception as e:
        logger.error(f"Error parsing section content: {str(e)}", exc_info=True)
        raise

def parse_session_outline(outline: str) -> List[Dict]:
    """Parse the session outline into a structured format."""
    sessions = []
    current_session = None
    current_section = None  # Track which section we're in
    
    try:
        # Split into lines and process
        lines = outline.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check for session header
            if line.startswith("**Session"):
                # Save previous session if it exists
                if current_session and current_session.get("title"):
                    sessions.append(current_session)
                
                # Extract session number and title
                parts = line.strip("*").strip().split(":", 1)
                if len(parts) == 2:
                    session_info = parts[0].strip()
                    title = parts[1].strip()
                    
                    # Extract session number
                    number_match = re.search(r'\d+(\.\d+)?', session_info)
                    if number_match:
                        session_number = number_match.group(0)
                    else:
                        continue
                    
                    current_session = {
                        "session_number": session_number,
                        "title": title,
                        "description": "",
                        "key_concepts": [],
                        "visual_elements": [],
                        "resources": []
                    }
                    current_section = None
            
            elif current_session and line.startswith("* "):
                # Identify which section we're in
                if "Description:" in line:
                    current_section = "description"
                    current_session["description"] = line.split("Description:", 1)[1].strip()
                elif "Key Concepts:" in line:
                    current_section = "key_concepts"
                elif "Visual Elements:" in line:
                    current_section = "visual_elements"
                elif "Resources:" in line:
                    current_section = "resources"
            
            elif current_session and current_section and line.startswith(("+", "-", "\t+")):
                # Clean up the line content
                line_content = line.strip("+-\t").strip()
                
                # Add to appropriate section
                if current_section == "key_concepts":
                    current_session["key_concepts"].append(line_content)
                elif current_section == "visual_elements":
                    current_session["visual_elements"].append(line_content)
                elif current_section == "resources":
                    current_session["resources"].append(line_content)
        
        # Add the last session
        if current_session and current_session.get("title"):
            sessions.append(current_session)
        
        num_sessions = len(sessions)
        logger.info(f"Successfully parsed {num_sessions} sessions")
        
        # Log session details
        session_details = [f"{s['session_number']}: {s['title']}" for s in sessions]
        logger.debug(f"Session details: {session_details}")
        
        return sessions
        
    except Exception as e:
        logger.error(f"Error parsing session outline: {str(e)}", exc_info=True)
        raise

def should_continue(state: Dict) -> str:
    """Determine the next step in the workflow based on current state"""
    try:
        # Check if we've reached max retries
        if state.get("retries", 0) >= 5:
            logger.warning("Max retries reached, ending workflow")
            return "end"
            
        # Check for error state
        if state.get("error"):
            logger.error(f"Error detected: {state['error']}")
            return "end"
            
        # Check completion status
        if state.get("completed"):
            logger.info("Course generation completed successfully")
            return "end"
            
        # Check current stage
        current_stage = state.get("current_stage", "start")
        
        if current_stage == "start":
            return "create_outline"
        elif current_stage == "outline_created":
            return "create_modules"
        elif current_stage == "modules_created":
            return "create_sessions"
        elif current_stage == "sessions_created":
            return "finalize"
        else:
            logger.warning(f"Unknown stage: {current_stage}")
            return "end"
            
    except Exception as e:
        logger.error(f"Error in should_continue: {str(e)}", exc_info=True)
        state["error"] = str(e)
        return "end"

async def create_initial_state(state: Dict) -> Dict:
    """Create the initial state for course generation"""
    try:
        state.update({
            "current_stage": "start",
            "status": "Initializing course generation",
            "error": None,
            "retries": 0,
            "completed": False
        })
        return state
    except Exception as e:
        logger.error(f"Error in create_initial_state: {str(e)}", exc_info=True)
        state["error"] = str(e)
        return state

async def create_course_outline_state(state: Dict) -> Dict:
    """Create the course outline"""
    try:
        state["current_stage"] = "outline_creation"
        state["status"] = "Creating course outline"
        
        outline = await create_course_outline(state["topic"], state["language"])
        state["course_outline"] = outline
        state["current_stage"] = "outline_created"
        
        return state
    except Exception as e:
        logger.error(f"Error in create_course_outline_state: {str(e)}", exc_info=True)
        state["error"] = str(e)
        return state

async def create_module_content_state(state: Dict) -> Dict:
    """Create content for all modules"""
    try:
        state["current_stage"] = "module_creation"
        state["status"] = "Creating module content"
        
        modules = []
        for module in state["course_outline"]["modules"]:
            module_content = await create_module_content(
                module_info=module,
                language=state["language"]
            )
            modules.append(module_content)
        
        state["modules"] = modules
        state["current_stage"] = "modules_created"
        
        return state
    except Exception as e:
        logger.error(f"Error in create_module_content_state: {str(e)}", exc_info=True)
        state["error"] = str(e)
        return state

async def create_session_content_state(state: Dict) -> Dict:
    """Create content for all sessions in all modules"""
    try:
        state["current_stage"] = "session_creation"
        state["status"] = "Creating session content"
        
        for module in state["modules"]:
            sessions = []
            for session in module["sessions"]:
                session_content = await create_session_content(
                    module_number=module["module_number"],
                    session_number=session["session_number"],
                    title=session["title"],
                    language=state["language"]
                )
                sessions.append(session_content)
            module["sessions"] = sessions
        
        state["current_stage"] = "sessions_created"
        
        return state
    except Exception as e:
        logger.error(f"Error in create_session_content_state: {str(e)}", exc_info=True)
        state["error"] = str(e)
        return state

async def finalize_course_state(state: Dict) -> Dict:
    """Finalize the course generation"""
    try:
        state["current_stage"] = "finalizing"
        state["status"] = "Finalizing course"
        
        # Create the final course structure
        course = {
            "topic": state["topic"],
            "language": state["language"],
            "description": state["course_outline"]["description"],
            "prerequisites": state["course_outline"]["prerequisites"],
            "modules": state["modules"]
        }
        
        state["course"] = course
        state["completed"] = True
        state["current_stage"] = "completed"
        
        return state
    except Exception as e:
        logger.error(f"Error in finalize_course_state: {str(e)}", exc_info=True)
        state["error"] = str(e)
        return state

def end_workflow(state: Dict) -> Dict:
    """End the workflow and return final state"""
    try:
        if state.get("error"):
            state["status"] = f"Course generation failed: {state['error']}"
        elif state.get("completed"):
            state["status"] = "Course generation completed successfully"
        else:
            state["status"] = "Course generation ended"
        return state
    except Exception as e:
        logger.error(f"Error in end_workflow: {str(e)}", exc_info=True)
        state["error"] = str(e)
        return state

# Create the workflow
workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("start", create_initial_state)
workflow.add_node("create_outline", create_course_outline_state)
workflow.add_node("create_modules", create_module_content_state)
workflow.add_node("create_sessions", create_session_content_state)
workflow.add_node("finalize", finalize_course_state)
workflow.add_node("end", end_workflow)

# Add edges with conditions
workflow.add_conditional_edges(
    "start",
    should_continue,
    {
        "create_outline": "create_outline",
        "end": "end"
    }
)

workflow.add_conditional_edges(
    "create_outline",
    should_continue,
    {
        "create_modules": "create_modules",
        "end": "end"
    }
)

workflow.add_conditional_edges(
    "create_modules",
    should_continue,
    {
        "create_sessions": "create_sessions",
        "end": "end"
    }
)

workflow.add_conditional_edges(
    "create_sessions",
    should_continue,
    {
        "finalize": "finalize",
        "end": "end"
    }
)

workflow.add_conditional_edges(
    "finalize",
    should_continue,
    {
        "end": "end"
    }
)

# Set entry and exit points
workflow.set_entry_point("start")
workflow.set_finish_point("end")

# Compile the workflow
app = workflow.compile()

async def generate_course(topic: str, language: str = "English") -> AsyncGenerator[Dict[str, Any], None]:
    """Generate a course with proper structure validation"""
    try:
        logger.info("Creating course outline...")
        yield {"status": "📚 Creating course outline...", "progress": 10}
        
        # Generate initial outline
        outline = await generate_course_outline(topic, language)
        
        # Initialize course structure
        course = {
            "topic": topic,
            "language": language,
            "description": outline.get("description", ""),
            "prerequisites": outline.get("prerequisites", []),
            "modules": []
        }
        
        # Generate 2-3 modules
        module_count = 3
        module_titles = outline.get("modules", [])[:module_count]
        
        for module_idx in range(module_count):
            module_title = module_titles[module_idx] if module_idx < len(module_titles) else f"Module {module_idx + 1}"
            module = {
                "title": module_title,
                "description": outline.get("module_descriptions", {}).get(str(module_idx + 1), ""),
                "sessions": []
            }
            
            yield {
                "status": f"📘 Generating Module {module_idx + 1}: {module_title}",
                "progress": 20 + (module_idx * 20)
            }
            
            # Generate 3-5 sessions per module
            session_count = 4
            for session_idx in range(session_count):
                session_number = f"{module_idx + 1}.{session_idx + 1}"
                
                # Generate session content
                session_content = await create_session_content(session_number, topic, language)
                session_title = session_content.get("session_name", f"Session {session_number}")
                
                session = {
                    "session_number": session_number,
                    "title": session_title,
                    "description": session_content.get("description", ""),
                    "learning_objectives": session_content.get("learning_objectives", []),
                    "sections": []
                }
                
                yield {
                    "status": f"📝 Generating Session {session_number}: {session_title}",
                    "progress": 40 + int((module_idx * session_count + session_idx) / (module_count * session_count) * 30)
                }
                
                # Add sections from session content
                sections = session_content.get("sections", [])
                # Ensure 2-4 sections per session
                section_count = min(max(2, len(sections)), 4)
                
                for section_idx in range(section_count):
                    section_number = f"{session_number}.{section_idx + 1}"
                    section_data = sections[section_idx] if section_idx < len(sections) else {}
                    
                    # Generate section content if not present
                    if not section_data.get("section_content"):
                        section_prompt = f"""Create comprehensive content for section {section_number} of {session_title} about {topic} in {language}.
                        This section should:
                        1. Build on previous content
                        2. Include clear explanations and examples
                        3. Use markdown formatting for better readability
                        4. Focus on practical understanding
                        """
                        section_content = await generate_section_content(section_prompt)
                    else:
                        section_content = section_data["section_content"]
                    
                    section_title = section_data.get("section_name", f"Section {section_number}")
                    section = {
                        "section_number": section_number,
                        "title": section_title,
                        "content": section_content,
                        "examples": section_data.get("examples", []),
                        "key_concepts": section_data.get("key_concepts", []),
                        "references": section_data.get("references", [])
                    }
                    session["sections"].append(section)
                    
                    yield {
                        "status": f"✍️ Generating Section {section_number}: {section_title}",
                        "progress": 70 + int((module_idx * session_count * section_count + session_idx * section_count + section_idx) / (module_count * session_count * section_count) * 20)
                    }
                
                # Generate assessment
                yield {
                    "status": f"📋 Creating assessment for Session {session_number}: {session_title}",
                    "progress": 90 + int((module_idx * session_count + session_idx) / (module_count * session_count) * 10)
                }
                
                session["assessment"] = await generate_session_assessment(
                    session_number=session_number,
                    topic=topic,
                    language=language
                )
                
                module["sessions"].append(session)
            
            course["modules"].append(module)
        
        # Validate final course structure
        if not validate_course_structure(course):
            logger.error("Course validation failed")
            yield {
                "status": "❌ Error: Course validation failed. Please try again.",
                "progress": 100,
                "error": "Failed to generate valid course structure"
            }
            return
        
        yield {
            "status": "✅ Course generation complete!",
            "progress": 100,
            "course_state": course
        }
        
    except Exception as e:
        logger.error(f"Error generating course: {str(e)}")
        yield {
            "status": f"❌ Error generating course: {str(e)}",
            "progress": 100,
            "error": str(e)
        }

async def create_course_from_state(state: Dict) -> Dict:
    """Main function to create a course from the current state"""
    try:
        # Initialize state if needed
        if not state.get('course_plan'):
            logger.error("No course plan found in state")
            raise ValueError("No course plan found in state")
        
        total_modules = len(state['course_plan']['modules'])
        state['total_modules'] = total_modules
        
        # Process each module
        for module_index in range(total_modules):
            state['current_module_number'] = module_index
            current_module = state['course_plan']['modules'][module_index]
            
            # Update status with module progress
            status_msg = f"[Module {module_index + 1}/{total_modules}] Generating content for Module: {current_module.get('title', '')}"
            logger.info(status_msg)
            state['status'] = status_msg
            
            try:
                # Generate module content
                state = await generate_module_content(state)
                
                # Process each session in the module
                total_sessions = len(current_module.get('sessions', []))
                state['total_sessions'] = total_sessions
                
                for session_index in range(total_sessions):
                    state['current_session_number'] = session_index
                    current_session = current_module['sessions'][session_index]
                    
                    # Update status with session progress
                    status_msg = f"[Module {module_index + 1}/{total_modules}] Generating Session {session_index + 1}: {current_session.get('title', '')}"
                    logger.info(status_msg)
                    state['status'] = status_msg
                    
                    try:
                        state = await generate_session_content(state)
                    except Exception as e:
                        logger.error(f"Error generating session {session_index + 1}: {str(e)}")
                        state['errors'].append(f"Failed to generate session {session_index + 1}: {str(e)}")
                        continue
                
                # Update status after completing the module
                status_msg = f"[Module {module_index + 1}/{total_modules}] Completed module '{current_module['title']}'"
                logger.info(status_msg)
                state['status'] = status_msg
                
            except Exception as e:
                logger.error(f"Error generating module {module_index + 1}: {str(e)}")
                state['errors'].append(f"Failed to generate module {module_index + 1}: {str(e)}")
                continue
        
        # Create the final course structure
        course = {
            "topic": state["topic"],
            "language": state["language"],
            "description": state["course_outline"]["description"],
            "prerequisites": state["course_outline"]["prerequisites"],
            "modules": state["course_plan"].get("modules", [])
        }
        
        return course
        
    except Exception as e:
        logger.error(f"Error creating course from state: {str(e)}", exc_info=True)
        raise

def parse_assessment_content(content: str) -> Dict[str, Any]:
    """Parse assessment content from LLM response"""
    try:
        questions = []
        answers = []
        
        # Split content into lines and process each question
        lines = content.strip().split('\n')
        current_question = None
        current_answer = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Check if line starts with a number (new question)
            if re.match(r'^\d+\.', line):
                if current_question:
                    questions.append(current_question)
                    answers.append(current_answer)
                current_question = line
                current_answer = None
            elif line.lower().startswith(('answer:', 'correct answer:')):
                current_answer = line.split(':', 1)[1].strip()
        
        # Add the last question
        if current_question and current_answer:
            questions.append(current_question)
            answers.append(current_answer)
        
        return {
            "questions": questions,
            "answers": answers
        }
    except Exception as e:
        logger.error(f"Error parsing assessment content: {str(e)}")
        return {"questions": [], "answers": []}

async def generate_section_content(prompt: str) -> str:
    """Generate content for a section based on the given prompt"""
    try:
        messages = [
            SystemMessage(content="""You are an expert educator creating focused, practical learning content.
            Create content that is clear, engaging, and builds understanding step by step.
            Use markdown formatting for better readability."""),
            HumanMessage(content=prompt)
        ]
        
        response = await llm.ainvoke(messages)
        return response.content
    except Exception as e:
        logger.error(f"Error generating section content: {str(e)}")
        return "Content generation failed"

async def generate_session_assessment(session_number: str, topic: str, language: str) -> Dict[str, Any]:
    """Generate assessment questions for a session"""
    try:
        prompt = f"""
        Create an assessment for Session {session_number} about {topic} in {language}.
        
        Create 5 questions that test understanding of the key concepts.
        Include a mix of:
        - Multiple choice questions
        - Short answer questions
        - Practical application questions
        
        For each question, provide:
        1. The question text
        2. The correct answer
        3. Explanation of why it's correct

        Do not include any other content other than the questions and answers.
        """
        
        messages = [
            SystemMessage(content="""You are an expert in creating effective assessments.
            Create questions that test both understanding and practical application.
            Make questions clear and unambiguous."""),
            HumanMessage(content=prompt)
        ]
        
        response = await llm.ainvoke(messages)
        assessment = parse_assessment_content(response.content)
        
        return {
            "questions": assessment.get("questions", []),
            "answers": assessment.get("answers", [])
        }
    except Exception as e:
        logger.error(f"Error generating assessment: {str(e)}")
        return {"questions": [], "answers": []}

def validate_course_structure(course: Dict[str, Any]) -> bool:
    """Validate that the course follows the required structure"""
    try:
        # Check basic course structure
        if not isinstance(course, dict):
            logger.error("Course must be a dictionary")
            return False
        
        if 'modules' not in course:
            logger.error("Course must have modules")
            return False
        
        modules = course['modules']
        if not isinstance(modules, list):
            logger.error("Modules must be a list")
            return False
        
        # Check module count
        if not (2 <= len(modules) <= 3):
            logger.error(f"Course must have 2-3 modules, found {len(modules)}")
            return False
        
        # Check each module
        for i, module in enumerate(modules, 1):
            if not isinstance(module, dict):
                logger.error(f"Module {i} must be a dictionary")
                return False
            
            if 'sessions' not in module:
                logger.error(f"Module {i} must have sessions")
                return False
            
            sessions = module['sessions']
            if not isinstance(sessions, list):
                logger.error(f"Sessions in module {i} must be a list")
                return False
            
            # Check session count
            if not (3 <= len(sessions) <= 5):
                logger.error(f"Module {i} must have 3-5 sessions, found {len(sessions)}")
                return False
            
            # Check each session
            for j, session in enumerate(sessions, 1):
                if not isinstance(session, dict):
                    logger.error(f"Session {i}.{j} must be a dictionary")
                    return False
                
                if 'sections' not in session:
                    logger.error(f"Session {i}.{j} must have sections")
                    return False
                
                sections = session['sections']
                if not isinstance(sections, list):
                    logger.error(f"Sections in session {i}.{j} must be a list")
                    return False
                
                # Check section count
                if not (2 <= len(sections) <= 4):
                    logger.error(f"Session {i}.{j} must have 2-4 sections, found {len(sections)}")
                    return False
                
                # Validate section content
                for k, section in enumerate(sections, 1):
                    if not isinstance(section, dict):
                        logger.error(f"Section {i}.{j}.{k} must be a dictionary")
                        return False
                    
                    if not section.get('section_content'):
                        logger.error(f"Section {i}.{j}.{k} must have content")
                        return False
        
        return True
    
    except Exception as e:
        logger.error(f"Error validating course structure: {str(e)}")
        return False

async def generate_course(topic: str, language: str = "English") -> AsyncGenerator[Dict[str, Any], None]:
    """Generate a course with proper structure validation"""
    try:
        logger.info("Creating course outline...")
        yield {"status": "📚 Creating course outline...", "progress": 10}
        
        # Generate course outline
        course = {
            "topic": topic,
            "language": language,
            "modules": []
        }
        
        # Generate 2-3 modules
        module_count = 3
        for module_idx in range(module_count):
            module = {
                "title": f"Module {module_idx + 1}",
                "sessions": []
            }
            
            # Generate 3-5 sessions per module
            session_count = 4
            for session_idx in range(session_count):
                session_number = f"{module_idx + 1}.{session_idx + 1}"
                session = {
                    "title": f"Session {session_number}",
                    "session_number": session_number,
                    "sections": []
                }
                
                # Generate 2-4 sections per session
                section_count = 3
                for section_idx in range(section_count):
                    section = {
                        "section_number": f"{session_number}.{section_idx + 1}",
                        "title": f"Section {session_number}.{section_idx + 1}",
                        "content": ""
                    }
                    session["sections"].append(section)
                
                module["sessions"].append(session)
            
            course["modules"].append(module)
            yield {"status": f"Generated module {module_idx + 1} structure", "progress": 20 + (module_idx * 20)}
        
        # Generate content for each section
        total_sections = sum(len(s["sections"]) for m in course["modules"] for s in m["sessions"])
        current_section = 0
        
        for module in course["modules"]:
            for session in module["sessions"]:
                for section in session["sections"]:
                    current_section += 1
                    progress = 40 + int((current_section / total_sections) * 50)
                    
                    yield {
                        "status": f"Generating content for section {section['section_number']}",
                        "progress": progress
                    }
                    
                    # Generate section content
                    section_prompt = f"Generate comprehensive content for section {section['section_number']} about {topic} in {language}."
                    section["content"] = await generate_section_content(section_prompt)
                
                # Generate session assessment
                session["assessment"] = await generate_session_assessment(
                    session_number=session["session_number"],
                    topic=topic,
                    language=language
                )
        
        # Validate final course structure
        if not validate_course_structure(course):
            yield {
                "status": "Error: Invalid course structure",
                "progress": 100,
                "error": "Failed to generate valid course structure"
            }
            return
        
        yield {
            "status": "Course generation complete",
            "progress": 100,
            "course_state": course
        }
        
    except Exception as e:
        logger.error(f"Error generating course: {str(e)}")
        yield {
            "status": "Error generating course",
            "progress": 100,
            "error": str(e)
        }
