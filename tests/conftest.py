import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["BOT_TOKEN"] = ""
os.environ["SEED_DEMO"] = "1"
os.environ["ADMIN_LOGIN"] = "demo"
os.environ["ADMIN_PASSWORD"] = "demo"
