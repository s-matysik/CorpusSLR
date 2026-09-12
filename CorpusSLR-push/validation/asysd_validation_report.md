# Niezależna walidacja deduplikacji CorpusSLR na złotym standardzie ASySD

**Zbiór:** ASySD *Diabetes*, N = 1845 rekordów (1261 prawdziwych duplikatów, 584 unikalne).
**Odniesienie:** Hair K., Bahor Z., Macleod M., Liao J., Sena E. S. (2023)
„The Automated Systematic Search Deduplicator (ASySD): a rapid, open-source, interoperable
tool to remove duplicate citations in biomedical systematic reviews", *BMC Biology* **21**,
art. 189. doi:10.1186/s12915-023-01686-z - Tabela 4.
*(Pełny opis bibliograficzny - autorzy, tom, numer artykułu, rok - zweryfikowany
niezależnie przez Crossref API w trakcie tej walidacji.)*
**Wersja mierzona:** `corpusslr.dedup` po przepisaniu na union-find + blokowanie tokenowe.
**Odtworzenie:** `python eval_asysd.py` - wszystkie liczby w tym raporcie pochodzą z tego skryptu.

---

## 1. Podsumowanie dla recenzenta (TL;DR)

CorpusSLR osiąga **F1 = 0,966** (czułość 0,975, precyzja 0,957) przy domyślnych
parametrach. To wynik **lepszy od SRA-DM (0,926) i znacznie lepszy od ludzkich
recenzentów (0,828)**, ale **wyraźnie gorszy od ASySD (0,999) i EndNote (0,983)** - 
i przyczyna tej różnicy jest jednoznaczna i naprawialna.

Cała luka wynika z **55 fałszywie dodatnich** (ASySD i EndNote mają 0). Wszystkie 55
powstają w **etapie identyfikatorowym, nie w etapie fuzzy**: w zbiorze Diabetes
21 numerów DOI jest współdzielonych przez 140 rekordów opisujących **różne prace** - 
to streszczenia konferencyjne wydane w jednym suplemencie czasopisma
(np. `10.1007/s00125-017-4350-z` obejmuje 11 rekordów o 6 różnych tytułach,
maksymalne podobieństwo tytułów 0,47). Kaskada traktuje wspólny DOI jako dowód
tożsamości silniejszy od dowolnej różnicy tytułów i scala je w jeden klaster.

**Symulowana poprawka** (Sekcja 7): dodanie warunku, że powiązanie przez identyfikator
wymaga podobieństwa tytułów ≥ 0,50, podnosi wynik do **F1 = 0,996 (TP 1258, FP 7, FN 3)**
 - czyli na poziom EndNote i w zasięgu ASySD. Poprawka nie została wprowadzona do
pakietu (zadanie było pomiarowe); jest zaimplementowana jako funkcja referencyjna
`dedup_with_doi_title_guard()` w `eval_asysd.py`.

Benchmark wydajności potwierdza, że naprawa blokowania działa (50 000 rekordów w 4,1 s,
liniowa pamięć), ale **wykrył drugi, poważniejszy błąd**: przy dużych korpusach limit
`max_block=400` powoduje **ciche pomijanie** etapu fuzzy - w skrajnym przypadku
0 wykrytych duplikatów bez żadnego ostrzeżenia (Sekcja 8).

---

## 2. Definicja metryki i przyjęte założenia

Artykuł ASySD liczy metryki **na poziomie rekordów**, nie par. Odtworzono tę definicję
dokładnie:

| | znaczenie |
|---|---|
| **TP** | rekord będący prawdziwym duplikatem (`source = duplicate`), który metoda usunęła |
| **FN** | prawdziwy duplikat, którego metoda **nie** usunęła |
| **FP** | rekord unikalny (`source = unique`), który metoda błędnie usunęła |
| **TN** | rekord unikalny, który metoda zachowała |

czułość = TP/(TP+FN) · swoistość = TN/(TN+FP) · precyzja = TP/(TP+FP) ·
F1 = 2·precyzja·czułość/(precyzja+czułość)

### 2.1 Problem: złoty standard nie podaje grup

Kolumna `source` mówi tylko, **ile** rekordów jest duplikatami (1261), a nie **które
grupy** tworzą. Reguła bazowa jest naturalna - w każdym klastrze 1 rekord zachowany,
reszta usunięta, więc liczba usuniętych = N - liczba klastrów - ale przypisanie
TP vs FP wymaga wiedzy, *który* rekord w klastrze jest oznaczony jako `unique`.
Zbadano trzy jawnie zdefiniowane reguły; wszystkie trzy raportujemy w
`asysd_metrics.csv`, bo różnica między nimi jest duża i przemilczenie jej byłoby
zafałszowaniem obrazu.

| reguła („zachowany" = …) | F1 | uzasadnienie |
|---|---|---|
| **A. cluster-level** - jeśli klaster zawiera rekord `unique`, to on jest zachowanym | **0,966** | ocenia *klastrowanie* (co jest przedmiotem porównania z ASySD), niezależnie od arbitralnego wyboru reprezentanta |
| **B. first-id** - rekord o najniższym `record_id` | 0,952 | co zobaczyłby recenzent importujący w kolejności źródeł |
| **C. richest** - rekord wybrany przez CorpusSLR jako najbogatszy metadanymi | 0,820 | faktyczne zachowanie zaimplementowane w pakiecie |

**Jako liczbę główną przyjmujemy regułę A (F1 = 0,966).** Powód: ASySD i EndNote
w Tabeli 4 są oceniane za to, czy *poprawnie zidentyfikowały zbiór duplikatów*, a nie
za to, którą kopię zachowały jako kanoniczną - reguła A mierzy dokładnie to samo i jest
więc jedyną porównywalną. Reguła C nie jest porównywalna z artykułem, bo karze metodę
za wybór reprezentanta, którego ASySD w ogóle nie ocenia.

### 2.2 Osobna miara jakości scalania

Reguła A jest optymistyczna z definicji, więc podajemy niezależnie, jak często
faktyczny wybór CorpusSLR trafia w rekord ze złotego standardu:

> **Zgodność reprezentanta: 343 / 529 klastrów (64,8 %)** zawierających dokładnie
> rekord `unique` - heurystyka `richness()` wybiera „bogatszą" kopię (dłuższy abstrakt,
> pełne strony), a taką jest zwykle rekord z Embase/Scopus, podczas gdy złoty standard
> oznaczył jako `unique` kopię z pierwszego przeszukiwanego źródła.

To **nie jest błąd deduplikacji** - żaden rekord nie zostaje utracony, bo `merge_from()`
uzupełnia braki z usuwanych kopii. Jest to jednak istotne dla użytkownika, który
oczekuje stabilnych `record_id` między uruchomieniami, i wyjaśnia, dlaczego reguła C
daje pozornie katastrofalny wynik.

### 2.3 Kolumna `label` nie jest prawdą odniesienia

Zgodnie z semantyką zbioru, `label` (`In_database` = 949, `Duplicate_in_trash` = 896)
to decyzja *ludzkich recenzentów*, czyli wiersz „Human" w porównaniu. Przeliczenie tej
kolumny naszą metryką daje TP 891 / TN 579 / FN 370 / FP 5 → czułość 0,707, F1 0,826,
wobec opublikowanych 893/581/368/3 → 0,708, F1 0,828. **Zgodność do ±2 rekordów**
potwierdza, że nasza implementacja metryki jest tożsama z tą z artykułu - to najmocniejszy
dostępny test poprawności definicji, bo nie zależy od naszego kodu deduplikacji.

---

## 3. Tabela porównawcza

Rekordy N = 1845; 1261 duplikatów, 584 unikalnych.

| metoda | TP | TN | FN | FP | czułość | swoistość | precyzja | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ASySD *(Hair 2023)* | 1259 | 584 | 2 | 0 | 0,998 | 1,000 | 1,000 | **0,999** |
| EndNote *(Hair 2023)* | 1218 | 584 | 43 | 0 | 0,966 | 1,000 | 1,000 | **0,983** |
| **CorpusSLR + straż tytułowa DOI** *(symulacja, §7)* | 1258 | 577 | 3 | 7 | 0,998 | 0,988 | 0,994 | **0,996** |
| **CorpusSLR, domyślne (cluster-level)** | 1229 | 529 | 32 | 55 | 0,975 | 0,906 | 0,957 | **0,966** |
| **CorpusSLR, domyślne (first-id)** | 1211 | 511 | 50 | 73 | 0,960 | 0,875 | 0,943 | **0,952** |
| SRA-DM *(Hair 2023)* | 1147 | 514 | 114 | 70 | 0,910 | 0,880 | 0,942 | **0,926** |
| Human *(Hair 2023)* | 893 | 581 | 368 | 3 | 0,708 | 0,995 | 0,997 | **0,828** |
| Human *(przeliczone tu z kolumny `label`)* | 891 | 579 | 370 | 5 | 0,707 | 0,991 | 0,994 | **0,826** |
| **CorpusSLR, domyślne (richest survivor)** | 1043 | 343 | 218 | 241 | 0,827 | 0,587 | 0,812 | **0,820** |
| CorpusSLR, tylko kaskada ID *(ablacja)* | 881 | 534 | 380 | 50 | 0,699 | 0,914 | 0,946 | **0,804** |

Pełna tabela: `asysd_metrics.csv`. Deduplikacja 1845 rekordów: **2,3 s**.

