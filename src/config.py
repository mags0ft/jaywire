from yaml import load, FullLoader


CONFIG_FILEPATH = "./config.yaml"

def load_config():
    with open(CONFIG_FILEPATH, "r") as f:
        config = load(f, FullLoader)
    
    return config

configuration = load_config()
