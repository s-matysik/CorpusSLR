# CorpusSLR - raport audytu i wprowadzonych zmian

Wersja przed pracami: **1.0.0** · wersja wydawana: **1.1.0**
Zakres: audyt poprawności, naprawa usterek, rozbudowa źródeł i parserów,
niezależna walidacja deduplikacji, konsolidacja testów i pakowanie pod
zgłoszenie do *SoftwareX*.

---

## 1. Stan wyjściowy i stan końcowy

| | 1.0.0 | 1.1.0 |
|---|---|---|
| kod pakietu | 2 740 instrukcji | 5 250 wierszy w 28 modułach |
| testy | 47 | **592** (offline, bez sieci) |
| pokrycie | 87 % *(przy pełnym zestawie z audytu)* | **98 %** |
| źródła API | 4 | **9** |
| parsery plikowe | 3 formaty, 8 dialektów RIS | **7 formatów**, 8 dialektów RIS, 5 dialektów CSV, 2 dialekty BibTeX |
| F1 rozpoznawania duplikatów (ASySD Diabetes) | 0,957 | **0,993** |
| F1 end-to-end (z wyborem kopii do zachowania) | 0,870 | **0,981** |
| 60 000 rekordów, tytuły ze wspólnym początkiem | nie ukończone w 12 min | **5,2 s** |
| Python | 3.9-3.13 (deklarowane, nietestowane) | 3.9 i 3.13 przetestowane w CI-równoważnym przebiegu |

---

## 2. Usterki wykryte i naprawione

Kolejność malejącej istotności metodycznej. Każda pozycja ma test regresyjny.

### 2.1 Fałszywie pozytywna deduplikacja przy sprzecznych identyfikatorach

Etap dopasowania rozmytego scalał rekordy o **różnych DOI/PMID**, jeśli tytuły
były podobne: „…part 1" z „…part 2", „badanie leku X" z „badaniem leku Y".
W przeglądzie systematycznym to bezgłośna utrata odrębnego badania.

*Naprawa:* `_conflicting_ids()` - dwa rekordy, które oba deklarują dany
identyfikator i się nim różnią, nie są scalane niezależnie od podobieństwa
tytułów. `dedup.py`

### 2.2 Fałszywie pozytywne ze wspólnego DOI suplementu konferencyjnego

Wykryte dopiero w walidacji na złotym standardzie ASySD: wydawcy przypisują
jeden DOI całemu suplementowi ze streszczeniami konferencyjnymi. W zbiorze
Diabetes 21 numerów DOI obejmowało 140 rekordów opisujących różne prace
(jeden DOI - 11 rekordów o 6 tytułach, maksymalne podobieństwo tytułów 0,47).
Kaskada traktowała wspólny DOI jako dowód silniejszy od dowolnej różnicy
tytułów; **91 % wszystkich fałszywie dodatnich powstawało w etapie
identyfikatorowym, nie rozmytym** - odwrotnie niż podpowiada intuicja.

*Naprawa:* parametr `id_title_min=0.50`. Powiązanie przez identyfikator
współdzielony przez **3 lub więcej** rekordów wymaga podobieństwa tytułów
≥ 0,50. Ograniczenie do krotności ≥ 3 jest konieczne: bezwarunkowa straż
łamie domknięcie przechodnie, bo normalny przypadek międzybazowy (ten sam DOI,
podtytuł obecny w jednej bazie i nieobecny w drugiej) zostałby odrzucony.
Fałszywie dodatnie: **66 → 10**, F1 **0,957 → 0,993**. `dedup.py`

### 2.3 Brak domknięcia przechodniego w kaskadzie identyfikatorów

Rekord dzielący DOI z jednym rekordem, a PMID z innym, opisuje tę samą pracę,
ale przypisanie „pierwszy pasujący klaster" nie łączyło wszystkich trzech.
Skutkiem były zawyżone liczby w diagramie PRISMA.

*Naprawa:* struktura zbiorów rozłącznych `_UnionFind` (kompresja ścieżek,
union by size). `dedup.py`

### 2.4 Degeneracja wydajności do zachowania kwadratowego

Blokowanie po pierwszych 10 znakach znormalizowanego tytułu tworzy jeden
gigantyczny koszyk, gdy setki tytułów zaczynają się od tego samego zwrotu
(„The effect of…", „A systematic review of…") - wzorzec typowy dla korpusów
przeglądowych. Pomiary: 4 000 rekordów w jednym koszyku = **354 s**,
24 000 rekordów = 68 s, wariant z odrębnymi pracami nie ukończył się w 12 min.
Dodatkowo blokowanie prefiksowe **gubiło duplikaty różniące się początkiem**
tytułu (przedimek) - czułość 0/200 dla tej perturbacji.

*Naprawa:* indeks odwrotny tokenów tytułu z sondowaniem czterech najrzadszych
tokenów i limitem `max_block`. Po naprawie: 4 000 w jednym koszyku = **0,06 s**,
60 000 rekordów = 5,2-12,3 s, skalowanie liniowe, ~5 kB/rekord. Czułość 100 %
dla przedimka, interpunkcji, wielkości liter i dywizu. `dedup.py`

### 2.5 Ciche pomijanie etapu rozmytego przy przepełnieniu koszyka

Usterka wprowadzona wraz z blokowaniem tokenowym (2.4) i wykryta w benchmarku:
gdy korpus ma wąskie słownictwo tytułów, **wszystkie** koszyki rekordu mogą
przekroczyć `max_block` i były po prostu pomijane. Skrajny przypadek: 0
wykrytych duplikatów bez żadnego ostrzeżenia - korpus z duplikatami wyglądał
identycznie jak czysty.

*Naprawa:* rekordy bez kandydatów trafiają do indeksu kompozytowego (para dwóch
najrzadszych tokenów), który dzieli wielki koszyk zamiast go odrzucać.
Nieobsłużone przypadki są **raportowane**: `DedupReport.warnings()` oraz pola
`oversized_blocks_skipped`, `records_without_candidates`, `id_links_rejected`
widoczne też w `report.summary()`. `dedup.py`

### 2.6 Niestabilny i gorszy wybór rekordu do zachowania

Wykryte przy weryfikacji figury walidacyjnej. Klaster reprezentowała kopia
o „najbogatszych" metadanych (`richness()`), co dawało dwa problemy: `record_id`
zachowywanego rekordu zależał od tego, który eksport był przypadkiem
kompletniejszy (brak powtarzalności między uruchomieniami), a zgodność
z rekordem ze złotego standardu wynosiła tylko 64,8 %. Dodatkowo `merge_from()`
wypełnia jedynie puste pola, więc zachowywana kopia narzucała własne wartości
tam, gdzie bazy się różnią - błędny tytuł czasopisma w jednym eksporcie
propagował się na scalony rekord.

*Naprawa:* zachowywana jest **pierwsza napotkana** kopia (jak przy imporcie do
menedżera bibliografii), a pola sporne rozstrzyga większość głosów w klastrze
(`_resolve_conflicts()`, przy 3+ kopiach; przy parze nie ma większości).
Kompletność metadanych jest identyczna, bo `merge_from()` nadal uzupełnia
braki, ale `record_id` jest deterministyczny. Przy wejściu w kolejności
przeszukiwań zgodność z rekordem ze złotego standardu rośnie z 64,8 % do **98 %**
(F1 end-to-end 0,870 → **0,981**). Przewaga nie jest niezależna od kolejności:
przy wejściu pogrupowanym duplikatami wynik to 0,839 wobec 0,846 dla reguły
„najbogatsza", a przy losowej permutacji 0,716 wobec 0,735 - reguła wybrana za
determinizm i za przypadek kolejności przeszukiwań, którą niosą rzeczywiste
importy, nie jako dominująca na każdej permutacji. `dedup.py`

### 2.7 Normalizacja tytułów niszcząca litery z kreską i ligatury