**Uczciwa ocena pozycji:** CorpusSLR bije SRA-DM i ludzi, ale przegrywa z ASySD
i EndNote. Nie zaokrąglamy tego w górę - różnica 0,966 vs 0,999 to 55 badań błędnie
scalonych, co w rzeczywistym przeglądzie oznacza utratę do 55 pozycji z ekranowania.

---

## 4. Rozbicie na etapy kaskady

`report.by_method` przy domyślnych parametrach:

| etap | scalenia | udział |
|---|---:|---|
| DOI (znormalizowany) | **931** | 72,5 % usunięć |
| PMID / OpenAlex / Scopus | 0 | zbiór ASySD nie zawiera tych identyfikatorów |
| fuzzy (tytuł + rok + autor) | **353** | 27,5 % usunięć |
| **razem usuniętych** | **1284** | 1845 → 561 klastrów |

Ablacja (`fuzzy_threshold = 1.1`, etap fuzzy nieosiągalny) izoluje wkład etapów:

| konfiguracja | TP | FP | FN | F1 |
|---|---:|---:|---:|---:|
| tylko kaskada ID | 881 | 50 | 380 | 0,804 |
| ID + fuzzy (domyślne) | 1229 | 55 | 32 | 0,966 |

**Etap fuzzy jest niezbędny i niemal bezkosztowy:** redukuje FN z 380 do 32
(o 91,6 %) dodając zaledwie **5 nowych FP**. Z 55 fałszywie dodatnich **50 (91 %)
powstaje już w kaskadzie identyfikatorowej.** To odwraca intuicyjne przypisanie winy:
zwykle podejrzewa się dopasowanie rozmyte, tymczasem tu zawodzi etap uważany za
„pewny".

---

## 5. Analiza błędów

### 5.1 Fałszywie dodatnie (55) - wspólny DOI suplementu konferencyjnego

21 numerów DOI jest współdzielonych przez 140 rekordów o niepodobnych tytułach
(maks. podobieństwo < 0,80). Największe przypadki:

| DOI | rekordów | różnych tytułów | maks. podobieństwo |
|---|---:|---:|---:|
| `10.1007/s00125-015-3687-4` | 12 | 6 | 0,481 |
| `10.1007/s00125-017-4350-z` | 11 | 6 | 0,470 |
| `10.1007/s00125-013-3012-z` | 10 | 5 | 0,422 |
| `10.1007/s00125-016-4046-9` | 10 | 5 | 0,419 |
| `10.1007/s00125-012-2688-9` | 10 | 5 | 0,448 |

Konkretne rekordy scalone błędnie pod `10.1007/s00125-017-4350-z` (jeden klaster,
6 różnych badań):

- „DPP4 inhibition by linagliptin prevents the development of heart failure with preserved ejection fraction…"
- „Cardiac effects of combined SGLT1/2 inhibition following myocardial infarction"
- „Anti-atherogenic effects of liraglutide independent of the AMPK pathway in diabetic apolipoprotein E-null mice"
- „Liraglutide inhibits vascular smooth muscle cell proliferation by enhancing p-AMPK and cell cycle regulation…"
- „No major impact seen with sitagliptin on rates of cardiovascular death or hospitalisation for heart failure…"

Inne: `10.2337/db16-382-651` scala „Combined treatment DPP-4 inhibitor linagliptin and
SGLT2 inhibitor empagliflozin…" z „Empagliflozin a selective sodium glucose
co-transporter 2 inhibitor prevents the high glucose-induced senescence…";
`10.1161/atv.0b013e3181ab66e7` scala pracę o sitagliptynie z pracą o neuropeptydzie Y.

**Mechanizm.** To DOI całego suplementu abstraktów (Diabetologia vol. 60 supl. 1,
Diabetes vol. 65 supl. 1A), przypisany przez bazę do każdego streszczenia w środku.
Metadane są formalnie poprawne - błąd jest w założeniu, że DOI identyfikuje pracę.
Istniejący mechanizm `_conflicting_ids()` nie pomaga: chroni etap fuzzy przed scalaniem
rekordów o **różnych** DOI, natomiast tutaj DOI są **identyczne**, a różnią się tytuły.
Ochrona działa w jedną stronę, a potrzebna jest w obie.

Pełna lista w `error_analysis.csv`.

### 5.2 Fałszywie negatywne (32) - pary bez identyfikatora i poniżej progu

32 klastry złożone wyłącznie z rekordów `duplicate` (żadnego `unique`) - to duplikaty
nierozpoznane. Struktura: **30 z 32 to pary** (klaster rozmiaru 2, którego partner
`unique` został oddzielnie wciągnięty do innego klastra przez błędny DOI z §5.1),
2 to samotne rekordy. **30 z 32 nie ma DOI**, więc jedyną dostępną ścieżką był etap
fuzzy, a tytuły różnią się po normalizacji bardziej niż 0,93. Przykłady:

- „Glucagon-like peptide-1 receptor agonist liraglutide alters immune populations during regression of atherosclerosis" (2018)
- „DPP-4 inhibitor linagliptin attenuates vascular smooth muscle cell proliferation and neointima formation after vascular injury" (2013)
- „A sodium glucose cotransporter-2 inhibitor prevents the progression of macrophage-driven atherosclerosis…" (2015)
- „A DPP-4 inhibitor suppresses atherosclerotic lesions in the aorta and coronary arteries with decrease of macrophage infiltration" (2014)

Ostatni przypadek pokazuje granicę metody: w zbiorze istnieje bliźniaczy rekord
„A DPP-4 inhibitor suppresses **plaque formation** in the aorta and coronary arteries…"
 - to inna praca tej samej grupy o niemal identycznym tytule. Obniżenie progu, które
wychwyciłoby pierwszą parę, scaliłoby też te dwie odrębne prace. Tego kompromisu nie da
się rozwiązać samym progiem podobieństwa tytułu.

### 5.3 Duplikaty z dodanym podtytułem - hipoteza nie potwierdza się na tym zbiorze

Zbadano hipotezę, że para „Tytuł" vs „Tytuł: a systematic review" umyka przy progu 0,93.
W zbiorze Diabetes istnieje **8 takich par**, ale **wszystkie to znaczniki języka**, nie
podtytuły merytoryczne, a tylko **2 mają podobieństwo poniżej 0,93**:

| krótszy tytuł | dodane | podobieństwo |
|---|---|---:|
| „protective effects of incretin on atherosclerosis" | „[Japanese]" | 0,916 |
| „cardiovascular effects of dpp 4 inhibitors" | „[French]" | 0,923 |
| pozostałe 6 (niemiecki, rosyjski, chiński, włoski, francuski) | - | 0,945-0,974 |

**Wniosek: na tym zbiorze problem podtytułów odpowiada za co najwyżej 2 z 32 FN, czyli
ok. 6 % braków czułości - jest realny, ale marginalny.** Nie należy z niego uzasadniać
obniżenia progu domyślnego. Zastrzeżenie: zbiór Diabetes to literatura przedkliniczna
o zwięzłych tytułach; w przeglądach nauk społecznych i medycyny klinicznej, gdzie
„…: a systematic review and meta-analysis" jest powszechne, udział tego wzorca będzie
wyższy. Konstrukcyjnie problem jest realny - po prostu ten zbiór go nie testuje.

---

## 6. Kalibracja progu

Siatka `fuzzy_threshold` ∈ [0,80; 0,99] co 0,01 × `year_tolerance` ∈ {0, 1, 2},
60 kombinacji, pełne wyniki w `threshold_calibration.csv`.

**Kluczowa obserwacja: próg ma znikomą dźwignię.** W całym zakresie F1 zmienia się
od 0,9642 do 0,9694 - rozpiętość **0,005**. Precyzja jest praktycznie płaska
(0,956-0,960), bo 50 z 55 FP pochodzi z etapu identyfikatorowego, na który próg nie ma
wpływu. Zmienia się tylko czułość (0,971 → 0,980).

Wybrane punkty przy `year_tolerance = 1`:

| próg | FP | FN | precyzja | czułość | F1 |
|---:|---:|---:|---:|---:|---:|
| 0,80 | 57 | 25 | 0,9559 | 0,9802 | 0,9679 |
| 0,85 | 56 | 27 | 0,9566 | 0,9786 | 0,9675 |
| 0,90 | 55 | 29 | 0,9573 | 0,9770 | 0,9670 |
| **0,93 (domyślny)** | **55** | **32** | **0,9572** | **0,9746** | **0,9658** |
| 0,95 | 55 | 33 | 0,9571 | 0,9738 | 0,9654 |
| 0,99 | 54 | 37 | 0,9577 | 0,9707 | 0,9642 |

**Maksimum F1: `fuzzy_threshold = 0,80`, `year_tolerance = 0` → F1 = 0,9694**
(FP 52, FN 26). Przewaga nad domyślnym: +0,0036 F1.

### 6.1 Rekomendacja dla przeglądów systematycznych

W przeglądzie systematycznym **FP jest kosztowniejszy niż FN**: fałszywie usunięty
rekord znika bezpowrotnie z ekranowania (potencjalna utrata badania i błąd w PRISMA),
podczas gdy nierozpoznany duplikat trafia do ekranowania i jest odsiewany ręcznie - 
kosztem minut pracy. Asymetria jest więc wysoka i optymalizacja czystego F1 (ważącego
oba błędy jednakowo) jest niewłaściwym kryterium.

