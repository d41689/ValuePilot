import re
from typing import Optional, Tuple

class Scaler:
    SCALE_FACTORS = {
        'k': 1_000,
        'thousand': 1_000,
        'm': 1_000_000,
        'mil': 1_000_000,
        'million': 1_000_000,
        'b': 1_000_000_000,
        'bil': 1_000_000_000,
        'billion': 1_000_000_000,
        't': 1_000_000_000_000,
        'tril': 1_000_000_000_000,
        'trillion': 1_000_000_000_000,
    }

    @classmethod
    def normalize(cls, raw_value: str, value_type: str = "number") -> Tuple[Optional[float], Optional[str]]:
        """
        Normalizes a raw text value into a float and a base unit.
        
        Args:
            raw_value: The string to parse (e.g., "$1.2 bil", "5.4%")
            value_type: expected type hint ("number", "percent", "ratio", "currency")
            
        Returns:
            (normalized_value, base_unit)
            e.g. (1200000000.0, "USD")
        """
        if not raw_value:
            return None, None

        clean_text = raw_value.lower().strip()
        clean_text = clean_text.replace(',', '') # Remove commas

        # Handle Percentages
        if '%' in clean_text or value_type == "percent":
            clean_text = clean_text.replace('%', '')
            try:
                val = float(clean_text)
                return val / 100.0, "ratio"
            except ValueError:
                return None, None

        # Handle Currency / Scale
        # Detect currency
        currency = "USD" if '$' in clean_text else None # Default assumption for VL V1
        clean_text = clean_text.replace('$', '')

        # Detect Scale
        scale_multiplier = 1.0
        
        # Check for scale tokens at the end or embedded
        for token, factor in cls.SCALE_FACTORS.items():
            # Check if token is in the string as a word
            # simplistic regex check
            if re.search(r'\b' + re.escape(token) + r'\b', clean_text):
                scale_multiplier = factor
                # Remove the token
                clean_text = re.sub(r'\b' + re.escape(token) + r'\b', '', clean_text)
                break
            # Check if it ends with the token (e.g. "1.2bil") without space
            elif clean_text.endswith(token) and not clean_text[0].isdigit(): 
                # Edge case handling needed? Usually VL has space or punctuation.
                pass 

        # Clean up remaining whitespace and common punctuation
        clean_text = clean_text.strip().rstrip('.')
        
        try:
            val = float(clean_text)
            normalized = val * scale_multiplier
            
            unit = "USD" if currency else "number"
            if value_type == "ratio":
                unit = "ratio"
                
            return normalized, unit
        except ValueError:
            return None, None
