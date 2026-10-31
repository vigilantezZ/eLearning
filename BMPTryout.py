import os
import sys

# Ensure working directory is always the folder of the .exe when running as Windows Service / Task Scheduler
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

import webbrowser
from app import create_app, db
from app.models import User
from seed_data import seed_database
from waitress import serve

def ensure_database_ready(app):
    with app.app_context():
        # Check if database file exists or if User table has records
        try:
            admin_user = User.query.filter_by(username='admin').first()
            if not admin_user:
                print("[*] Database belum diinisialisasi. Menjalankan auto-seeding awal...")
                seed_database()
            else:
                print("[*] Database siap.")
        except Exception as e:
            print(f"[*] Inisialisasi database awal... ({e})")
            seed_database()

def main():
    print("================================================================")
    print("  BMP Tryout & CBT System - Production Server (Waitress WSGI)")
    print("================================================================")
    
    app = create_app()
    ensure_database_ready(app)

    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0'

    print(f"\n[+] Server berjalan pada:")
    print(f"    - Lokal       : http://localhost:{port}")
    print(f"    - IP Jaringan : http://127.0.0.1:{port}")
    print("\n[+] Akun Login Default:")
    print("    - Administrator : admin / admin123")
    print("    - Supervisor    : supervisor / spv123")
    print("    - Peserta Demo  : peserta1 / peserta123")
    print("\n[+] Tekan CTRL + C di jendela ini untuk menghentikan server.")
    print("================================================================\n")

    # Serve using high-performance Waitress WSGI server
    serve(app, host=host, port=port, threads=8)

if __name__ == '__main__':
    main()
