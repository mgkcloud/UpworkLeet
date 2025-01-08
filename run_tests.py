#!/usr/bin/env python3
import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path

def setup_test_environment():
    """Set up directories and files needed for testing"""
    # Create test directories if they don't exist
    dirs = [
        "tests/test_data",
        "tests/test_data/job_tracking",
        "tests/test_data/cache",
        "tests/test_data/logs",
        "coverage_html"
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)

def cleanup_test_artifacts(keep_coverage=False):
    """Clean up test artifacts"""
    paths_to_clean = [
        ".pytest_cache",
        "tests/__pycache__",
        "tests/test_data/job_tracking",
        "tests/test_data/cache",
        "tests/test_data/logs"
    ]
    
    if not keep_coverage:
        paths_to_clean.append("coverage_html")
        paths_to_clean.append(".coverage")
    
    for path in paths_to_clean:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

def run_tests(args):
    """Run pytest with specified arguments"""
    # Add project root to PYTHONPATH
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
    
    pytest_args = [
        "pytest",
        "--verbose",
        "--color=yes"
    ]
    
    # Add coverage options if requested
    if args.coverage:
        pytest_args.extend([
            "--cov=src",
            "--cov-report=term-missing",
            "--cov-report=html"
        ])
    
    # Add specific test path if provided
    if args.test_path:
        pytest_args.append(args.test_path)
    
    # Add markers if specified
    if args.markers:
        pytest_args.extend(["-m", args.markers])
    
    # Run tests
    result = subprocess.run(pytest_args, env=env)
    return result.returncode

def main():
    parser = argparse.ArgumentParser(description="Run tests for Upwork Job Automation")
    parser.add_argument("--test-path", help="Specific test file or directory to run")
    parser.add_argument("--markers", help="Only run tests with specific markers (e.g., 'not slow')")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage reports")
    parser.add_argument("--keep-coverage", action="store_true", help="Don't clean up coverage files")
    parser.add_argument("--skip-cleanup", action="store_true", help="Skip cleanup of test artifacts")
    
    args = parser.parse_args()
    
    try:
        # Set up test environment
        setup_test_environment()
        
        # Run tests
        return_code = run_tests(args)
        
        # Clean up unless skipped
        if not args.skip_cleanup:
            cleanup_test_artifacts(keep_coverage=args.keep_coverage)
        
        sys.exit(return_code)
        
    except KeyboardInterrupt:
        print("\nTest run interrupted by user")
        cleanup_test_artifacts(keep_coverage=args.keep_coverage)
        sys.exit(1)
    except Exception as e:
        print(f"Error running tests: {e}")
        cleanup_test_artifacts(keep_coverage=args.keep_coverage)
        sys.exit(1)

if __name__ == "__main__":
    main()
