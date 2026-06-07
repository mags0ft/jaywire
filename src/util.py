def squeeze(text: str):
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = " ".join(text.split())

    return text.strip()
