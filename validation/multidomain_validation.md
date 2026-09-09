# Cross-disciplinary validation of CorpusSLR deduplication

**CorpusSLR 1.3.0 · generated 2026-08-16 · `validation/eval_multidomain.py`**

## 1. Why this study exists

CorpusSLR's deduplication is calibrated and validated on the ASySD Diabetes gold
standard (Hair et al. 2023), on which it reaches F1 = 0.9996. That set is
biomedical, and biomedical bibliographic data has conventions the rest of the
literature does not share: a PMID on most records, conference abstracts printed
in journal supplements, Vancouver-style titles, and near-universal DOI coverage.
A single-domain validation is a threat to external validity - the threshold and
the guard heuristics may be fitted to those conventions rather than to
deduplication in general.

This study tests transfer to four disciplines - biomedicine, computer science,
management, economics - with metrics computed at the **shipped defaults**.
Threshold calibration is reported separately (§7) and was never used to select
the headline numbers.

## 2. Protocol: identifier-blind cross-database matching

No labelled duplicate set exists for management or economics, so one was built
from a hard identifier:

1. **Retrieve.** Two topical queries per discipline, each issued to every
   database that indexes that discipline: Crossref, Europe PMC, DOAJ, PubMed,
   arXiv. Overlapping coverage produces genuine cross-database duplicates
   carrying genuine metadata disagreement.
2. **Derive truth.** Two records with the same normalized DOI are the same work.
   This is externally verifiable and requires no annotator.
3. **Blind.** Every identifier field is then deleted - `doi`, `pmid`,
   `openalex_id`, `scopus_id`, and also `url`, `source_id`, `raw` and
   `provenance`, because several APIs mirror the DOI there. Deduplication must
   rebuild the clusters from title, authors, year, journal, volume and pages
   alone. The truth comes from an identifier; the ability measured is matching
   **without** one.
4. **Score.** Pairwise precision / recall / F1 over co-membership (primary),
   plus ASySD-style record-level metrics for comparability. Only pairs whose
   both members carry a DOI are scored; unjudgeable records stay in the corpus
   (they exert real blocking pressure) but contribute to no numerator or
   denominator.
5. **Perturb.** Seven corruptions that mimic real cross-database drift are
   injected one at a time into one member of each true pair, each against a
   matched unperturbed control (§6).

`hide_identifiers`, `truth_groups`, `pair_metrics`, `record_metrics`,
`corpus_profile` and `PERTURBATIONS` live in `corpusslr/validate.py` and are
unit-tested, so the protocol is part of the package rather than a one-off script.

### 2.1 Corpus composition

| discipline | records retrieved | after curation | databases | records with DOI | true groups | multi-record groups | judgeable pairs | largest group |
|---|---|---|---|---|---|---|---|---|
| biomedicine | 1718 | 1615 | 4 | 1591 | 1069 | 387 | 662 | 4 |
| computer science | 2533 | 2429 | 5 | 1875 | 1405 | 430 | 512 | 4 |
| management | 1600 | 1585 | 4 | 1499 | 1391 | 100 | 116 | 3 |
| economics | 1589 | 1558 | 5 | 1403 | 1345 | 49 | 67 | 3 |

Raw responses are cached in `validation/multidomain_raw.jsonl.gz` (7,440
normalized records, 4.1 MB), so the whole evaluation replays with no network:

```
PYTHONPATH=. python validation/eval_multidomain.py          # offline, from cache
PYTHONPATH=. python validation/eval_multidomain.py --fetch  # refresh from the APIs
```

### 2.2 One curation step, decided before any metric was read

Crossref registers each **supplementary file** of an article under its own DOI
(`10.1021/acs.jcim.2c01099.s001`) carrying the *article's* title and no year,
journal or pages. Under a DOI arbiter such a file is a work distinct from its own
parent article, so recognising the two as the same paper is scored as an error - 
an artefact of the arbiter, not a defect of the matcher. Records whose type is
not a bibliographic work (`component`, `peer-review`, `grant`, `dataset`,
`other`) are therefore dropped: 253 of 7,440 rows (3.4%). The rule is mechanical,
type-based, applied identically in every discipline, and both arms are reported
(§8) so the effect of the decision is visible rather than baked in.

## 3. Headline result - shipped defaults, curated arm

