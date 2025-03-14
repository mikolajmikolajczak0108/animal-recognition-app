"""
Routes for the model testing module.
"""
import os
import cv2
import numpy as np
from flask import (
    Blueprint, render_template, request, jsonify, 
    current_app, redirect, url_for
)

from app.utils.file_helpers import (
    allowed_file, is_video_file, save_uploaded_file
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
    
    # Save the uploaded file
    file_path = save_uploaded_file(file)
    
    # Handle the classification
    if is_video_file(file.filename):
        # Video processing will be implemented in another function
        return jsonify({
            'success': False,
            'error': 'Video processing not implemented yet'
        }), 501
    else:
        # Process the image
        try:
            # Load the model
            model = load_model(model_name)
            if model is None:
                return jsonify({
                    'success': False,
                    'error': 'Failed to load model'
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
            return jsonify({
                'success': False,
                'error': f'Error processing image: {str(e)}'
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
    
    # Load the model
    model = load_model(model_name)
    if model is None:
        return jsonify({
            'success': False,
            'error': 'Failed to load model'
        }), 500
    
    # Process each image
    results = []
    class_counts = {}
    total_confidence = 0
    
    from fastai.vision.all import PILImage
    
    for file in files:
        if not allowed_file(file.filename):
            continue
        
        try:
            # Save the file
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