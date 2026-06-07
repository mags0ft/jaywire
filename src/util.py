"""
This file has some utilities I need across the codebase.
"""


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
