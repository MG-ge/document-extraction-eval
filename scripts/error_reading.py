"""Hand reading of every real-value error the three large models made.

`scripts/error_analysis.ts` sorts every counted error into a type by rule. Most of the large
models' lost score is how an empty field is written; the rest are real values that are
missing, extra or different. Each of those was read against the document's text (50
documents, 97 document-model pairs; the script prints both counts), and the judgement is recorded below as one rule per
pattern: which document, which models, which fields, and whose error it is.

    model      the model is wrong: the document clearly supports the correct answer
    answer     the correct answer is wrong: the document contradicts it
    either     the document supports both the correct answer and the model's

The script checks that every real-value error of the three models is covered by exactly
one rule, then prints the fields lost per cause and pattern.

Usage: python3 scripts/error_reading.py   (run from the repository root; needs bun)
"""

import collections
import json
import re
import subprocess
import sys

MODELS = ["gemini-3.8-flash", "gpt-5.6-terra", "gpt-5.6-luna"]
REAL = {"not_json", "value_left_out", "value_added", "filled_empty", "emptied_value", "wrong_value", "wrong_shape"}
ALL = None
PAY_IN = [94, 198, 235, 263, 378, 383, 409, 539, 540, 542, 587, 612, 620, 906, 951]
GLOSSARY = [106, 312, 603, 740, 774, 806]

# (documents, models or ALL, field path regex, cause, pattern, what was read)
RULES = [
    (PAY_IN, ALL, r"^\.title$", "either", "title keeps the date",
     "The heading reads 'Pay-In Sheet - 2025-09'; the correct answer drops the date, the models copy the heading."),
    (GLOSSARY, ALL, r"^\.glossarySections", "either", "glossary letter repeated",
     "The document repeats a letter heading after a page break; the correct answer merges the two sections, the models keep both."),
    ([911], ALL, r"^\.migration_options?\[", "answer", "answer key differs from schema",
     "The schema names the list 'migration_option'; the correct answer calls it 'migration_options'. The models follow the schema."),
    ([56], ALL, r"\.description$", "answer", "answer misspells the text",
     "The receipt reads 'INDUNA'; the correct answer has 'INDINIA'."),
    ([56], ["gpt-5.6-luna"], r"\.total_price_with_discount$", "either", "receipt price with no discount",
     "Items without a discount: the correct answer leaves the discounted price empty, the model repeats the price."),
    ([56], ["gemini-3.8-flash"], r"^\.customer_name$", "either", "customer name",
     "'CUSTOMER: LOYALTY CUSTOMER' and later 'HI MOSOTHOANE'; the model took the person's name."),
    ([56], ["gemini-3.8-flash"], r"\.unit_price$", "model", "value missed",
     "'2 @ 17.99' is on the line below the item; the model left the unit price out."),
    ([59], ALL, r"^\.store_info\.name$", "either", "store name cut short",
     "The heading line ends with a registration number '(930311-W)'; the models drop it, gpt-5.6-luna also drops '(FC) S/3'."),
    ([127, 239, 261, 471], ALL, r"^\.companyCity$", "either", "city includes the state",
     "'ACWORTH, GEORGIA'; these schemas have no companyState, so the models kept the state with the city."),
    ([184, 187, 381, 471, 830], ALL, r"^\.transferAgentCity$", "either", "city includes the state",
     "'BALLICO, CALIFORNIA'; these schemas have no transferAgentState, so the models kept the state with the city."),
    ([261], ["gpt-5.6-terra"], r"^\.transferAgentCity$", "model", "city includes the state",
     "The schema has transferAgentState, so the state does not belong in the city."),
    ([187], ["gpt-5.6-luna"], r"^\.companyState$", "model", "value missed",
     "'GREENWOOD, MISSOURI 64034'; the model left the state out."),
    ([239, 240, 269, 381, 471], ALL, r"^\.transferAgent$", "model", "care-of company taken",
     "'FIDELITY INVESTMENTS / C/O NORTHERN TRUST'; the model named the care-of company as the transfer agent."),
    ([261, 297, 381, 471], ALL, r"^\.votingBreakdown\[\d+\]\.name$", "model", "field the schema does not have",
     "The schema's voting rows have no 'name'; the models added the row label anyway."),
    ([269], ["gpt-5.6-terra"], r"recentVotes\.against$", "model", "values swapped",
     "Two proposals' 'against' votes (0 and 753) swapped between rows."),
    ([558], ["gpt-5.6-luna"], r"micr\.(checkNumber|routingNumber)$", "model", "values swapped",
     "The MICR line '⑆19030445⑆ … ⑈8280⑈': routing and check numbers swapped."),
    ([558], ["gpt-5.6-terra"], r"personalInfo\.(city|address)$", "either", "words run together",
     "The text runs the address and city together ('10232 HAYES CAPEPORT PRECIOUSCESTER'); the split is a guess either way."),
    ([622], ["gpt-5.6-luna"], r"^\.mostRecentShipment\.", "model", "wrong row",
     "Asked for the most recent shipment, the model took the 1958 row instead of the 1988 one."),
    ([1], ALL, r"^\.productRevenue\.segments", "model", "list rows missed",
     "The chart names three segments and, in a table below, ten business units; the schema asks for a "
     "'detailed product/segment breakdown'. The models listed the three segments and left out the ten units."),
    ([41], ALL, r"\.calories$", "model", "value missed",
     "Two calorie figures sit on a garbled line under the table ('A00 400 CAL 2750'); all three models left them out."),
    ([7], ["gpt-5.6-terra"], r"^\.first_name$", "either", "middle name",
     "'DAVID FRANKLIN THOMAS'; the correct answer counts Franklin in the first name, the model does not."),
    ([285], ["gpt-5.6-luna"], r"lastName$", "model", "text copied wrong",
     "'CAMRON SMITHAM302 …'; the model wrote SMITH."),
    ([451], ["gpt-5.6-luna"], r"equipmentId$", "model", "text copied wrong",
     "'NW2I1O0Y'; the model dropped the last character."),
    ([366], ["gpt-5.6-terra"], r"^\.portfolioSummary\.", "model", "value in the wrong place",
     "The period's ending balance was written as an extra row of the changes table."),
    ([465], ["gemini-3.8-flash"], r"departure_time$", "either", "answer reformats the date",
     "The form reads '2/21/80 4:00 P.M.'; the correct answer rewrites it as '1980/02/21 04:00 PM', the model copies it."),
    ([569, 764, 773], ALL, r"prescriptionDrugs\.other", "either", "ticked boxes put in 'other'",
     "Ticked drugs the schema has no field for. The 'Other:' line is blank, except in 773 where it names one drug, "
     "which the correct answer keeps on its own. The models list the ticked drugs under 'other'."),
    ([607], ["gpt-5.6-luna"], r"passedInspection$", "model", "tick box misread",
     "'Inspection Result: ☑'; the model answered false."),
    ([764], ["gpt-5.6-terra"], r"^\.maritalStatus$", "model", "tick box misread",
     "'SEPARATED ☑ WIDOWED □'; the model answered widowed."),
    ([664], ["gemini-3.8-flash"], r"cashier_number$", "either", "cashier number not printed",
     "The receipt prints 'POS NO : 181', not a cashier number; the correct answer uses it, the model left it empty."),
    ([117], ["gemini-3.8-flash"], r"^$", "model", "answer not valid JSON",
     "The answer could not be read as JSON, so every field counts as missing."),
]


