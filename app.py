from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
import os
import subprocess
import uuid
import time
import pandas as pd
import matplotlib.pyplot as plt
import io
import base64
from werkzeug.utils import secure_filename

# Import functionality from your scripts
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from commentbuilder2 import get_documents_for_docket, get_comments_for_document, get_comment_details, save_comments_to_csv
import cc2
# Import the TextFeatureExtractor class directly to make it available in main namespace
from cc2 import TextFeatureExtractor

# Configure application
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

# Ensure upload and output directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)


@app.route('/')
def index():
    # Clear any existing session data for a fresh start
    session.clear()
    return render_template('index.html')


@app.route('/fetch_comments', methods=['POST'])
def fetch_comments():
    # Get the docket ID from the form
    docket_id = request.form.get('docket_id')
    
    if not docket_id:
        flash('Please enter a valid docket ID', 'error')
        return redirect(url_for('index'))
    
    # Generate a unique session ID to keep track of this user's files
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    session_id = session['session_id']
    
    try:
        # Create a folder for this session if it doesn't exist
        session_folder = os.path.join(app.config['OUTPUT_FOLDER'], session_id)
        os.makedirs(session_folder, exist_ok=True)
        
        # Get all documents for the docket
        documents = get_documents_for_docket(docket_id)
        
        if not documents:
            flash(f'No documents found for docket ID: {docket_id}', 'error')
            return redirect(url_for('index'))
        
        # Get all comments for each document
        all_comments = []
        for doc in documents:
            object_id = doc.get("attributes", {}).get("objectId")
            if object_id:
                document_comments = get_comments_for_document(object_id)
                all_comments.extend(document_comments)
        
        if not all_comments:
            flash(f'No comments found for docket ID: {docket_id}', 'error')
            return redirect(url_for('index'))
        
        # Save comments to CSV
        csv_filename = save_comments_to_csv(all_comments, docket_id)
        
        # Move the CSV to the session folder
        os.rename(csv_filename, os.path.join(session_folder, csv_filename))
        
        # Store the CSV filename in the session
        session['csv_filename'] = csv_filename
        session['docket_id'] = docket_id
        session['comment_count'] = len(all_comments)
        
        flash(f'Successfully retrieved {len(all_comments)} comments for docket ID: {docket_id}', 'success')
        return redirect(url_for('upload_pdf'))
        
    except Exception as e:
        flash(f'Error fetching comments: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/upload_pdf')
def upload_pdf():
    if 'csv_filename' not in session:
        flash('Please start by entering a docket ID', 'error')
        return redirect(url_for('index'))
    
    return render_template('upload_pdf.html', 
                          docket_id=session.get('docket_id'),
                          comment_count=session.get('comment_count'))


@app.route('/classify_comments', methods=['POST'])
def classify_comments():
    if 'csv_filename' not in session:
        flash('Please start by entering a docket ID', 'error')
        return redirect(url_for('index'))
    
    # Check if file was uploaded
    if 'rule_pdf' not in request.files:
        flash('No PDF file uploaded', 'error')
        return redirect(url_for('upload_pdf'))
    
    file = request.files['rule_pdf']
    
    # Check if user submitted empty file input
    if file.filename == '':
        flash('No PDF file selected', 'error')
        return redirect(url_for('upload_pdf'))
    
    session_id = session['session_id']
    session_folder = os.path.join(app.config['OUTPUT_FOLDER'], session_id)
    
    if file and file.filename.lower().endswith('.pdf'):
        # Save PDF file
        pdf_filename = secure_filename(file.filename)
        pdf_path = os.path.join(session_folder, pdf_filename)
        file.save(pdf_path)
        
        # Get the CSV file path
        csv_filename = session['csv_filename']
        csv_path = os.path.join(session_folder, csv_filename)
        
        try:
            # Create instance of classifier
            classifier = cc2.SubstantiveCommentClassifier()
            
            # Load the model or train a new one
            if os.path.exists("substantive_classifier_model.pkl"):
                classifier.load_model()
            else:
                if not classifier.load_training_data():
                    flash('Error loading training data', 'error')
                    return redirect(url_for('upload_pdf'))
                classifier.train_models()
                classifier.save_model()
            
            # Process the rule PDF
            rule_features = classifier.read_pdf(pdf_path)
            
            # Load comments from CSV
            # Need to temporarily copy the CSV to the current directory for the classifier
            temp_csv_path = os.path.basename(csv_path)
            os.system(f"cp '{csv_path}' '{temp_csv_path}'")
            
            # Load comments
            comment_col = classifier.load_comments_csv(temp_csv_path)
            
            if comment_col is None:
                flash('Error loading comments from CSV', 'error')
                return redirect(url_for('upload_pdf'))
            
            # Classify comments
            if not classifier.classify_comments(rule_features):
                flash('Error classifying comments', 'error')
                return redirect(url_for('upload_pdf'))
            
            # Save results
            classifier.save_results()
            
            # Move the result file to the session folder
            os.rename("classified_comments.csv", os.path.join(session_folder, "classified_comments.csv"))
            
            # Clean up temp file
            if os.path.exists(temp_csv_path):
                os.remove(temp_csv_path)
            
            # Create visualizations
            df = pd.read_csv(os.path.join(session_folder, "classified_comments.csv"))
            
            # Store results in session
            session['classified_csv'] = "classified_comments.csv"
            session['total_comments'] = int(len(df))  # Convert to native int
            session['substantive_comments'] = int(df['Substantive'].sum())  # Convert to native int
            session['nonsubstantive_comments'] = int(len(df) - df['Substantive'].sum())  # Convert to native int
            
            # Create visualizations and encode them as base64 for embedding in HTML
            create_visualizations(df, session_folder)
            
            return redirect(url_for('results'))
            
        except Exception as e:
            flash(f'Error in classification process: {str(e)}', 'error')
            return redirect(url_for('upload_pdf'))
    else:
        flash('Only PDF files are allowed', 'error')
        return redirect(url_for('upload_pdf'))


