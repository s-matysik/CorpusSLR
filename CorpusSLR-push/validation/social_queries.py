"""Query design for the social-sciences arm (track = "social").

Five domains x two topical queries.  Each spec records the compiled blocks, the
year window and whether the query is restricted to the title field.

`title_only` is a measured decision, not a stylistic one.  WoS and Scopus both
return relevance-ranked results, and a 150-record window is only useful for
cross-database matching if the two windows describe the same works.  For
management topics the TITLE-ABS-KEY form retrieves thousands of records whose
top-150 windows barely intersect, because a phrase in the abstract of a
loosely-related paper ranks as highly as a phrase in the title of a core one.

Two separate changes were measured, and they are not interchangeable:

*Field restriction, query held fixed.*  ``dynamic capabilities AND firm
performance``: TITLE-ABS-KEY gave 19/150 shared DOIs between WoS and Scopus,
the identical query restricted to the title gave 39 out of much smaller result
sets (WoS 44, Scopus 78).  That is the comparison the ``title_only=True`` flag
on ``mgmt1`` rests on.

*Query redefinition.*  For ambidexterity the field restriction alone does
**not** help: ``organizational ambidexterity AND innovation`` gave 25/150
shared DOIs as TITLE-ABS-KEY and 17 (of 23 and 28 records) as title-only --
lower, not higher, because the second AND-block cuts the result set to a few
dozen records before the windows can overlap.  What produced the aligned window
was dropping the ``innovation`` block entirely and searching the ambidexterity
synonyms alone in the title field: 95/150 shared DOIs.  ``mgmt2`` as shipped is
therefore a different query from the one originally proposed, not the same
query in a different field, and it is reported as a single-concept query.

The queries where the abstract form already produces an aligned window are left
as TITLE-ABS-KEY.
"""

SOCIAL_QUERIES = [
    # ---------------- economics ----------------
    dict(domain="economics", qid="econ1",
         label="minimum wage and employment effects",
         blocks=[["minimum wage"], ["employment effects", "disemployment"]],
         years=(2015, 2024), title_only=False),
    dict(domain="economics", qid="econ2",
         label="monetary policy and inflation expectations",
         blocks=[["monetary policy"], ["inflation expectations"]],
         years=(2015, 2024), title_only=False),
    # ---------------- marketing ----------------
    dict(domain="marketing", qid="mkt1",
         label="influencer marketing and purchase intention",
         blocks=[["influencer marketing"], ["purchase intention"]],
         years=(2015, 2024), title_only=False),
    dict(domain="marketing", qid="mkt2",
         label="brand equity and consumer loyalty",
         blocks=[["brand equity"], ["consumer loyalty", "brand loyalty"],
                 ["brand image", "customer satisfaction"]],
         years=(2015, 2024), title_only=False),
    # ---------------- management ----------------
    dict(domain="management", qid="mgmt1",
         label="dynamic capabilities and firm performance",
         blocks=[["dynamic capabilities"], ["firm performance"]],
         years=(2015, 2024), title_only=True),
    dict(domain="management", qid="mgmt2",
         label="organizational ambidexterity",
         blocks=[["organizational ambidexterity", "organisational ambidexterity",
                  "ambidextrous organization"]],
         years=(2015, 2024), title_only=True),
    # ---------------- logistics ----------------
    dict(domain="logistics", qid="log1",
         label="supply chain resilience and disruption",
         blocks=[["supply chain resilience"], ["disruption"],
                 ["COVID-19", "pandemic"]],
         years=(2015, 2024), title_only=False),
    dict(domain="logistics", qid="log2",
         label="last mile delivery and urban logistics",
         blocks=[["last mile delivery", "last-mile delivery"],
                 ["urban logistics", "city logistics"]],
         years=(2015, 2024), title_only=False),
    # ---------------- transport ----------------
    dict(domain="transport", qid="tr1",
         label="modal shift to public transport",
         blocks=[["modal shift"], ["public transport", "public transit"]],
         years=(2015, 2024), title_only=False),
    dict(domain="transport", qid="tr2",
         label="electric vehicle charging infrastructure",
         blocks=[["electric vehicle"], ["charging infrastructure"],
                 ["charging station siting", "location model", "deployment"]],
         years=(2015, 2024), title_only=False),
]

#: Records per database per query.  The Web of Science daily budget is shared
#: with two other validation tracks running in parallel, so the cap stays at
#: 150 (10 queries x 150 = 15 pages of WoS traffic for this track).
MAX_PER_DB = 150
