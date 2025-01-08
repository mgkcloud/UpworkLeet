from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging
import json
import os
from datetime import datetime

logger = logging.getLogger('health_check')

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            # Get system health information
            health_info = {
                "status": "OK",
                "timestamp": datetime.now().isoformat(),
                "uptime": self.get_uptime(),
                "memory": self.get_memory_usage(),
                "environment": {
                    "polling_interval": os.getenv("POLLING_INTERVAL", "480"),
                    "max_jobs_per_poll": os.getenv("MAX_JOBS_PER_POLL", "10"),
                    "high_value_threshold": os.getenv("HIGH_VALUE_THRESHOLD", "7.0")
                }
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(health_info, indent=2).encode())
        else:
            self.send_response(404)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not Found"}).encode())
    
    def get_uptime(self):
        """Get system uptime"""
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                return {
                    "seconds": uptime_seconds,
                    "formatted": self.format_uptime(uptime_seconds)
                }
        except:
            return {"seconds": 0, "formatted": "unknown"}
    
    def get_memory_usage(self):
        """Get memory usage information"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return {
                "rss": memory_info.rss,
                "vms": memory_info.vms,
                "percent": process.memory_percent()
            }
        except:
            return {"rss": 0, "vms": 0, "percent": 0}
    
    def format_uptime(self, seconds):
        """Format uptime seconds into human-readable string"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{days}d {hours}h {minutes}m"
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr"""
        logger.info("%s - - [%s] %s" % (self.address_string(),
                                       self.log_date_time_string(),
                                       format%args))

def start_health_check_server(host='0.0.0.0', port=8000):
    """Start the health check server
    
    Args:
        host (str): Host to bind to (default: '0.0.0.0' for Docker compatibility)
        port (int): Port to listen on (default: 8000)
    
    Returns:
        HTTPServer: The started server instance
    """
    try:
        server = HTTPServer((host, port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        logger.info(f"Health check server started on {host}:{port}")
        return server
    except Exception as e:
        logger.error(f"Failed to start health check server: {str(e)}")
        # Try alternate port if specified port is in use
        if isinstance(e, OSError) and port != 0:
            logger.info("Trying alternate port...")
            return start_health_check_server(host, 0)
        raise
