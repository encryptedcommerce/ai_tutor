import os
import logging
import gradio as gr
from typing import Dict, Any, Tuple, AsyncGenerator
from course_generator import generate_course
from course_storage import CourseStorage
from progress_tracker import ProgressTracker
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SessionState:
    def __init__(self):
        self.course = None
        self.course_id = None
        self.current_module_idx = 0
        self.current_session_idx = 0
        self.show_assessment = False
        self.storage = CourseStorage()
        self.progress = ProgressTracker()

state = SessionState()

def format_session_content(module: Dict[str, Any], session: Dict[str, Any], session_num: int) -> str:
    """Format session content for display"""
    return f"""# {module['title']} - Session {session_num}

{session.get('title', '')}

{session.get('description', '')}

Learning Objectives:
{chr(10).join('- ' + obj for obj in session.get('objectives', []))}

Duration: {session.get('duration', '45 minutes')}

Content:
{session.get('content', '')}
"""

def format_assessment(session: Dict[str, Any]) -> str:
    """Format assessment questions"""
    if not session.get('assessment'):
        return "No assessment available for this session."
    
    questions = session['assessment'].get('questions', [])
    if not questions:
        return "No questions available for this assessment."
    
    current_q = questions[state.current_question_idx]
    return f"""# Assessment Question {state.current_question_idx + 1}/{len(questions)}

{current_q.get('text', '')}
"""

async def generate_with_status(topic: str, language: str) -> AsyncGenerator[Dict[str, Any], None]:
    """Generate course content with status updates"""
    try:
        async for update in generate_course(topic, language):
            if isinstance(update, dict):
                if "status" in update:
                    yield {
                        "status": update["status"],
                        "progress": update.get("progress", 0),
                        "course_state": update.get("course_state", None),
                        "error": None
                    }
                elif "error" in update:
                    yield {
                        "status": "Error",
                        "progress": 0,
                        "course_state": None,
                        "error": update["error"]
                    }
            else:
                # If update is the final course state
                yield {
                    "status": "Course generation complete",
                    "progress": 100,
                    "course_state": update,
                    "error": None
                }
    except Exception as e:
        logger.error(f"Error in generate_with_status: {str(e)}")
        yield {
            "status": "Error",
            "progress": 0,
            "course_state": None,
            "error": str(e)
        }

async def on_generate(topic: str, language: str = "English") -> AsyncGenerator[Tuple[str, str], None]:
    """Handle generate button click with improved error handling"""
    try:
        status_text = "Starting course generation..."
        content = ""
        
        async for update in generate_with_status(topic, language):
            progress = update.get("progress", 0)
            status_text = f"{update['status']} ({progress}%)"
            
            if update.get("error"):
                yield (
                    f"Error: {update['error']}",
                    ""
                )
                return
            
            # Only save the course when it's complete
            if progress == 100 and update.get("course_state"):
                try:
                    course_data = update["course_state"]
                    if isinstance(course_data, dict) and course_data.get("modules"):
                        state.course = course_data
                        # Save the course
                        state.course_id = state.storage.save_course(state.course)
                        # Initialize progress
                        state.progress.create_new_progress(state.course_id)
                        # Format first session
                        current_module = state.course["modules"][0]
                        if current_module.get("sessions"):
                            current_session = current_module["sessions"][0]
                            content = format_session_content(current_module, current_session, 1)
                except Exception as e:
                    logger.error(f"Error saving course: {str(e)}")
                    yield (
                        f"Error saving course: {str(e)}",
                        ""
                    )
                    return
            
            yield (
                status_text,
                content
            )
        
    except Exception as e:
        logger.error(f"Error generating course: {str(e)}")
        yield (
            f"Error: {str(e)}",
            ""
        )

async def load_course(course_id: str) -> Tuple[str, str, bool, bool]:
    """Load an existing course"""
    try:
        # Load course data
        course_data = state.storage.load_course(course_id)
        if not course_data:
            return "Error: Course not found", "", False, False
        
        # Set course state
        state.course = course_data
        state.course_id = course_id
        
        # Load progress
        progress_data = state.progress.load_progress(course_id)
        state.current_module_idx = progress_data['current_module']
        state.current_session_idx = progress_data['current_session']
        
        # Get current session content
        current_module = state.course["modules"][state.current_module_idx]
        current_session = current_module["sessions"][state.current_session_idx]
        content = format_session_content(current_module, current_session, state.current_session_idx + 1)
        
        return (
            f"Loaded course: {state.course['topic']}",
            content,
            True,  # Show submit button
            True   # Show next button
        )
        
    except Exception as e:
        logger.error(f"Error loading course: {str(e)}")
        return f"Error loading course: {str(e)}", "", False, False

