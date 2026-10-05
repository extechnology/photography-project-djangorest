def format_bytes_human(size_bytes: int | float | None) -> str:
    """
    Format byte size into human readable string with units (B, KB, MB, GB).
    """
    if not size_bytes or size_bytes <= 0:
        return "0 MB"
    
    bytes_val = float(size_bytes)
    if bytes_val >= 1024 * 1024 * 1024:
        return f"{round(bytes_val / (1024 * 1024 * 1024), 2)} GB"
    elif bytes_val >= 1024 * 1024:
        return f"{round(bytes_val / (1024 * 1024), 1)} MB"
    elif bytes_val >= 1024:
        return f"{round(bytes_val / 1024, 1)} KB"
    return f"{int(bytes_val)} B"


# Re-export watermark utility
from utils.watermark import stamp_watermark_on_image