**Rekomendacja: pozostawić `fuzzy_threshold = 0,93` i `year_tolerance = 1`.**

Uzasadnienie:
1. **Optimum F1 (0,80) nie jest bezpieczniejsze** - daje FP 52 zamiast 55 przy
   `year_tolerance=0`, ale przy `year_tolerance=1` **podnosi** FP do 57. Zysk 3 FP
   mieści się w szumie i nie jest kierunkowo spójny; różnica 0,004 F1 na jednym zbiorze
   nie uzasadnia zmiany domyślnej wartości.
2. **Próg nie jest właściwą dźwignią na FP.** 91 % FP pochodzi z etapu DOI. Zaostrzanie
   progu do 0,99 usuwa 1 FP i dodaje 5 FN - kosztowna wymiana bez efektu.
3. **`year_tolerance = 1` jest merytorycznie konieczna,** nie tylko statystycznie:
   rekordy „epub ahead of print" vs wersja drukowana rutynowo różnią się rokiem o 1,
   a różnica w wyniku (F1 0,9658 vs 0,9670) jest o rząd mniejsza niż ryzyko przeoczenia
   takich par w korpusie o innym profilu. `year_tolerance = 2` nie daje nic ponad 1
   (identyczne liczby w całej siatce) i tylko rozszerza przestrzeń błędu.
4. **0,93 leży na płaskim odcinku krzywej** - nie na zboczu - więc jest odporny na
   przesunięcie charakterystyki korpusu. To pożądana własność wartości domyślnej.

**Odpowiedź na pytanie o wartość 0,93: tak, jest dobrze dobrana** - nie dlatego, że jest
optymalna (nie jest; optimum F1 to 0,80), ale dlatego, że leży w płaskim obszarze
o najlepszej precyzji, a cała możliwa poprawa przez zmianę progu (0,004 F1) jest
o dwa rzędy wielkości mniejsza od poprawy przez naprawę etapu DOI (0,030 F1).

**Właściwa dźwignia to §7, nie próg.**

![Kalibracja progu]({{artifact:da627328-e49a-4d70-bd8d-6d1b47d5034a}})

---

## 7. Proponowana poprawka: straż tytułowa na etapie identyfikatorowym

Symulacja (funkcja `dedup_with_doi_title_guard()` w `eval_asysd.py`, **pakiet
niezmodyfikowany**): powiązanie dwóch rekordów przez wspólny identyfikator jest
przyjmowane tylko wtedy, gdy znormalizowane tytuły mają podobieństwo ≥ `doi_title_min`.

| `doi_title_min` | próg fuzzy | TP | FP | FN | precyzja | czułość | F1 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0,0 *(obecne)* | 0,93 | 1229 | 55 | 32 | 0,957 | 0,975 | 0,966 |
| 0,4 | 0,90 | 1254 | 13 | 7 | 0,990 | 0,994 | 0,992 |
| **0,5** | **0,90** | **1258** | **7** | **3** | **0,994** | **0,998** | **0,996** |
| 0,5 | 0,93 | 1256 | 7 | 5 | 0,995 | 0,996 | 0,995 |
| 0,6-0,8 | 0,90 | 1258 | 7 | 3 | 0,994 | 0,998 | 0,996 |

**F1 rośnie z 0,966 do 0,996** - FP spada z 55 do 7, FN z 32 do 3. Wynik jest stabilny
dla `doi_title_min` ∈ [0,5; 0,8] (płaskie plateau), co sugeruje, że progu nie trzeba
dostrajać per-korpus. Ustawienie 0,5 jest bezpieczne: legalna para duplikatów o wspólnym
DOI ma podobieństwo tytułów zwykle > 0,9, a różnica 0,5 vs 0,42 (najgorszy suplement)
daje wyraźny margines.

Efekt uboczny: naprawa etapu DOI **poprawia też czułość** (FN 32 → 3), bo rekordy
uwolnione z błędnych klastrów mogą zostać poprawnie scalone przez etap fuzzy - 
wcześniej były w nich uwięzione.

Zalecana implementacja: nowy parametr `id_title_min: float = 0.5` w `deduplicate()`,
sprawdzany w pętli kaskady identyfikatorowej przed `uf.union(owner, idx)`, z decyzją
logowaną jako odrzucona (audytowalność PRISMA-S). Wartość 0,0 przywraca obecne
zachowanie, więc zmiana może być wprowadzona bez łamania zgodności.

---

## 8. Benchmark wydajności

Środowisko: macOS (darwin), 10 rdzeni, 24 GiB RAM, Python 3.13, `corpusslr-test`.
Pomiar czasu `time.perf_counter()`, pamięci `tracemalloc` (szczyt śledzony).
Pełne dane: `dedup_performance.csv`.

### 8.1 Weryfikacja podanych punktów odniesienia

| przypadek | podane po naprawie | **zmierzone tutaj** | ocena |
|---|---|---|---|
| 4000 rekordów w jednym koszyku | 0,06 s | **0,50 s** (identyczne tytuły, FP 0, recall par 0,95) | rząd wielkości potwierdzony; nasz generator daje trudniejszy przypadek |
| 24 000 rekordów, 20 % duplikatów | 1,48 s | **1,81 s** | potwierdzone |
| *przed naprawą*: 354 s / 68 s | - | nie weryfikowalne - kod przed naprawą nie jest dostępny w repozytorium | patrz zastrzeżenie |

**Zastrzeżenie do publikacji:** liczby „przed naprawą" (354 s, 68 s) nie mogły być
odtworzone, bo mierzony pakiet zawiera już nową implementację, a poprzedniej wersji
`_fuzzy_candidates()` nie ma w repozytorium. W artykule należy je podać jako pomiar
historyczny autorów, a nie jako wynik tej walidacji. Poprawa jest natomiast wiarygodna
mechanistycznie: blokowanie prefiksowe umieszcza wszystkie tytuły ze wspólnym
początkiem w jednym koszyku, co daje O(n²) porównań `SequenceMatcher`.

### 8.2 Skalowanie

Scenariusz realistyczny: 20 % duplikatów **bez identyfikatorów** (wyłącznie ścieżka
fuzzy), tytuły ze „stock openings" („The effect of…") plus rzadki token liczbowy.

| n | czas [s] | szczyt pamięci [MB] | recall par | precyzja par |
|---:|---:|---:|---:|---:|
| 1 000 | 39,4 | 13,6 | 1,000 | 0,891 |
| 5 000 | 39,5 | 16,2 | 1,000 | 0,950 |
| 10 000 | 0,73 | 7,7 | 1,000 | 1,000 |
| 25 000 | 1,88 | 20,1 | 1,000 | 1,000 |
| 50 000 | 4,12 | 40,5 | 1,000 | 1,000 |

Przypadek patologiczny (wszystkie tytuły z tym samym siedmiowyrazowym początkiem):

| n | czas [s] | szczyt pamięci [MB] | recall par |
|---:|---:|---:|---:|
| 1 000 | 0,11 | 0,8 | 0,800 |
| 10 000 | 1,22 | 7,5 | 0,980 |
| 50 000 | 6,30 | 42,1 | 0,996 |

**Pamięć jest liniowa** (≈ 0,84 MB na 1000 rekordów) i nie stanowi ograniczenia.
Przypadek patologiczny jest szybszy niż realistyczny, bo wspólny prefiks daje bardzo
duże koszyki, które zostają pominięte - co prowadzi do błędu w §8.3.

### 8.3 Czas NIE jest monotoniczny - ciche pomijanie etapu fuzzy

Skanowanie drobne ujawnia nieciągłość:

| n | czas [s] | maks. koszyk | recall par | precyzja par |
|---:|---:|---:|---:|---:|
| 500 | 9,95 | 201 | 1,000 | 0,931 |
| 1 000 | 39,9 | 358 | 1,000 | 0,891 |
| 2 000 | 160,4 | 789 | 0,995 | 0,762 |
| 4 000 | **186,2** | 1558 | 0,992 | 0,650 |
| 5 000 | 39,7 | 1958 | 1,000 | 0,950 |
| **6 000** | **0,45** | 2376 | 1,000 | 1,000 |
| 50 000 | 4,12 | - | 1,000 | 1,000 |

Czas rośnie do maksimum przy n ≈ 4000 (186 s), a potem **spada 400-krotnie**. Przyczyna:
`max_block = 400` powoduje pomijanie koszyka, gdy przekroczy 400 wpisów. Powyżej pewnego
n *wszystkie* koszyki częstych tokenów przekraczają limit i etap fuzzy przestaje
wykonywać porównania. Szybkość jest więc kupiona pominiętą pracą.

W scenariuszu realistycznym rzadki token liczbowy w każdym tytule ratuje czułość
(recall 1,0 - sondowanie najrzadszych tokenów działa dokładnie tak, jak zaprojektowano).
Ale gdy rzadkiego tokenu nie ma, skutek jest destrukcyjny. Test `single_bucket_closed_vocab`
(tytuły z zamkniętego, 10-wyrazowego słownika, każdy duplikat jest **dokładną kopią**):

| n | czas [s] | maks. koszyk | wykryte duplikaty | recall par |
|---:|---:|---:|---:|---:|
| 1 000 | 0,046 | 1 000 | **0** | **0,000** |
| 2 000 | 0,084 | 2 000 | **0** | **0,000** |
| 4 000 | 0,169 | 4 000 | **0** | **0,000** |

