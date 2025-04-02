import requests
import csv
import os
from datetime import datetime
import time
import tempfile
import shutil
from urllib.parse import urlparse
import random
from collections import deque

# Try importing optional packages for file processing
PDF_SUPPORT = False
DOCX_SUPPORT = False

try:
    import PyPDF2
    PDF_SUPPORT = True
except ImportError:
    pass

try:
    import docx2txt
    DOCX_SUPPORT = True
except ImportError:
    pass

# API Configuration
API_KEYS = [
    "le3yia7EgtawuXKcCXUBSZqUBtSuGzyPyWtwmeUa",
    "lJ1THACguVQVwkfVh1OFjkmhYruFIctj7ncjlxld",
    "Yspc7hIBVpC9qvBQpmJJzUUSlK4yzvFgs6d6uCr8",
    "ckxLZXWgdghbnxsZrsH8f93N6qw7MM2v9HFrYpXy"
]
# Create a rotating queue of API keys
API_KEY_QUEUE = deque(API_KEYS)
CURRENT_API_KEY = API_KEY_QUEUE[0]
BASE_URL = "https://api.regulations.gov/v4"

def get_headers():
    """Get headers with the current API key"""
    return {
        "X-Api-Key": CURRENT_API_KEY,
        "Accept": "application/json"
    }

def rotate_api_key():
    """Rotate to the next API key in the queue"""
    global CURRENT_API_KEY
    # Move the current key to the end of the queue
    API_KEY_QUEUE.rotate(-1)
    # Get the new current key from the front
    CURRENT_API_KEY = API_KEY_QUEUE[0]
    print(f"Rotating to next API key: {CURRENT_API_KEY[:8]}...")
    return CURRENT_API_KEY

def make_api_request(url, params=None, max_retries=5):
    """Make an API request with automatic key rotation on rate limit"""
    retries = 0
    while retries < max_retries:
        headers = get_headers()
        try:
            response = requests.get(url, params=params, headers=headers)
            
            # If successful, return the response
            if response.status_code == 200:
                return response
                
            # If rate limited, rotate API key and retry
            elif response.status_code == 429:
                print(f"Rate limit reached for key {CURRENT_API_KEY[:8]}...")
                rotate_api_key()
                retries += 1
                time.sleep(1)  # Brief pause before retry
                
            # For other errors, wait and retry
            else:
                print(f"Error: HTTP {response.status_code}")
                print(response.text)
                retries += 1
                time.sleep(2)  # Longer pause for other errors
                
        except Exception as e:
            print(f"Exception making request: {str(e)}")
            retries += 1
            time.sleep(2)
    
    print(f"Failed to make request after {max_retries} attempts")
    return None

def get_documents_for_docket(docket_id):
    """Get all documents associated with a docket ID"""
    print(f"Finding documents for docket: {docket_id}")
    documents = []
    page = 1
    
    while True:
        url = f"{BASE_URL}/documents"
        params = {
            "filter[docketId]": docket_id,
            "page[size]": 250,
            "page[number]": page
        }
        
        response = make_api_request(url, params)
        
        if not response:
            break
        
        data = response.json()
        documents.extend(data.get("data", []))
        
        meta = data.get("meta", {})
        if not meta.get("hasNextPage", False):
            break
            
        page += 1
        # Be nice to the API with a small delay
        time.sleep(0.1)
    
    print(f"Found {len(documents)} documents")
    return documents

def get_comments_for_document(object_id):
    """Get all comments for a specific document using its objectId"""
    print(f"Getting comments for document object ID: {object_id}")
    comments = []
    page = 1
    
    while True:
        url = f"{BASE_URL}/comments"
        params = {
            "filter[commentOnId]": object_id,
            "page[size]": 250,
            "page[number]": page,
            "sort": "postedDate"
        }
        
        response = make_api_request(url, params)
        
        if not response:
            break
        
        data = response.json()
        comments.extend(data.get("data", []))
        
        meta = data.get("meta", {})
        total_elements = meta.get("totalElements", 0)
        
        if not meta.get("hasNextPage", False):
            break
            
        page += 1
        # Be nice to the API with a small delay
        time.sleep(0.1)
        
        # Show progress for documents with many comments
        if total_elements > 250 and page % 5 == 0:
            print(f"  Retrieved {len(comments)} of {total_elements} comments...")
    
    print(f"  Found {len(comments)} comments")
    return comments

