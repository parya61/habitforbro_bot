"""One-time Telethon auth script. Run interactively to create session file."""
import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

SESSION_PATH = os.path.join("data", "telethon.session")
API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")


async def main():
    if not API_ID or not API_HASH:
        print("Set TG_API_ID and TG_API_HASH in .env")
        print("Get them at https://my.telegram.org/apps")
        return

    os.makedirs("data", exist_ok=True)
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"Authorized as {me.first_name} (id={me.id})")
    print(f"Session saved to {SESSION_PATH}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
