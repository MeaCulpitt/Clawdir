"""Simple test agent server for verification testing."""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.parse

# Store the verification token when received
VERIFICATION_TOKEN = None


class TestAgentHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        
        if parsed.path == "/.well-known/clawdir-verify":
            # Extract token from query params
            params = urllib.parse.parse_qs(parsed.query)
            token = params.get("token", [None])[0]
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"token": token}).encode())
            
        elif parsed.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
            
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "name": "TestVerifyAgent",
                "version": "1.0",
                "capabilities": ["test", "verify"]
            }).encode())
    
    def log_message(self, format, *args):
        print(f"[TestAgent] {args[0]}")


if __name__ == "__main__":
    port = 8765
    server = HTTPServer(("0.0.0.0", port), TestAgentHandler)
    print(f"Test agent running on port {port}")
    server.serve_forever()
