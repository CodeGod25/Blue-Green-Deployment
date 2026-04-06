"""
Blue-Green Deployment - Input Validation Module

Provides strict validation for configuration, profiles, upstreams, and user inputs
to prevent injection attacks and configuration errors.
"""

import re
from typing import Tuple


class ValidationError(Exception):
    """Validation error with clear user-facing message."""
    pass


def validate_profile_name(name: str) -> str:
    """
    Validate profile name format.
    
    Rules:
    - Must be 1-50 characters
    - Alphanumeric, underscore, and hyphen only
    - Cannot start or end with hyphen
    
    Args:
        name: Profile name to validate
        
    Returns:
        Validated profile name
        
    Raises:
        ValidationError: If validation fails
    """
    if not name:
        raise ValidationError("Profile name cannot be empty")
    
    if not isinstance(name, str):
        raise ValidationError(f"Profile name must be a string, got {type(name).__name__}")
    
    name = name.strip()
    
    if not name:
        raise ValidationError("Profile name cannot be whitespace only")
    
    if len(name) > 50:
        raise ValidationError(f"Profile name too long ({len(name)} chars, max 50)")
    
    if len(name) < 1:
        raise ValidationError("Profile name too short (min 1 char)")
    
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise ValidationError(
            f"Profile '{name}' contains invalid characters. "
            "Use only: letters, numbers, underscore, hyphen"
        )
    
    if name.startswith('-') or name.endswith('-'):
        raise ValidationError(
            f"Profile '{name}' cannot start or end with hyphen"
        )
    
    return name


def validate_hostname(host: str) -> str:
    """
    Validate hostname or IP address.
    
    Rules:
    - Max 253 characters
    - Valid DNS characters only
    - Can contain dots, numbers, letters, hyphens
    
    Args:
        host: Hostname or IP to validate
        
    Returns:
        Validated hostname
        
    Raises:
        ValidationError: If validation fails
    """
    if not host or not str(host).strip():
        raise ValidationError("Hostname cannot be empty")
    
    host = str(host).strip()
    
    if len(host) > 253:
        raise ValidationError(
            f"Hostname too long ({len(host)} chars, max 253)"
        )
    
    if len(host) < 1:
        raise ValidationError("Hostname too short")
    
    # Check for valid DNS hostname format
    if not re.match(r'^[a-zA-Z0-9.-]+$', host):
        raise ValidationError(
            f"Invalid hostname: '{host}'. "
            "Use DNS-compliant format (alphanumeric, dot, hyphen only)"
        )
    
    # Prevent multiple consecutive dots
    if '..' in host:
        raise ValidationError(f"Hostname '{host}' contains consecutive dots")
    
    # Check labels (parts between dots)
    labels = host.split('.')
    for label in labels:
        if not label:
            raise ValidationError(f"Hostname '{host}' has empty label")
        if len(label) > 63:
            raise ValidationError(f"Hostname label too long: '{label}'")
        if label.startswith('-') or label.endswith('-'):
            raise ValidationError(f"Label '{label}' cannot start/end with hyphen")
    
    return host


def validate_port(port: int | str) -> int:
    """
    Validate port number (1-65535).
    
    Args:
        port: Port number to validate
        
    Returns:
        Validated port as integer
        
    Raises:
        ValidationError: If validation fails
    """
    try:
        port_int = int(port)
    except (ValueError, TypeError):
        raise ValidationError(
            f"Port must be a number, got: {port}"
        )
    
    if port_int < 1:
        raise ValidationError(f"Port {port_int} is too low (minimum 1)")
    
    if port_int > 65535:
        raise ValidationError(f"Port {port_int} is too high (maximum 65535)")
    
    return port_int


def validate_upstream(upstream: str) -> str:
    """
    Validate upstream address (host:port format).
    
    Examples:
    - localhost:8000 ✓
    - blue:80 ✓
    - 192.168.1.1:3000 ✓
    - http://localhost:8000 ✗ (scheme not allowed)
    - localhost ✗ (missing port)
    
    Args:
        upstream: Upstream address to validate
        
    Returns:
        Validated upstream string
        
    Raises:
        ValidationError: If validation fails
    """
    if not upstream or not str(upstream).strip():
        raise ValidationError("Upstream address cannot be empty")
    
    upstream = str(upstream).strip()
    
    # Reject URLs with schemes
    if '://' in upstream:
        raise ValidationError(
            f"Upstream '{upstream}' should not include scheme (e.g., http://). "
            "Use format: hostname:port"
        )
    
    # Must contain exactly one colon
    if ':' not in upstream:
        raise ValidationError(
            f"Upstream '{upstream}' missing port. "
            "Use format: hostname:port (e.g., localhost:8000)"
        )
    
    parts = upstream.rsplit(':', 1)
    if len(parts) != 2:
        raise ValidationError(f"Invalid upstream format: '{upstream}'")
    
    host, port_str = parts
    
    # Validate both parts
    try:
        validate_hostname(host)
    except ValidationError as e:
        raise ValidationError(f"Upstream '{upstream}' has invalid hostname: {e}")
    
    try:
        validate_port(port_str)
    except ValidationError as e:
        raise ValidationError(f"Upstream '{upstream}' has invalid port: {e}")
    
    return upstream


