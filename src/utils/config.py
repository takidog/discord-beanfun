import os

# Guild: Server id.
LIMIT_GUILD = os.environ.get("LIMIT_GUILD", "").split(",")

BOT_TOKEN = os.environ.get("BOT_TOKEN", None)

LOGIN_TIME_OUT = int(os.environ.get("LOGIN_TIME_OUT", 180))

OTP_DISPLAY_TIME = int(os.environ.get("OTP_DISPLAY_TIME", 20))

HIDDEN_PRIVATE_MESSAGE = bool(int(os.environ.get("HIDDEN_PRIVATE_MESSAGE", 1)))

REDIRECT_URL = os.environ.get("REDIRECT_URL", False)