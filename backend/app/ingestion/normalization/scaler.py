import re
from typing import Optional, Tuple

class Scaler:
    SCALE_FACTORS = {
        'k': 1_000,
        'thousand': 1_000,
        'm': 1_000_000,
        'mill': 1_000_000,
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
        clean_text = clean_text.replace(',', '')  # Remove commas
        clean_text = re.sub(r'\([^)]*\)', '', clean_text)  # Remove parenthetical notes

        # Handle Percentages
        if '%' in clean_text or value_type == "percent":
            match = re.search(r'[-+]?\d*\.?\d+', clean_text.replace('%', ''))
            if not match:
                return None, None
            try:
                val = float(match.group(0))
                return val / 100.0, "ratio"
            except ValueError:
                return None, None

        # Handle Currency / Scale
        # Detect currency
        currency = "USD" if '$' in clean_text else None  # Default assumption for VL V1
        clean_text = clean_text.replace('$', '')

        # Detect Scale
        scale_multiplier = 1.0
        scale_match = re.search(
            r'(thousand|trillion|tril|billion|bil|million|mill|mil|k|m|b|t)\.?\b',
            clean_text,
        )
        if scale_match:
            token = scale_match.group(1)
            scale_multiplier = float(cls.SCALE_FACTORS.get(token, 1.0))
            clean_text = (
                clean_text[: scale_match.start()] + clean_text[scale_match.end() :]
            )

        # Clean up remaining whitespace and common punctuation
        clean_text = clean_text.strip().rstrip('.')

        try:
            number_match = re.search(r'[-+]?\d*\.?\d+', clean_text)
            if not number_match:
                return None, None
            val = float(number_match.group(0))
            normalized = val * scale_multiplier
            
            unit = "USD" if currency else "number"
            if value_type == "ratio":
                unit = "ratio"
                
            return normalized, unit
        except ValueError:
            return None, None