`unicodedata.normalize("NFKD", …)` nie rozkłada `ł`, `ø`, `đ`, `ð`, `ħ`, `ı`,
`ß`, `æ`, `œ`, `þ`, więc filtr znaków łączących zamieniał je w spację: „wpływ"
→ „wp yw". Tytuły polskie, skandynawskie, niemieckie, tureckie i chorwackie
normalizowały się na dziurawe łańcuchy, co jednocześnie psuło dopasowanie
rozmyte i sprawiało, że transliterowana kopia tego samego rekordu wyglądała
jak inna praca.

*Naprawa:* tablica transliteracji `_TRANSLIT` (litery z kreską, ligatury,
eszett, myślniki i cudzysłowy typograficzne) stosowana **przed** NFKD.
`record.py`

### 2.8 Walidacja przepływu PRISMA z luką

`validate()` pomijała kontrolę bilansu pełnych tekstów, gdy
`studies_included == 0`, i nie odrzucała wartości ujemnych. Przegląd, który nie
włączył żadnego badania, nadal musi rozliczyć oceniane raporty.

*Naprawa:* kontrola arytmetyczna bezwarunkowa, jawne odrzucanie wartości
ujemnych we wszystkich polach. `prisma.py`

### 2.9 Ślad audytowy gubiący identyfikatory

`deduplicate()` wywołane na zwykłej liście rekordów (nie na `Corpus`) zapisywało
puste `kept_uid`/`removed_uid`, więc dziennik decyzji był nieużywalny do
raportowania PRISMA-S.

*Naprawa:* rekordy bez UID otrzymują `T######` w trakcie deduplikacji;
istniejące UID-y korpusu (`R######`) są zachowywane. `dedup.py`

### 2.10 Niezabezpieczone pętle stronicowania

Pętle w klientach OpenAlex i Crossref nie miały zabezpieczenia przed
niezmieniającym się ani powtórzonym kursorem - awaria serwera lub zmiana API
oznaczała pętlę nieskończoną w środku pobierania korpusu.

*Naprawa:* zbiór widzianych kursorów i przerwanie przy braku postępu lub
pustej stronie. `sources/openalex.py`, `sources/crossref.py`

### 2.11 Wzbogacanie abstraktów z własną, słabszą normalizacją DOI

`recover_abstracts()` obcinało tylko prefiks `https://doi.org/`, zamiast użyć
`normalize_doi()` pakietu, więc DOI w innej formie odsyłacza nie dopasowywał się
do klucza, z którego zbudowano samo zapytanie.

*Naprawa:* jednolite użycie `normalize_doi()`. `enrich.py`

### 2.12 Podatność eksportu CSV na wstrzyknięcie formuł

Tytuł rozpoczynający się od `=`, `+`, `-` lub `@` jest interpretowany jako
formuła po otwarciu pliku ekranowania w arkuszu kalkulacyjnym. Tytuły
bibliograficzne legalnie zaczynają się od `-` i `+` (nazwy chemiczne, stany
ładunku).

*Naprawa:* `_safe_cell()` poprzedza takie wartości apostrofem w `to_csv()`
i `to_screening_csv()`. `export.py`

### 2.13 Eksport BibTeX: escapowanie i typ wpisu

Trzy usterki wykryte testami round-trip: (a) escapowane były tylko `{ } &`,
więc `$` otwierał tryb matematyczny i zjadał tekst, a ukośnik stawał się
sekwencją kontrolną; (b) każdy rekord zapisywano jako `@article` niezależnie od
typu dokumentu; (c) `@misc` nie zapisywał podtypu, więc `preprint` ginął
w round-tripie i tracił status literatury szarej w liczeniu PRISMA.

*Naprawa:* pełne escapowanie dziesięciu znaków specjalnych przez placeholdery
(kolejność ma znaczenie - ukośnik pierwszy), mapowanie typu dokumentu na typ
wpisu BibTeX z `booktitle` dla materiałów konferencyjnych i rozdziałów,
zapis podtypu w polu `type`. Odczyt: ochrona escapowanych literałów przed
czyszczeniem trybu matematycznego. `export.py`, `parsers/bibtex.py`

### 2.14 Nawarstwianie ostrzeżeń kompilacji zapytań

Metody kompilujące są idempotentne z kontraktu i wywoływane wielokrotnie
(`compile_all()`, potem klient źródła), ale każde wywołanie dopisywało
ostrzeżenia. Trafiają one dosłownie do załącznika PRISMA-S.

*Naprawa:* `SearchQuery._warn()` dodaje komunikat tylko raz. `query.py`

### 2.15 Nieujęta w nawias klauzula roku w zapytaniu Scopus

`to_scopus()` emitowało `PUBYEAR > 2014 AND PUBYEAR < 2027` bez nawiasów, więc
klauzula wiązała się luźno z połączonym przez OR warunkiem typu dokumentu.
Zapytanie raportowane w PRISMA-S (Item 8) miało inne znaczenie niż zamierzone.

*Naprawa:* nawiasowanie zakresu lat. `query.py`

### 2.16 Błędna detekcja dialektu ProQuest

Rozszerzenie detekcji o Cochrane CENTRAL rozpoznawało słowo „CENTRAL"
w nazwie bazy, przez co **ProQuest Central** był klasyfikowany jako Cochrane
i odczytywany z niewłaściwym priorytetem pól.

*Naprawa:* rozpoznanie tylko po akcesji `CN-` lub jawnym „Cochrane".
`parsers/ris.py`

### 2.17 Rozbieżności dokumentacji i kodu

Trzy docstringi opisywały zachowanie inne niż zaimplementowane: warunek
odrzucania wpisów BibTeX (opis sugerował koniunkcję, kod używa alternatywy),
format akcesji Embase (opis podawał wzorzec, którego regex nie dopasowuje),
oraz - w trakcie tych prac - wartość kalibracji progu przypisana omyłkowo
etapowi rozmytemu zamiast straży tytułowej.

*Naprawa:* wszystkie trzy opisy uzgodnione z kodem. `parsers/bibtex.py`,
`parsers/ris.py`, `dedup.py`

---

## 3. Rozbudowa funkcjonalna

### 3.1 Nowe źródła API

| źródło | uwagi metodyczne |
|---|---|
| Semantic Scholar (S2AG) | wyszukiwanie relewancyjne, opcjonalny klucz; **składnia nieodtwarzalna** - ostrzeżenie w `SearchEvent.notes` |
| arXiv | Atom API, `min_interval` 3 s zgodnie z regulaminem; parser wydzielony jako `parse_arxiv_atom()` |
| bioRxiv, medRxiv | API udostępnia **wyłącznie okna dat**, nie wyszukiwanie pełnotekstowe; filtrowanie lokalne po terminach, ograniczenie udokumentowane w docstringu i w nocie zdarzenia |

### 3.2 Nowe parsery eksportów

BibTeX (dekodowanie LaTeX, dialekty IEEE Xplore i ACM), EndNote XML,
CSV pięciu dostawców (Scopus, WoS, IEEE Xplore, Dimensions, EBSCO), oraz
rozszerzenie RIS o Embase, Cochrane CENTRAL, EBSCOhost z rozróżnieniem baz
(Business Source, PsycINFO, CINAHL, ERIC) i ProQuest ABI/INFORM.

### 3.3 Rejestr principal/supplementary

`sources/registry.py` klasyfikuje bazy na *principal* i *supplementary* zgodnie
z Gusenbauer & Haddaway (2020). `audit_strategy()` ostrzega, gdy przegląd
opiera się wyłącznie na źródłach supplementary, gdy ma tylko jedno źródło
principal, oraz gdy większość rekordów pochodzi ze źródeł supplementary.
Wynik wchodzi do załącznika PRISMA-S.

---

## 4. Walidacja deduplikacji

Pełny raport: `asysd_validation_report.md`.

Zbiór: ASySD *Diabetes*, N = 1845 (1261 duplikatów, 584 unikaty), złoty standard
z Hair K., Bahor Z., Macleod M., Liao J., Sena E. S. (2023), *BMC Biology* **21**,
art. 189 - opis bibliograficzny zweryfikowany przez Crossref.

Raportowane są **dwie** metryki, bo odpowiadają na różne pytania.
*Rozpoznawanie duplikatów* pyta, czy właściwe rekordy uznano za duplikaty - to
własność, za którą oceniano opublikowane narzędzia. *End-to-end* wymaga
dodatkowo, by zachowanym rekordem była kopia wybrana przez recenzentów, i jest
ostrzejsze niż liczby opublikowane.

