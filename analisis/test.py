import pickle
import re
import string
from pathlib import Path

import pandas as pd

try:
    import nltk
    from nltk.corpus import stopwords
    from nltk.tokenize import word_tokenize
except Exception:
    nltk = None
    stopwords = None
    word_tokenize = None

from Sastrawi.Stemmer.StemmerFactory import StemmerFactory

# ===== Path =====
base_dir = Path(__file__).resolve().parent
model_dir = base_dir / "model_machine"
data_dir = base_dir / "data" / "raw"

# ===== Load Artifacts =====
with open(model_dir / "vectorizer.pkl", "rb") as f:
    vectorizer = pickle.load(f)

with open(model_dir / "naive_bayes_model.pkl", "rb") as f:
    nb_model = pickle.load(f)

with open(model_dir / "SVM_model.pkl", "rb") as f:
    svm_model = pickle.load(f)

# ===== Preprocessing =====
def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = re.sub(r"http\\S+|www\\S+|https\\S+", "", text)
    text = re.sub(r"@\\w+", "", text)
    text = re.sub(r"#", "", text)
    text = re.sub(r"bintang\\s*1", " bintang satu ", text, flags=re.IGNORECASE)
    text = re.sub(r"bintang\\s*2", " bintang dua ", text, flags=re.IGNORECASE)
    text = re.sub(r"bintang\\s*3", " bintang tiga ", text, flags=re.IGNORECASE)
    text = re.sub(r"bintang\\s*4", " bintang empat ", text, flags=re.IGNORECASE)
    text = re.sub(r"bintang\\s*5", " bintang lima ", text, flags=re.IGNORECASE)
    text = re.sub(r"\\d+", "", text)
    text = re.sub(r"[^a-zA-Z\\s]", " ", text)
    text = re.sub(r"(.)\\1{1,}", r"\\1", text)
    text = re.sub(r"\\s+", " ", text).strip()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = text.encode("ascii", "ignore").decode("ascii")
    return text

def safe_tokenize(text: str) -> list[str]:
    if not text:
        return []
    if nltk and word_tokenize:
        try:
            nltk.download("punkt", quiet=True)
            return word_tokenize(text)
        except Exception:
            pass
    return re.findall(r"[a-zA-Z]+", text)

def load_normalisasi_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, sep=";")
    out = {}
    for awal_kata, normal in zip(df["kata"], df["normalisasi"]):
        if awal_kata not in out:
            out[str(awal_kata).strip()] = str(normal).strip()
    return out

def build_stopwords(path: Path) -> set[str]:
    stopwords_custom = set()
    if path.exists():
        df = pd.read_csv(path)
        if "stopword" in df.columns:
            stopwords_custom = set(df["stopword"].astype(str).str.strip().str.lower())

    stopwords_nltk = set()
    if nltk and stopwords:
        try:
            nltk.download("stopwords", quiet=True)
            stopwords_nltk = set(stopwords.words("indonesian"))
        except Exception:
            stopwords_nltk = set()

    stopwords_removal = {
        "tidak",
        "bukan",
        "jangan",
        "banyak",
        "masalah",
        "penting",
        "waktu",
        "kurang",
        "mau",
        "dijawab",
        "meminta",
        "tempat",
        "dekat",
        "ingat",
        "gunkan",
        "besar",
        "kerja",
    }

    stopwords_final = (stopwords_custom | stopwords_nltk) - stopwords_removal
    return set(w.strip().lower() for w in stopwords_final if isinstance(w, str))

normalisasi_map = load_normalisasi_map(data_dir / "normalisasi_aveta.csv")
stopwords_final = build_stopwords(data_dir / "stopword_aveta.csv")

stemmer = StemmerFactory().create_stemmer()

def normalize_tokens(tokens: list[str]) -> list[str]:
    return [normalisasi_map.get(t, t) for t in tokens]

def remove_stopwords(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in stopwords_final]

def stem_tokens(tokens: list[str]) -> list[str]:
    return [stemmer.stem(t) for t in tokens]

def preprocess_ulasan(text: str) -> str:
    cleaned = clean_text(text)
    tokens = safe_tokenize(cleaned)
    tokens = normalize_tokens(tokens)
    tokens = remove_stopwords(tokens)
    tokens = stem_tokens(tokens)
    return " ".join(tokens)

# ===== Predict =====
ulasan = input("Masukkan ulasan: ").strip()
preprocessed = preprocess_ulasan(ulasan)
X = vectorizer.transform([preprocessed])

nb_pred = nb_model.predict(X)[0]
svm_pred = svm_model.predict(X)[0]

label_map = {0: "Negatif", 1: "Positif"}

print("Preprocessed:", preprocessed)
print("NB  :", label_map.get(int(nb_pred), nb_pred))
print("SVM :", label_map.get(int(svm_pred), svm_pred))
