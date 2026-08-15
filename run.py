import os
from app import create_app, db

app = create_app()

if __name__ == '__main__':
    # Ensure database exists
    with app.app_context():
        db.create_all()
    
    port = int(os.environ.get('PORT', 5000))
    print(f"Server CBT Tryout berjalan di: http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)