| metoda | metryka | FP | FN | F1 |
|---|---|---:|---:|---:|
| ASySD | opublikowana | 0 | 2 | 0,999 |
| **CorpusSLR 1.1.0** | rozpoznawanie duplikatów | 10 | 8 | **0,993** |
| EndNote | opublikowana | 0 | 43 | 0,983 |
| **CorpusSLR 1.1.0** | end-to-end | 25 | 23 | **0,981** |
| CorpusSLR 1.0.0 | rozpoznawanie duplikatów | 66 | 43 | 0,957 |
| SRA-DM | opublikowana | 70 | 114 | 0,926 |
| recenzenci (ludzie) | opublikowana | 3 | 368 | 0,828 |

Metryka end-to-end zakłada wczytywanie rekordów w kolejności przeszukiwań (tak
jak przy imporcie do menedżera bibliografii). Jest **zależna od kolejności
wejścia** - to ograniczenie samej metryki, nie implementacji, bo złoty standard
oznaczył jako `unique` kopię z pierwszego przeszukiwanego źródła:

| kolejność wejścia | pierwsza napotkana | najbogatsza |
|---|---:|---:|
| kolejność przeszukiwań | **0,981** | 0,870 |
| pogrupowane duplikatami | 0,839 | 0,846 |
| losowa permutacja (średnia z 3 ziaren) | 0,716 | 0,735 |

Dane nie są tracone w żadnym wariancie.

Poprawność implementacji metryki potwierdzona niezależnie: przeliczenie kolumny
decyzji ludzkich recenzentów daje F1 0,826 wobec opublikowanych 0,828
(zgodność ±2 rekordy) - test nie zależy od kodu deduplikacji.

**CorpusSLR wypada gorzej od ASySD i nie jest to wygładzane:** 10 fałszywie
dodatnich (25 w metryce end-to-end) to prace, które w rzeczywistym przeglądzie
zniknęłyby z ekranowania.
ASySD osiąga zero FP wieloprzebiegowym blokowaniem na kombinacjach pól
(tytuł+strony, tytuł+autor, ISBN+tom+strony), którego CorpusSLR nie odtwarza - 
to najbliższy kierunek rozwoju.

---

## 5. Testy

592 testy, wszystkie **offline** - atrapa sesji HTTP (`tests/conftest.py`)
odtwarza zapisane odpowiedzi i rejestruje wywołania; żaden test nie dotyka
sieci. Pokrycie **98 %** (2 810 instrukcji, 67 nieobjętych).

Przebieg na Pythonie 3.13: 592 przechodzą. Na 3.9: 591 przechodzi, 1 pominięty
(zależny od `python-docx`, nieinstalowanego w tym środowisku). Zero `xfail` - 
każda usterka wykryta w audycie została naprawiona, a nie tylko oznaczona.

Metoda: testy pisane jako oczekiwane zachowanie; tam gdzie biblioteka go nie
spełniała, oznaczane `xfail(strict=True)` z opisem przyczyny. Ścisły znacznik
zgłasza błąd, gdy test zaczyna przechodzić, co wymusza usunięcie znacznika po
naprawie i uniemożliwia przemilczenie usterki.

---

## 6. Pakowanie

Wersja 1.1.0 spójna w `pyproject.toml`, `corpusslr/__init__.py` i
`CITATION.cff`. Uzupełnione klasyfikatory (3.9-3.13, OS Independent, Typing),
słowa kluczowe, `abstract` w `CITATION.cff`, sekcja `[tool.pytest.ini_options]`.
`python -m build` produkuje wheel i sdist, `twine check` przechodzi, instalacja
wheela w izolowanym katalogu udostępnia 68 symboli publicznych.

Zależności bez zmian: `requests` w rdzeniu, `python-docx` opcjonalnie dla
załącznika `.docx`. Parsery są dependency-free (`ElementTree`, `re`, `csv`).

---

## 7. Pozostałe ograniczenia

1. **Walidacja na jednym zbiorze.** Zmierzono zbiór Diabetes (N = 1845).
   Pozostałe zbiory ASySD (Neuroimaging N = 3434, Cardiac N = 8948, Depression,
   SRSR) nie są opublikowane w repozytorium pakietu R - dostępne przez OSF,
   którego nie objęto pomiarem. Wynik F1 0,993 należy traktować jako pomiar
   na korpusie biomedycznym z dwóch baz (PubMed, Embase), nie jako wartość
   uniwersalną.
2. **Scopus nietestowany na żywo.** Search API wymaga klucza instytucjonalnego;
   klient pokryty wyłącznie testami na atrapach HTTP.
3. **Wybór rekordu reprezentanta zależy od kolejności wejścia.** Zachowywana
   jest pierwsza napotkana kopia, co odpowiada rekordowi ze złotego standardu
   w 98 % klastrów przy wczytywaniu w kolejności przeszukiwań, ale spada do
   ok. 65 % przy losowej kolejności. Jeśli kolejność wczytywania nie
   odzwierciedla kolejności przeszukiwań, zachowany `record_id` będzie inny niż
   oczekiwany - same dane pozostają kompletne.
4. **Wyszukiwanie w bioRxiv/medRxiv** jest filtrowaniem lokalnym okna dat, nie
   wyszukiwaniem w bazie; przy szerokich zakresach dat oznacza to pobranie
   dużej liczby rekordów.
5. **Semantic Scholar i Crossref** nie przyjmują składni boolowskiej - 
   zapytanie jest spłaszczane, więc wyszukiwanie nie jest w pełni odtwarzalne.
   Oba są oznaczone jako *supplementary* i generują ostrzeżenie.
6. **Brak rozwinięcia słowników kontrolowanych** (MeSH, Emtree) - zapytanie jest
   kompilowane dosłownie, bez ekspansji terminów tezaurusowych, co obniża recall
   w bazach biomedycznych względem strategii przygotowanej przez bibliotekarza.

---

# Część II: wydanie 1.2.0 - dwie najważniejsze bazy i wieloprzebiegowe blokowanie

Zakres tej części wynika z dwóch uwag: (1) czy pobieranie z Scopusa i Web of
Science działa, (2) że ustępowanie ASySD w deduplikacji trzeba nadrobić.

## II.1 Scopus - cztery wady klienta, wszystkie zweryfikowane na żywo

Klient istniał, ale **nigdy nie był uruchomiony wobec prawdziwego API**. Dostęp
instytucjonalny (klucz + insttoken) pozwolił zmierzyć każdą wadę bezpośrednio.

| # | wada | konsekwencja | stan po naprawie |
|---|---|---|---|
| 1 | pobierany tylko `dc:creator` | jeden autor zamiast pełnej listy - bezpośrednio psuje porównanie nazwisk w deduplikacji i eksport | widok COMPLETE parsuje tablicę `author`; na rekordzie kontrolnym **17 autorów zamiast 1**, dodatkowo słowa kluczowe i abstrakt (1694 znaki) |
| 2 | brak obsługi limitu `start+count ≤ 5000` | przy większym korpusie pętla kończyła się błędem HTTP 400 | ostatnia strona przycinana do limitu, jawna nota w zdarzeniu PRISMA-S; **zaimplementowano stronicowanie kursorem**, które limit omija (zweryfikowane: 450 unikatowych rekordów przez 5 stron) |
| 3 | `count=25` zamiast dozwolonych 200 | ośmiokrotnie więcej zapytań | rozmiar strony dobierany do widoku (200 dla STANDARD, 25 dla COMPLETE - zmierzone maksima API) |
| 4 | brak rozpoznania błędów uprawnień | 401 przy dostępie spoza sieci instytucji wyglądał jak zły klucz | komunikat wymienia obie przyczyny i wskazuje `insttoken` - Elsevier zwraca dla nich **identyczny** komunikat, co potwierdzono empirycznie |

