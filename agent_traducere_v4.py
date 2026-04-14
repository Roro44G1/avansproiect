import os
import re
import time
import shutil
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup, NavigableString, Tag, Comment

# ============================================
#  AGENT TRADUCERE NUTRISIB v3
#  Foloseste BeautifulSoup pentru extragere corecta
#  Necesita: pip install anthropic beautifulsoup4
# ============================================

FOLDER = Path(__file__).parent.resolve()
OUTPUT = FOLDER / "en"
BLOG_OUTPUT = OUTPUT / "blog"

IGNORA = [
    "footer.html", "success.html", "eval_bia.html", "eval_bio.html",
    "acord_EN.html", "acord_RO.html", "acord_RO1.html",
    "celos - Copie.html", "povestea - Copie.html",
    "disclaimer_EN.html",
]

TAGURI_TRADUSIBILE = {
    'title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'li', 'td', 'th', 'span', 'a', 'button',
    'label', 'figcaption', 'blockquote', 'dt', 'dd',
    'caption', 'summary', 'option', 'small', 'em', 'strong'
}

TAGURI_IGNORA = {'script', 'style', 'code', 'pre', 'svg', 'math'}

DELAY = 0.8

# API KEY — pune cheia ta aici
API_KEY = "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"

# ============================================
#  EXTRAGERE TEXTE CU BEAUTIFULSOUP
# ============================================

def extrage_noduri_text(soup):
    """
    Parcurge DOM-ul si gaseste toate nodurile de text tradusibile.
    Returneaza lista de noduri NavigableString.
    """
    noduri = []

    def parcurge(element, in_ignorat=False):
        if isinstance(element, Tag):
            # Ignora script, style, etc.
            if element.name in TAGURI_IGNORA:
                return
            # Verifica daca tagul e tradusibil
            este_tradusibil = element.name in TAGURI_TRADUSIBILE
            for copil in element.children:
                parcurge(copil, in_ignorat or False)
        elif isinstance(element, Comment):
            return  # Ignora comentariile HTML
        elif isinstance(element, NavigableString):
            # NavigableString = text pur
            text = str(element).strip()
            if (len(text) >= 3 and
                not re.match(r'^[\d\s\.\,\:\;\!\?\-\+\%\/\(\)\[\]©]+$', text) and
                not text.startswith(('{', '/', '@', '#')) and
                not re.match(r'^[A-Z_]{3,}$', text) and  # constante
                element.parent.name not in TAGURI_IGNORA):
                noduri.append(element)

    parcurge(soup)
    return noduri

def extrage_atribute(soup):
    """
    Gaseste atributele tradusibile (alt, placeholder, title pe taguri non-link).
    """
    atribute = []  # lista de (tag, attr_name, valoare_originala)

    for tag in soup.find_all(True):
        if tag.name in TAGURI_IGNORA:
            continue
        # alt pe imagini
        if tag.name == 'img' and tag.get('alt'):
            val = tag['alt'].strip()
            if len(val) >= 3 and not val.startswith(('/','http')):
                atribute.append((tag, 'alt', val))
        # placeholder pe input/textarea
        if tag.name in ('input', 'textarea') and tag.get('placeholder'):
            val = tag['placeholder'].strip()
            if len(val) >= 3:
                atribute.append((tag, 'placeholder', val))
        # meta description/title
        if tag.name == 'meta':
            name = tag.get('name', tag.get('property', ''))
            if name in ('description', 'og:description', 'og:title',
                       'twitter:title', 'twitter:description') and tag.get('content'):
                val = tag['content'].strip()
                if len(val) >= 3:
                    atribute.append((tag, 'content', val))

    return atribute

# ============================================
#  TRADUCERE IN LOTURI
# ============================================

def traduce_lot(texte_list, client, dimensiune_lot=50):
    """
    Traduce o lista de texte, returneaza lista de traduceri in aceeasi ordine.
    """
    if not texte_list:
        return []

    toate_traduse = []

    for i in range(0, len(texte_list), dimensiune_lot):
        lot = texte_list[i:i + dimensiune_lot]

        # Construieste promptul cu index numeric
        linii_input = "\n".join([f"{j}: {text}" for j, text in enumerate(lot)])

        prompt = f"""Traduce aceste texte din romana in engleza.
Sunt de pe un site de nutritie (NutriSib, metoda C.E.L.O.S.).

REGULI:
- Traducere naturala si profesionista
- Pastreaza netradusi: C.E.L.O.S., BIA, NutriSib, low-friction, Tanita
- Pastreaza numele: Radu Pascu, Sibiu
- Returneaza EXACT formatul: INDEX: traducere
- Exact {len(lot)} linii in raspuns, cate una per text
- Fara explicatii, fara text extra
- Capitalizare engleza corecta

TEXTE:
{linii_input}

TRADUCERI:"""

        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )

            raspuns = message.content[0].text.strip()
            traduse_lot = {}

            for linie in raspuns.split('\n'):
                linie = linie.strip()
                if re.match(r'^\d+:', linie):
                    parts = linie.split(':', 1)
                    if len(parts) == 2:
                        idx = int(parts[0].strip())
                        val = parts[1].strip()
                        traduse_lot[idx] = val

            # Construieste lista in ordine, fallback la original daca lipseste
            for j, text_original in enumerate(lot):
                toate_traduse.append(traduse_lot.get(j, text_original))

            print(f"    Lot {i//dimensiune_lot + 1}: {len(lot)} texte traduse")
            time.sleep(DELAY)

        except Exception as e:
            print(f"    Eroare lot {i}: {e}")
            toate_traduse.extend(lot)  # fallback la original

    return toate_traduse

