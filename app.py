import os
import logging
import gradio as gr
from typing import Dict, Any, Tuple, AsyncGenerator
from course_generator import generate_course
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SessionState:
    def __init__(self):
        self.course = None
        self.current_module_idx = 0
        self.current_session_idx = 0
        self.current_question_idx = 0
        self.show_assessment = False

state = SessionState()

async def create_course(topic: str, language: str) -> Tuple[str, str, str, bool, bool]:
    """Create a new course"""
    try:
        status = "Starting course generation..."
        state.course = await generate_course(topic, language)
        state.current_module_idx = 0
        state.current_session_idx = 0
        state.current_question_idx = 0
        state.show_assessment = False
        
        # Get the first session content
        if state.course and state.course.get("modules"):
            current_module = state.course["modules"][state.current_module_idx]
            if current_module.get("sessions"):
                current_session = current_module["sessions"][state.current_session_idx]
                
                # Format the session content
                content = f"""# {current_module['title']} - Session {state.current_session_idx + 1}

{current_session.get('title', '')}

{current_session.get('description', '')}

Learning Objectives:
{chr(10).join('- ' + obj for obj in current_session.get('objectives', []))}

Duration: {current_session.get('duration', '45 minutes')}

Content:
{current_session.get('content', '')}
"""
                
                status = f"Course generated successfully: {topic}"
                return (
                    status,  # status_output
                    content,  # course_content
                    "",      # your_answer
                    True,    # submit_btn visibility
                    True     # next_btn visibility
                )
        
        return (
            "Error: No course content generated",
            "",
            "",
            False,
            False
        )
        
    except Exception as e:
        logger.error(f"Error creating course: {str(e)}")
        return (
            f"Error: {str(e)}",
            "",
            "",
            False,
            False
        )

async def submit_answer(answer: str) -> Tuple[str, str, str, bool, bool]:
    """Submit an answer for evaluation"""
    if not state.course:
        return (
            "No active course. Please create a course first.",
            "",
            "",
            False,
            False
        )
    
    try:
        current_module = state.course["modules"][state.current_module_idx]
        current_session = current_module["sessions"][state.current_session_idx]
        current_question = current_session["assessment"]["questions"][state.current_question_idx]
        
        # Evaluate answer (implement your evaluation logic here)
        is_correct = evaluate_answer(answer, current_question)
        
        feedback = "Correct! " if is_correct else "Incorrect. "
        feedback += current_question["explanation"]
        
        # Show next question or next session button
        state.current_question_idx += 1
        show_next = state.current_question_idx >= len(current_session["assessment"]["questions"])
        
        return (
            "Answer submitted",  # status
            feedback,           # feedback
            "",                # clear answer input
            not show_next,     # submit button visibility
            show_next          # next button visibility
        )
    except Exception as e:
        logger.error(f"Error submitting answer: {str(e)}")
        return (
            f"Error: {str(e)}",
            "",
            "",
            False,
            False
        )

def evaluate_answer(answer: str, question: Any) -> bool:
    """Evaluate if the answer is correct"""
    # Implement your answer evaluation logic here
    # For now, just check if the answer contains any of the correct answers
    return any(correct.lower() in answer.lower() for correct in question["correct_answers"])

async def next_session() -> Tuple[str, str, str, bool, bool, str]:
    """Move to the next session"""
    if not state.course:
        return (
            "No active course. Please create a course first.",
            "",
            "",
            False,
            False,
            ""
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
                    "Course completed! ",
                    "Congratulations! You have completed all sessions in this course.",
                    "",
                    False,
                    False,
                    ""
                )
        
        # Get new session content
        current_module = state.course["modules"][state.current_module_idx]
        current_session = current_module["sessions"][state.current_session_idx]
        state.current_question_idx = 0
        state.show_assessment = False
        
        # Format the session content
        content = f"""# {current_module['title']} - Session {state.current_session_idx + 1}

{current_session.get('title', '')}

{current_session.get('description', '')}

Learning Objectives:
{chr(10).join('- ' + obj for obj in current_session.get('objectives', []))}

Duration: {current_session.get('duration', '45 minutes')}

Content:
{current_session.get('content', '')}
"""
        
        return (
            f"Module {state.current_module_idx + 1}, Session {state.current_session_idx + 1}",
            content,
            "",
            True,
            True,
            ""
        )
    except Exception as e:
        logger.error(f"Error moving to next session: {str(e)}")
        return (
            f"Error: {str(e)}",
            "",
            "",
            False,
            False,
            ""
        )

async def show_assessment() -> Tuple[str, str, bool, bool]:
    """Show the assessment for the current session"""
    if not state.course:
        return (
            "No active course. Please create a course first.",
            "",
            False,
            False
        )
    
    try:
        current_module = state.course["modules"][state.current_module_idx]
        current_session = current_module["sessions"][state.current_session_idx]
        current_question = current_session["assessment"]["questions"][state.current_question_idx]
        
        state.show_assessment = True
        
        return (
            "Assessment started",
            current_question["text"],
            True,   # show answer input
            True    # show submit button
        )
    except Exception as e:
        logger.error(f"Error showing assessment: {str(e)}")
        return (
            f"Error: {str(e)}",
            "",
            False,
            False
        )

async def generate_with_status(topic: str, language: str) -> AsyncGenerator[Dict[str, Any], None]:
    """Generate course content with status updates"""
    try:
        async for update in generate_course(topic, language):
            if "status" in update:
                yield {
                    "status": update["status"],
                    "progress": update.get("progress", 0),
                    "content": "",
                    "error": None
                }
            
            if "error" in update:
                yield {
                    "status": "Error",
                    "progress": 0,
                    "content": "",
                    "error": update["error"]
                }
        
    except Exception as e:
        logger.error(f"Error in generate_with_status: {str(e)}")
        yield {
            "status": "Error",
            "progress": 0,
            "content": "",
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
            
            # If we have a course state, try to display the first session
            if "course_state" in update:
                state.course = update["course_state"]
                if state.course and state.course.get("modules"):
                    current_module = state.course["modules"][0]
                    if current_module.get("sessions"):
                        current_session = current_module["sessions"][0]
                        content = format_session_content(current_module, current_session, 1)
            
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

def create_interface():
    """Create the Gradio interface with improved status display"""
    with gr.Blocks(title="AI Learning Platform Generator") as app:
        gr.Markdown("""
        # 🎓 AI Learning Platform Generator
        Generate personalized educational content with AI assistance.
        """)
        
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
            
            with gr.Column():
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
