#!/bin/bash

# USDA FSIS Comment Classifier Web Application
# Startup Script

# Check if Python is installed
if ! command -v python3 &> /dev/null
then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Check if virtual environment exists, create if not
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment."
        exit 1
    fi
fi

# Activate virtual environment
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Error: Failed to activate virtual environment."
    exit 1
fi

# Install or upgrade required packages
echo "Installing required packages..."
pip install --upgrade flask pandas matplotlib scikit-learn PyPDF2 requests
if [ $? -ne 0 ]; then
    echo "Warning: Some packages may not have installed correctly."
fi

# Create necessary directories
mkdir -p templates static uploads outputs

# Check if required Python scripts exist
for script in "app.py" "commentbuilder.py" "cc2.py"; do
    if [ ! -f "$script" ]; then
        echo "Error: Required script $script not found."
        exit 1
    fi
done

# Check if template files exist
for template in "templates/base.html" "templates/index.html" "templates/upload_pdf.html" "templates/results.html"; do
    if [ ! -f "$template" ]; then
        echo "Error: Required template $template not found."
        exit 1
    fi
done

# Get the server's IP address
IP_ADDRESS=$(hostname -I | awk '{print $1}')

echo "Starting USDA FSIS Comment Classifier Web Application..."
echo "The application will be accessible at: http://$IP_ADDRESS:5000"
echo "Press Ctrl+C to stop the server."

# Start the Flask application
python3 app.py