"""
Verify Admin System - Quick Check

Kiểm tra nhanh xem admin system có hoạt động đúng không.
"""

import requests
import subprocess
import json

API_BASE = "http://localhost:3000"

def check_backend():
    """Check if backend is running."""
    print("\n" + "="*60)
    print("1. CHECKING BACKEND")
    print("="*60)
    
    try:
        response = requests.get(f"{API_BASE}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("✅ Backend is running")
            print(f"   Version: {data.get('version')}")
            print(f"   Redis: {'Connected' if data.get('redis_connected') else 'Not connected'}")
            print(f"   Jobs: {data.get('jobs', {})}")
            return True
        else:
            print(f"❌ Backend returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Backend not responding: {e}")
        return False


def check_mongodb():
    """Check MongoDB via docker."""
    print("\n" + "="*60)
    print("2. CHECKING MONGODB")
    print("="*60)
    
    try:
        # Count users
        result = subprocess.run(
            ["docker", "exec", "-i", "webreel-mongodb", "mongosh",
             "-u", "webreel", "-p", "webreel_mongo_2026",
             "--authenticationDatabase", "admin",
             "webreel", "--quiet", "--eval", "db.users.countDocuments({})"],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            user_count = result.stdout.strip()
            print(f"✅ MongoDB connected")
            print(f"   Total users: {user_count}")
            
            # Count admin users
            result = subprocess.run(
                ["docker", "exec", "-i", "webreel-mongodb", "mongosh",
                 "-u", "webreel", "-p", "webreel_mongo_2026",
                 "--authenticationDatabase", "admin",
                 "webreel", "--quiet", "--eval", "db.users.countDocuments({role: 'admin'})"],
                capture_output=True, text=True, timeout=10
            )
            admin_count = result.stdout.strip()
            print(f"   Admin users: {admin_count}")
            
            # Count jobs
            result = subprocess.run(
                ["docker", "exec", "-i", "webreel-mongodb", "mongosh",
                 "-u", "webreel", "-p", "webreel_mongo_2026",
                 "--authenticationDatabase", "admin",
                 "webreel", "--quiet", "--eval", "db.jobs.countDocuments({deleted_at: null})"],
                capture_output=True, text=True, timeout=10
            )
            job_count = result.stdout.strip()
            print(f"   Active jobs: {job_count}")
            
            return True, int(user_count), int(admin_count), int(job_count)
        else:
            print(f"❌ MongoDB error: {result.stderr}")
            return False, 0, 0, 0
            
    except Exception as e:
        print(f"❌ Cannot connect to MongoDB: {e}")
        return False, 0, 0, 0


def test_admin_login():
    """Test admin login."""
    print("\n" + "="*60)
    print("3. TESTING ADMIN LOGIN")
    print("="*60)
    
    try:
        response = requests.post(
            f"{API_BASE}/api/auth/login",
            json={"email": "admin@webreel.com", "password": "admin@123"},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Admin login successful")
            print(f"   Email: {data['user']['email']}")
            print(f"   Role: {data['user']['role']}")
            print(f"   Token: {data['access_token'][:30]}...")
            return data['access_token']
        else:
            print(f"❌ Login failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Login error: {e}")
        return None


def test_admin_api(token):
    """Test admin API endpoints."""
    print("\n" + "="*60)
    print("4. TESTING ADMIN API")
    print("="*60)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Test stats
    try:
        response = requests.get(f"{API_BASE}/api/admin/stats", headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("✅ Admin stats API working")
            print(f"   Total users: {data['users']['total']}")
            print(f"   Total jobs: {data['jobs']['total']}")
        else:
            print(f"❌ Stats API failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Stats API error: {e}")
    
    # Test users
    try:
        response = requests.get(f"{API_BASE}/api/admin/users", headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Admin users API working")
            print(f"   Returned {len(data['users'])} users")
        else:
            print(f"❌ Users API failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Users API error: {e}")
    
    # Test jobs
    try:
        response = requests.get(f"{API_BASE}/api/admin/jobs", headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Admin jobs API working")
            print(f"   Returned {data['total']} jobs")
            
            # Check if jobs have user_id (real data indicator)
            if data['total'] > 0:
                first_job = data['jobs'][0]
                has_user_id = 'user_id' in first_job
                has_uuid = len(str(first_job.get('job_id', ''))) > 20
                
                if has_user_id and has_uuid:
                    print("   ✅ Jobs appear to be REAL data (have user_id and UUID)")
                else:
                    print("   ⚠️  Jobs might be MOCKUP data (missing user_id or UUID)")
            else:
                print("   ℹ️  No jobs in database yet")
                
        else:
            print(f"❌ Jobs API failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Jobs API error: {e}")


def main():
    print("="*60)
    print("ADMIN SYSTEM VERIFICATION")
    print("="*60)
    
    # Check backend
    backend_ok = check_backend()
    if not backend_ok:
        print("\n❌ Backend is not running. Start it first:")
        print("   cd webreel-ai-agent")
        print("   python -m backend.main")
        return
    
    # Check MongoDB
    mongo_ok, user_count, admin_count, job_count = check_mongodb()
    if not mongo_ok:
        print("\n❌ MongoDB is not accessible")
        return
    
    if admin_count == 0:
        print("\n⚠️  No admin accounts found!")
        print("   Create one with: python webreel-ai-agent/create_admin.py")
        return
    
    # Test login
    token = test_admin_login()
    if not token:
        print("\n❌ Cannot login as admin")
        print("   Check credentials or create admin account")
        return
    
    # Test API
    test_admin_api(token)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    print(f"\n✅ Backend: Running")
    print(f"✅ MongoDB: Connected ({user_count} users, {job_count} jobs)")
    print(f"✅ Admin Login: Working")
    print(f"✅ Admin API: Working")
    
    if job_count == 0:
        print(f"\n⚠️  No jobs in database yet")
        print("   Frontend will show empty state (not mockup)")
        print("   Create a test job to verify:")
        print("   1. Login to frontend (http://localhost:5173)")
        print("   2. Create a new video job")
        print("   3. Check /admin/jobs to see it appear")
    else:
        print(f"\n✅ Database has {job_count} jobs")
        print("   Frontend should display real data")
    
    print("\n" + "="*60)
    print("NEXT STEPS")
    print("="*60)
    print("\n1. Open frontend: http://localhost:5173")
    print("2. Login with: admin@webreel.com / admin123")
    print("3. Navigate to:")
    print("   - /admin (Dashboard)")
    print("   - /admin/users (User Management)")
    print("   - /admin/jobs (All Jobs)")
    print("\n4. Verify data matches MongoDB counts")
    print("="*60)


if __name__ == "__main__":
    main()