def create_visualizations(df, folder):
    """Create visualizations from classification results"""
    if 'Substantive' in df.columns and df['Substantive'].dtype == object:
        df['Substantive'] = df['Substantive'].map({'True': True, 'False': False})
    
    # Create pie chart
    plt.figure(figsize=(8, 8))
    counts = df['Substantive'].value_counts()
    labels = ['Substantive', 'Non-substantive']
    values = [counts.get(True, 0), counts.get(False, 0)]
    plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=90, colors=['#4CAF50', '#F44336'])
    plt.title('Comment Classification Results')
    plt.tight_layout()
    pie_chart_path = os.path.join(folder, 'classification_pie.png')
    plt.savefig(pie_chart_path)
    plt.close()
    
    # Create confidence distribution chart
    if 'Confidence' in df.columns:
        plt.figure(figsize=(10, 6))
        # Create separate series for substantive and non-substantive
        substantive_conf = df[df['Substantive'] == True]['Confidence']
        nonsubstantive_conf = df[df['Substantive'] == False]['Confidence']
        
        if len(substantive_conf) > 0 and len(nonsubstantive_conf) > 0:
            plt.hist([substantive_conf, nonsubstantive_conf], bins=10, 
                     label=['Substantive', 'Non-substantive'], alpha=0.7,
                     color=['#4CAF50', '#F44336'])
            plt.xlabel('Confidence Score')
            plt.ylabel('Number of Comments')
            plt.title('Confidence Score Distribution')
            plt.legend()
            plt.tight_layout()
            
            # Save chart
            confidence_chart_path = os.path.join(folder, 'confidence_histogram.png')
            plt.savefig(confidence_chart_path)
        plt.close()
    
    # Create comment length comparison chart
    if 'Comment_Length' in df.columns:
        plt.figure(figsize=(10, 6))
        substantive_len = df[df['Substantive'] == True]['Comment_Length']
        nonsubstantive_len = df[df['Substantive'] == False]['Comment_Length']
        
        if len(substantive_len) > 0 and len(nonsubstantive_len) > 0:
            plt.boxplot([substantive_len, nonsubstantive_len], labels=['Substantive', 'Non-substantive'])
            plt.ylabel('Comment Length (characters)')
            plt.title('Comment Length Comparison')
            plt.tight_layout()
            
            # Save chart
            length_chart_path = os.path.join(folder, 'length_comparison.png')
            plt.savefig(length_chart_path)
        plt.close()


# Add a route to serve images directly
@app.route('/image/<session_id>/<image_name>')
def serve_image(session_id, image_name):
    image_path = os.path.join(app.config['OUTPUT_FOLDER'], session_id, image_name)
    if os.path.exists(image_path):
        return send_file(image_path, mimetype='image/png')
    else:
        # Return a placeholder image or 404
        return "Image not found", 404


@app.route('/results')
def results():
    if 'classified_csv' not in session:
        flash('No classification results available', 'error')
        return redirect(url_for('index'))
    
    session_id = session['session_id']
    session_folder = os.path.join(app.config['OUTPUT_FOLDER'], session_id)
    df = pd.read_csv(os.path.join(session_folder, session['classified_csv']))
    
    if 'Substantive' in df.columns and df['Substantive'].dtype == object:
        df['Substantive'] = df['Substantive'].map({'True': True, 'False': False})
    
    substantive_examples = df[df['Substantive'] == True].head(5)
    nonsubstantive_examples = df[df['Substantive'] == False].head(5)
    
    # Create URLs for the images using our new route
    pie_chart = url_for('serve_image', session_id=session_id, image_name='classification_pie.png')
    confidence_chart = url_for('serve_image', session_id=session_id, image_name='confidence_histogram.png')
    length_chart = url_for('serve_image', session_id=session_id, image_name='length_comparison.png')
    
    return render_template('results.html',
                          docket_id=session.get('docket_id'),
                          total_comments=session.get('total_comments'),
                          substantive_comments=session.get('substantive_comments'),
                          nonsubstantive_comments=session.get('nonsubstantive_comments'),
                          substantive_examples=substantive_examples.to_dict('records'),
                          nonsubstantive_examples=nonsubstantive_examples.to_dict('records'),
                          pie_chart=pie_chart,
                          confidence_chart=confidence_chart,
                          length_chart=length_chart)


@app.route('/download/<filename>')
def download(filename):
    if 'session_id' not in session:
        flash('Session expired', 'error')
        return redirect(url_for('index'))
    
    session_id = session['session_id']
    session_folder = os.path.join(app.config['OUTPUT_FOLDER'], session_id)
    
    if filename == 'original':
        if 'csv_filename' not in session:
            flash('No comments file available', 'error')
            return redirect(url_for('results'))
        file_path = os.path.join(session_folder, session['csv_filename'])
        return send_file(file_path, as_attachment=True)
    
    elif filename == 'classified':
        if 'classified_csv' not in session:
            flash('No classification results available', 'error')
            return redirect(url_for('results'))
        file_path = os.path.join(session_folder, session['classified_csv'])
        return send_file(file_path, as_attachment=True)
    
    else:
        flash('Invalid file requested', 'error')
        return redirect(url_for('results'))


@app.route('/reset')
def reset():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
