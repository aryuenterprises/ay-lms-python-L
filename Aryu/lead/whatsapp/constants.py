# lead/whatsapp/constants.py

GRAPH_API_BASE_URL = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v23.0"

# Message Directions
INCOMING = "incoming"
OUTGOING = "outgoing"

# Sender Types
SENDER_CUSTOMER = "customer"
SENDER_AGENT = "agent"
SENDER_SYSTEM = "system"

# Message Types
TEXT = "text"
IMAGE = "image"
VIDEO = "video"
DOCUMENT = "document"
AUDIO = "audio"
STICKER = "sticker"
LOCATION = "location"
INTERACTIVE = "interactive"
TEMPLATE = "template"

# Message Status
STATUS_SENT = "sent"
STATUS_DELIVERED = "delivered"
STATUS_READ = "read"
STATUS_FAILED = "failed"

SUPPORTED_MESSAGE_TYPES = [
    TEXT,
    IMAGE,
    VIDEO,
    DOCUMENT,
    AUDIO,
    STICKER,
    LOCATION,
    INTERACTIVE,
    TEMPLATE,
]