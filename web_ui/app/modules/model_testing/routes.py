"""
Routes for the model testing module.
"""
import os
import cv2
import numpy as np
import time
import sys
import subprocess
import threading
import queue
import json
from flask import (
    Blueprint, render_template, request, jsonify, 
    current_app, redirect, url_for, Response
)
from werkzeug.utils import secure_filename

from app.utils.file_helpers import (
    allowed_file, is_video_file, save_uploaded_file, queue_file_upload
)
from app.utils.ml_helpers import (
    load_model, get_available_models
)

# Create blueprint
model_testing_bp = Blueprint(
    'model_testing', 
    __name__, 
    url_prefix='/test',
    template_folder='../../templates/model_testing'
)

# Global variables for installation status
installation_queue = queue.Queue()
installation_status = {
    'status': 'idle',
    'progress': 0,
    'message': '',
    'success': False,
    'error': ''
}

def install_tensorflow_thread():
    """Background thread to install TensorFlow"""
    global installation_status
    
    try:
        # Update status
        installation_status = {
            'status': 'installing',
            'progress': 10,
            'message': 'Installing TensorFlow and dependencies...',
            'success': False,
            'error': ''
        }
        installation_queue.put(installation_status.copy())
        
        # Execute pip install command
        process = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "tensorflow", "numpy", "h5py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Update progress periodically
        for i in range(5):
            installation_status['progress'] = 10 + (i * 15)
            installation_status['message'] = f'Installing TensorFlow... (this may take a few minutes)'
            installation_queue.put(installation_status.copy())
            time.sleep(5)  # Sleep to simulate progress
        
        # Get the command output
        stdout, stderr = process.communicate()
        
        # Check if installation was successful
        if process.returncode == 0:
            installation_status = {
                'status': 'completed',
                'progress': 100,
                'message': 'TensorFlow successfully installed!',
                'success': True,
                'error': ''
            }
        else:
            installation_status = {
                'status': 'completed',
                'progress': 100,
                'message': 'Failed to install TensorFlow',
                'success': False,
                'error': stderr
            }
    except Exception as e:
        installation_status = {
            'status': 'completed',
            'progress': 100,
            'message': 'Error during installation',
            'success': False,
            'error': str(e)
        }
    
    # Put final status in queue
    installation_queue.put(installation_status.copy())


@model_testing_bp.route('/install_tensorflow', methods=['POST'])
def install_tensorflow():
    """Handle TensorFlow installation request"""
    global installation_status
    
    # Reset status
    installation_status = {
        'status': 'starting',
        'progress': 0,
        'message': 'Starting installation...',
        'success': False,
        'error': ''
    }
    
    # Clear the queue
    while not installation_queue.empty():
        installation_queue.get()
    
    # Start installation in background thread
    thread = threading.Thread(target=install_tensorflow_thread)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'message': 'Installation started'
    })


@model_testing_bp.route('/install_status')
def install_status():
    """Stream installation status updates using server-sent events"""
    def generate():
        while True:
            try:
                # Get latest status update from queue
                status = installation_queue.get(timeout=1)
                yield f"data: {json.dumps(status)}\n\n"
                
                # If installation is complete, end stream
                if status['status'] == 'completed':
                    break
            except queue.Empty:
                # If no updates, send the current status
                yield f"data: {json.dumps(installation_status)}\n\n"
                time.sleep(1)
    
    return Response(generate(), mimetype='text/event-stream')


@model_testing_bp.route('/check_tensorflow')
def check_tensorflow():
    """Check if TensorFlow is installed"""
    try:
        import tensorflow
        return jsonify({
            'installed': True,
            'version': tensorflow.__version__
        })
    except ImportError:
        return jsonify({
            'installed': False
        })


@model_testing_bp.route('/')
def index():
    """Render the model testing homepage."""
    models = get_available_models()
    return render_template('test_index.html', models=models)


