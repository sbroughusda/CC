import requests
import csv
import os
from datetime import datetime
import time
import tempfile
import shutil
from urllib.parse import urlparse
import sys

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

# API Configuration with multiple keys
API_KEYS = [
    "le3yia7EgtawuXKcCXUBSZqUBtSuGzyPyWtwmeUa",
    "lJ1THACguVQVwkfVh1OFjkmhYruFIctj7ncjlxld"
    # Add more API keys here as needed
]
BASE_URL = "https://api.regulations.gov/v4"
current_key_index = 0

def get_headers():
    """Get the current API headers with the active API key"""
    global current_key_index
    return {
        "X-Api-Key": API_KEYS[current_key_index],
        "Accept": "application/json"
    }

def rotate_api_key():
    """Rotate to the next available API key"""
    global current_key_index
    
    previous_key = API_KEYS[current_key_index]
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    current_key = API_KEYS[current_key_index]
    
    print(f"Rotating API key: {previous_key[:8]}... -> {current_key[:8]}...")
    
    # Small delay to ensure we don't hit the new key with requests too quickly
    time.sleep(1)
    
    return current_key

def make_api_request(url, params=None, max_retries=3):
    """Make an API request with automatic key rotation on rate limits"""
    global current_key_index
    
    for attempt in range(max_retries * len(API_KEYS)):
        try:
            headers = get_headers()
            response = requests.get(url, params=params, headers=headers)
            
            # If successful, return the response
            if response.status_code == 200:
                return response
                
            # If rate limited, rotate key and try again
            elif response.status_code == 429:
                print(f"Rate limit reached with key {API_KEYS[current_key_index][:8]}...")
                rotate_api_key()
                time.sleep(2)  # Additional delay after rotation
                
            # Handle other errors
            else:
                print(f"Error with API request: {response.status_code}")
                print(response.text)
                
                # If we've tried all keys for this request, give up
                if (attempt + 1) % len(API_KEYS) == 0:
                    print(f"All API keys have been tried. Waiting 30 seconds...")
                    time.sleep(30)
                else:
                    # Try another key
                    rotate_api_key()
                    
        except Exception as e:
            print(f"Exception during API request: {str(e)}")
            time.sleep(2)
            
            # If we've tried all keys for this request, rotate anyway
            if (attempt + 1) % len(API_KEYS) == 0:
                rotate_api_key()
    
    # If we've exhausted all retries and keys
    print(f"Failed to get a successful response after {max_retries} attempts with all keys")
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
        
        if response is None:
            print("Unable to retrieve documents. Stopping.")
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

def get_comments_for_document(object_id, max_comments=None):
    """Get comments for a specific document using its objectId
    
    Args:
        object_id: The object ID of the document
        max_comments: Maximum number of comments to retrieve (None for all)
    """
    print(f"Getting comments for document object ID: {object_id}")
    comments = []
    page = 1
    
    while True:
        # Check if we've already reached the maximum comments
        if max_comments is not None and len(comments) >= max_comments:
            print(f"  Reached maximum of {max_comments} comments. Stopping.")
            break
            
        url = f"{BASE_URL}/comments"
        params = {
            "filter[commentOnId]": object_id,
            "page[size]": 250,
            "page[number]": page,
            "sort": "postedDate"
        }
        
        response = make_api_request(url, params)
        
        if response is None:
            print("Unable to retrieve comments. Continuing with partial data.")
            break
        
        data = response.json()
        batch = data.get("data", [])
        
        # If we have a max_comments limit, only add up to that limit
        if max_comments is not None:
            remaining = max_comments - len(comments)
            batch = batch[:remaining]
            
        comments.extend(batch)
        
        meta = data.get("meta", {})
        total_elements = meta.get("totalElements", 0)
        
        # Stop if we've reached the max or there are no more pages
        if max_comments is not None and len(comments) >= max_comments:
            print(f"  Reached maximum of {max_comments} comments. Stopping.")
            break
        elif not meta.get("hasNextPage", False):
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
    
    response = make_api_request(url, params)
    
    if response is None:
        print(f"Failed to get details for comment {comment_id}")
        return None
        
    return response.json()

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

def load_api_keys_from_file(filename):
    """Load API keys from a text file, one key per line"""
    global API_KEYS
    
    if not os.path.exists(filename):
        print(f"API keys file not found: {filename}")
        return False
        
    try:
        with open(filename, 'r') as f:
            keys = [line.strip() for line in f if line.strip()]
            
        if not keys:
            print("No API keys found in the file")
            return False
            
        API_KEYS = keys
        print(f"Loaded {len(API_KEYS)} API keys from {filename}")
        return True
    except Exception as e:
        print(f"Error loading API keys: {str(e)}")
        return False

def main():
    print("=== Enhanced Regulations.gov Comment Extractor with API Key Rotation ===")
    
    # Check if we have keys loaded
    if len(API_KEYS) == 0:
        print("Error: No API keys available. Please add at least one API key.")
        return
        
    print(f"Using {len(API_KEYS)} API keys for rotation")
    
    # Allow loading additional keys from a file
    if len(sys.argv) > 1 and sys.argv[1].endswith('.txt'):
        load_api_keys_from_file(sys.argv[1])
    
    check_dependencies()
    
    # Prompt user for docket ID
    docket_id = input("\nEnter the docket ID (e.g., FSIS-2010-0004): ")
    
    if not docket_id:
        print("Docket ID is required.")
        return
    
    # Set the maximum comments to collect
    max_comments = 500
    print(f"\nThe script will stop after collecting {max_comments} comments.")
    
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
    
    # 2. Get all comments for each document, with a running count
    all_comments = []
    comments_remaining = max_comments
    
    for doc in documents:
        # Stop if we've already collected enough comments
        if comments_remaining <= 0:
            break
            
        object_id = doc.get("attributes", {}).get("objectId")
        if object_id:
            document_comments = get_comments_for_document(object_id, comments_remaining)
            all_comments.extend(document_comments)
            
            # Update the remaining comments to collect
            comments_remaining = max_comments - len(all_comments)
            
            print(f"Total comments collected so far: {len(all_comments)}/{max_comments}")
            
            # Break the loop if we've reached the maximum
            if comments_remaining <= 0:
                print(f"Reached the maximum of {max_comments} comments.")
                break
    
    if not all_comments:
        print("No comments found for documents in this docket.")
        return
    
    # 3. Save comments to CSV with attachment processing
    csv_file = save_comments_to_csv(all_comments, docket_id, extract_attachments)
    print(f"\nComment data saved to {csv_file}")
    print(f"\nDone! Collected {len(all_comments)} comments (maximum set to {max_comments}).")

if __name__ == "__main__":
    main()