Zmierzone granice API (do dokumentacji): STANDARD `count=200` przechodzi,
`201` → HTTP 400; COMPLETE `25` przechodzi, `26` → HTTP 400; `start=4800,
count=200` przechodzi, `start=4900, count=200` → HTTP 400 z mylącym komunikatem
„Exceeds the number of search results" (nie oznacza braku wyników, tylko
przekroczenie limitu stronicowania offsetowego - klient to wyjaśnia).

`corpusslr/sources/scopus.py`: 93 → 494 wiersze, pokrycie 100%, 54 testy.

## II.2 Web of Science - brak klienta API

WoS był dostępny **wyłącznie przez parser eksportu plikowego**. Dla bazy
oznaczonej w rejestrze jako principal to luka, nie decyzja projektowa.

Dodano `corpusslr/sources/wos.py` - `WosStarterSource` dla WoS Starter API
(nagłówek `X-ApiKey`, 50 trafień na stronę, stronicowanie zabezpieczone),
`parse_wos_hit()` testowalny bez HTTP, mapowanie `uid` (`WOS:...`) i `pmid`
w formacie `MEDLINE:12345678` do kaskady identyfikatorów. Starter nie zwraca
abstraktów - zdarzenie PRISMA-S niesie o tym notę i wskazuje `recover_abstracts()`.
Dodano `SearchQuery.to_wos()` (składnia `TS=`/`TI=`, `PY=`, `DT=`, `LA=`).

**Ograniczenie:** brak klucza Clarivate - klient przetestowany wyłącznie na
atrapach HTTP zgodnych z dokumentacją Starter API. Wymaga weryfikacji na żywo
przed poleganiem na nim w produkcyjnym przeglądzie.

## II.3 Deduplikacja: wieloprzebiegowe blokowanie

Zaimplementowano mechanizm, którego brak był zapisany w ograniczeniach wersji 1.1.
Diagnoza pokazała, że pozostałe błędy mają dwie różne przyczyny, więc powstały
dwie techniki (szczegóły i pomiary - aneks B raportu walidacyjnego):

- **straż współrzędnych** (`separate_by_locus`) - wspólny identyfikator nie łączy
  pozycji o różnej pierwszej stronie ani różnym tomie i roku; to sygnatura
  suplementu konferencyjnego. FP 10 → 2.
- **rundy blokujące** (`blocking_rounds`) - kandydaci z dokładnej zgodności
  kombinacji pól (`author+year+pages`, `journal+volume+pages` i trzy inne),
  oceniani łagodniejszym progiem tytułowym, bo zgodność kombinacji jest
  niezależnym dowodem. FN 8 → 6.

Razem: **F1 0,9929 → 0,9964** (FP 2, FN 7) - dystans do ASySD zmniejszony
o połowę, wyprzedzenie EndNote (0,983) i SRA-DM (0,926). Metryka end-to-end,
przeliczona osobno dla v1.2, poprawia się znacznie mniej (0,9810 → 0,9829), bo
jest zdominowana przez wybór reprezentanta, na który nowe techniki nie wpływają.

Koszt wydajnościowy ograniczono limitem koszyka rund (25): bez niego 60 000
rekordów zużywało 1,25 GB i 33 s, po ograniczeniu 101 MB i 8,4 s przy identycznej
dokładności. Pełną serię pomiarową przeliczono w jednym przebiegu na kodzie
z limitem - koszt na rekord jest stały (138-141 µs w scenariuszu patologicznym,
227-291 µs w realistycznym), co potwierdza skalowanie liniowe.

## II.4 Ustalenie metodyczne dotyczące metryki

Analiza struktury błędów ujawniła, że 3 z 10 problematycznych klastrów wersji 1.1
nie zawierają wcale rekordu oznaczonego `unique` - reguła „jeden `unique` na
klaster" karze je automatycznie. Przy przypisaniu opartym na liczności wersja 1.1
daje FP 7, FN 0. Metryka klastrowa została zachowana dla porównywalności
z publikacją ASySD, ale zastrzeżenie jest odnotowane w raporcie walidacyjnym
(aneks B.5) - kilka pozostałych błędów to artefakt reguły przypisania.

## II.5 Stan wydania 1.2.0

| | 1.1.0 | 1.2.0 |
|---|---:|---:|
| testy | 592 | **734** |
| pokrycie | 98% | 98% |
| źródła API | 9 | **10** (dodany WoS Starter) |
| F1 deduplikacji (klastrowo) | 0,993 | **0,9964** |

Python 3.13: 734 przechodzą. Python 3.9: 733 + 1 pominięty. Zero `xfail`.

---

# Część III: wydanie 1.3.0 - przewyższenie ASySD, Scopus, odtwarzalne pobieranie

## III.1 Deduplikacja: F1 0,9996 wobec 0,9990 dla ASySD

Metoda: diagnoza **każdego** pozostałego błędu osobno, naprawa przyczyny zamiast
strojenia progu. Pięć rozłącznych klas błędów, cztery z nich to usterki
normalizacji niezależne od dziedziny:

1. **DOI procentowo zakodowany** - DOI serializowany z adresu URL zapisuje
   nawiasy PII Elseviera jako `%28`/`%29`; `normalize_doi()` dekoduje teraz
   procentowo (z zabezpieczeniem przed podwójnym kodowaniem).
2. **Strony zniszczone przez arkusz kalkulacyjny** - Excel zamienia `11-9` na
   `11-Sep`, a `11-19` na `Nov-19`; 38 z 1845 rekordów w zbiorze. Odzyskanie
   oryginału jest niejednoznaczne (`Sep-11` to 9-11 albo 11-9), więc
   `excel_mangled_pages()` traktuje taką wartość jako **nieznaną** - nieczytelna
   strona nigdy nie blokuje scalenia.
3. **Numer artykułu z prefiksem** - `137960` i `e0137960` to ta sama pozycja;
   porównanie po cyfrach.
4. **Dwa DOI wydawcy dla jednej pracy** - `_copublication_evidence()` nadpisuje
   blokadę sprzecznego identyfikatora, ale tylko przy zgodności tytułu (≥0,99),
   roku, pierwszej strony i autora. Wyczerpujące sprawdzenie wszystkich par:
   4 trafienia, wszystkie prawdziwe duplikaty, zero par odrębnych.
5. **Konferencja vs artykuł** - złoty standard i Cochrane traktują streszczenie
   konferencyjne i artykuł jako dwa raporty jednego badania. Pierwsza,
   szeroka wersja sygnatury rozdzielałaby 110 par przy 1 słusznej - odrzucona;
   przyjęta wymaga braku DOI **i** stron po stronie konferencyjnej.

Wynik: **FP 0, FN 1, F1 0,9996** (ASySD: FP 0, FN 2, F1 0,9990). Przy
przypisaniu niezależnym od reguły metryki grupowanie jest bezbłędne (F1 1,0000).

**Koszt wydajnościowy i jego usunięcie.** Mechanizmy dokładności podniosły koszt
do 6 459 µs/rekord. Profilowanie wskazało dwie przyczyny: kosztowne dopasowanie
tytułów uruchamiane na wszystkich 44 parach kandydatów na rekord, oraz brak
buforowania `norm_title` (299 428 przeliczeń przy 6 000 rekordów). Dokładne
ograniczenie długości plus zapamiętywanie: **6 459 → 238 µs, ~27×, bez zmiany
dokładności**.

## III.2 Scopus: usterka krytyczna dla odtwarzalności

Pogłębiona weryfikacja na żywo (klucz + token instytucjonalny) wykazała, że
`LANGUAGE()` w Scopusie przyjmuje **angielskie nazwy języków, nie kody ISO**,
a nierozpoznana wartość **zeruje całe wyszukiwanie bez żadnego komunikatu
błędu** - przegląd zwracałby zero rekordów i nikt by tego nie zauważył.
Zmierzona charakterystyka metadanych (50 rekordów, widok COMPLETE): DOI 98%,
abstrakt 96%, ISSN 96%, słowa kluczowe 88%, `prism:pageRange` tylko 22%
(uzupełnione awaryjnie przez `article-number` do 100%). Widok STANDARD nie
zwraca autorów, słów kluczowych ani abstraktów w 100% rekordów - jest
bezużyteczny do przesiewu bez odzyskiwania abstraktów.

