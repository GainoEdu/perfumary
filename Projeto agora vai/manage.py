"""Comandos de manutenção. No Render, `python manage.py init_db` roda sozinho no start."""
import sys

from app import create_app
from app.bootstrap import init_database

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init_db"
    if cmd == "init_db":
        init_database(create_app())
    else:
        print("Comando desconhecido. Use: python manage.py init_db")
        sys.exit(1)
