# main.py
from pipeline.place_id import extract_place_id

def get_place_id_from_input(value: str):
    # Sama persis dengan logic register: support id langsung, URL penuh, dan short URL redirect.
    return extract_place_id(value, resolve_redirect=True)
if __name__ == "__main__":
    sample = "https://www.google.com/maps/place/Aveta+Hotel+Malioboro/@-7.793821,110.3633018,748m/data=!3m2!1e3!4b1!4m9!3m8!1s0x2e7a59c6e514a5a3:0xbeca960436f8fe88!5m2!4m1!1i2!8m2!3d-7.7938263!4d110.3658767!16s%2Fg%2F11ffltnndc?entry=ttu&g_ep=EgoyMDI2MDIyNS4wIKXMDSoASAFQAw%3D%3D"
    place_id = get_place_id_from_input(sample)
    print(f"Hasil: {place_id or 'Place ID tidak ditemukan.'}")
