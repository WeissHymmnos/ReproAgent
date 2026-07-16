from pathlib import Path
from .factor_db import FactorDB
from .factor_library_dashboard import generate_dashboard

def main():
    db_path = Path("/tmp/legacy_factor.db")
    html_path = Path("/tmp/factor_library.html")
    
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception as e:
            print(f"Warning: could not remove existing db: {e}")
            
    print(f"Seeding demo data to {db_path}...")
    db = FactorDB(db_path)
    db.seed_demo()
    db.close()
    
    print(f"Generating dashboard to {html_path}...")
    generate_dashboard(db_path=db_path, output_path=html_path)
    print("Done!")

if __name__ == "__main__":
    main()
