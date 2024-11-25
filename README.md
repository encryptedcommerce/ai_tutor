# AI-Powered Adaptive Learning Platform

An advanced e-learning platform that uses LLMs to dynamically generate and deliver personalized educational content. The system creates a hierarchical curriculum structure with modules, sessions, and sections, complete with assessments and adaptive learning paths.

## Features

- **Dynamic Course Generation**: Creates complete course content based on any topic
- **Multi-language Support**: Supports English, Spanish, and Portuguese
- **Adaptive Learning**: Adjusts content based on student performance
- **Visual Learning**: Includes Mermaid diagrams for concept visualization
- **Comprehensive Assessments**: Multiple-choice and free-form questions
- **Mastery-based Progression**: Requires 90% proficiency to advance

## Prerequisites

- Python 3.11 or higher
- Ollama installed with Llama 2 model
- Virtual environment (recommended)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ai-tutor
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install and run Ollama with Llama 2:
```bash
# Install Ollama (if not already installed)
curl https://ollama.ai/install.sh | sh

# Pull the Llama 2 model
ollama pull llama2
```

## Usage

1. Start the application:
```bash
python app.py
```

2. Open your web browser and navigate to the URL shown in the terminal (typically http://localhost:7860)

3. Enter a topic and select your preferred language

4. Click "Create Course" to generate the course content

5. Progress through the course:
   - Read the session content
   - Complete the assessments
   - Achieve 90% mastery to proceed to the next session

## Project Structure

- `app.py`: Main Gradio interface and course delivery logic
- `course_generator.py`: LangGraph-based course generation pipeline
- `models.py`: Data models for course structure
- `prompts.json`: LLM prompts for content generation

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