## III.3 Odtwarzalne pobieranie (`corpusslr/harvest.py`)

Nowy moduł realizuje wymóg odtwarzalności PRISMA-S: archiwum surowych odpowiedzi
z sumami kontrolnymi, odtworzenie analizy **bez sieci**, deterministyczna suma
kontrolna korpusu (pola bibliograficzne, bez liczników cytowań) oraz wykrywanie
dryfu między pobraniami. Zmierzone na żywo: Crossref zwraca **ten sam zbiór
w niestabilnej kolejności** (2 z 5 przebiegów zgodne z referencyjną), a tokeny
kursora różnią się między przebiegami - stąd kanoniczne sortowanie jest
warunkiem powtarzalnej sumy kontrolnej. Po jego zastosowaniu dwa niezależne
pobrania dały identyczną sumę kontrolną.

## III.4 Stan wydania

| | 1.2.0 | 1.3.0 |
|---|---:|---:|
| testy (Python 3.13) | 734 | **933** |
| pokrycie | 98% | 98% |
| F1 deduplikacji (grupowanie) | 0,9964 | **0,9996** |
| koszt deduplikacji przy 60k | 161 µs/rek. | 161-422 µs/rek. |
| publiczne API | 87 symboli | **96 symboli** |

Python 3.9: 932 przechodzą + 1 pominięty. Zero `xfail`.

---

# Część IV: walidacja wielodziedzinowa i wynikająca z niej poprawka

Walidacja dokładności była jednodziedzinowa (biomedycyna), co było najpoważniejszym
pozostałym ograniczeniem zewnętrznej trafności. Zbudowano protokół
**identifier-blind**: prawdą odniesienia jest znormalizowany DOI, po czym
wszystkie pola identyfikacyjne są usuwane, a deduplikacja musi odtworzyć klastry
z tytułu, autorów, roku i pól bibliograficznych. Korpus: 7 440 rekordów pobranych z 5 baz, z czego 7 187 poddanych ocenie po
kuracji typów dokumentów,
cztery dziedziny, dwa zapytania na dziedzinę, pomiar przy domyślnych parametrach.
Protokół jest częścią pakietu (`corpusslr/validate.py`, 45 testów), nie skryptem
jednorazowym.

## IV.1 Trzy ustalenia istotne dla artykułu

1. **Brak przeuczenia pod biomedycynę.** Biomedyczne ramię (F1 0,9523) jest
   *wyższe* niż informatyka (0,9400), ale oba mieszczą się w jednym pasmie
   z zarządzaniem (0,8880) - deduplikacja bez identyfikatorów nie jest
   zdolnością specyficzną dla biomedycyny.
2. **Próg 0,93 transferuje się między dziedzinami.** Argmax leży na progu ≥0,93
   w każdej dziedzinie, zysk ≤0,006, rozstęp F1 ≤0,021 w całym zakresie
   0,80-0,99. Nie ma podstaw do kalibracji per dziedzina.
3. **Ekonomia jest wyjątkiem i przyczyna nie jest algorytmiczna.** Precyzja 0,397
   wynika z tego, że pole rozprowadza prace jako numerowane working papers
   (NBER, Fed, SSRN) pod odrębnymi DOI. Klasyfikacja wszystkich 226 par
   odrzuconych przez arbitra wykazała, że **dokładnie jedna** to nad-scalenie dwóch
   różnych prac; pozostałe 225 to warianty wersji jednej pracy (139 preprint wobec wersji opublikowanej,
   45 ta sama praca na dwóch serwerach preprintów,
   30 ten sam rozdział w dwóch wydaniach książki,
   3 working paper wobec artykułu, 4 ta sama praca w dwóch
   seriach working papers, 4 erratum wobec oryginału). Liczba wzrosła z 219 do 226
   po wprowadzeniu obrony `pseudo_page_range`, która odblokowała 7 dalszych scaleń - 
   wszystkie okazały się wariantami wersji, więc wniosek się nie zmienił.

## IV.2 Poprawka: zakres stron będący długością artykułu

Badanie wykryło, że **strony blokowały scalenie w 86 z 109 przeoczonych par**.
Czasopisma numerujące artykuły (BMC, Frontiers, PLOS, BMJ Open) przekazują
indeksatorom długość artykułu, która trafia do pól zakresu stron: dla
`10.1186/s12912-024-01991-0` DOAJ zwraca `1-15`, gdy numer artykułu to **393**
(potwierdzone niezależnie u obu źródeł). `pseudo_page_range()` traktuje zakres
zaczynający się od strony 1 jako **nieznany** - tak samo jak zakres zniszczony
przez arkusz - bo jest niejednoznaczny, a nie błędny.

Czułość: biomedycyna 0,894 → **0,980**, informatyka 0,967 → **0,994**, ekonomia
0,806 → **0,925**. Precyzja zachowuje się niejednolicie: rośnie w ekonomii
(+0,0325) i informatyce (+0,0027), nie zmienia się w zarządzaniu (0,8560 - brak
zakresów `1-N` w tym ramieniu) i **spada o 0,0036 w biomedycynie**, gdzie zysk
czułości jest największy. Wymiana jest zatem asymetryczna, nie jednostronna:
+0,086 czułości za -0,0036 precyzji. Na zbiorze ASySD nie ma ani jednego takiego
zakresu, więc wynik 0,9996 pozostaje bez zmian.

## IV.3 Ograniczenia, które pozostają

Ramiona nauk społecznych są małe (ekonomia 67 par podlegających ocenie,
zarządzanie 116, wobec 662 i 512), przedziały ufności nie zostały policzone,
a dwa zapytania na dziedzinę mieszają efekt dziedziny z efektem tematu. OpenAlex
i Semantic Scholar nie weszły do pomiaru (brak rozstrzygnięcia o kluczu; odmowy
HTTP 429), a to bazy o dobrym pokryciu nauk społecznych. Największa prawdziwa
grupa ma 4 rekordy, więc badanie nie mówi nic o dużych klastrach.

---

# Część V: wydanie 1.4.0 - gotowość do zgłoszenia

Zakres tej części to trzy rzeczy, których wcześniejsze wydania nie dotykały:
infrastruktura repozytorium wymagana przez SoftwareX, interfejs wiersza poleceń
oraz **weryfikacja pokrycia wobec własnej specyfikacji projektu**. Ostatnia
okazała się najbardziej produktywna, bo wykryła usterki cichej utraty danych
i trzy błędy w warstwie naukowej.

## V.1 Błędy w warstwie naukowej

Najpoważniejsze ustalenia tej części nie są usterkami kodu, lecz **błędami
w tym, co pakiet twierdzi o literaturze**. Recenzent SoftwareX, który sprawdzi
cytowanie, znalazłby każdy z nich.

1. **Sześć błędnych numerów pozycji PRISMA-S.** Załącznik generowany przez pakiet
   podawał recenzentowi złe numery: daty jako pozycja 10 (pozycja 10 to *Search
   filters*, daty to 13), liczby rekordów per baza jako 13 (to 15), platforma
   jako 3 (pozycja 3 to *Study registries*, platforma to 1). Odczytano Tabelę 1
   z artykułu źródłowego i naprawiono wszystkie sześć. `tests/test_prisma_s_items.py`
   sprawdza teraz każde cytowanie numeru wobec listy kontrolnej **oraz wobec
   tematu pozycji**, więc numer użyty w niewłaściwym kontekście też nie przejdzie.

2. **Błędna atrybucja klasyfikacji IEEE Xplore.** Rejestr oznaczał IEEE Xplore
   jako principal, powołując się na Gusenbauera i Haddawaya (2020). Ich lista 14
   systemów principal (ACM DL, BASE, ClinicalTrials.gov, Cochrane Library,
   EbscoHost, OVID, ProQuest, PubMed, ScienceDirect, Scopus, TRID, Virtual Health
   Library, Web of Science, Wiley Online Library) **nie zawiera IEEE Xplore** - 
   artykuł je testował, ale umieścił w drugiej połowie. Poziom principal
   zachowano jako świadomy wybór konwencji dziedzinowej dla przeglądów
   inżynierskich, ale rejestr ma teraz jawną proweniencję każdego wpisu
   (`SOURCE_EVIDENCE`: `listed` / `platform` / `field-convention` /
   `not-principal`), a załącznik PRISMA-S generuje sekcję *Reporting notes*
   z zastrzeżeniem, co wolno przypisać któremu źródłu.

