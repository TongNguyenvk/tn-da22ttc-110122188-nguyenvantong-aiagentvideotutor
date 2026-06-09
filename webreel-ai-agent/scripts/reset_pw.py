"""Reset admin password to admin@123."""
import asyncio
from backend.database import Database
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def main():
    await Database.connect()
    db = Database.get_db()
    
    new_hash = pwd_context.hash("admin@123")
    result = await db["users"].update_one(
        {"email": "admin@webreel.com"},
        {"$set": {"password_hash": new_hash}}
    )
    
    if result.modified_count:
        print("OK - Password da doi thanh admin@123")
        # Verify
        user = await db["users"].find_one({"email": "admin@webreel.com"})
        ok = pwd_context.verify("admin@123", user["password_hash"])
        print(f"Verify: {ok}")
    else:
        print("FAILED - Khong tim thay admin@webreel.com")

asyncio.run(main())