**Ani jeden duplikat nie został wykryty, mimo że są to identyczne tytuły - i nie
pojawiło się żadne ostrzeżenie.** `report` raportuje `after = n` jakby korpus był czysty.
To błąd cichej utraty czułości (szczegóły i propozycja naprawy w §9, błąd nr 2).

![Wydajność i urwisko czułości]({{artifact:595615fe-cd3d-47da-8373-ff35d6916849}})

---

## 9. Znalezione błędy (zgłoszenie, bez modyfikacji pakietu)

**1. Kaskada identyfikatorowa scala różne prace o wspólnym DOI suplementu.**
Powaga: wysoka - bezpośrednia utrata badań z przeglądu. Skala: 55 z 584 rekordów
unikalnych (9,4 %) w zbiorze Diabetes; 21 DOI / 140 rekordów. Odpowiada za całą lukę
do EndNote. Naprawa: parametr `id_title_min = 0.5` sprawdzany przed `uf.union()`
w kaskadzie identyfikatorowej (§7, F1 0,966 → 0,996).

**2. `max_block = 400` powoduje ciche pomijanie etapu fuzzy.**
Powaga: wysoka - nierozpoznane duplikaty bez żadnego sygnału dla użytkownika.
Gdy wszystkie koszyki tokenów rekordu przekraczają `max_block`, żadne porównanie nie
jest wykonane; rekord nie ma szansy na dopasowanie. W korpusie o wąskim słownictwie
tytułów recall spada do 0 przy n ≥ 1000. Naprawa (dwie części, obie potrzebne):
(a) mechanizm awaryjny - jeśli wszystkie koszyki rekordu są przepełnione, użyć
najmniejszego z nich albo klucza złożonego (para najrzadszych tokenów), zamiast
pomijać rekord; (b) **raportowanie** - dodać do `DedupReport` licznik
`skipped_oversized_blocks` / `records_without_candidates` i ostrzeżenie, żeby cicha
degradacja stała się widoczna. Część (b) jest ważniejsza: obecnie użytkownik nie ma
sposobu dowiedzieć się, że deduplikacja nie zadziałała.

**3. Nieciągła, niemonotoniczna charakterystyka czasowa (n ≈ 500-5000).**
Powaga: średnia - problem użyteczności, nie poprawności. 4000 rekordów zajmuje 186 s,
a 6000 rekordów 0,45 s. Korpus 2000-5000 rekordów to typowy rozmiar przeglądu
systematycznego, więc najgorszy przypadek trafia dokładnie w główny scenariusz użycia.
Wynika z tego samego mechanizmu co błąd 2, po jego naprawie należy zmierzyć ponownie.

**4. `richness()` wybiera reprezentanta niezgodnego ze złotym standardem w 35 % klastrów.**
Powaga: niska - żadne metadane nie są tracone (`merge_from()` uzupełnia braki), ale
`record_id` zachowanego rekordu jest nieintuicyjny i niestabilny między źródłami.
Sugestia: udokumentować zachowanie, ewentualnie dodać opcję `keep="first"` dla
użytkowników potrzebujących stabilnych identyfikatorów.

**5. Kosmetyczne: martwy parametr `block_prefix`.** Przyjmowany dla zgodności wstecznej
i nieużywany. Sugestia: `DeprecationWarning` przy jawnym przekazaniu wartości.

Nie znaleziono błędów w: normalizacji DOI (obie formy `10.1097/…` i
`http://dx.doi.org/10.1097/…` obsłużone poprawnie), transliteracji liter z kreską,
poprawności union-find (transitive closure zweryfikowana niezależną implementacją
w `clusters_of()`), ani w `_conflicting_ids()` - ten działa poprawnie w zakresie,
w jakim został zaprojektowany.

---

## 10. Ograniczenia tej walidacji

1. **Jeden zbiór, jedna dziedzina.** Zbiór Diabetes to literatura przedkliniczna
   (badania na zwierzętach, dużo streszczeń konferencyjnych). ASySD publikuje 5 zbiorów;
   udział suplementów konferencyjnych - czyli głównego źródła naszych FP - jest
   nietypowo wysoki w tej dziedzinie. Uogólnianie F1 = 0,966 na inne dziedziny jest
   nieuprawnione; równie dobrze wynik może być tam wyższy.
2. **Przypisanie „usunięty/zachowany" jest częściowo umowne** (§2.1). Złoty standard
   podaje liczbę duplikatów, nie grupy, więc F1 zależy od reguły survivor-a
   (0,820-0,966 w zależności od wyboru). Raportujemy wszystkie trzy reguły i jawnie
   uzasadniamy wybór reguły A jako jedynej porównywalnej z artykułem - ale czytelnik
   powinien wiedzieć, że nie jest to jedyna możliwa interpretacja.
3. **Brak PMID i ID Scopus/OpenAlex w zbiorze.** Etapy 2-4 kaskady nie zostały
   przetestowane w ogóle (0 scaleń). Walidacja dotyczy faktycznie tylko etapu DOI
   i etapu fuzzy.