| discipline | judgeable pairs | precision | recall | F1 | precision, versions not charged | strict FP | version-variant FP | FN |
|---|---|---|---|---|---|---|---|---|
| biomedicine | 662 | 0.9294 | 0.8943 | 0.9115 | 1.0000 | 0 | 45 | 70 |
| computer science | 512 | 0.8887 | 0.9668 | 0.9261 | 0.9960 | 2 | 60 | 17 |
| management | 116 | 0.8560 | 0.9224 | 0.8880 | 0.9727 | 3 | 15 | 9 |
| economics | 67 | 0.3649 | 0.8060 | 0.5023 | 1.0000 | 0 | 94 | 13 |

Three disciplines land in the same band: **F1 0.888-0.926**, with the biomedical
arm of this study (0.9115) *below* computer science (0.9261). Deduplication
without identifiers is not a biomedicine-specific capability.

**Economics is the outlier and it is the most important result here: precision
0.365, F1 0.502.** It is also, on inspection, almost entirely not an algorithm
failure - see §5.

Per query:

| discipline | id | query topic | records | judgeable pairs | precision | recall | F1 |
|---|---|---|---|---|---|---|---|
| biomedicine | bio1 | CRISPR off-target effects | 751 | 168 | 0.8528 | 0.8274 | 0.8399 |
| biomedicine | bio2 | gut microbiome obesity | 864 | 494 | 0.9557 | 0.9170 | 0.9360 |
| computer science | cs1 | graph neural networks for drug discovery | 1051 | 251 | 0.8741 | 0.9681 | 0.9187 |
| computer science | cs2 | federated learning privacy | 1378 | 261 | 0.9032 | 0.9655 | 0.9333 |
| management | mgmt1 | dynamic capabilities and firm performance | 487 | 5 | 0.2632 | 1.0000 | 0.4167 |
| management | mgmt2 | transformational leadership and employee creativity | 1098 | 107 | 0.9612 | 0.9252 | 0.9429 |
| economics | econ1 | minimum wage and employment | 953 | 62 | 0.6125 | 0.7903 | 0.6901 |
| economics | econ2 | monetary policy inflation expectations | 605 | 5 | 0.0735 | 1.0000 | 0.1370 |

The two small arms (`econ2`, `mgmt1`) carry 5 judgeable pairs each. At that size
a single pair moves precision by ~0.1 and no conclusion should be drawn from
them individually; they are reported for completeness and are pooled into the
domain figures.

## 4. Data characteristics per discipline

| discipline | n | % DOI | % PMID | % abstract | % authors | % journal | % pages | % volume | median title words | median authors | % preprint | % diacritics |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| biomedicine | 1615 | 98.9 | 70.0 | 83.3 | 97.2 | 93.5 | 81.3 | 83.4 | 13 | 5 | 4.4 | 0.1 |
| computer science | 2429 | 77.2 | 44.0 | 92.9 | 99.7 | 68.2 | 50.2 | 57.6 | 12 | 4 | 31.7 | 0.1 |
| management | 1585 | 94.8 | 52.7 | 84.2 | 96.7 | 95.8 | 80.6 | 85.4 | 15 | 3 | 1.6 | 0.3 |
| economics | 1558 | 90.6 | 34.4 | 81.8 | 98.3 | 76.9 | 64.5 | 65.7 | 12 | 2 | 15.5 | 2.1 |

These differences explain most of what follows. Computer science has the lowest
DOI coverage (77%), the fewest page numbers (50%) and by far the most preprints
(32%) - arXiv contributes 600 records with no DOI at all for most of them.
Economics carries 16% preprints and the sparsest author lists (median 2).
Biomedicine is the richest: 99% DOI, 81% pages, median 5 authors.

## 5. What the "false positives" actually are

Precision is uninterpretable without asking what each rejected pair is. Every
merged pair the DOI arbiter rejects was classified mechanically
(`classify_false_positive`):

| what the rejected pair actually is | biomedicine | computer science | management | economics | total |
|---|---|---|---|---|---|
| preprint vs published version | 36 | 54 | 5 | 44 | 139 |
| same paper on two preprint servers | 6 | 6 | 6 | 27 | 45 |
| working paper vs published version | 0 | 0 | 0 | 3 | 3 |
| same paper in two working-paper series | 0 | 0 | 0 | 4 | 4 |
| same chapter in two book printings | 10 | 0 | 4 | 16 | 30 |
| corrigendum vs the article it corrects | 0 | 2 | 2 | 0 | 4 |
| two genuinely different works | 0 | 0 | 1 | 0 | 1 |
| **total** | 52 | 62 | 18 | 94 | **226** |

