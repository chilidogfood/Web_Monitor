import requests
from bs4 import BeautifulSoup
import time
import logging
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
import json
import os

class WebMonitor:
    def __init__(self):
        """Initialize the web monitor using environment variables."""
        # Get required environment variables
        self.url = os.getenv('MONITOR_URL', 'https://texags.com/forums/67')
        self.search_strings = os.getenv('SEARCH_STRINGS', 'official,pick').lower().split(',')
        self.check_interval = int(os.getenv('CHECK_INTERVAL', '300'))
        
        # Email configuration
        self.email_config = {
            'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
            'smtp_port': int(os.getenv('SMTP_PORT', '587')),
            'sender_email': os.getenv('SENDER_EMAIL'),
            'sender_password': os.getenv('SENDER_PASSWORD'),
            'recipient_email': os.getenv('RECIPIENT_EMAIL')
        }
        
        # Setup storage and logging
        self.seen_matches_file = '/app/config/seen_matches.json'
        self.setup_logging()
        self.load_seen_matches()
        
        # Validate configuration
        self.validate_config()
        
    def validate_config(self):
        """Validate all required configuration is present."""
        missing = []
        if not self.email_config['sender_email']:
            missing.append('SENDER_EMAIL')
        if not self.email_config['sender_password']:
            missing.append('SENDER_PASSWORD')
        if not self.email_config['recipient_email']:
            missing.append('RECIPIENT_EMAIL')
            
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
            
        print("\nCurrent Configuration:")
        print(f"URL: {self.url}")
        print(f"Search Strings: {', '.join(self.search_strings)}")
        print(f"Check Interval: {self.check_interval} seconds")
        print(f"SMTP Server: {self.email_config['smtp_server']}:{self.email_config['smtp_port']}")
        print(f"Sender Email: {self.email_config['sender_email']}")
        print(f"Recipient Email: {self.email_config['recipient_email']}")
        
    def setup_logging(self):
        """Set up logging configuration."""
        logging.basicConfig(
            filename='/app/logs/monitor.log',
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        # Also log to console
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        logging.getLogger('').addHandler(console)
    
    def load_seen_matches(self):
        """Load previously seen matches from file."""
        try:
            if os.path.exists(self.seen_matches_file):
                with open(self.seen_matches_file, 'r') as f:
                    self.seen_matches = set(json.load(f))
            else:
                self.seen_matches = set()
        except Exception as e:
            logging.error(f"Error loading seen matches: {str(e)}")
            self.seen_matches = set()
    
    def save_seen_matches(self):
        """Save seen matches to file."""
        try:
            os.makedirs(os.path.dirname(self.seen_matches_file), exist_ok=True)
            with open(self.seen_matches_file, 'w') as f:
                json.dump(list(self.seen_matches), f)
        except Exception as e:
            logging.error(f"Error saving seen matches: {str(e)}")
    
    def fetch_page_content(self):
        """Fetch and parse the webpage."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            response = requests.get(self.url, headers=headers)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logging.error(f"Error fetching page: {str(e)}")
            return None
    
    def check_for_keywords(self, html_content):
        """Check for search strings appearing in the same line."""
        if not html_content:
            return False, []
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        for script in soup(["script", "style"]):
            script.decompose()
            
        text = soup.get_text()
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        new_matching_lines = []
        for line in lines:
            line_lower = line.lower()
            if all(word in line_lower for word in self.search_strings):
                normalized_line = ' '.join(line_lower.split())
                if normalized_line not in self.seen_matches:
                    new_matching_lines.append(line)
                    self.seen_matches.add(normalized_line)
        
        if new_matching_lines:
            self.save_seen_matches()
            
        return bool(new_matching_lines), new_matching_lines
    
    def send_email_notification(self, matching_lines):
        """Send an email notification for new matching lines."""
        subject_text = matching_lines[0][:100] + "..." if len(matching_lines[0]) > 100 else matching_lines[0]
        title = f"New Pick Thread: {subject_text}"
        
        message = "Found new thread(s) with your search terms:\n\n"
        message += "\n\n".join(matching_lines)
        message += f"\n\nView thread(s) at: {self.url}"
        
        try:
            msg = MIMEText(message)
            msg['Subject'] = title
            msg['From'] = self.email_config['sender_email']
            msg['To'] = self.email_config['recipient_email']
            
            with smtplib.SMTP(self.email_config['smtp_server'], self.email_config['smtp_port']) as server:
                server.starttls()
                server.login(
                    self.email_config['sender_email'],
                    self.email_config['sender_password']
                )
                server.send_message(msg)
            
            logging.info("Email notification sent successfully")
            return True
        except Exception as e:
            logging.error(f"Error sending email: {str(e)}")
            return False
    
    def start_monitoring(self):
        """Start the monitoring loop."""
        logging.info("Started monitoring webpage")
        print(f"\nMonitoring started")
        print(f"Currently tracking {len(self.seen_matches)} previously seen matches")
        print("Press Ctrl+C to stop monitoring\n")
        
        try:
            while True:
                content = self.fetch_page_content()
                if content:
                    found, new_matches = self.check_for_keywords(content)
                    
                    if new_matches:
                        print(f"\nFound {len(new_matches)} new matching lines!")
                        self.send_email_notification(new_matches)
                    else:
                        print(".", end="", flush=True)
                
                time.sleep(self.check_interval)
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
            logging.info("Monitoring stopped by user")

def main():
    try:
        monitor = WebMonitor()
        monitor.start_monitoring()
    except ValueError as e:
        logging.error(f"Configuration error: {str(e)}")
        print(f"\nError: {str(e)}")
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        print(f"\nUnexpected error: {str(e)}")

if __name__ == "__main__":
    main()