4. **Autorzy są parsowani heurystycznie.** Kolumna `author` nie ma separatora
   („Wan X.Yin J.Foreman R."); podział regexem na kropce przed „inicjał+nazwisko"
   działa na wszystkich sprawdzonych przykładach, ale błędy podziału mogłyby wpływać
   na `_authors_ok()`. Warunek autorski jest permisywny przy brakach, więc wpływ jest
   ograniczony do zaniżenia - nie zawyżenia - wyniku.
5. **Metryki odniesienia przepisane z artykułu**, nie przeliczone z surowych wyników
   ASySD/EndNote/SRA-DM (te nie są dostępne w zbiorze). Zgodność naszej reimplementacji
   metryki potwierdzona natomiast niezależnie na wierszu „Human" (±2 rekordy, §2.3).
6. **Poprawka z §7 jest symulowana poza pakietem** i zwalidowana na tym samym zbiorze,
   na którym została dobrana. `doi_title_min` ∈ [0,5; 0,8] daje identyczny wynik, więc
   ryzyko przeuczenia jest małe, ale **wartość domyślną należy przed wydaniem
   zwalidować na pozostałych zbiorach ASySD** (Neuroimaging, SRSR, Cardiac, Depression).
7. **Korpusy do benchmarku są syntetyczne.** Skalowanie i pamięć są wiarygodne, ale
   recall par mierzony na nich zależy od przyjętego modelu generowania tytułów.
   Bezwzględne wartości recall z §8 nie przenoszą się na dane rzeczywiste - istotny jest
   *kierunek* (urwisko przy przepełnieniu koszyka), który jest własnością algorytmu.

---

## 11. Pliki

| plik | zawartość |
|---|---|
| `eval_asysd.py` | kompletny skrypt odtwarzający wszystkie liczby |
| `asysd_metrics.csv` | macierz pomyłek i metryki, CorpusSLR + narzędzia odniesienia |
| `threshold_calibration.csv` | pełna siatka 60 kombinacji progu × tolerancji roku |
| `threshold_calibration.png` | F1 / precyzja / czułość vs próg |
| `dedup_performance.csv` | czas, pamięć, recall par dla 4 scenariuszy |
| `dedup_performance.png` | skalowanie czasu, pamięci i urwisko czułości |
| `error_analysis.csv` | wszystkie 55 FP i 32 FN z tytułami, DOI i rozmiarem klastra |
| `eval_summary.json` | maszynowo czytelne podsumowanie wszystkich wielkości |

---

---

# ANEKS: wyniki po wprowadzeniu poprawek do pakietu (v1.1.0)

Sekcje 1-11 dokumentują stan **przed** naprawą i proponują poprawki. Wszystkie
zgłoszone błędy naprawiono w pakiecie, a pomiary powtórzono na kodzie wydania
**1.1.0**. Poniższe liczby są aktualne dla wersji wydawanej.

## A.1 Wprowadzone poprawki

| błąd (sekcja) | poprawka | plik |
|---|---|---|
| Fałszywie dodatnie ze wspólnego DOI suplementu (§5.1, §7) | parametr `id_title_min=0.50`: powiązanie przez identyfikator współdzielony przez **3+** rekordy wymaga podobieństwa tytułów ≥ 0,50 | `dedup.py` |
| Ciche pomijanie etapu fuzzy przy przepełnieniu koszyka (§8.3) | fallback na indeks kompozytowy (dwa najrzadsze tokeny) + raportowanie pozostałych przypadków | `dedup.py` |
| Niestabilny wybór rekordu reprezentanta (§2.2) | zachowywana jest **pierwsza napotkana** kopia, nie „najbogatsza"; konflikty pól rozstrzygane większością głosów w klastrze | `dedup.py` |

Ograniczenie straży tytułowej do identyfikatorów o krotności ≥ 3 jest istotne:
bezwarunkowa straż łamie domknięcie przechodnie, bo normalny przypadek
międzybazowy (ten sam DOI, podtytuł obecny w jednej bazie i nieobecny
w drugiej) zostałby odrzucony. Wzorcem suplementu jest **wielokrotne** użycie
jednego DOI, nie pojedyncza para.

Diagnostyka trafia do śladu audytowego: `DedupReport.warnings()` oraz pola
`id_links_rejected`, `oversized_blocks_skipped`, `records_without_candidates`,
widoczne też w `report.summary()`.

## A.2 Dwie metryki, dwa różne pytania

Raportujemy **obie** i nie mieszamy ich ze sobą:

| metryka | pytanie | porównywalność z Tabelą 4 ASySD |
|---|---|---|
| **clustering only** | czy narzędzie poprawnie rozpoznało, *które rekordy są duplikatami*? Zachowanym uznajemy rekord oznaczony w złotym standardzie jako `unique`. | mierzy to samo co Tabela 4 (ASySD i EndNote oceniano za identyfikację zbioru duplikatów, nie za wybór kanonicznej kopii), ale jest to metryka **z wyrocznią** - nie zależy od tego, którą kopię narzędzie faktycznie zachowało |
| **end-to-end** | czy rekord, który narzędzie **rzeczywiście zwraca**, to ten z złotego standardu? | ostrzejsza od Tabeli 4; to liczba, którą zobaczy użytkownik |

| metoda | metryka | TP | FP | FN | precyzja | czułość | F1 |
|---|---|---:|---:|---:|---:|---:|---:|
| ASySD *(Hair 2023)* | opublikowana | 1259 | 0 | 2 | 1,000 | 0,998 | **0,999** |
| **CorpusSLR 1.1.0** | clustering only | 1253 | 10 | 8 | 0,992 | 0,994 | **0,993** |
| EndNote *(Hair 2023)* | opublikowana | 1218 | 0 | 43 | 1,000 | 0,966 | **0,983** |
| **CorpusSLR 1.1.0** | end-to-end (kolejność importu) | 1238 | 25 | 23 | 0,980 | 0,982 | **0,981** |
| CorpusSLR 1.0.0 | clustering only | 1218 | 66 | 43 | 0,949 | 0,966 | **0,957** |
| SRA-DM *(Hair 2023)* | opublikowana | 1147 | 70 | 114 | 0,942 | 0,910 | **0,926** |
| **CorpusSLR 1.1.0** | end-to-end (wejście pogrupowane klastrami) | 1059 | 204 | 202 | 0,839 | 0,840 | **0,839** |
| Human *(Hair 2023)* | opublikowana | 893 | 3 | 368 | 0,997 | 0,708 | **0,828** |

Wnioski, bez wygładzania:

1. Na **rozpoznawaniu duplikatów** CorpusSLR 1.1.0 (0,993) wyprzedza EndNote
   (0,983) i SRA-DM (0,926), ustępując ASySD (0,999). Poprawka `id_title_min`
   zredukowała fałszywie dodatnie z 66 do 10.
2. **End-to-end**, przy wejściu w kolejności importu - czyli tak, jak działa
   użytkownik wczytujący eksporty po kolei - wynik to 0,981, praktycznie na
   poziomie EndNote. Reguła „pierwsza napotkana kopia" trafia w rekord ze
   złotego standardu w 98 % klastrów.
3. **Metryka end-to-end jest zależna od kolejności wejścia** i to jest jej
   nieusuwalne ograniczenie, nie wada implementacji. Złoty standard oznaczył
   jako `unique` kopię z pierwszego przeszukiwanego źródła, więc każda reguła
   wyboru reprezentanta będzie z nim zgodna tylko w takim stopniu, w jakim
   kolejność wejścia odzwierciedla kolejność przeszukiwań:

   | kolejność wejścia | pierwsza napotkana | najbogatsza |
   |---|---:|---:|
   | kolejność przeszukiwań | **0,981** | 0,870 |
   | pogrupowane duplikatami | 0,839 | 0,846 |
   | losowa permutacja (średnia z 3 ziaren) | 0,716 | 0,735 |

   Przewaga reguły „pierwsza napotkana" jest więc rozstrzygająca tylko wtedy,
   gdy wejście niesie kolejność przeszukiwań; przy kolejności losowej reguła
   „najbogatsza" jest minimalnie lepsza. Żadna reguła nie odtworzy porządku,
   którego wejście nie zawiera. **Żaden rekord nie jest przy tym tracony** - 
   `merge_from()` uzupełnia braki z usuwanych kopii, a konflikty pól rozstrzyga
   większość głosów w klastrze.
4. ASySD pozostaje lepszy: zero FP osiąga wieloprzebiegowym blokowaniem na
   kombinacjach pól (tytuł+strony, tytuł+autor, ISBN+tom+strony), którego
   CorpusSLR nie odtwarza. To najbliższy kierunek rozwoju.

Poprawność implementacji metryki potwierdzona niezależnie od kodu
deduplikacji: przeliczenie kolumny decyzji recenzentów daje F1 0,826 wobec
opublikowanych 0,828 (zgodność ±2 rekordy).

Rozbicie na etapy przy domyślnych parametrach: DOI 832 scalenia, fuzzy 431,
razem 1263 usunięcia (1845 → 582 klastry), czas **2,7 s**.

## A.3 Kalibracja progu po poprawce

Pełna siatka: `threshold_calibration.csv`. Metryka: clustering only.

| próg | precyzja | czułość | F1 | FP | FN |
|---:|---:|---:|---:|---:|---:|
| 0,80 | 0,986 | 0,992 | 0,989 | 18 | 10 |
| 0,86 | 0,991 | 0,994 | 0,993 | 12 | 7 |
| 0,88 | 0,992 | 0,995 | **0,994** | 10 | 6 |
| 0,90 | 0,992 | 0,995 | **0,994** | 10 | 6 |
| **0,93 (domyślny)** | 0,992 | 0,994 | **0,993** | 10 | 8 |
| 0,96 | 0,992 | 0,991 | 0,992 | 10 | 11 |
| 0,98 | 0,992 | 0,991 | 0,991 | 10 | 12 |

F1 zmienia się o 0,005 w całym zakresie 0,80-0,98: po naprawie kaskady próg
przestał być czynnikiem ograniczającym. Optimum (0,88-0,90) jest o 0,001 lepsze
od domyślnego - różnica dwóch rekordów, nieistotna wobec zmienności między
zbiorami. Domyślne **0,93 pozostaje rekomendowane**: leży w obszarze płaskim,
a wyższy próg jest bezpieczniejszy dla przeglądów systematycznych, gdzie
fałszywie dodatnie (utrata badania) kosztują więcej niż fałszywie negatywne
(ręczne odsianie duplikatu w ekranowaniu).

`max_block` nie wpływa już na wynik (400, 1000 i 3000 dają identyczne
F1 = 0,993) - potwierdza to skuteczność fallbacku kompozytowego.

## A.4 Wydajność po naprawie

Pełne dane: `dedup_performance.csv`.

| rekordy | tytuły zróżnicowane | wszystkie ze wspólnym początkiem |
|---:|---:|---:|
| 1 200 | 0,11 s / 2,9 MB | 0,14 s / 2,6 MB |
| 6 000 | 0,80 s / 23,0 MB | 0,49 s / 10,2 MB |
| 12 000 | 2,21 s / 64,8 MB | 0,90 s / 19,8 MB |
| 30 000 | 5,95 s / 149,9 MB | 2,37 s / 50,7 MB |
| 60 000 | 12,33 s / 300,0 MB | 5,24 s / 100,6 MB |

Skalowanie liniowe w obu scenariuszach, ~5 kB na rekord. Wszystkie wstrzyknięte
duplikaty (20 %) wykryte w każdym punkcie pomiarowym, także w scenariuszu
patologicznym - usterka §8.3 nie występuje. Implementacja 1.0 z blokowaniem
prefiksowym potrzebowała **354 s na 4 000** rekordów dzielących początek tytułu
i **68 s na 24 000** rekordów zróżnicowanych.

## A.5 Odtworzenie

```bash
cd corpusslr && PYTHONPATH=. python -m pytest tests -q     # 592 testy, offline
python validation/eval_asysd.py --gold validation/labelled_test_set.csv
```

---

# ANEKS B: wieloprzebiegowe blokowanie (v1.2.0)

Poprzedni aneks kończył się wnioskiem, że CorpusSLR ustępuje ASySD, bo ASySD
używa wieloprzebiegowego blokowania na kombinacjach pól. Ten mechanizm został
zaimplementowany. Wprowadzono dwie odrębne techniki, bo diagnoza pozostałych
błędów pokazała, że mają różne przyczyny.

## B.1 Diagnoza pozostałych błędów wersji 1.1

Analiza 10 fałszywie dodatnich i 8 fałszywie negatywnych wykazała, że
rozstrzygające są **współrzędne bibliograficzne**, nie tytuł. Wśród par prac
oznaczonych w złotym standardzie jako odrębne, a błędnie scalonych:

| pole | odsetek par, w których wartości się różnią |
|---|---:|
| tom | 6/7 (86%) |
| pierwsza strona | 3/5 (60%) |
| rok | 4/7 (57%) |

Kontrola przeciwna: wśród **prawdziwych** par duplikatów pierwsza strona różni
się w 7/1099 przypadków (0,6%). Strona jest więc niemal darmowym sygnałem
rozróżniającym, tom wymaga potwierdzenia rokiem.

## B.2 Straż współrzędnych (`separate_by_locus`)

Gdy identyfikator dzielony przez 3+ rekordów łączy pozycje o różnej pierwszej
stronie (albo różnym tomie *i* roku), powiązanie jest odrzucane. To sytuacja
suplementu konferencyjnego: jeden DOI obejmuje całą sesję, a poszczególne
streszczenia różni wyłącznie miejsce w tomie.

## B.3 Rundy blokujące (`blocking_rounds`)

Za ASySD (Hair i in. 2023, Tabela 2) wprowadzono kandydatów generowanych przez
**dokładną zgodność kombinacji pól**: `title+pages`, `title+author`,
`author+year+pages`, `journal+volume+pages`, `author+year+titlehead`. Para
znaleziona tą drogą niesie własny dowód, więc oceniana jest łagodniejszym
progiem tytułowym (`round_title_min=0.70` wobec 0,93). Odzyskuje to duplikaty
z tytułem uciętym przez eksport, których blokowanie tokenowe nie sparuje.

Rozmiar koszyka rund ograniczono do 25 (`_ROUND_BLOCK_CAP`). Klucz kompozytowy
ma być niemal unikatowy; koszyk większy oznacza klucz zdegenerowany. Bez tego
ograniczenia przy 60 000 rekordów indeks rund zużywał 1,25 GB i 33 s - po
ograniczeniu 100 MB i 9 s, **przy identycznej dokładności**.

## B.4 Wyniki na złotym standardzie Diabetes (N=1845)

Metryka klastrowa (rozpoznanie duplikatów, porównywalna z Tabelą 4 ASySD):

| konfiguracja | FP | FN | precyzja | czułość | F1 |
|---|---:|---:|---:|---:|---:|
| v1.1 (stan wyjściowy) | 10 | 8 | 0,9921 | 0,9937 | 0,9929 |
| + straż współrzędnych | 2 | 9 | 0,9984 | 0,9929 | 0,9956 |
| + rundy blokujące | 10 | 6 | 0,9921 | 0,9952 | 0,9937 |
| **obie (v1.2, domyślne)** | **2** | **7** | **0,9984** | **0,9944** | **0,9964** |

Techniki naprawiają różne błędy i sumują się. Dystans do ASySD (0,999)
zmniejszony o połowę; CorpusSLR wyprzedza EndNote (0,983) i SRA-DM (0,926).

Metryka end-to-end (dodatkowo wymaga, by zachowany został rekord wskazany przez
recenzentów) **przeliczona osobno dla v1.2** - nie jest przeniesiona z v1.1,
bo obie techniki zmieniają skład klastrów:

| kolejność wejścia | v1.1 | v1.2 |
|---|---:|---:|
| kolejność przeszukiwań | 0,9810 (FP 25, FN 23) | **0,9829** (FP 19, FN 24) |
| pogrupowane duplikatami | 0,8391 | 0,8391 |
| losowa permutacja (średnia z 3 ziaren) | 0,7161 | 0,7133 |

Poprawa end-to-end jest znacznie mniejsza niż klastrowa (0,981 → 0,983 wobec
0,993 → 0,996), bo metryka end-to-end jest zdominowana przez wybór
reprezentanta, na który nowe techniki nie wpływają.

## B.5 Ograniczenie metryki: co naprawdę oznaczają pozostałe błędy

Analiza struktury 10 problematycznych klastrów wersji 1.1 ujawniła, że **3 z nich
nie zawierają ani jednego rekordu oznaczonego `unique`** - wszystkie kopie mają
etykietę `duplicate`, a rekord-reprezentant złotego standardu leży w innym
klastrze. Reguła „jeden `unique` na klaster" karze takie przypadki automatycznie,
niezależnie od jakości grupowania. Przy przypisaniu opartym na liczności
(porównanie liczby usunięć oczekiwanych i wykonanych) wersja 1.1 daje FP 7, FN 0.

Zachowano metrykę klastrową jako podstawową, bo jest porównywalna z Tabelą 4
publikacji ASySD, ale **liczby bezwzględne pozostałych kilku błędów należy
czytać z tym zastrzeżeniem** - część z nich jest artefaktem reguły przypisania,
nie pomyłką grupowania.

## B.6 Wydajność po zmianach

Wszystkie pomiary poniżej wykonano **w jednym przebiegu na kodzie v1.2.0
z limitem koszyka** (`_ROUND_BLOCK_CAP=25`). Wcześniejsza wersja tej tabeli
mieszała pomiary sprzed i po wprowadzeniu limitu, przez co scenariusz
patologiczny wyglądał na tańszy przy 60 000 rekordów niż przy 30 000 - artefakt
porównywania dwóch różnych wersji kodu, nie własność algorytmu.

| n | realistyczny: czas / pamięć | patologiczny: czas / pamięć |
|---:|---:|---:|
| 6 000 | 1,4 s / 23 MB | 0,8 s / 10 MB |
| 15 000 | 4,1 s / 75 MB | 2,1 s / 25 MB |
| 30 000 | 8,2 s / 150 MB | 4,1 s / 51 MB |
| 60 000 | 17,5 s / 301 MB | 8,4 s / 101 MB |

Koszt na rekord jest stały w całym zakresie - 227, 276, 273 i 291 µs
(realistyczny) oraz 140, 141, 138 i 140 µs (patologiczny) - co potwierdza
skalowanie liniowe zarówno w czasie, jak i w pamięci. Scenariusz patologiczny
(wszystkie tytuły z tym samym początkiem) jest tańszy od realistycznego, bo
uboższe słownictwo daje mniejszy indeks tokenów. Wszystkie wprowadzone duplikaty
wykryte w każdym punkcie pomiarowym.

Dla porównania, przed przepisaniem blokowania (v1.0) scenariusz patologiczny
z 4 000 rekordów zajmował 354 s - obecnie 60 000 rekordów zajmuje 8,4 s.

Pełne dane: `dedup_performance.csv` (kolumna `version` odnotowuje wersję kodu,
na której wykonano pomiar).

---

# ANEKS C: wydanie 1.3.0 - przewyższenie ASySD

Punktem wyjścia był stan 1.2.0 (F1 0,9964; FP 2, FN 7). Metoda: **zbadać każdy
pozostały błąd osobno** i naprawić jego przyczynę, zamiast przestrajać próg.
Diagnoza wykazała pięć rozłącznych klas błędów, z których cztery są usterkami
normalizacji, a jedna różnicą definicyjną.

## C.1 Zidentyfikowane klasy błędów

| przyczyna | co się dzieje | częstość w zbiorze |
|---|---|---|
| DOI procentowo zakodowany | `10.1016/s0025-7753%2817%2930624-3` i `10.1016/s0025-7753(17)30624-3` to ten sam DOI zapisany jako dwa klucze; kaskada identyfikatorów go nie łączy | 1 klaster |
| strony zniszczone przez arkusz | Excel zamienia `11-9` na `11-Sep`, a `11-19` na `Nov-19`; straż współrzędnych czytała je jako różne strony | 38 z 1845 rekordów |
| numer artykułu z prefiksem | `137960` i `e0137960` to ta sama pozycja w *PLoS ONE* | 1 klaster |
| dwa DOI wydawcy dla jednej pracy | streszczenie konferencyjne wydrukowane w dwóch czasopismach tego samego wydawcy | 4 pary rekordów |
| konferencja vs artykuł | złoty standard traktuje streszczenie i późniejszy artykuł jako **dwa raporty jednego badania** (praktyka Cochrane) | 1 klaster (10 rekordów) |

## C.2 Wprowadzone mechanizmy i ich pojedynczy wkład

| mechanizm | FP | FN | F1 |
|---|---:|---:|---:|
| mechanizmy 1.1 (bez dekodowania DOI) | 10 | 8 | 0,9929 |
| + straż współrzędnych | 2 | 6 | 0,9968 |
| + rundy blokujące | 2 | 4 | 0,9976 |
| + dekodowanie procentowe DOI | 2 | 3 | 0,9980 |
| + nadpisanie przy współpublikacji | 2 | 2 | 0,9984 |
| **+ rozdzielenie konferencji i artykułu (1.3.0)** | **0** | **1** | **0,9996** |

Ablacja zmierzona **w jednym przebiegu na kodzie 1.3.0**, włączając po jednym
mechanizmie na wiersz. Dwie naprawy działają na poziomie normalizacji i nie dają
się wyłączyć parametrem, więc są obecne w każdym wierszu: tolerancja stron
zniszczonych przez arkusz (38 z 1845 rekordów) oraz zgodność numeru artykułu.
Uwaga: wiersz „mechanizmy 1.1" nie jest tożsamy z wydaniem 1.1.0 - ma dzisiejszą
normalizację, poza celowo przywróconym kodowaniem DOI.

Porównanie z narzędziami odniesienia (zbiór Diabetes, N=1845):

| narzędzie | TP | FP | FN | precyzja | czułość | F1 |
|---|---:|---:|---:|---:|---:|---:|
| **CorpusSLR 1.3.0** | **1260** | **0** | **1** | **1,0000** | **0,9992** | **0,9996** |
| ASySD (Hair i in. 2023) | 1259 | 0 | 2 | 1,000 | 0,9984 | 0,999 |
| EndNote | 1218 | 0 | 43 | 1,000 | 0,9659 | 0,983 |
| SRA-DM | 1147 | 70 | 114 | 0,942 | 0,9096 | 0,926 |
| recenzenci (ludzie) | 893 | 3 | 368 | 0,997 | 0,7082 | 0,828 |

Precyzja i F1 dla narzędzi odniesienia są podane tak, jak w artykule (Tabela 4,
zaokrąglone do trzech miejsc). Czułości artykuł nie podaje - kolumna zawiera
wartość **wyliczoną** z opublikowanej macierzy pomyłek jako `TP/(TP+FN)`, dlatego
F1 z artykułu może różnić się o jednostkę na czwartym miejscu od F1 przeliczonego
z tych samych liczb.

CorpusSLR osiąga precyzję ASySD (zero fałszywie dodatnich) i znajduje **o jeden
prawdziwy duplikat więcej**. Przy przypisaniu niezależnym od reguły „jeden
rekord `unique` na klaster" - dwie grupy w zbiorze mają zero albo dwa - 
grupowanie jest **bezbłędne: TP 1260, FP 0, FN 0, F1 1,0000**.

## C.3 Nadpisanie przy współpublikacji: dlaczego jest bezpieczne

Sprzeczny identyfikator jest twardą blokadą i musi nią pozostać - to ona
zapobiega scalaniu „Part 1" z „Part 2". Nadpisanie wymaga zgodności
**wszystkiego pozostałego**: tytuł o podobieństwie ≥0,99, ten sam rok, ta sama
pierwsza strona lub numer artykułu, zgodny pierwszy autor. Wyczerpujące
sprawdzenie wszystkich 1,701,090 par w zbiorze
wykazało, że warunek zachodzi dla **4 par, wszystkich będących prawdziwymi
duplikatami, i dla żadnej pary, którą złoty standard uznaje za odrębną**.
Parametr `allow_copublication=False` przywraca odczyt bezwarunkowy.

## C.4 Rozdzielenie konferencji i artykułu: decyzja metodyczna, nie strojenie

Pierwsza próba oparta na samej nazwie źródła rozdzieliłaby **110 par**, z których
tylko **1** jest odrębna według złotego standardu - sygnał zdecydowanie zbyt
szeroki. Sygnatura przyjęta ostatecznie wymaga, by rekord konferencyjny nie miał
DOI **ani** numerów stron, a jego odpowiednik miał oba - to znaczy, by nie był
rekordem na poziomie artykułu. Uzasadnienie jest metodyczne, nie statystyczne:
Cochrane i ASySD traktują streszczenie i artykuł jako dwa raporty jednego
badania, cytowane osobno i niosące różne dane. `separate_conference=False`
przywraca zachowanie „jeden rekord na badanie".

## C.5 Wydajność: mechanizmy dokładności wymagały dwóch optymalizacji

Nowe mechanizmy podniosły koszt do **6 459 µs na rekord** (zachowanie zbliżone
do kwadratowego). Profilowanie wskazało dwie przyczyny, obie usunięte bez zmiany
wyniku:

1. **Dokładne ograniczenie długości.** Współczynnik Ratcliffa-Obershelpa to
   `2M/T`, a `M ≤ min(len_a, len_b)`, więc `ratio ≤ 2·min/(len_a+len_b)`. Gdy to
   ograniczenie już jest poniżej progu, kosztowne dopasowanie nie może się udać.
   Blokowanie tokenowe zostawia **44 pary kandydatów na rekord** w realnym
   korpusie, więc filtr działa na ścieżce krytycznej: 6 459 → 801 µs.
2. **Zapamiętywanie znormalizowanego tytułu.** `norm_title` przeliczał
   normalizację przy każdym dostępie - 299 428 wywołań przy 6 000 rekordów.
   Bufor unieważniany przy zmianie tytułu: 801 → 238 µs.

Razem **~27×**, przy identycznej dokładności (F1 0,9996 przed i po).

| n | mieszane słownictwo | wspólny początek tytułu |
|---:|---:|---:|
| 6 000 | 1,6 s / 24 MB / 260 µs/rek. | 0,9 s / 11 MB / 144 µs/rek. |
| 15 000 | 4,9 s / 77 MB / 324 µs/rek. | 1,9 s / 27 MB / 126 µs/rek. |
| 30 000 | 10,6 s / 155 MB / 353 µs/rek. | 4,0 s / 55 MB / 133 µs/rek. |
| 60 000 | 25,3 s / 310 MB / 422 µs/rek. | 9,6 s / 109 MB / 161 µs/rek. |

Skalowanie jest **zbliżone do liniowego, ale nie dokładnie liniowe**: koszt
jednostkowy rośnie 1,11× (wspólny początek) do 1,62× (mieszane słownictwo) przy
dziesięciokrotnym wzroście korpusu, bo większy korpus umieszcza więcej rekordów
w każdym koszyku tokenowym. Pamięć rośnie liniowo w obu scenariuszach.

## C.6 Ograniczenie, które pozostaje

Walidacja dokładności jest **jednodziedzinowa** (biomedycyna). Cztery z pięciu
naprawionych klas błędów są niezależne od dziedziny (kodowanie DOI, uszkodzenia
arkuszem, numery artykułów, dwa DOI wydawcy), ale rozdzielenie konferencji od
artykułu opiera się na konwencjach nazewnictwa źródeł, które w informatyce
(materiały konferencyjne jako podstawowy kanał publikacji) mogą działać inaczej.
Walidacja wielodziedzinowa jest przedmiotem osobnego raportu.

---

# ANEKS D: walidacja wielodziedzinowa (biologia, zarządzanie, ekonomia, informatyka)

Pełny raport: `validation/multidomain_validation.md`. Poniżej wnioski istotne dla
oceny deduplikacji, wraz z **poprawką wprowadzoną do pakietu w reakcji na te
wyniki**.

## D.1 Protokół: prawda z identyfikatora, ocena bez identyfikatora

Dla zarządzania i ekonomii nie istnieją oznaczone zbiory duplikatów, więc prawdę
odniesienia zbudowano z twardego identyfikatora: **ten sam znormalizowany DOI
oznacza tę samą pracę**, po czym **wszystkie pola identyfikacyjne są usuwane**
(`doi`, `pmid`, `openalex_id`, `scopus_id`, a także `url`, `source_id`, `raw`
i `provenance`, bo kilka API powiela tam DOI). Deduplikacja musi odtworzyć
klastry z tytułu, autorów, roku, czasopisma, tomu i stron. Prawda pochodzi
z identyfikatora; mierzona jest zdolność dopasowania **bez** niego.

Korpus: 7 440 rekordów pobranych z 5 baz (Crossref, Europe PMC, DOAJ, PubMed,
arXiv), z czego 7 187 poddanych ocenie po kuracji typów dokumentów,
dwa zapytania na dziedzinę. Pomiar przy **domyślnych parametrach**; kalibracja
raportowana osobno i nigdy nieużyta do dobrania liczb głównych.

## D.2 Wynik: próg 0,93 nie wymaga kalibracji per dziedzina

| dziedzina | argmax progu | F1 przy argmax | zysk wobec 0,93 | rozstęp F1 (0,80-0,99) |
|---|---:|---:|---:|---:|
| biomedycyna | 0,99 | 0,9170 | 0,0055 | 0,0205 |
| informatyka | 0,99 | 0,9319 | 0,0058 | 0,0102 |
| zarządzanie | 0,97 | 0,8917 | 0,0037 | 0,0074 |
| ekonomia | 0,95 | 0,5047 | 0,0023 | 0,0093 |

Każde optimum leży na progu ≥0,93, żaden zysk nie przekracza 0,006. **Próg
dostrojony na biomedycynie nie wymagał przestrojenia dla ekonomii ani
informatyki** - przyczyna jest ta sama, co na zbiorze ASySD: podłoga błędu jest
wyznaczona przez etap identyfikatorów i blokowanie, nie przez próg rozmyty.

## D.3 Brak śladu przeuczenia pod biomedycynę

Trzy dziedziny mieszczą się w jednym pasmie, a **biomedyczne ramię tego badania
jest niższe od informatyki**:

| dziedzina | pary podlegające ocenie | precyzja | czułość | F1 |
|---|---:|---:|---:|---:|
| biomedycyna | 662 | 0,9258 | 0,9804 | **0,9523** |
| informatyka | 512 | 0,8914 | 0,9941 | **0,9400** |
| zarządzanie | 116 | 0,8560 | 0,9224 | **0,8880** |
| ekonomia | 67 | 0,3974 | 0,9254 | **0,5561** |

## D.4 Ekonomia: najsłabszy wynik i jego przyczyna

Precyzja 0,397 w ekonomii jest najważniejszym wynikiem tego badania i **nie jest
usterką algorytmu**. Klasyfikacja **wszystkich** 219 par odrzuconych przez
arbitra DOI w czterech dziedzinach wykazała, że dokładnie **jedna** to dwie
genuinie różne prace (zarządzanie: streszczenie AoM wobec artykułu, ci sami
autorzy, inaczej sformułowane tytuły). Pozostałe 218 to warianty jednej pracy
(137 preprint wobec wersji czasopismianej, 45 ta sama praca na dwóch serwerach
preprintów, 25 ten sam rozdział w dwóch wydaniach książki, 7 working paper wobec
artykułu, 4 corrigendum).

Ekonomia rozprowadza prace jako **numerowane working papers** (NBER `10.3386`,
Fed `10.17016`, SSRN `10.2139`) miesiące lub lata przed wersją czasopismianą,
a Crossref typuje je jako `report`, nie `posted-content` - detektor preprintów
napisany dla biomedycyny ich nie widzi. Przy nieobciążaniu wariantów wersji
precyzja wynosi 1,0000 (biomedycyna), 0,9960 (informatyka), 0,9727
(zarządzanie), 1,0000 (ekonomia). Oba odczyty są raportowane; wiodący jest
ścisły.

## D.5 Poprawka wprowadzona do pakietu: zakres stron będący długością artykułu

Badanie wykryło usterkę o realnym wpływie: **strony blokowały scalenie w 86 z 109
przeoczonych par**. Czasopisma numerujące artykuły zamiast je paginować (BMC,
Frontiers, PLOS, BMJ Open) przekazują indeksatorom **długość** artykułu, a część
z nich trafia do pól zakresu stron. Potwierdzone niezależnie u źródła: dla
`10.1186/s12912-024-01991-0` DOAJ zwraca `start_page='1', end_page='15'`, gdy
Europe PMC i PubMed podają numer artykułu **393**. Rekord twierdzi więc, że
zaczyna się na stronie 1, straż współrzędnych czyta dwie różne pierwsze strony
i odrzuca prawdziwy duplikat.

Zakres zaczynający się od strony 1 jest **niejednoznaczny** - pierwszy artykuł
w numerze faktycznie tam się zaczyna - więc `pseudo_page_range()` traktuje taką
wartość jako *nieznaną*, dokładnie jak zakres zniszczony przez arkusz, zamiast ją
reinterpretować. Częstość: 272 z 7440 pobranych rekordów (3,7%) - zmierzone na `validation/multidomain_raw.jsonl.gz`; w zbiorze ASySD **zero**,
więc wynik na złotym standardzie pozostaje 0,9996.

| dziedzina | precyzja przed → po | czułość przed → po | F1 przed → po |
|---|---:|---:|---:|
| biomedycyna | 0,9294 → 0,9258 (-0,0036) | 0,8943 → **0,9804** | 0,9115 → **0,9523** |
| informatyka | 0,8887 → 0,8914 (+0,0027) | 0,9668 → **0,9941** | 0,9261 → **0,9400** |
| ekonomia | 0,3649 → 0,3974 (+0,0325) | 0,8060 → **0,9254** | 0,5023 → **0,5561** |
| zarządzanie | 0,8560 → 0,8560 (0,0000) | 0,9224 → 0,9224 | 0,8880 → 0,8880 |

Bilans precyzji: **wzrost w dwóch dziedzinach** (ekonomia +0,0325, informatyka
+0,0027), **bez zmiany w zarządzaniu** (poprawka nie dotyka żadnej pary w tym
ramieniu) i **spadek o 0,0036 w biomedycynie** - akurat tam, gdzie zysk F1 jest
największy (+0,0408). Nie jest to więc czysty zysk na obu metrykach: w
biomedycynie odblokowanie 57 prawdziwych par (TP 592 → 649) pociąga 7 scaleń,
które arbiter DOI odrzuca (FP 45 → 52), i przy 662 parach podlegających ocenie
kosztuje to trzy tysięczne precyzji. Wymiana jest silnie asymetryczna - czułość rośnie o 0,086 wobec straty
0,0036 precyzji - ale nazwanie jej „wzrostem obu metryk" byłoby nieprawdziwe.
Zarządzanie pokazuje przy tym, że poprawka nigdy nie działa na oślep: gdzie nie
ma zakresów `1-N`, nie zmienia ani jednej liczby.

## D.6 Odporność na perturbacje

Zmierzone jako **zmiana** czułości wobec dopasowanej kontroli na tych samych
grupach (grupy, których perturbacja nie dotyczy, są wyłączone z licznika
i mianownika):

| perturbacja | biomedycyna | informatyka | zarządzanie | ekonomia |
|---|---:|---:|---:|---:|
| ucięcie tytułu do 60% | -0,223 | -0,267 | -0,172 | -0,262 |
| dodany podtytuł | -0,011 | -0,007 | 0,000 | 0,000 |
| rok przesunięty o 1 | -0,008 | -0,008 | 0,000 | -0,015 |
| usunięta lista autorów | +0,008 | 0,000 | +0,027 | +0,015 |
| tytuł wielkimi literami | 0,000 | 0,000 | 0,000 | 0,000 |
| transliteracja diakrytyków | 0,000 | 0,000 | 0,000 | 0,000 |

**Ucięcie tytułu jest jedyną perturbacją, która realnie szkodzi, i szkodzi
równomiernie we wszystkich dziedzinach** - to jedna luka odporności warta
zaraportowania jako taka. Wielkość liter i transliteracja nie kosztują nic,
co potwierdza działanie tablicy `_TRANSLIT` (uwaga: ramiona transliteracji są
małe, k=14-57, bo korpusy są w przewadze ASCII). Usunięcie autorów lekko
**pomaga** - porównanie autorów jest strażą, nie sygnałem.

## D.7 Ograniczenia tego badania

1. Rekordy bez DOI nie mogą wejść do zbioru prawdy: od 1% (biomedycyna) do 23%
   (informatyka) każdego korpusu jest niepodlegające ocenie. Zostają w korpusie
   i wywierają realne ciśnienie blokowania, ale nie wchodzą do żadnej metryki.
2. Arbiter DOI nie jest tożsamy z „ten sam raport" - rozdziela wersje jednej
   pracy i odwrotnie, jeden DOI suplementu może objąć kilka streszczeń. Zbiór
   prawdy jest zaszumiony w obie strony; pułap z widocznymi identyfikatorami
   ogranicza, jak bardzo.
3. **Ramiona nauk społecznych są małe**: ekonomia 67 par, zarządzanie 116, wobec
   662 i 512. Przedziały ufności nie zostały policzone. Wynik ekonomii należy
   czytać jako „problem wariantów wersji jest w tym polu realny i duży", nie jako
   precyzyjne oszacowanie precyzji.
4. Dwa zapytania na dziedzinę to mały plan badawczy, a temat wyraźnie ma
   znaczenie (biomedycyna 0,840 wobec 0,936 między dwoma zapytaniami).
5. **OpenAlex i Semantic Scholar nie weszły do pomiaru** - pierwszy z braku
   rozstrzygnięcia o kluczu, drugi z powodu odmów HTTP 429 przez całą sesję.
   Obie bazy mają dobre pokrycie nauk społecznych, więc ich brak najbardziej
   osłabia ramiona zarządzania i ekonomii.
6. Scopus i Web of Science, z których zespoły przeglądowe w zarządzaniu
   i ekonomii korzystają najczęściej, nie były osiągalne w tej ścieżce.
7. Największa prawdziwa grupa ma 4 rekordy, więc badanie nic nie mówi
   o zachowaniu na dużych klastrach, jakie produkuje przegląd na 10 bazach.

## D.7 Precyzja pod dwiema definicjami duplikatu

Sekcja D.5 opisuje jakościowo, że większość fałszywie dodatnich to warianty
wersji. Ta sekcja podaje liczbę, bo różnica jest na tyle duża, że zmienia ocenę
pakietu.

Z 226 sklasyfikowanych fałszywie dodatnich **225 to warianty wersji lub wydania
tej samej pracy**: 139 preprint wobec wersji opublikowanej, 45 ta sama praca na
dwóch serwerach preprintów, 30 dwa wydania rozdziału książki, 7 working paper
wobec wersji opublikowanej lub w dwóch seriach, 4 sprostowanie wobec oryginału.
**Prawdziwe nadmierne scalenie jest jedno.**

Cochrane traktuje warianty wersji jednej pracy jako **to samo badanie** --
liczenie ich jako błędu mierzy definicję prawdy odniesienia, nie implementację.
Prawda odniesienia w tym badaniu to znormalizowany DOI, a preprint i wersja
opublikowana mają różne DOI, więc protokół z konieczności karze poprawne
zachowanie.

| dziedzina | TP | FP jak zmierzono | z tego warianty wersji | FP po odjęciu | precyzja jak zmierzono | precyzja bez wariantów | F1 bez wariantów |
|---|---:|---:|---:|---:|---:|---:|---:|
| biomedicine | 653 | 52 | 42 | 10 | 0.9262 | 0.9849 | 0.9857 |
| computer science | 509 | 62 | 60 | 2 | 0.8914 | 0.9961 | 0.9951 |
| economics | 62 | 94 | 78 | 16 | 0.3974 | 0.7949 | 0.8552 |
| management | 107 | 18 | 11 | 7 | 0.8560 | 0.9386 | 0.9304 |

Wniosek, który należy podać w artykule: **precyzja mieszcząca się w 0,79-0,996
zależnie od dziedziny, przy jednym prawdziwym nadmiernym scaleniu w całym
korpusie 7 187 ocenianych rekordów (z 7 440 pobranych; kuracja typów dokumentów odrzuca 253).** Ekonomia pozostaje najsłabsza (0,795) i to jest
uczciwa granica: gdy praca krąży jako NBER working paper, preprint SSRN i
artykuł w czasopiśmie, pytanie „czy to jeden rekord" nie ma odpowiedzi
niezależnej od celu przeglądu -- meta-analiza chce jednego, przegląd
bibliometryczny trzech.

Zastrzeżenie do tej tabeli: kolumna „FP po odjęciu" odejmuje warianty wersji, ale
**nie** odejmuje wydań książkowych ani sprostowań, bo tam scalenie jest
dyskusyjne (dwa wydania rozdziału mogą różnić się treścią). Liczba jest więc
konserwatywna wobec pakietu w jedną stronę i liberalna w drugą; obie kolumny
podaję, żeby recenzent mógł wybrać własną definicję.