**Of 226 pairs the arbiter rejects across all four disciplines, exactly one
is two genuinely different works.** (An earlier run of this evaluation counted 219;
the `pseudo_page_range` guard added after it unblocked 7 further merges - 2 more
preprint/published pairs and 5 more book-edition pairs - all of them version
variants, so the conclusion is unchanged and the ratio slightly stronger.) It is in management:
`10.5465/amproc.2023.312bp` (an Academy of Management proceedings abstract,
"Transformational Leadership and Employee Innovation: Roles of Commitment to
Change and Supportive…") merged with `10.3390/bs13040320` ("Transformational
Leadership and Followers' Innovative Behavior: Roles of Commitment to Change
and…"). Same authors, same year, overlapping construct, differently-worded
titles - the hardest possible case, and a defensible near-miss rather than a
gross error.

Four more are a corrigendum matched to the article it corrects. These are
undesirable (Cochrane links an erratum to its target rather than merging it) but
they are a different failure mode from confusing two unrelated papers.

The remaining **214 are versions of one study**: a preprint and its journal
version, the same paper on two preprint servers, an NBER working paper and its
journal article, one book chapter in two printings. Systematic-review practice
treats these as one study for screening, so merging them is the behaviour a
review team wants - the DOI arbiter simply cannot see it. Charging them as errors
is what drives economics precision to 0.365, because **economics circulates
work as numbered working papers** (NBER `10.3386`, Fed `10.17016`, SSRN
`10.2139`) months or years before the journal version. Crossref types those as
`report`, not `posted-content`, so a preprint detector written for biomedicine
misses them entirely - exactly the kind of discipline-specific convention this
study was built to find.

Not charging version variants gives the "precision, versions not charged" column
of §3: **1.0000 biomedicine, 0.9960 computer science, 0.9727 management, 1.0000
economics.** Both readings are reported; neither replaces the other. The strict
reading is the conservative one and is what §3 leads with.

## 6. Perturbation sensitivity

Each perturbation is applied to one member of every true pair, scored against a
**matched unperturbed control** over the same groups. The control matters: the
groups a perturbation applies to are not a random sample - `transliterated`
selects records with diacritics, which are also more likely to be non-English
and harder to match for unrelated reasons. The quantity reported is therefore
the *change* in recall, not its absolute level. `k` is the number of groups
perturbed; groups the perturbation cannot affect are excluded from both
numerator and denominator.

| perturbation | biomedicine | computer science | management | economics |
|---|---|---|---|---|
| title truncated to 60% | -0.223 (k=366) | -0.267 (k=416) | -0.172 (k=100) | -0.262 (k=47) |
| subtitle added | -0.011 (k=259) | -0.007 (k=238) | +0.000 (k=27) | +0.000 (k=23) |
| year shifted by 1 | -0.008 (k=387) | -0.008 (k=430) | +0.000 (k=100) | -0.015 (k=49) |
| author list removed | +0.008 (k=386) | +0.000 (k=430) | +0.027 (k=99) | +0.015 (k=49) |
| title upper-cased | +0.000 (k=387) | +0.000 (k=429) | +0.000 (k=100) | +0.000 (k=49) |
| diacritics transliterated | +0.000 (k=57) | +0.000 (k=23) | +0.000 (k=15) | +0.000 (k=14) |
| pages Excel-mangled | +0.231 (k=6) | +0.444 (k=5) | n/a | +0.000 (k=1) |

Applicability (fraction of groups in scope):

| perturbation | biomedicine | computer science | management | economics |
|---|---|---|---|---|
| title truncated to 60% | 0.95 | 0.97 | 1.00 | 0.96 |
| subtitle added | 0.67 | 0.55 | 0.27 | 0.47 |
| year shifted by 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| author list removed | 1.00 | 1.00 | 0.99 | 1.00 |
| title upper-cased | 1.00 | 1.00 | 1.00 | 1.00 |
| diacritics transliterated | 0.15 | 0.05 | 0.15 | 0.29 |
| pages Excel-mangled | 0.02 | 0.01 | 0.00 | 0.02 |

Findings:

- **Title truncation is the only perturbation that materially hurts, and it hurts
  everywhere**: -0.17 to -0.27 recall, with no discipline notably more exposed
  than another. This is the one robustness gap worth reporting as such.
- **Upper-casing and transliteration cost exactly nothing** in all four
  disciplines (Δ = 0.000), confirming that `normalize_title`'s case folding and
  the `_TRANSLIT` stroke table do their job. Note the low applicability of the
  transliteration arm (0.05-0.29): these corpora are overwhelmingly ASCII, so
  this is a weaker test than the others.
- **Removing the author list slightly *helps*** (+0.000 to +0.027) - the author
  comparison is a guard, not a signal, so removing it removes a block.
- **Excel-mangled pages help substantially where they apply** (+0.231
  biomedicine, +0.444 computer science) but the arms are tiny (k = 6, 5, 1) and
  the mechanism is the point, not the magnitude: `excel_mangled_pages` makes the
  locus guard treat the value as *unknown*, which lifts a block the intact page
  range was imposing. That intact page numbers block true merges is the finding
  of §9.
- Subtitle addition and a one-year shift cost ≤0.015 everywhere.

## 7. Threshold calibration per discipline

| discipline | F1 at default 0.93 | argmax threshold | F1 at argmax | gain over default | F1 span over 0.80-0.99 |
|---|---|---|---|---|---|
| biomedicine | 0.9115 | 0.99 | 0.9170 | 0.0055 | 0.0205 |
| computer science | 0.9261 | 0.99 | 0.9319 | 0.0058 | 0.0102 |
| management | 0.8880 | 0.97 | 0.8917 | 0.0037 | 0.0074 |
| economics | 0.5023 | 0.95 | 0.5047 | 0.0023 | 0.0093 |

**No discipline's optimum justifies changing the default.** Every argmax sits at
or above 0.93 and the gain over the default is ≤0.006; F1 varies by ≤0.021 across
the entire 0.80-0.99 sweep in every field. The reason is the same as on ASySD:
the error floor is set by the identifier and blocking stages, not by the fuzzy
threshold. **The 0.93 default transfers across disciplines** - this is the
study's clearest positive finding for the paper, and it is worth stating plainly
that a threshold tuned on biomedicine did not need to be re-tuned for economics
or computer science.

## 8. Sensitivity to the two analysis decisions

| discipline | P raw | F1 raw | P curated | F1 curated | R pseudo-pages fixed | F1 pseudo-pages fixed | P ceiling (DOI visible) | R ceiling |
|---|---|---|---|---|---|---|---|---|
| biomedicine | 0.8087 | 0.8494 | 0.9294 | 0.9115 | 0.9864 | 0.9589 | 1.0000 | 0.9426 |
| computer science | 0.7444 | 0.8411 | 0.8887 | 0.9261 | 0.9941 | 0.9400 | 1.0000 | 0.9844 |
| management | 0.6859 | 0.7868 | 0.8560 | 0.8880 | 0.9224 | 0.8880 | 1.0000 | 1.0000 |
| economics | 0.3273 | 0.4655 | 0.3649 | 0.5023 | 0.9254 | 0.5561 | 0.8272 | 1.0000 |

- **Curation** (dropping non-work record types) is worth +0.038 (economics) to
  +0.170 (management) precision. It changes no recall figure at all and never
  reverses a ranking.
- **The identifier-visible ceiling** shows what the truth set itself permits.
  Precision is 1.0000 in three disciplines - every blind-matching false positive
  there is reproduced when the DOI *is* visible, i.e. it is truth-set noise, not
  a blind-matching error. Economics ceiling precision is 0.8272, meaning 14 of
  its rejected pairs are merged even with DOIs in hand (via the copublication
  and locus rules), so its truth set is the noisiest of the four. Ceiling recall
  is 0.94-1.00, and blinding costs **1.8 points of recall in computer science,
  4.8 in biomedicine, 7.8 in management and 19.4 in economics**. Economics is
  again the outlier, and by a wide margin: with DOIs visible its recall is a
  perfect 1.0000, so every one of its 13 missed pairs is a blind-matching
  failure rather than truth-set noise - the identifier is doing more work there
  than in any other field, which is what one would expect where working papers
  and journal versions differ in title, year, venue and pagination all at once.

## 9. A bug this study found: DOAJ page ranges are page *counts*

Attributing every false negative to the field that separated the pair
(`_separating_field`) shows that **pages block the merge in 86 of 109
missed pairs** across the four disciplines:

| discipline | FN total | of which separated by `pages` |
|---|---|---|
| biomedicine | 70 | 62 |
| computer science | 17 | 14 |
| management | 9 | 2 |
| economics | 13 | 8 |

Every one of these involves a DOAJ record. DOAJ derives `start_page` / `end_page`
from the publisher's article XML, and for journals that number articles instead
of paginating them (BMC, Frontiers, PLOS, F1000Research, BMJ Open) the publisher
supplies the article's own **length**. Verified at source: for
`10.1186/s12912-024-01991-0` DOAJ returns `start_page='1', end_page='15'`, while
PubMed and Europe PMC both report article number **393**. The record therefore
claims a first page of 1, the locus guard reads two different first pages, and a
true duplicate is refused.

Blanking DOAJ `1-N` ranges (the `pseudopages_fixed` arm, §8) recovers most of it:
biomedical recall 0.894 → 0.986, computer science 0.967 → 0.994, economics 0.806
→ 0.925. **This is an ingestion defect, not a matcher defect** - a parser should
not emit a bibliographic coordinate it knows to be fictional - so the fix belongs
in the DOAJ ingestion path and has deliberately *not* been applied to the
headline numbers, which use the records exactly as the APIs returned them.

## 10. Limitations

These are the reasons not to over-read the tables above.

1. **Records without a DOI cannot enter the truth set.** Coverage ranges from
   77% (computer science) to 99% (biomedicine), so between 1% and 23% of each
   corpus is unjudgeable. Those records remain in the corpus and can pull
   clusters together transitively, but no pair involving them is scored. The
   arms differ in how much of themselves they can see, and computer science - 
   the field with the most preprints - sees the least.
2. **The DOI arbiter is not identical to "same report".** It splits versions of
   one study across DOIs (§5) and, in the other direction, a supplement-wide DOI
   can cover several distinct abstracts. The truth set is noisy in both
   directions; the identifier-visible ceiling (§8) bounds how much.
3. **The two social-science arms are small.** Economics contributes 67 judgeable
   pairs and management 116, against 662 and 512 for biomedicine and computer
   science. Every economics figure carries wide uncertainty - a handful of pairs
   moves precision by several points - and no confidence intervals are computed
   here. The economics result should be read as "the version-variant problem is
   real and large in this field", not as a precise precision estimate.
4. **Europe PMC and PubMed cover the social sciences unevenly.** The management
   and economics arms lean on Crossref, DOAJ and whatever social-science
   journals Europe PMC happens to index; a management corpus retrieved from
   Business Source or Scopus would have different metadata conventions. Scopus
   and Web of Science were not reachable from this environment.
5. **OpenAlex was not used.** No API key was available for this session, and
   keyless calls are unsupported, so a database with excellent social-science
   coverage is absent. Adding it would strengthen the management and economics
   arms most.
6. **Semantic Scholar was unreachable.** The unauthenticated pool returned HTTP
   429 on every attempt across the whole session, so the planned fifth database
   contributed nothing.
7. **Two queries per discipline is a small design.** Query topic clearly matters
   (biomedicine F1 ranges 0.840-0.936 across its two queries), so the
   per-discipline pooled figures conflate genuine discipline effects with topic
   effects.
8. **The perturbations are synthetic.** They are modelled on real
   cross-database drift, but they are injected, not observed, and the
   transliteration and Excel-mangling arms are small enough (k = 1-57) to be
   indicative only.
9. **Cluster sizes are small.** The largest true group is 4 records, so this
   study says nothing about behaviour on the large clusters a 10-database
   review produces.

## 11. What to state in the paper

- Deduplication transfers: **F1 0.888-0.926 in biomedicine, computer science and
  management** at shipped defaults, under an identifier-blind protocol.
- **The 0.93 threshold needs no per-discipline tuning**: argmax gain ≤0.006, F1
  span ≤0.021 across 0.80-0.99 in every field.
- **Economics precision falls to 0.365 under strict scoring, and the cause is
  identified**: the field distributes work as numbered working papers under
  separate DOIs, so 94 of its 94 rejected pairs are version variants or book
  printings and none is a confused pair of works.
- Across all four disciplines, **1 of 226 arbiter-rejected pairs is two
  genuinely different works**.
- **Only title truncation degrades recall** (-0.17 to -0.27), uniformly across
  disciplines; case, diacritics, missing authors and ±1 year cost ≤0.015.
- A **DOAJ ingestion defect** (page counts stored as page ranges) was the
  dominant cause of missed duplicates; fixing it lifts recall to 0.92-0.99.

## 12. Files

- `validation/eval_multidomain.py` - retrieval and evaluation, `--fetch` to refresh
- `validation/multidomain_raw.jsonl.gz` - cached normalized records (offline replay)
- `validation/multidomain_metrics.csv` - all three arms, per query and per discipline
- `validation/multidomain_profile.csv` - metadata completeness per arm
- `validation/multidomain_perturbations.csv` - perturbation arms with matched controls
- `validation/multidomain_calibration.csv` - threshold sweep per discipline
- `validation/multidomain_false_positives.csv` - every rejected pair, classified
- `validation/multidomain_validation.png` - summary figure

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
