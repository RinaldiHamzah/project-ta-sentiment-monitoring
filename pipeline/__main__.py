# pipeline/__main__.py
from .pipeline import run_pipeline

def main():
    results = run_pipeline()
    for row in results:
        print(row)

if __name__ == "__main__":
    main()