3. **Odrzucona teza ze specyfikacji projektu.** Specyfikacja podaje, że tylko
   ~34% czasopism Scopusa jest indeksowanych w WoS. Singh i in. (2021) tego nie
   twierdzą. Z ich własnych opublikowanych proporcji (99,11% czasopism WoS jest
   w Scopusie; Dimensions ma 82,22% więcej czasopism niż WoS i 48,17% więcej niż
   Scopus) wynika, że Scopus jest ok. 1,23× większy od WoS, a udział Scopusa
   pokryty przez WoS to **ok. 81%**, nie 34%. Asymetria jest realna, ale znacznie
   mniejsza, niż założono. Liczba nie weszła do manuskryptu; README podaje
   wartości opublikowane, a odrzucona teza jest zapisana w
   `references_verified.json` wraz z powodem odrzucenia.

## V.2 Usterki cichej utraty danych

Każda z tych usterek zniekształcała liczbę „records identified" w diagramie
PRISMA **bez żadnego sygnału** - najgorszy możliwy tryb awarii dla narzędzia
przeglądowego, bo autor przeglądu raportuje liczbę, której nie ma jak
zweryfikować.

| usterka | skutek |
|---|---|
| eksport UTF-16 (WoS/OVID na Windowsie) | plik dawał **zero** rekordów, bez błędu |
| obcięty EndNote XML | cały plik tracony zamiast niekompletnego ogona |
| jedno pole > 200 kB w CSV | przerwanie parsowania, utrata wszystkich dalszych rekordów |
| `parse_csv_export(text)` | zawodził na **każdym** dialekcie |
| stronicowanie bioRxiv/medRxiv | 30 z 220 rekordów w oknie daty (serwer zwraca 30/stronę, nie 100) |
| niezbalansowany cudzysłów w CSV | odrzucenie wszystkich dalszych wierszy |
| `examples/review_config.json` poza dystrybucją | test walidujący konfigurację **pomijał się**, czyli przechodził pozornie |

Wprowadzono niezmiennik importu (`ParseReport`): *wejścia przeczytane = rekordy
zwrócone + odrzucenia policzone*, każde z podanym powodem. To zamienia „parser
zgubił rekordy" z sytuacji niewykrywalnej w sytuację raportowaną. Odporność
zweryfikowano na 133 kombinacjach (parser × tryb uszkodzenia) i 49 przejściach
(parser × kodowanie): zero nieobsłużonych wyjątków, zero nierozliczonych utrat.

Osobna obserwacja metodyczna: pominięcie testu (`skip`) jest **ukrytą awarią**.
Test walidujący przykładową konfigurację pomijał się, gdy pliku nie było - czyli
przechodził pozornie dokładnie w tej sytuacji, dla której istniał (rozpakowany
sdist). Zamieniono na twardy błąd z komunikatem wskazującym `MANIFEST.in`.

## V.3 Pokrycie wobec specyfikacji

Pokrycie jest **mierzone, nie deklarowane**: `validation/measure_parser_coverage.py`
uruchamia każdy punkt wejścia na próbce odwzorowującej realny eksport vendora
i raportuje 32/32 pozycje. Wzmocniono przy tym sam pomiar - klienty API były
sprawdzane wyłącznie na istnienie klasy i metody, co niczego nie dowodzi, więc
każdy przepuszcza teraz nagraną odpowiedź i raportuje, ile rekordów z niej
powstało i jakie identyfikatory niosą. Wykryło to natychmiast błąd w atrapie
PubMedu (endpoint `esearch` zwraca XML, nie JSON) - po naprawie wszystkie osiem
klientów parsuje odpowiedź do rekordów z identyfikatorami.

## V.4 Infrastruktura

- Ciągła integracja na macierzy Pythonów 3.9-3.13, z budową dystrybucji,
  instalacją wheela w czystym interpreterze i przebiegiem zestawu
  **z rozpakowanego sdist** - to ostatnie wykryło niekompletność `MANIFEST.in`.
- Zabezpieczenie offline (`tools/no_network.py`) podmienia primitywy gniazd na
  zgłaszające wyjątek. Teza „zestaw nie rusza sieci" jest teraz wymuszona przez
  zestaw, nie zapisana w prozie; potwierdzone pozytywnie (realne połączenie
  zgłasza wyjątek) i negatywnie (w chwili wydania 1.4.0: 1788 testów przechodzi
  bez zmian).
- Bramka spójności metadanych (11 testów) pilnuje wersji, licencji, autora
  i adresu repozytorium w pięciu plikach. Skuteczność potwierdzona przez
  **wstrzyknięcie rozbieżności**, nie przez założenie.
- ruff: 165 zgłoszeń → 0; mypy: 28 błędów → 0, bez zmiany zachowania.
  Dwie reguły wyłączone z uzasadnieniem zapisanym w `pyproject.toml`, nie po cichu.
- `codemeta.json`, `.zenodo.json`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, szablony zgłoszeń.

## V.5 Stan wydania

| miara | 1.3.0 | 1.4.0 |
|---|---:|---:|
| testy (3.13), stan w chwili wydania | 981 | **1788** |
| pokrycie | 98% | 98% |
| pozycje specyfikacji pokryte | niemierzone | **32/32** |
| ruff / mypy | nieskonfigurowane | **0 / 0**, blokujące w CI |
| CI | brak | **macierz 3.9-3.13** |

Python 3.9 w chwili wydania 1.4.0: 1785 przechodzi + 3 pominięte. Pominięcia to **brak dwóch
opcjonalnych bibliotek w tym środowisku**, nie różnica zachowania kodu:
`python-docx` (załącznik `.docx`) i PyYAML (dwa testy konfiguracji YAML; PyYAML
jest świadomie poza zależnościami, a CLI czyta JSON ze stdlib). Żaden test nie
zachowuje się inaczej na obu interpreterach. Zero `xfail`. `twine check --strict`
przechodzi dla wheela i sdist; zestaw uruchomiony **z rozpakowanego sdist** daje
1788 przechodzących i zero pominięć w chwili wydania, bo tam obie opcjonalne
biblioteki są obecne.

## V.6 Interfejs wiersza poleceń i dokumentacja

CLI (`corpusslr`, 10 podkomend, 169 testów, 97% pokrycia `cli.py`) prowadzi cały
przegląd z jednego pliku konfiguracyjnego. Trzy decyzje projektowe warte
zapisania:

1. **Klucze tylko ze zmiennych środowiskowych.** Obecność `api_key`, `insttoken`,
   `token`, `mailto` itp. w pliku konfiguracyjnym jest **błędem użytkownika**
   z wyjaśnieniem, że plik ma być deponowany jako materiał uzupełniający. Test
   sprawdza, że sama wartość sekretu nie pojawia się w żadnym strumieniu wyjścia.
2. **Literówka w kluczu sekcji jest odrzucana**, nie połykana. `fuzy_threshold`
   kończy się błędem, a nie cichym użyciem domyślnej wartości - inaczej parametr
   raportowany w załączniku PRISMA-S byłby nieprawdziwy.
3. **Kody wyjścia rozróżniają rodzaj awarii**: 0 sukces, 1 błąd użytkownika,
   2 błąd danych, 3 błąd wewnętrzny, 130 przerwanie. Zweryfikowane empirycznie,
   nie wywnioskowane z kodu.

### Usterka wykryta przez CLI: RIS czytany jako MEDLINE

MEDLINE i RIS mają niemal ten sam kształt tagu (`XX  - wartość`), więc wymuszenie
`--format nbib` na eksporcie RIS **nie zawodziło** - zwracało rekordy z tytułem
i bez żadnego identyfikatora, bo RIS zapisuje DOI jako `DO`, a MEDLINE czyta
`LID`/`AID`. Import wyglądał na udany, liczba w diagramie PRISMA była poprawna,
a deduplikacja nie dopasowywała niczego.

