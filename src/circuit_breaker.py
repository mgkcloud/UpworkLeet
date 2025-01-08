"""Circuit breaker implementation for external service calls"""
import time
from functools import wraps
from typing import Callable, Any, Dict
import logging

logger = logging.getLogger(__name__)

class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: int = 60,
        half_open_timeout: int = 30
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_timeout = half_open_timeout
        
        self.failures = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half-open
        
    def can_execute(self) -> bool:
        """Check if the protected function can be executed"""
        now = time.time()
        
        if self.state == "closed":
            return True
            
        if self.state == "open":
            if now - self.last_failure_time >= self.reset_timeout:
                self.state = "half-open"
                return True
            return False
            
        if self.state == "half-open":
            return now - self.last_failure_time >= self.half_open_timeout
            
        return True
        
    def record_failure(self):
        """Record a failure and update circuit state"""
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.failures >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failures} failures")
            
    def record_success(self):
        """Record a success and potentially reset the circuit"""
        if self.state == "half-open":
            self.state = "closed"
            self.failures = 0
            logger.info("Circuit breaker reset to closed state")

class CircuitBreakerRegistry:
    """Registry to manage multiple circuit breakers"""
    _instance = None
    _breakers: Dict[str, CircuitBreaker] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_breaker(self, name: str) -> CircuitBreaker:
        """Get or create a circuit breaker by name"""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker()
        return self._breakers[name]

def with_circuit_breaker(breaker_name: str):
    """Decorator to protect function calls with a circuit breaker
    
    Args:
        breaker_name: Name of the circuit breaker to use
        
    Example:
        @with_circuit_breaker("gemini-api")
        def call_gemini_api():
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            breaker = CircuitBreakerRegistry().get_breaker(breaker_name)
            
            if not breaker.can_execute():
                raise Exception(
                    f"Circuit breaker '{breaker_name}' is open, "
                    f"request blocked for {breaker.reset_timeout}s"
                )
            
            try:
                result = func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception as e:
                breaker.record_failure()
                raise
                
        return wrapper
    return decorator
