import requests
from bs4 import BeautifulSoup
import time
import logging
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
import json
import os
import re
from urllib.parse import urlparse

class ConfigError(Exception):
    """Custom exception for configuration errors"""
    pass

class WebMonitor:
    def __init__(self):
        """Initialize the web monitor using environment variables."""
        self.setup_logging()
        self.validate_and_set_config()
        self.load_seen_matches()
        
    def validate_url(self, url):
        """Validate URL format and accessibility."""
        if not url:
            raise ConfigError("MONITOR_URL is required")
            
        # Check URL format
        try:
            result = urlparse(url)
            if not all([result.scheme, result.netloc]):
                raise ConfigError("Invalid URL format. Must include http:// or https://")
        except Exception:
            raise ConfigError("Invalid URL format")
            
        # Test URL accessibility
        try:
            response = requests.head(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise ConfigError(f"Unable to access URL: {str(e)}")
            
        return url

    def validate_search_terms(self, terms):
        """Validate search terms."""
        if not terms:
            raise ConfigError("SEARCH_STRINGS is required")
            
        terms_list = [term.strip() for term in terms.split(',')]
        if not terms_list:
            raise ConfigError("No valid search terms provided")
            
        if any(len(term) < 2 for term in terms_list):
            raise ConfigError("Search terms must be at least 2 characters long")
            
        return terms_list

    def validate_interval(self, interval):
        """Validate check interval."""
        try:
            interval = int(interval)
            if interval < 60:
                raise ConfigError("CHECK_INTERVAL must be at least 60 seconds")
            if interval > 86400:  # 24 hours
                raise ConfigError("CHECK_INTERVAL must not exceed 86400 seconds (24 hours)")
            return interval
        except ValueError:
            raise ConfigError("CHECK_INTERVAL must be a valid number")

    def validate_email_config(self, config):
        """Validate email configuration."""
        required_fields = ['smtp_server', 'smtp_port', 'sender_email', 
                         'sender_password', 'recipient_email']
        
        for field in required_fields:
            if not config.get(field):
                raise ConfigError(f"Missing required email configuration: {field}")

        # Validate email addresses
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, config['sender_email']):
            raise ConfigError("Invalid sender email address")
        if not re.match(email_pattern, config['recipient_email']):
            raise ConfigError("Invalid recipient email address")

        # Validate SMTP port
        try:
            port = int(config['smtp_port'])
            if port < 1 or port > 65535:
                raise ConfigError("Invalid SMTP port number")
        except ValueError:
            raise ConfigError("SMTP port must be a valid number")

        return config

    def validate_and_set_config(self):
        """Validate and set all configuration from environment variables."""
        # Website configuration
        self.url = self.validate_url(os.getenv('MONITOR_URL'))
        self.search_strings = self.validate_search_terms(os.getenv('SEARCH_STRINGS'))
        self.check_interval = self.validate_interval(os.getenv('CHECK_INTERVAL', '300'))
        
        # Email configuration
        email_config = {
            'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
            'smtp_port': os.getenv('SMTP_PORT', '587'),
            'sender_email': os.getenv('SENDER_EMAIL'),
            'sender_password': os.getenv('SENDER_PASSWORD'),
            'recipient_email': os.getenv('RECIPIENT_EMAIL')
        }
        self.email_config = self.validate_email_config(email_config)
        
        # Storage configuration
        self.seen_matches_file = '/app/config/seen_matches.json'
        
        # Log configuration summary
        logging.info("Configuration loaded successfully:")
        logging.info(f"URL: {self.url}")
        logging.info(f"Search Terms: {', '.join(self.search_strings)}")
        logging.info(f"Check Interval: {self.check_interval} seconds")
        logging.info(f"SMTP Server: {self.email_config['smtp_server']}:{self.email_config['smtp_port']}")
        logging.info(f"Sender Email: {self.email_config['sender_email']}")
        logging.info(f"Recipient Email: {self.email_config['recipient_email']}")
        
    def setup_logging(self):
        """Set up logging configuration."""
        log_dir = '/app/logs'
        os.makedirs(log_dir, exist_ok=True)
        
        logging.basicConfig(
            filename=f'{log_dir}/monitor_{datetime.now().strftime("%Y%m%d")}.log',
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
            os.makedirs(os.path.dirname(self.seen_matches_file), exist_ok=True)
            if os.path.exists(self.seen_matches_file):
                with open(self.seen_matches_file, 'r') as f:
                    self.seen_matches = set(json.load(f))
            else:
                self.seen_matches = set()
                self.save_seen_matches()  # Create initial file
        except Exception as e:
            logging.error(f"Error loading seen matches: {str(e)}")
            self.seen_matches = set()
    
    def save_seen_matches(self):
        """Save seen matches to file."""
        try:
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
            response = requests.get(self.url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.Timeout:
            logging.error("Timeout while fetching page")
            return None
        except requests.RequestException as e:
            logging.error(f"Error fetching page: {str(e)}")
            return None
    
    def check_for_keywords(self, html_content):
        """Check for search strings appearing in the same line."""
        if not html_content:
            return False, []
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            for script in soup(["script", "style"]):
                script.decompose()
                
            text = soup.get_text()
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            
            new_matching_lines = []
            for line in lines:
                line_lower = line.lower()
                if all(word.lower() in line_lower for word in self.search_strings):
                    normalized_line = ' '.join(line_lower.split())
                    if normalized_line not in self.seen_matches:
                        new_matching_lines.append(line)
                        self.seen_matches.add(normalized_line)
            
            if new_matching_lines:
                self.save_seen_matches()
                
            return bool(new_matching_lines), new_matching_lines
        except Exception as e:
            logging.error(f"Error parsing content: {str(e)}")
            return False, []
    
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
            
            with smtplib.SMTP(self.email_config['smtp_server'], 
                            int(self.email_config['smtp_port']), 
                            timeout=30) as server:
                server.starttls()
                server.login(
                    self.email_config['sender_email'],
                    self.email_config['sender_password']
                )
                server.send_message(msg)
            
            logging.info("Email notification sent successfully")
            return True
        except smtplib.SMTPAuthenticationError:
            logging.error("SMTP authentication failed. Check your email credentials")
            return False
        except Exception as e:
            logging.error(f"Error sending email: {str(e)}")
            return False
    
    def start_monitoring(self):
        """Start the monitoring loop."""
        logging.info("Started monitoring webpage")
        print(f"\nMonitoring started")
        print(f"Currently tracking {len(self.seen_matches)} previously seen matches")
        print("Press Ctrl+C to stop monitoring\n")
        
        consecutive_errors = 0
        
        try:
            while True:
                try:
                    content = self.fetch_page_content()
                    if content:
                        found, new_matches = self.check_for_keywords(content)
                        
                        if new_matches:
                            print(f"\nFound {len(new_matches)} new matching lines!")
                            if self.send_email_notification(new_matches):
                                consecutive_errors = 0  # Reset error counter on success
                            else:
                                consecutive_errors += 1
                        else:
                            print(".", end="", flush=True)
                            consecutive_errors = 0  # Reset error counter on successful check
                    else:
                        consecutive_errors += 1
                        
                    # If we've had too many errors, increase wait time
                    if consecutive_errors > 5:
                        logging.warning(f"Multiple errors occurred. Waiting {self.check_interval * 2} seconds")
                        time.sleep(self.check_interval * 2)
                        consecutive_errors = 0  # Reset after extended wait
                    else:
                        time.sleep(self.check_interval)
                        
                except Exception as e:
                    logging.error(f"Unexpected error in monitoring loop: {str(e)}")
                    consecutive_errors += 1
                    time.sleep(self.check_interval)
                    
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
            logging.info("Monitoring stopped by user")

def main():
    try:
        monitor = WebMonitor()
        monitor.start_monitoring()
    except ConfigError as e:
        logging.error(f"Configuration error: {str(e)}")
        print(f"\nConfiguration Error: {str(e)}")
        print("Please check your environment variables and try again.")
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        print(f"\nUnexpected error: {str(e)}")
        print("Check the logs for more details.")

if __name__ == "__main__":
    main()