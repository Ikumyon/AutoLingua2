from . import platform as platform
from . import bootstrap as bootstrap
from . import source_watch as source_watch
from . import classification as classification

def read_text_auto(path: str) -> tuple[str, str]: ...
def detect_encoding(data: bytes) -> str: ...