async def submit_answer(answer: str) -> Tuple[str, str, str, bool, bool]:
    """Submit an answer for evaluation"""
    if not state.course:
        return (
            "No active course",
            "",
            "",
            False,
            False
        )
    
    try:
        current_module = state.course["modules"][state.current_module_idx]
        current_session = current_module["sessions"][state.current_session_idx]
        
        if not state.show_assessment:
            # Show first assessment question
            state.show_assessment = True
            state.current_question_idx = 0
            return (
                "Starting assessment",
                format_assessment(current_session),
                "",
                True,
                False
            )
        
        # Evaluate answer
        questions = current_session['assessment']['questions']
        current_question = questions[state.current_question_idx]
        is_correct = evaluate_answer(answer, current_question)
        
        feedback = "Correct! " if is_correct else "Incorrect. "
        feedback += current_question.get('explanation', '')
        
        # Move to next question or complete assessment
        state.current_question_idx += 1
        if state.current_question_idx >= len(questions):
            # Complete session
            state.progress.update_session_progress(
                state.course_id,
                state.current_module_idx,
                state.current_session_idx,
                completed=True,
                score=0.0  # TODO: Calculate actual score
            )
            return (
                "Assessment completed!",
                feedback + "\n\nClick 'Next Session' to continue.",
                "",
                False,
                True
            )
        
        # Show next question
        return (
            feedback,
            format_assessment(current_session),
            "",
            True,
            False
        )
        
    except Exception as e:
        logger.error(f"Error in submit_answer: {str(e)}")
        return (
            f"Error: {str(e)}",
            "",
            "",
            False,
            False
        )

def evaluate_answer(answer: str, question: Dict[str, Any]) -> bool:
    """Evaluate if the answer is correct"""
    correct_answers = question.get('correct_answers', [])
    if not correct_answers:
        return False
    
    # Simple string matching for now
    answer = answer.lower().strip()
    return any(correct.lower().strip() in answer for correct in correct_answers)

async def next_session() -> Tuple[str, str, str, bool, bool]:
    """Move to the next session"""
    if not state.course:
        return (
            "No active course",
            "",
            "",
            False,
            False
        )
    
    try:
        current_module = state.course["modules"][state.current_module_idx]
        
        # Move to next session or module
        state.current_session_idx += 1
        if state.current_session_idx >= len(current_module["sessions"]):
            state.current_module_idx += 1
            state.current_session_idx = 0
            
            if state.current_module_idx >= len(state.course["modules"]):
                return (
                    "Course completed!",
                    "Congratulations! You have completed all sessions in this course.",
                    "",
                    False,
                    False
                )
        
        # Get new session content
        current_module = state.course["modules"][state.current_module_idx]
        current_session = current_module["sessions"][state.current_session_idx]
        state.current_question_idx = 0
        state.show_assessment = False
        
        # Update progress
        state.progress.update_session_progress(
            state.course_id,
            state.current_module_idx,
            state.current_session_idx
        )
        
        content = format_session_content(current_module, current_session, state.current_session_idx + 1)
        
        return (
            f"Module {state.current_module_idx + 1}, Session {state.current_session_idx + 1}",
            content,
            "",
            True,
            True
        )
        
    except Exception as e:
        logger.error(f"Error moving to next session: {str(e)}")
        return (
            f"Error: {str(e)}",
            "",
            "",
            False,
            False
        )

def create_interface():
    """Create the Gradio interface with improved status display"""
    with gr.Blocks(title="AI Learning Platform Generator") as app:
        gr.Markdown("""
        # 🎓 AI Learning Platform Generator
        Generate personalized educational content with AI assistance.
        """)
        
        with gr.Tab("Generate New Course"):
            with gr.Row():
                with gr.Column():
                    topic_input = gr.Textbox(
                        label="Course Topic",
                        placeholder="Enter the topic you want to learn about..."
                    )
                    language_input = gr.Dropdown(
                        choices=["English", "Español", "Português", "Français"],
                        value="English",
                        label="Language"
                    )
                    generate_btn = gr.Button("Generate Course", variant="primary")
        
        with gr.Tab("Load Existing Course"):
            def get_course_choices():
                courses = state.storage.list_courses()
                return [(k, f"{v['topic']} ({v['language']})") for k, v in courses.items()]
            
            courses_dropdown = gr.Dropdown(
                label="Select a Course",
                choices=get_course_choices(),
                type="value",
                value=None,
                interactive=True
            )
            load_btn = gr.Button("Load Course")
            
            # Refresh course list when tab is selected
            def refresh_courses():
                return gr.Dropdown(choices=get_course_choices())
            
            courses_dropdown.change(
                fn=refresh_courses,
                inputs=[],
                outputs=[courses_dropdown]
            )
        
        status_output = gr.Textbox(
            label="Status",
            interactive=False
        )
        
        content_output = gr.Markdown(
            label="Course Content",
            value=""
        )
        
        with gr.Row():
            submit_btn = gr.Button("Submit Answer", visible=False)
            next_btn = gr.Button("Next Session", visible=False)
        
        answer_input = gr.Textbox(
            label="Your Answer",
            visible=False
        )
        
        # Event handlers
        generate_btn.click(
            fn=on_generate,
            inputs=[topic_input, language_input],
            outputs=[status_output, content_output]
        )
        
        load_btn.click(
            fn=load_course,
            inputs=[courses_dropdown],
            outputs=[status_output, content_output, submit_btn, next_btn]
        )
        
        submit_btn.click(
            fn=submit_answer,
            inputs=[answer_input],
            outputs=[status_output, content_output, answer_input, submit_btn, next_btn]
        )
        
        next_btn.click(
            fn=next_session,
            inputs=[],
            outputs=[status_output, content_output, answer_input, submit_btn, next_btn]
        )
        
    return app

if __name__ == "__main__":
    app = create_interface()
    app.queue()
    app.launch(show_error=True)