# ============================================
#  PROCESEAZA UN FISIER
# ============================================

def proceseaza_fisier(fisier, dest_folder, index, total, client):
    print(f"\n  [{index}/{total}] {fisier.name}")

    with open(fisier, "r", encoding="utf-8", errors="ignore") as f:
        html_original = f.read()

    print(f"    Dimensiune: {len(html_original):,} caractere")

    # Parseaza cu BeautifulSoup
    soup = BeautifulSoup(html_original, 'html.parser')

    # Extrage noduri de text
    noduri = extrage_noduri_text(soup)
    atribute = extrage_atribute(soup)

    total_texte = len(noduri) + len(atribute)
    if total_texte == 0:
        print(f"    -> Nimic de tradus, copiat direct")
        dest_folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fisier, dest_folder / fisier.name)
        return "ok"

    print(f"    Texte de tradus: {len(noduri)} noduri + {len(atribute)} atribute")

    # Traduce nodurile de text
    texte_noduri = [str(n).strip() for n in noduri]
    traduse_noduri = traduce_lot(texte_noduri, client)

    # Reinjecteaza in DOM
    for nod, traducere in zip(noduri, traduse_noduri):
        # Pastreaza spatiile originale
        text_original = str(nod)
        spatiu_inainte = text_original[:len(text_original) - len(text_original.lstrip())]
        spatiu_dupa = text_original[len(text_original.rstrip()):]
        nod.replace_with(NavigableString(spatiu_inainte + traducere + spatiu_dupa))

    # Traduce atributele
    if atribute:
        texte_attr = [val for _, _, val in atribute]
        traduse_attr = traduce_lot(texte_attr, client)
        for (tag, attr_name, _), traducere in zip(atribute, traduse_attr):
            tag[attr_name] = traducere

    # Actualizeaza lang
    html_tag = soup.find('html')
    if html_tag:
        html_tag['lang'] = 'en'

    # Genereaza HTML final
    html_tradus = str(soup)

    # Salveaza
    dest_folder.mkdir(parents=True, exist_ok=True)
    dest_file = dest_folder / fisier.name

    with open(dest_file, "w", encoding="utf-8") as f:
        f.write(html_tradus)

    print(f"    -> Salvat ({len(html_tradus):,} caractere) ✓")
    return "ok"

# ============================================
#  MAIN
# ============================================

def main():
    print("\n" + "="*55)
    print("  AGENT TRADUCERE NUTRISIB v3")
    print("  (BeautifulSoup — extragere corecta)")
    print("="*55)
    print(f"\n  Folder site: {FOLDER}")

    # Verifica dependinte
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("\n  EROARE: Ruleaza: pip install beautifulsoup4")
        input("\n  Apasa Enter...")
        return

    try:
        import anthropic
    except ImportError:
        print("\n  EROARE: Ruleaza: pip install anthropic")
        input("\n  Apasa Enter...")
        return

    # API Key
    api_key = API_KEY
    if "CHEIA_TA" in api_key:
        api_key = input("\n  Introdu API key-ul Anthropic: ").strip()

    import anthropic as ant
    client = ant.Anthropic(api_key=api_key)

    # Scaneaza
    fisiere_principale = [
        f for f in sorted(FOLDER.glob("*.html"))
        if f.name not in IGNORA
    ]
    fisiere_blog = []
    folder_blog = FOLDER / "blog"
    if folder_blog.exists():
        fisiere_blog = [
            f for f in sorted(folder_blog.rglob("*.html"))
            if f.name not in IGNORA
        ]

    total = len(fisiere_principale) + len(fisiere_blog)
    print(f"\n  Pagini principale: {len(fisiere_principale)}")
    print(f"  Articole blog:     {len(fisiere_blog)}")
    print(f"  Total:             {total}")
    print(f"  Cost estimat:      ~$0.30-0.80")

    if input("\n  Continui? (d/n): ").strip().lower() not in ["d", "da", "y"]:
        print("  Anulat.")
        input("\nApasa Enter...")
        return

    # Backup
    if OUTPUT.exists():
        backup = FOLDER / f"en_backup_{datetime.now().strftime('%Y%m%d_%H%M')}"
        shutil.move(str(OUTPUT), str(backup))
        print(f"\n  Backup: {backup.name}")

    OUTPUT.mkdir(exist_ok=True)
    BLOG_OUTPUT.mkdir(exist_ok=True)

    ok = erori = 0
    index = 0

    print("\n  --- PAGINI PRINCIPALE ---")
    for fisier in fisiere_principale:
        index += 1
        try:
            if proceseaza_fisier(fisier, OUTPUT, index, total, client) == "ok":
                ok += 1
            else:
                erori += 1
        except Exception as e:
            print(f"    EROARE: {e}")
            erori += 1

    print("\n  --- ARTICOLE BLOG ---")
    for fisier in fisiere_blog:
        index += 1
        try:
            if proceseaza_fisier(fisier, BLOG_OUTPUT, index, total, client) == "ok":
                ok += 1
            else:
                erori += 1
        except Exception as e:
            print(f"    EROARE: {e}")
            erori += 1

    # Copiaza CSS/JS
    print("\n  Copiez CSS/JS...")
    for ext in ["*.css", "*.js"]:
        for f in FOLDER.glob(ext):
            if not f.name.startswith("_"):
                shutil.copy2(f, OUTPUT / f.name)

    print("\n" + "="*55)
    print(f"  GATA! Traduse: {ok} | Erori: {erori}")
    print(f"  Fisierele EN sunt in: /en/")
    print("="*55)

    input("\n  Apasa Enter pentru a inchide...")

if __name__ == "__main__":
    main()
