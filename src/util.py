"""
This file has some utilities I need across the codebase.
"""

from .config import configuration


def squeeze(text: str):
    """
    Compress text using basic whitespace removal to make it more token
    efficient.
    """

    text = text.replace("\n", " ")
    text = text.replace("\t", " ")

    # remove the double or triple or whatever spaces
    text = " ".join(text.split())

    return text.strip()


def limit_length(text: str, max_length: int = configuration.get("tool_output_length_limit", 2048)) -> str:
    """
    Limit text length to max_length by cutting off the middle part if, without
    doing so, it would exceed the limit. This is useful for keeping tool
    outputs concise and within token limits, while still preserving the
    beginning and end of the output which often contain the most relevant
    information.
    """

    if len(text) <= max_length:
        return text

    half_length = max_length // 2

    return text[:half_length] + "\n...[output truncated]...\n" + text[-half_length:]