def get_comment_details(comment_id):
    """Get detailed information for a specific comment"""
    url = f"{BASE_URL}/comments/{comment_id}"
    params = {"include": "attachments"}
    
    # Try up to 3 times, possibly with different API keys
    for attempt in range(3):
        response = make_api_request(url, params)
        if response:
            return response.json()
        
        # Brief pause between attempts
        time.sleep(1)
    
    print(f"Failed to get details for comment {comment_id} after 3 attempts")
    return None

def download_file(url, destination):
    """Download a file from a URL to a local destination"""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"Error downloading file: {str(e)}")
        return False

def get_file_extension(url):
    """Extract file extension from URL"""
    parsed_url = urlparse(url)
    path = parsed_url.path
    return os.path.splitext(path)[1].lower()

def clean_text(text):
    """Clean extracted text to remove problematic characters"""
    if not text:
        return ""
    
    # Remove null bytes and other control characters except newlines and tabs
    cleaned = ""
    for char in text:
        if char in ('\n', '\t', '\r') or (ord(char) >= 32 and ord(char) < 127):
            cleaned += char
    
    return cleaned.strip()

def extract_text_from_pdf(file_path):
    """Extract text from a PDF file"""
    if not PDF_SUPPORT:
        return ""
        
    try:
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page_num in range(len(reader.pages)):
                text += reader.pages[page_num].extract_text() + "\n"
            return clean_text(text)
    except Exception as e:
        print(f"Error extracting text from PDF: {str(e)}")
        return ""

def extract_text_from_docx(file_path):
    """Extract text from a DOCX file"""
    if not DOCX_SUPPORT:
        return ""
        
    try:
        text = docx2txt.process(file_path)
        return clean_text(text)
    except Exception as e:
        print(f"Error extracting text from DOCX: {str(e)}")
        return ""

def process_attachments(comment_details):
    """Process attachments and extract text if possible"""
    if not comment_details:
        return "", False
    
    has_attachment = False
    attachment_text = ""
    
    # Get included items (attachments)
    included = comment_details.get("included", [])
    if not included:
        return attachment_text, has_attachment
    
    # Create a temporary directory for downloads
    temp_dir = tempfile.mkdtemp()
    
    try:
        for item in included:
            if item.get("type") == "attachments":
                file_formats = item.get("attributes", {}).get("fileFormats", [])
                
                for file_format in file_formats:
                    file_url = file_format.get("fileUrl")
                    if not file_url:
                        continue
                    
                    has_attachment = True
                    extension = get_file_extension(file_url)
                    
                    if extension in ['.pdf', '.docx', '.doc']:
                        # Create a temporary file
                        temp_file = os.path.join(temp_dir, f"attachment{extension}")
                        
                        # Download the file
                        print(f"  Downloading attachment: {file_url}")
                        if download_file(file_url, temp_file):
                            # Extract text based on file type
                            if extension == '.pdf':
                                text = extract_text_from_pdf(temp_file)
                                if text:
                                    attachment_text = text
                                    break
                            elif extension in ['.docx', '.doc']:
                                text = extract_text_from_docx(temp_file)
                                if text:
                                    attachment_text = text
                                    break
                        else:
                            print(f"  Failed to download attachment: {file_url}")
    finally:
        # Clean up the temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    return attachment_text, has_attachment

