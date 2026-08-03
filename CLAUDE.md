# Egzamin Żeglarski — kontekst projektu

## Co to jest

Aplikacja webowa do przygotowania na egzamin żeglarza jachtowego PZŻ.
Repo: https://github.com/pbochynski/egzamin-zeglarski
Hosting: GitHub Pages (statyczna strona, bez backendu)

## Pliki w projekcie

### Do repozytorium (wrzucamy)
- `index.html` — aplikacja webowa (HTML/CSS/JS, bez frameworków)
- `questions.json` — baza 455 pytań A/B/C z poprawnymi odpowiedziami
- `images/` — 107 plików JPEG (ilustracje do pytań, ~8.6MB łącznie)
- `convert.py` — skrypt do (re)generowania questions.json z PDFów
- `CLAUDE.md` — ten plik

### NIE wrzucamy do repo
- `*.pdf` — oryginalne pliki źródłowe z pytaniami (za duże, prawa autorskie)
- `checkpoint.json` — plik tymczasowy generowany przez convert.py
- `docs/` — dokumentacja projektowa (spec, plan)
- `test-fetch.html`, `test2.html` — pliki debugowe (można usunąć)

## Struktura questions.json

```json
{
  "questions": [
    {
      "id": 1,                          // globalny ID (1-455)
      "orig_number": 1,                 // numer pytania w PDFie (w ramach kategorii)
      "category": "Budowa jachtów",     // jedna z 7 kategorii
      "text": "Treść pytania...",
      "answers": {"A": "...", "B": "...", "C": "..."},
      "correct": "C",                   // poprawna odpowiedź
      "image": "images/q_46.jpg"        // null jeśli brak ilustracji
    }
  ]
}
```

## Kategorie (455 pytań łącznie)
- Budowa jachtów: 102
- Manewrowanie: 50
- Meteorologia: 50
- Podstawy locji: 73
- Przepisy drogi: 63
- Ratownictwo wodne: 50
- Teoria żeglowania: 67

## Uwagi o questions.json

- `orig_number` odpowiada numerowi pytania w PDFie — może się powtarzać w ramach kategorii (celowe duplikaty w oryginale, np. to samo pytanie z innym obrazkiem)
- 15 odpowiedzi zostało zweryfikowanych i poprawionych przez Claude Opus (patrz sekcja poniżej)
- Obrazki to całe strony PDF (JPEG 85%), kliknięcie w aplikacji otwiera powiększenie

## Poprawione odpowiedzi (weryfikacja przez AI)

| ID | Kategoria | Stara | Nowa | Powód |
|----|-----------|-------|------|-------|
| 25, 38 | Budowa jachtów | A | C | Optymist = ket, nie slup |
| 64 | Budowa jachtów | C | A | Kipa nie jest częścią żagla |
| 79 | Budowa jachtów | C | B | Sztormreling = uchwyt, nie drabinka |
| 92 | Budowa jachtów | B | A | Ket = 1 maszt i 1 żagiel |
| 243, 259 | Podstawy locji | B | A | Zasada mijania znaków pod prąd |
| 272 | Podstawy locji | C | B | Polska mapa: metry, nie sążnie |
| 281 | Przepisy drogi | A | C | Jacht ustępuje statkowi łowiącemu |
| 289 | Przepisy drogi | B | C | Minąć od strony rombów, nie kul |
| 319 | Przepisy drogi | A | B | Czarny stożek = motorowo-żaglowy |
| 376 | Ratownictwo wodne | A | C | Najpierw wzywać pomocy |
| 390 | Teoria żeglowania | B | A | Wiatr pozorny > rzeczywisty na bajdewindzie |
| 406 | Teoria żeglowania | C | A | Lewy hals = wiatr z lewej burty |
| 415 | Teoria żeglowania | B | A | Zarefowanie grota → zawietrzność |

## Regeneracja questions.json

Jeśli trzeba przetworzyć PDFy od nowa:

```bash
pip install pymupdf anthropic pillow
export ANTHROPIC_API_KEY=...   # lub używa ~/.claude/settings.json automatycznie
python3 convert.py             # wszystkie PDFy → /tmp/egzamin/
python3 convert.py --resume    # wznów po przerwaniu
python3 convert.py --pdf "Meteorologia.pdf"  # tylko jeden PDF
```

PDFy muszą być w tym samym katalogu co convert.py.

## GitHub Pages

Po pushu do main włącz Pages: Settings → Pages → Source: main, folder /.
URL: https://pbochynski.github.io/egzamin-zeglarski/

## Lokalny serwer (testowanie)

```bash
python3 -m http.server 8000
# otwórz http://localhost:8000
```

Nie otwieraj index.html bezpośrednio jako plik (fetch questions.json nie zadziała).
