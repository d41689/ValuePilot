import re

def is_valid_cusip(cusip: str | None) -> bool:
    """Validate CUSIP string format and basic rules."""
    if not cusip:
        return False
    
    cusip = cusip.strip().upper()
    
    # Check length
    if len(cusip) != 9:
        return False
        
    # Check if all zeros
    if cusip == "000000000":
        return False
        
    # Check alphanumeric format (first 8 chars alphanumeric, last char digit)
    # Note: We aren't doing the full check-digit math in MVP 1B unless strictly required,
    # but we can enforce alphanumeric.
    if not re.match(r"^[A-Z0-9]{8}[0-9]$", cusip):
        return False
        
    return True