def validate_environment_name(name: str) -> str:
    """
    Validate environment name (blue|green).
    
    Args:
        name: Environment name
        
    Returns:
        Validated environment name (lowercase)
        
    Raises:
        ValidationError: If not valid environment
    """
    valid_envs = ['blue', 'green']
    
    if not isinstance(name, str):
        raise ValidationError(f"Environment must be 'blue' or 'green', got {type(name).__name__}")
    
    name_lower = name.strip().lower()
    
    if name_lower not in valid_envs:
        raise ValidationError(
            f"Invalid environment '{name}'. Must be one of: {', '.join(valid_envs)}"
        )
    
    return name_lower


def validate_source(source: str) -> str:
    """
    Validate event source type.
    
    Valid sources: manual, demo, promote, auto-rollback, initial
    
    Args:
        source: Source type
        
    Returns:
        Validated source
        
    Raises:
        ValidationError: If invalid source
    """
    valid_sources = ['manual', 'demo', 'promote', 'auto-rollback', 'initial']
    
    if not source or not str(source).strip():
        return 'manual'
    
    source = str(source).strip().lower()
    
    if source not in valid_sources:
        raise ValidationError(
            f"Invalid source '{source}'. Must be one of: {', '.join(valid_sources)}"
        )
    
    return source


def validate_profile_config(profile_dict: dict) -> dict:
    """
    Validate a complete profile configuration object.
    
    Expected format:
    {
        "description": str,
        "blue": "hostname:port",
        "green": "hostname:port"
    }
    
    Args:
        profile_dict: Profile configuration to validate
        
    Returns:
        Validated profile config
        
    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(profile_dict, dict):
        raise ValidationError("Profile must be a dictionary")
    
    required_keys = {'blue', 'green'}
    provided_keys = set(profile_dict.keys())
    
    if not required_keys.issubset(provided_keys):
        missing = required_keys - provided_keys
        raise ValidationError(f"Profile missing required keys: {', '.join(missing)}")
    
    validated = {}
    
    if 'description' in profile_dict:
        validated['description'] = str(profile_dict['description'])[:500]
    
    try:
        validated['blue'] = validate_upstream(str(profile_dict['blue']))
    except ValidationError as e:
        raise ValidationError(f"Profile 'blue' upstream invalid: {e}")
    
    try:
        validated['green'] = validate_upstream(str(profile_dict['green']))
    except ValidationError as e:
        raise ValidationError(f"Profile 'green' upstream invalid: {e}")
    
    return validated


# Usage examples
if __name__ == '__main__':
    print("=== Blue-Green Deployment Input Validation Tests ===\n")
    
    test_cases = [
        ("Profile Names", validate_profile_name, [
            ("prod-east", True),
            ("local_test", True),
            ("invalid@name", False),
            ("", False),
        ]),
        ("Hostnames", validate_hostname, [
            ("localhost", True),
            ("blue.example.com", True),
            ("192.168.1.1", True),
            ("invalid..host", False),
            ("", False),
        ]),
        ("Ports", validate_port, [
            ("8080", True),
            ("80", True),
            ("65535", True),
            ("0", False),
            ("99999", False),
        ]),
        ("Upstreams", validate_upstream, [
            ("localhost:8000", True),
            ("blue:80", True),
            ("http://localhost:8000", False),
            ("localhost", False),
            ("", False),
        ]),
        ("Environments", validate_environment_name, [
            ("blue", True),
            ("GREEN", True),
            ("red", False),
            ("", False),
        ]),
    ]
    
    for category, func, cases in test_cases:
        print(f"{category}:")
        for value, should_pass in cases:
            try:
                result = func(value)
                status = "✓ PASS" if should_pass else "✗ FAIL (expected error)"
                print(f"  {status}: {func.__name__}('{value}') → '{result}'")
            except ValidationError as e:
                status = "✓ PASS" if not should_pass else "✗ FAIL (unexpected error)"
                print(f"  {status}: {func.__name__}('{value}') → {e}")
        print()