@model_testing_bp.route('/classify', methods=['POST'])
def classify_image():
    """
    Classify a single image using the selected model.
    
    Returns:
        JSON response with classification results
    """
    # Check if model was selected
    if 'model' not in request.form:
        return jsonify({
            'success': False,
            'error': 'No model selected'
        }), 400
        
    model_name = request.form.get('model')
    
    # Check if a file was uploaded
    if 'file' not in request.files:
        return jsonify({
            'success': False, 
            'error': 'No file uploaded'
        }), 400
        
    file = request.files['file']
    
    # Check if file is valid
    if file.filename == '':
        return jsonify({
            'success': False, 
            'error': 'No file selected'
        }), 400
        
    if not allowed_file(file.filename):
        return jsonify({
            'success': False, 
            'error': 'File type not allowed'
        }), 400
    
    # Generate a temporary filename and immediately return a response
    filename = secure_filename(file.filename)
    base, ext = os.path.splitext(filename)
    unique_filename = f"{base}_{int(time.time() * 1000)}{ext}"
    
    # Handle video files differently
    if is_video_file(file.filename):
        # Video processing will be implemented in another function
        return jsonify({
            'success': False,
            'error': 'Video processing not implemented yet'
        }), 501
        
    # Use direct file saving for single image classification (no need for queue)
    file_path = save_uploaded_file(file)
    
    try:
        # Load the model
        model = load_model(model_name)
        if model is None:
            return jsonify({
                'success': False,
                'error': 'Failed to load model. If this is a TensorFlow/Keras (.h5) model, you need to install TensorFlow.'
            }), 500
            
        # Create a PILImage from file path
        from fastai.vision.all import PILImage
        img = PILImage.create(file_path)
        
        # Get the prediction
        pred_class, pred_idx, outputs = model.predict(img)
        
        # Get confidence scores
        confidences = {
            model.dls.vocab[i]: float(outputs[i]) 
            for i in range(len(outputs))
        }
        
        # Sort confidences by value in descending order
        sorted_confidences = {
            k: v for k, v in sorted(
                confidences.items(), 
                key=lambda item: item[1], 
                reverse=True
            )
        }
        
        return jsonify({
            'success': True,
            'prediction': str(pred_class),
            'confidences': sorted_confidences,
            'file_path': file_path.replace('\\', '/')
        })
        
    except Exception as e:
        error_msg = str(e)
        # Special handling for common errors
        if "TensorFlow required" in error_msg or "No module named 'tensorflow'" in error_msg:
            error_msg = "This model requires TensorFlow to be installed. Please install TensorFlow to use this model."
            
        return jsonify({
            'success': False,
            'error': f'Error processing image: {error_msg}'
        }), 500


@model_testing_bp.route('/batch', methods=['GET', 'POST'])
def batch_classify():
    """Batch classification of multiple images."""
    if request.method == 'GET':
        models = get_available_models()
        return render_template('batch_classify.html', models=models)
    
    # Process the batch of images
    if 'model' not in request.form:
        return jsonify({
            'success': False,
            'error': 'No model selected'
        }), 400
    
    model_name = request.form.get('model')
    
    # Check if files were uploaded
    if 'files[]' not in request.files:
        return jsonify({
            'success': False,
            'error': 'No files uploaded'
        }), 400
    
    files = request.files.getlist('files[]')
    if not files or files[0].filename == '':
        return jsonify({
            'success': False,
            'error': 'No files selected'
        }), 400
    
    # Load the model once outside the loop
    try:
        model = load_model(model_name)
        if model is None:
            return jsonify({
                'success': False,
                'error': 'Failed to load model. If this is a TensorFlow/Keras (.h5) model, you need to install TensorFlow.'
            }), 500
    except Exception as e:
        error_msg = str(e)
        # Special handling for common errors
        if "TensorFlow required" in error_msg or "No module named 'tensorflow'" in error_msg:
            error_msg = "This model requires TensorFlow to be installed. Please install TensorFlow to use this model."
        
        return jsonify({
            'success': False,
            'error': f'Error loading model: {error_msg}'
        }), 500
    
    # For batch processing, we'll use a synchronous approach but process
    # files in optimized batches
    from fastai.vision.all import PILImage
    
    results = []
    class_counts = {}
    total_confidence = 0
    
    # Process in batches to reduce memory usage
    batch_size = 10
    for i in range(0, len(files), batch_size):
        batch_files = files[i:i+batch_size]
        
        for file in batch_files:
            if not allowed_file(file.filename):
                continue
            
            try:
                # Save the file directly for immediate processing
                file_path = save_uploaded_file(file)
                
                # Skip video files
                if is_video_file(file.filename):
                    continue
                
                # Create a PILImage and predict
                img = PILImage.create(file_path)
                pred_class, pred_idx, outputs = model.predict(img)
                
                # Get confidence score for the prediction
                confidence = float(outputs[pred_idx])
                total_confidence += confidence
                
                # Update class counts
                class_name = str(pred_class)
                if class_name in class_counts:
                    class_counts[class_name] += 1
                else:
                    class_counts[class_name] = 1
                
                # Get all confidence scores
                confidences = {
                    model.dls.vocab[i]: float(outputs[i]) 
                    for i in range(len(outputs))
                }
                
                # Add to results
                results.append({
                    'filename': file.filename,
                    'prediction': class_name,
                    'confidence': confidence,
                    'confidences': confidences,
                    'file_path': file_path.replace('\\', '/')
                })
                
            except Exception as e:
                # Skip files that cause errors
                continue
    
    # Calculate statistics
    num_processed = len(results)
    avg_confidence = total_confidence / num_processed if num_processed > 0 else 0
    
    return jsonify({
        'success': True,
        'results': results,
        'stats': {
            'processed_count': num_processed,
            'average_confidence': avg_confidence,
            'class_distribution': class_counts
        }
    }) 