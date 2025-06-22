import os
from flask import Flask, request, render_template
import sys

# Ensure repository root is on the path so imports work
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import the lightweight Python renderer used by the web editor
from tools.editor.py_renderer import render_image

app = Flask(__name__,
            template_folder='tools/editor',
            static_folder='tools/editor')

@app.route('/')
def index():
    """Serve the main editor page."""
    return render_template('index.html')

@app.route('/draw', methods=['POST'])
def draw_image():
    """Render an image from YAML and return a base64 data URL."""
    try:
        yaml_data = request.form['yaml_data']
    except KeyError:
        return 'yaml_data form field required', 400

    try:
        return render_image(yaml_data)
    except Exception as exc:
        return f'Error: {exc}', 500

if __name__ == '__main__':
    # Run on port 5001 so it does not conflict with other local servers
    app.run(debug=True, port=5001)

