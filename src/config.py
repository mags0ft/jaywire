"""
Handles loading the configuration from our beloved YAML file.
"""

from yaml import load, FullLoader


CONFIG_FILEPATH = "./config.yaml"


def load_config():
    """
    Loads the YAML configuration file and returns it as a dictionary.
    """

    with open(CONFIG_FILEPATH, "r") as f:
        config = load(f, FullLoader)
    
    return config


configuration = load_config()
