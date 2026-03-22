# # # pipeline/model_predict.py
# import joblib

# class ModelPredict:
#     def __init__(self):
#         self.__nb_model = joblib.load("model_ml/naive_bayes_model.pkl")
#         self.__svm_model = joblib.load("model_ml/SVM_model.pkl")
#         self.__vectorizer = joblib.load("model_ml/vectorizer.pkl")

#     def __vectorize(self, text):
#          return self.__vectorizer.transform([text])

#     def __label(self, pred):
#          return "POSITIF" if pred[0] == 1 else "NEGATIF"

#     def predict_nb(self, text):
#          vec = self.__vectorize(text)
#          return self.__label(self.__nb_model.predict(vec))

#     def predict_svm(self, text):
#          vec = self.__vectorize(text)
#          return self.__label(self.__svm_model.predict(vec))

##Model Machine
from pathlib import Path
import joblib

class ModelPredict:
    def __init__(self):
        base_dir = Path(__file__).resolve().parent.parent
        model_dir = self.__resolve_model_dir(base_dir)

        self.__nb_model = joblib.load(model_dir / "naive_bayes_model.pkl")
        self.__svm_model = joblib.load(model_dir / "SVM_model.pkl")
        self.__vectorizer = joblib.load(model_dir / "vectorizer.pkl")

    def __resolve_model_dir(self, base_dir):
        candidate_dirs = [
            base_dir / "analisis" / "model_machine",
            base_dir / "model_machine",
        ]

        for candidate in candidate_dirs:
            if (candidate / "naive_bayes_model.pkl").exists():
                return candidate

        raise FileNotFoundError(
            "Model files tidak ditemukan. Cek folder model di model_ml, "
            "analisis/model_machine, atau model_machine."
        )

    def __vectorize(self, text):
        return self.__vectorizer.transform([text])

    def __label(self, pred):
        return "POSITIF" if pred[0] == 1 else "NEGATIF"

    def predict_nb(self, text):
        vec = self.__vectorize(text)
        return self.__label(self.__nb_model.predict(vec))

    def predict_svm(self, text):
        vec = self.__vectorize(text)
        return self.__label(self.__svm_model.predict(vec))

# ## Model SMOTE
# from pathlib import Path
# import sys
# import joblib

# def identity_tokenizer(text):
#     return text

# def identity_preprocessor(text):
#     return text

# class ModelPredict:
#     def __init__(self):
#         base_dir = Path(__file__).resolve().parent.parent
#         model_dir = self.__resolve_model_dir(base_dir)
#         self.__prepare_pickle_compat()

#         self.__nb_model = joblib.load(model_dir / "naive_bayes_model_smote.pkl")
#         self.__svm_model = joblib.load(model_dir / "SVM_model_smote.pkl")
#         self.__vectorizer = joblib.load(model_dir / "vectorizer_smote.pkl")

#     def __resolve_model_dir(self, base_dir):
#         candidate_dirs = [
#             base_dir / "analisis" / "model_machine_smote",
#             base_dir / "model_machine_smote",
#             base_dir / "analisis" / "analisis" / "model_machine_smote",
#         ]

#         for candidate in candidate_dirs:
#             if (candidate / "naive_bayes_model_smote.pkl").exists():
#                 return candidate

#         raise FileNotFoundError(
#             "Model SMOTE tidak ditemukan. Cek folder "
#             "analisis/model_machine_smote atau model_machine_smote."
#         )

#     def __prepare_pickle_compat(self):
#         main_module = sys.modules.get("__main__")
#         if main_module is not None:
#             setattr(main_module, "identity_tokenizer", identity_tokenizer)
#             setattr(main_module, "identity_preprocessor", identity_preprocessor)

#     def __vectorize(self, text):
#         if isinstance(text, str):
#             text = text.split()
#         return self.__vectorizer.transform([text])

#     def __label(self, pred):
#         return "POSITIF" if pred[0] == 1 else "NEGATIF"

#     def predict_nb(self, text):
#         vec = self.__vectorize(text)
#         return self.__label(self.__nb_model.predict(vec))

#     def predict_svm(self, text):
#         vec = self.__vectorize(text)
#         return self.__label(self.__svm_model.predict(vec))