Rozstrzygnięcie wymagało wyboru między dwoma kontraktami, bo naprawa w parserze
złamała regułę „żaden parser nie zgłasza wyjątku na uszkodzonym wejściu" (trzy
testy odporności). Ostateczny podział: `parse_nbib` pozostaje tolerancyjny
domyślnie (kontrakt odporności), `parse_nbib_file` jest ścisły (nazwanie pliku
formatem jest twierdzeniem o nim), a CLI **ostrzega** z podaniem
`detected_format` i `format_forced` zamiast odmawiać - to rozwiązanie ścieżki CLI
okazało się lepsze od mojego twardego błędu, bo nie odbiera możliwości wymuszenia
formatu. Test pilnuje, że autodetekcja tego samego pliku zachowuje DOI, który
ścieżka wymuszona traci.

### Wierność opisu metody w załączniku

Weryfikacja treści załącznika PRISMA-S wykazała, że opis kaskady deduplikacji
pomijał mechanizmy dodane w 1.2 i 1.3: domknięcie przechodnie, rundy blokujące,
blokadę sprzecznych identyfikatorów i rozdzielanie wersji konferencyjnych.
Załącznik opisywał więc **metodę, której pakiet już nie stosuje** - a to jest
treść raportowana recenzentowi jako pozycja 16. Opis rozszerzono i uzupełniono
warunkowym raportowaniem licznika każdej straży, która faktycznie zadziałała
(np. „wspólny identyfikator odrzucony jako dowód dla 2 par"), sprawdzonym na
korpusie celowo uruchamiającym te straże.

### Dokumentacja wykonywalna

`docs/user_guide.md` przechodzi od jednej strategii do gotowego załącznika,
z sekcją mówiącą wprost, czego pakiet **nie** robi (brak rozwijania tezaurusa,
brak przesiewu, brak parsowania `.xlsx`). Każdy blok kodu jest wykonywany przez
`tests/test_docs_examples.py` - trzy nazwy metod w pierwszej wersji przewodnika
nie istniały (`Corpus.add_result`, `Corpus.counts_by_database`,
`HarvestArchive.harvest`) i wyszło to wyłącznie dzięki uruchomieniu bloków.

---

# Część VI: pierwsze uruchomienie warstwy retrievalu wobec prawdziwych API

Cała walidacja do wydania 1.4.0 opierała się na nagranych odpowiedziach. Ta część
opisuje, co pokazało dopiero uruchomienie klientów wobec działających serwisów --
trzy wady, z których każda zniekształcała korpus w sposób niewidoczny w testach
offline.

## VI.1 Osiągalność

Zapytanie testowe: `("deep learning" OR "convolutional neural network") AND
"diabetic retinopathy"`, lata 2018-2024. Sześć z siedmiu API odpowiedziało.

| baza | wynik | uwaga |
|---|---|---|
| Scopus | 100 rekordów, 5,0 s | z kluczem i `insttoken` |
| PubMed | 100 rekordów, 1,7 s | - |
| Crossref | 100 rekordów, 1,0 s | zapytanie spłaszczone do rankingu |
| arXiv | 23 rekordy, 0,2 s | cały zasób to preprinty |
| bioRxiv / medRxiv | osiągalne | brak wyszukiwania -- patrz VI.3 |
| Semantic Scholar | HTTP 429 | limitowane przez całą sesję |
| OpenAlex | pominięte | wymagany klucz API; nie był dostępny, a wywołania bez klucza są niewspierane |
| Web of Science | niesprawdzone | brak klucza Clarivate |

## VI.2 Widok Scopusa okaleczał korpus

Klient domyślnie używał widoku `STANDARD`. Zmierzone na tym samym zapytaniu:

| widok | rekordy | abstrakty | rekordy z >1 autorem | maks. autorów |
|---|---:|---:|---:|---:|
| STANDARD (dawna domyślna) | 100 | **0** | **0** | **1** |
| COMPLETE | 100 | 99 | 100 | 10 |

Sprawdziłem konsekwencję zamiast ją założyć: deduplikacja **nie ucierpiała**
(scalanie niosą tytuły -- 4 pary w obu widokach przy zaślepionych
identyfikatorach), natomiast przesiew tytułowo-abstraktowy jest na korpusie bez
abstraktów **niewykonalny**. Szkoda dotyczy więc przeglądu, nie scalania.
Domyślna wartość to teraz `"auto"`: `COMPLETE` gdy podano `insttoken`, w
przeciwnym razie `STANDARD`. Widok podany wprost nigdy nie jest nadpisywany.

## VI.3 Klient preprintów bez budżetu skanowania

API Cold Spring Harbor udostępnia wyłącznie listowanie po oknie daty -- nie ma
wyszukiwania. Klient pobierał więc całe okno i filtrował lokalnie, bez żadnego
ograniczenia. Zmierzone na żywo dla `2018-01-01/2024-12-31` (bioRxiv):

- `messages.total` = **335 871** preprintów,
- 30 rekordów na żądanie, ~1,6 s na żądanie,
- **11 196 żądań, ok. 5 godzin** na jedno wywołanie `search()`.

Pierwsza próba zbudowania korpusu przekroczyła limit wykonania i musiała zostać
przerwana -- to nie była awaria, to była zaprojektowana ścieżka. Dodano budżet
(`MAX_SCANNED = 1500`) raportowany jako **ograniczenie zasięgu** w zdarzeniu
wyszukiwania, oraz `estimate_cost()`, które odpowiada jednym żądaniem: ile
rekordów jest w oknie, ile żądań kosztuje wyczerpujące przeszukanie i jakie
pokrycie daje domyślny budżet (0,45 % dla tego okna). Pierwsza wersja budżetu
(6000) nadal zajmowała 411 s, więc została obniżona.

## VI.4 Brak modelu wycofań -- ustalenie o największej wadze metodycznej

W korpusie 323 rekordów znalazły się **cztery rekordy z oznaczeniem wycofania**:
trzy wycofane badania i jedno zawiadomienie o wycofaniu, dotyczące jednego z nich
(ten sam czasopismo, `issued` 2019 i 2024 -- potwierdzone w Crossref).
Pakiet nie modelował statusu wycofania w żaden sposób. Deduplikacja słusznie
**nie scaliła** zawiadomienia z artykułem, którego dotyczy.

Dodano `corpusslr.integrity`, który **oznacza, a nie filtruje** -- decyzja o
wykluczeniu należy do autora przeglądu i musi trafić do diagramu PRISMA, a
zawiadomienie o wycofaniu jest osobną publikacją, którą przegląd może chcieć
cytować. Sprawdzenie rozdziela badania do wykluczenia od zawiadomień o innych
pracach i podaje własną granicę: czyta typ dokumentu i tytuł, więc jest **dolnym
oszacowaniem, nie zaświadczeniem**. `check_retractions_crossref()` jest ścieżką
autorytatywną, czytającą strukturalne relacje `update-to` / `updated-by`; na
żywej parze potwierdziła oznaczenia tytułowe dokładnie. Sprawdzenie trafia do
załącznika PRISMA-S niezależnie od wyniku, bo „brak oznaczonych rekordów" i
„sprawdzenia nie wykonano" nie mogą dla recenzenta wyglądać tak samo.

Przy pisaniu testów wyszła przy tym własna wada API: raport był kluczowany po
`Record.uid`, które jest puste dopóki rekord nie przejdzie deduplikacji -- cztery
oznaczone rekordy zapadały się na jeden klucz i trzy oznaczenia ginęły. Raport
jest kluczowany pozycją w wejściu, z `flagged_uids` obok dla korpusów po
deduplikacji.

## VI.5 Zbudowany korpus

323 rekordy zidentyfikowane, **297 unikatów** (26 scalonych: 24 po DOI, 2
rozmyte). Nakładanie: PubMed x Scopus 22, Crossref x Scopus 2, Crossref x arXiv
1. Niskie nakładanie Crossrefa sprawdziłem niezależnie od silnika, na surowych
przecięciach zbiorów DOI -- jest własnością danych, nie usterką: spłaszczone
zapytanie zwraca prace trafne tematycznie, ale inne.

## VI.6 Web of Science wobec prawdziwego API - próba i jej wynik

Klient WoS był jedynym nigdy nieuruchomionym wobec działającego serwisu i
głównym pozostałym ryzykiem recenzenckim. Z kluczem Expanded API udostępnionym
przez użytkownika (2026-08-24) udało się ustalić stan faktyczny, ale
**nie** zweryfikować klienta.

Klucz jest rozpoznawany przez bramkę Clarivate - wiemy to, bo klucz celowo
nieprawidłowy zwraca inne ciało odpowiedzi (`401 Unauthorized` z bramki) niż
klucz prawdziwy (`401 Server.authorization, Not authorized for product: WWS` z
backendu WoS). Konto nie ma jednak aktywnego uprawnienia do żadnego produktu
odpytywalnego:

| endpoint | odpowiedź |
|---|---|
| Expanded `/api/wos` | 401 „Not authorized for product: WWS" |
| Lite `/api/woslite` | 403 „You cannot consume this service" |
| Starter `/apis/wos-starter/v1/documents` | 403 |
| Journals `/apis/wos-journals/v1` | 403 |
| Researcher `/apis/wos-researcher/v1` | 403 |

Blokada jest na poziomie **planu, nie bazy**: identyczny błąd 401 dla
`databaseId` WOS, WOK, BIOABS, BCI, CCC, DIIDW i MEDLINE. Uwierzytelnienie
działa wyłącznie nagłówkiem `X-ApiKey` (wielkość liter dowolna); `Authorization:
Bearer` i parametr `?apikey=` bramka odrzuca komunikatem „No API key found in
request".

**Czego nie udało się sprawdzić i dlaczego:** kontrola uprawnień wyprzedza
parsowanie zapytania. Zapytanie skompilowane przez pakiet, zapytanie celowo
uszkodzone (`TS=((((`) i zapytanie puste zwracają **identyczny** błąd 401, więc
poprawność składni `to_wos()` pozostaje niesprawdzona wobec Expanded. Podawanie
tego jako weryfikacji byłoby nadinterpretacją.

**Ustalenie o wartości praktycznej:** pakiet ma klienta wyłącznie dla **Starter
API** (`/apis/wos-starter/v1`), a klucz użytkownika dotyczy **Expanded**
(`/api/wos`) - to inne endpointy o innym kształcie odpowiedzi. Dawna diagnostyka
błędu 403 kierowała użytkownika do sprawdzenia uprawnień do bazy danych, czyli w
złe miejsce. Komunikat wymienia teraz przypadek błędnego produktu jako pierwszy,
wraz ze zmierzonymi kodami statusu każdego trybu awarii, i stwierdza wprost, że
403 nigdy nie oznacza literówki w kluczu - bo nieprawidłowy klucz daje 401.
Trzy testy przypinają to brzmienie.

Pełny zapis: `validation/wos_live_verification.json`.

---

# Część VIII: format kanoniczny, interfejsy i walidacja piętnastu dziedzin

## VIII.1 Scopus CSV jako wynik kanoniczny - zweryfikowany wykonaniem

Po deduplikacji domyślnym formatem jest eksport Scopus CSV (46 kolumn), bo to
jego czytają bibliometrix, VOSviewer i EmbedSLR. Zgodność sprawdzono
**uruchomieniem, nie deklaracją**: `bibliometrix::convert2df(dbsource="scopus")`
w R 4.5.3 wczytał plik zapisany z żywego korpusu trzech baz jako **166 wierszy i
57 pól**, a `biblioAnalysis` policzył na nim 105 źródeł i roczny przyrost 5,92%.

Weryfikacja natychmiast ujawniła lukę: model rekordu **nie miał pola afiliacji**,
więc kolumna `C1` była zawsze pusta, a sieć współpracy instytucjonalnej
bibliometrix zwracała „Matrix is empty!!". Web of Science i Scopus afiliacje
zwracają - po dodaniu pola ten sam korpus daje sieć **156 instytucji**.

Kolumny bez odpowiednika w danych (Index Keywords, References) zostają puste.
Wymyślona afiliacja albo zmyślona lista cytowań byłaby fałszywym wynikiem w cudzej
analizie bibliometrycznej, a pusta kolumna jest brakiem danych, który widać.

## VIII.2 Trzy usterki cichej utraty danych

Każda zniekształcała wynik przeglądu bez żadnego sygnału dla użytkownika.

**Marker braku danych działał jak identyfikator.** `normalize_doi` zwracał
nierozpoznany łańcuch bez zmian, więc `NA` z R oraz `N/A`, `NULL`, `none`, `-`
z innych eksportów stawały się identyfikatorami - a wspólny identyfikator jest
dla kaskady najmocniejszym dowodem. W zbiorze ASySD Diabetes, gdzie brak DOI
zapisano jako `NA`, **492 z 1845 rekordów (26,7%)** dzieliło jeden klucz.
Po naprawie: F1 na złotym standardzie **0,9960 → 0,9984**, fałszywie dodatnie
**1 → 0**.

**Tytuł będący samym identyfikatorem napędzał dopasowanie rozmyte.** Część
wydawców deponuje DOI w polu tytułu; dwa takie „tytuły" z jednego numeru różnią
się końcowymi cyframi i mają podobieństwo ~0,95. Zaobserwowane na żywo: cztery
osobne prace z jednego numeru *Journal of Social Development in Africa* zlały się
w jeden rekord.

**Kolejne wydania serii były scalane.** Kwartalniki agencyjne, raporty roczne
i fale badań mają tytuł identyczny co do znaku i różnią się wyłącznie
oznaczeniem instalmentu. W korpusie transportowym straż eliminuje **19 fałszywych
scaleń (39 → 20 na 182 parach)**, wszystkie to kolejne kwartały jednej serii
raportów Departamentu Energii USA. Reguła działa tylko na tytuły angielskie i to
ograniczenie jest zapisane w kodzie.

## VIII.3 Piętnaście dziedzin

13,809 rekordów z czterech baz, po dwa zapytania na dziedzinę,
protokół identifier-blind (prawda z DOI, ocena po usunięciu wszystkich
identyfikatorów). Mediana F1 **0.9592**, każda dziedzina powyżej 0,85.

Rozstrzygające jest jednak nie samo F1, tylko **z czego składają się błędy**:
z 154 fałszywych scaleń na 2,584 ocenianych parach **141 to warianty
wersji tej samej pracy**, a jedynie **13 to prawdziwe nadmierne scalenia**
(0.50% par). Cochrane traktuje wersje jednego badania jako to
samo badanie, więc liczenie ich jako błędu mierzy definicję prawdy odniesienia,
nie implementację. Obie liczby podano obok siebie, bo rozstrzygnięcie należy do
zespołu przeglądowego, nie do pakietu.

Trzy straże z VIII.2 podniosły dziewięć z piętnastu dziedzin i **nie obniżyły
żadnej**; mediana F1 0,9500 → 0.9592. Jedna wersja reguły serii
obniżała nauki polityczne, bo traktowała rok w tytule jako oznaczenie
instalmentu - została zawężona po tym, jak rozdzieliła prawdziwy duplikat, którego
tytuł kończy się zakresem `2012-2022` renderowanym przez jedną bazę jako
`20122022`.

## VIII.4 Interfejsy

`python -m corpusslr` uruchamia menu terminalowe wyłącznie na bibliotece
standardowej - bez curses, bez bibliotek konsolowych, bez kolorów ANSI, w 80
kolumnach. Klucze czytane przez `getpass`, zapisywane z uprawnieniami 0600,
nigdy nieobecne w wyjściu programu (zweryfikowane testem wpisującym znacznikowy
klucz i skanującym cały transkrypt). Notatnik `notebooks/corpusslr_colab.ipynb`
prowadzi przez ten sam przegląd w 26 komórkach.

Dane: `validation/domains_15_final.csv`, `validation/bibliometrix_verification.json`,
`validation/na_doi_fix_impact.csv`, `validation/domains_*_raw.jsonl.gz`
(ewaluacja odtwarza się bez sieci).