def save_comments_to_csv(comments, docket_id, extract_attachments=True):
    """Save comments to a CSV file with attachment processing"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{docket_id.replace('-', '')}_comments_{timestamp}.csv"
    
    print(f"Saving {len(comments)} comments to {filename}")
    
    # Define fields for CSV output
    fields = ["id", "title", "comment", "postedDate", "documentType", "fromAttachment", "hasAttachment"]
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fields)
        writer.writeheader()
        
        for i, comment in enumerate(comments):
            comment_id = comment.get("id", "")
            print(f"Processing comment {i+1}/{len(comments)}: {comment_id}")
            
            # Start with data from the list response
            comment_data = {
                "id": comment_id,
                "fromAttachment": False,
                "hasAttachment": False
            }
            
            # Get attributes from list response
            list_attributes = comment.get("attributes", {})
            
            # Now get the detailed comment information for accurate text and attachment info
            comment_details = get_comment_details(comment_id)
            
            # If we got details, use the detailed attributes, otherwise use list attributes
            if comment_details:
                attributes = comment_details.get("data", {}).get("attributes", {})
            else:
                attributes = list_attributes
            
            # Fill in metadata fields
            comment_data["title"] = attributes.get("title", "")
            comment_data["postedDate"] = attributes.get("postedDate", "")
            comment_data["documentType"] = attributes.get("documentType", "")
            
            # Get comment text directly from the API response
            comment_text = attributes.get("comment", "")
            
            # Make sure comment_text is not None (convert to empty string if None)
            comment_text = comment_text if comment_text else ""
            
            # Process attachments if enabled
            attachment_text = ""
            if extract_attachments and comment_details:
                attachment_text, has_attachment = process_attachments(comment_details)
                comment_data["hasAttachment"] = has_attachment
                
                if attachment_text:
                    # If we have both comment_text and attachment_text, use the longer one
                    # This way we don't lose either source of information
                    if len(attachment_text) > len(comment_text):
                        comment_text = attachment_text
                        comment_data["fromAttachment"] = True
            
            # Set the final comment text
            comment_data["comment"] = comment_text
            
            # Write the row to CSV
            writer.writerow(comment_data)
    
    print(f"Successfully saved comments to {filename}")
    return filename

def check_dependencies():
    """Check if required packages are installed and print information"""
    print("\nDependency check:")
    print(f"PDF extraction: {'Available' if PDF_SUPPORT else 'Not available'}")
    print(f"DOCX extraction: {'Available' if DOCX_SUPPORT else 'Not available'}")
    
    if not PDF_SUPPORT:
        print("\nFor PDF support, install:")
        print("  pip install PyPDF2")
    
    if not DOCX_SUPPORT:
        print("\nFor DOCX support, install:")
        print("  pip install docx2txt")

def main():
    print("=== Enhanced Regulations.gov Comment Extractor ===")
    print(f"Loaded {len(API_KEYS)} API keys for rotation")
    check_dependencies()
    
    # Randomize starting API key to distribute usage
    random_start = random.randint(0, len(API_KEYS) - 1)
    for _ in range(random_start):
        rotate_api_key()
    print(f"Starting with API key: {CURRENT_API_KEY[:8]}...")
    
    # Prompt user for docket ID
    docket_id = input("\nEnter the docket ID (e.g., FSIS-2010-0004): ")
    
    if not docket_id:
        print("Docket ID is required.")
        return
    
    # Ask whether to extract text from attachments
    extract_attachments = True
    if not (PDF_SUPPORT or DOCX_SUPPORT):
        print("\nNOTE: No PDF or DOCX extraction libraries are installed.")
        extract_attachments = input("Do you want to try downloading attachments anyway? (y/n): ").lower() == 'y'
    
    # 1. Get all documents for the docket
    documents = get_documents_for_docket(docket_id)
    
    if not documents:
        print("No documents found for this docket ID.")
        return
    
    # 2. Get all comments for each document
    all_comments = []
    for doc in documents:
        object_id = doc.get("attributes", {}).get("objectId")
        if object_id:
            document_comments = get_comments_for_document(object_id)
            all_comments.extend(document_comments)
    
    if not all_comments:
        print("No comments found for documents in this docket.")
        return
    
    # 3. Save comments to CSV with attachment processing
    csv_file = save_comments_to_csv(all_comments, docket_id, extract_attachments)
    print(f"\nComment data saved to {csv_file}")
    print("\nDone!")

if __name__ == "__main__":
    main()