def examples(model):
    out = subprocess.run(["bun", "scripts/error_analysis.ts", "--examples", model],
                         capture_output=True, text=True, check=True).stdout
    return [json.loads(l) for l in out.splitlines()]


failures = []
fields = collections.Counter()  # (cause, pattern, model) -> fields
pairs = set()  # (model, document) with a real-value error
for m in MODELS:
    for e in examples(m):
        if e["type"] not in REAL:
            continue
        hits = [r for r in RULES
                if e["id"] in r[0] and (r[1] is ALL or m in r[1]) and re.search(r[2], e["path"])]
        if len(hits) != 1:
            failures.append(f"{m} doc {e['id']} {e['path']}: {len(hits)} rules match")
            continue
        pairs.add((m, e["id"]))
        n = e.get("fields", 1)
        fields[(hits[0][3], hits[0][4], m)] += n

if failures:
    sys.exit("\n".join(failures))

print(f"Read by hand: {len({d for _, d in pairs})} documents, {len(pairs)} document-model pairs.")
print("Fields lost to real-value errors, by whose error it is:")
print(" | ".join(["cause", "pattern", *MODELS]))
for cause in ("model", "answer", "either"):
    pats = sorted({p for c, p, _ in fields if c == cause}, key=lambda p: -sum(fields[(cause, p, m)] for m in MODELS))
    for p in pats:
        print(" | ".join([cause, p, *(str(fields[(cause, p, m)]) for m in MODELS)]))
    print(" | ".join([cause, "total", *(str(sum(v for (c, _, mm), v in fields.items() if c == cause and mm == m)) for m in MODELS)]))
