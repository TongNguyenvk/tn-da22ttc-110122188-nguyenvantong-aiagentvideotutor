"""Debug auth: list users and test password verification."""
import asyncio
from backend.database import Database
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def main():
    await Database.connect()
    db = Database.get_db()
    
    users = await db["users"].find(
        {}, {"email": 1, "password_hash": 1, "role": 1, "name": 1}
    ).to_list(20)
    
    if not users:
        print("NO USERS FOUND IN DATABASE!")
        return
    
    for u in users:
        email = u.get("email", "N/A")
        role = u.get("role", "user")
        h = u.get("password_hash", "")
        prefix = h[:30] if h else "NO HASH"
        print(f"  [{role}] {email} | hash: {prefix}...")
    
    # Test verify with first user
    first = users[0]
    h = first.get("password_hash", "")
    print(f"\nTesting verify on: {first['email']}")
    print(f"Full hash: {h}")
    
    # Test common passwords
    test_passwords = ["admin", "123456", "password", "admin123", "webreel"]
    for p in test_passwords:
        try:
            result = pwd_context.verify(p, h)
            print(f"  '{p}' -> {result}")
            if result:
                print(f"  >>> FOUND PASSWORD: {p}")
                break
        except Exception as e:
            print(f"  '{p}' -> ERROR: {e}")

asyncio.run(main())
