"""Level-2 scoring of built SAXO SML models (CM, AOCM) vs answer_key.yaml.
Static YAML reading was done by hand; judgments are encoded here and the
script computes P/R and writes cm.json, aocm.json, LEVEL2.md.
Usage: python scripts/ao/model_score_saxo.py
"""
import json, pathlib

OUT = pathlib.Path(__file__).resolve().parents[2] / "results/arms_saxo/level2_models"
R = [f"R{i}" for i in range(1, 26)]
REL, SQL, NO = "relationship", "derived-SQL", "none"

# id -> (how, note). how in {REL, SQL, NO, "REL+SQL"}
CM_R = {
 "R1": ("REL+SQL", "Asset Snapshot Row Detail -> Account on mk_ucraccountsid (also LEFT JOIN accounts in SQL)"),
 "R2": (REL, "Client Asset Snapshot / Asset Snapshot Row -> Contract on mk_contractsid"),
 "R3": (NO, "mk_toplevelcontractid carried, used only in window partitions; no Contract role-play"),
 "R4": (REL, "-> Client Segment"),
 "R5": (REL, "snapshotdate -> Snapshot Date; target is derived Snapshot Calendar, not public.dates"),
 "R6": (REL, "role_play 'Reporting {0}'; derived calendar"),
 "R7": (REL, "role_play 'Original {0}'; derived calendar"),
 "R8": (REL, "scenarioid -> Scenario"),
 "R9": (REL, "-> Earning Tier"),
 "R10": (REL, "sourceid -> Source System"),
 "R11": (REL, "Segment Asset Month -> Client Segment"),
 "R12": (REL, "-> Earning Tier"),
 "R13": (REL, "source_id -> Source System"),
 "R14": (REL, "Legacy mk_clientsegmentreportingid_* (aliased) -> Client Segment"),
 "R15": (REL, "Legacy mk_endclientearningcategoriesid_* (aliased) -> Earning Tier"),
 "R16": (REL, "bdsssourceid -> Source System"),
 "R17": (REL, "Client Lead -> Client Segment"),
 "R18": (SQL, "Client Lead Detail: getclients LEFT JOIN (dates grouped by mk_datesid); not an SML relationship; LEFT correct"),
 "R19": (REL, "role_play 'Balance Snapshot {0}'; derived calendar"),
 "R20": (SQL, "Client Segment Detail self LEFT JOIN x2 -> Parent/Grandparent Segment attrs; no SML parent-child hierarchy"),
 "R21": (SQL, "Contract Segment History Detail: LEFT JOIN contracts on contractid (MAX mk_contractsid), then SML rel on mk_contractsid"),
 "R22": (SQL, "Contract Office Assignment Detail LEFT JOIN contracts on contractid; Contract Detail LEFT JOIN office mappings; SML rel on mk_contractsid"),
 "R23": (REL, "Contract Segment History -> Client Segment (aliased key)"),
 "R24": (NO, "from-date key exposed as attribute / valid_from_date arithmetic; no join to dates"),
 "R25": (NO, "to-date key exposed as attribute; no join to dates"),
}
AO_R = {
 "R1": (REL, "paum_to_account on mk_ucraccountsid"),
 "R2": (REL, "paum_to_contract on mk_contractsid (also joined in contract_profile SQL)"),
 "R3": (NO, "top_level_contract_key attribute only; description treats each contract as its own umbrella"),
 "R4": (REL, "paum_to_segment"),
 "R5": (NO, "no dates join: year/month derived from integer key (builder trusted profile: calendar ends 2003)"),
 "R6": (SQL, "paum_snapshot LEFT JOIN dates dr on reportingsnapshotdate -> period/year attrs; no SML role-play"),
 "R7": (SQL, "paum_snapshot LEFT JOIN dates dor on originalsnapshotdate; no SML role-play"),
 "R8": ("REL+SQL", "paum_to_scenario; also LEFT JOIN scenarios in SQL"),
 "R9": (REL, "paum_to_tier"),
 "R10": (REL, "paum_to_source"),
 "R11": (REL, "segment_aum_to_segment"),
 "R12": (REL, "segment_aum_to_tier"),
 "R13": (REL, "segment_aum_to_source (source_id)"),
 "R14": (REL, "legacy_to_segment (segment_key alias)"),
 "R15": (REL, "legacy_to_tier (tier_key alias)"),
 "R16": (REL, "legacy_to_source (source_key alias)"),
 "R17": (REL, "client_to_segment"),
 "R18": (SQL, "client_lead LEFT JOIN public.dates on mk_datesid_newbusinesslivedate; LEFT correct; no SML relationship"),
 "R19": (NO, "balance feed year/month derived from key; no dates join"),
 "R20": (SQL, "client_segment_profile self LEFT JOIN x2 -> Parent/Grandparent attrs; no SML parent-child"),
 "R21": ("REL+SQL", "history_to_contract (contract_id -> Contract level contractid); contract_profile SQL joins customermodelhistory on contractid"),
 "R22": ("REL+SQL", "office_to_contract; contract_profile SQL joins office mappings on contractid"),
 "R23": ("REL+SQL", "history_to_segment; contract_profile SQL joins CSR via history current segment"),
 "R24": (NO, "from_date_key exposed as attribute only"),
 "R25": (NO, "to_date_key exposed as attribute only"),
}
CM_EXTRA = [
 "persistedassetsundermanagement.endclientid -> End Client (synthetic union-of-ids dimension, no source table)",
 "aum_demo.counterpartid -> End Client (synthetic)",
 "accountbalancedkkdemo.bk_ucrcounterpartsid -> End Client (synthetic)",
 "getclients.endclientid -> End Client (synthetic)",
 "customermodelhistory.endclientid -> End Client (synthetic)",
 "bdsslegacy_demo.mk_datesid_snapshotdate -> Snapshot Calendar (legacy date; not in key, plausible)",
 "aum_demo.mk_datesid -> Snapshot Calendar = DECOY D7 (masked: calendar is built from the fact's own keys)",
]
AO_EXTRA = [
 "accountbalancedkkdemo.bk_ucrcounterpartsid -> Contract Details.contractid (feed counterparty = contract number; not in key; plausible)",
]
DECOYS = {"CM": {"D7": True}, "AOCM": {}}   # D1-D6 not used by either

# metrics: id -> (score, semi_additive, note). semi in {native, variant, flag-only, n/a}
CM_M = {
 "M2": ("partial", "variant", "default Total AUM = SUM of MAX(totalaum) per client-snapshot (dedup), deviates from key SUM(totalaum); key-exact only as 'Total AUM (Summed Over Rows)'. Latest-snapshot windowed variants: Current AUM, Year-End, Last Reported (Per Client/Contract)"),
 "M3": ("partial", "variant", "default dedup'd; exact as 'Prior Month AUM (Summed Over Rows)'; Prior Month AUM (Per Client Last Snapshot) windowed variant (dedup basis)"),
 "M4": ("partial", "n/a", "IIF(prev=0,NULL,(Total-Prior)/Prior*100) on dedup'd Total AUM; key basis (summed rows) not offered as a growth calc; x100 scale"),
 "M5": ("full", "variant", "SUM(accountbalancedkk) on Asset Snapshot Row Detail; Last Reported Account Balance DKK (Per Account) windowed"),
 "M6": ("full", "n/a", "SUM(unrealizedprofitlossdkk), additive"),
 "M7": ("full", "n/a", "COUNT DISTINCT endclientid (Active Clients)"),
 "M9": ("partial", "flag-only", "AUM EOM DKK/EUR sums correct; only Is Latest Segment Asset Month flag, no latest-month metric"),
 "M10": ("full", "n/a", "Net AUM Change DKK = SUM(eom-bom) row-level column (equal to SUM-SUM unless a row has a NULL)"),
 "M11": ("full", "n/a", "Cash Ratio = Cash DKK EOM / AUM EOM DKK, NULL on 0"),
 "M12": ("full", "n/a", "Adjustment Value DKK / EUR sums"),
 "M13": ("full", "n/a", "Client Count = COUNT DISTINCT endclientid where isclient=1 (CASE column)"),
}
AO_M = {
 "M2": ("full", "variant", "Total AUM = SUM(totalaum) exactly; Current AUM, Year-End, Last Reported (Per Client) windowed variants + (One Per Client Snapshot) twins"),
 "M3": ("partial", "flag-only", "Prior Month AUM = SUM(prev_month_aum) exact; no last-snapshot measure, only Is * Snapshot flags"),
 "M4": ("full", "n/a", "AUM Growth % = (Total - Prior)/Prior*100, NULL on 0; summed-row basis matches key; plus one-per-client twin"),
 "M5": ("full", "variant", "SUM(accountbalancedkk); Last Reported Account Balance DKK (Per Account) windowed"),
 "M6": ("full", "n/a", "SUM(unrealizedprofitlossdkk)"),
 "M7": ("full", "n/a", "COUNT DISTINCT end_client_id"),
 "M9": ("partial", "flag-only", "AUM EOM DKK/EUR sums correct; only is_latest_month flag"),
 "M10": ("full", "n/a", "calc AUM EOM DKK - AUM BOM DKK (exact key form)"),
 "M11": ("full", "n/a", "Cash Ratio calc, NULL on 0"),
 "M12": ("full", "n/a", "Adjustment Value DKK / EUR sums"),
 "M13": ("full", "n/a", "Client Count COUNT DISTINCT end_client_id where is_client=1"),
}
HIER = {
 "CM": {
  "csr_level": "yes: Client Segment Level 1 > 2 > 3 > Client Segment (Client Segment Hierarchy)",
  "parent_child": "no SML parent-child; Parent/Grandparent Segment (+ID, Is Top Segment) attributes from SQL self-join",
  "snapshot_date": "yes (time dim, derived Snapshot Calendar): Year > Month ('YYYY-MM') > Day (YYYYMMDD key); month sorts lexically = chronological, Month Number secondary attr, no explicit sort column; 3+ role-plays (Reporting, Original, Asset Month, Legacy, Balance)",
 },
 "AOCM": {
  "csr_level": "yes: Segment Level 1 > 2 > 3 > Client Segment",
  "parent_child": "no SML parent-child; Parent/Grandparent Segment attrs from SQL self-join",
  "snapshot_date": "no: no calendar/time dimension; Snapshot Year / Year Month / Month / Date are flat attributes on each fact's record dimension (separately per fact), no hierarchy, no shared date dimension",
 },
}
G1 = {
 "CM": "documented default (no hard filter): Scenario dim + Total AUM/Active Clients/Prior Month/Unrealized P/L descriptions and model description say default Scenario Name = 'Actuals' unless scenarios compared; Is Default Scenario attr",
 "AOCM": "documented default (no hard filter): Scenario Details + model description; Is Actuals Scenario flag; Actuals baked into is_latest_snapshot/Current AUM and contract_profile last-reported subquery; Total AUM description asks row-vs-client reading (not G1)",
}
INVENTED = {
 "CM": "none of the unresolvable patterns (office/employee/lead/instrument/earning/product/trader/tool) get a dimension or join (office ids are plain attrs). One synthetic 'End Client' dimension (union of endclientid/counterpartid values from 5 tables) is joined from 5 fact columns - not an unresolvable pattern, but a dimension with no source table.",
 "AOCM": "none: office/employee/product keys exposed as plain code attributes only; no synthetic dimension",
}
DATES = {
 "CM": "Snapshot Calendar derived dataset: UNION of 7 fact date-key columns, year/month by integer arithmetic; does not read public.dates except for the Client Lead go-live LEFT JOIN. Avoids the calendar-range trap, at the cost of masking D7 and never joining Dates for R5-R7/R19.",
 "AOCM": "No calendar dimension. Builder trusted a sample-based profile (dates 1990..2003-09) and derived year/month from keys per fact; R5, R19 lost, R6/R7 only as LEFT JOINs in SQL. Answer key records R5-R7, R19 at 100% match to Dates; not re-verified (static run).",
}

def score(name, rmap, extras, mmap):
    real = [r for r in R if rmap[r][0] != NO]
    rp_strict = [r for r in real if not (name == "CM" and r in ("R5", "R6", "R7", "R19"))]
    P = len(real) / (len(real) + len(extras))
    return {
     "model": name,
     "relationships": {r: {"how": rmap[r][0], "note": rmap[r][1]} for r in R},
     "realised": real, "n_realised": len(real), "recall": round(len(real)/25, 3),
     "precision": round(P, 3), "extra_joins_not_in_key": extras, "n_extra": len(extras),
     "recall_strict_real_dates_table": round(len(rp_strict)/25, 3),
     "roleplay_R5_R7": {r: rmap[r][0] for r in ("R5", "R6", "R7")},
     "R3_toplevel_roleplay": rmap["R3"][0],
     "R20_parent_child": "SQL self-join + attributes; no SML parent-child hierarchy",
     "R18_left": rmap["R18"][0] != NO,
     "decoys_used": sorted(DECOYS[name]),
     "metrics": {m: {"score": v[0], "semi_additive": v[1], "note": v[2]} for m, v in mmap.items()},
     "metric_counts": {k: sum(1 for v in mmap.values() if v[0] == k) for k in ("full", "partial", "none")},
     "semi_additive_handled_native": 0,
     "semi_additive_handled_variant": sum(1 for m in ("M2","M3","M5","M9") if mmap[m][1] == "variant"),
     "semi_additive_flag_only": sum(1 for m in ("M2","M3","M5","M9") if mmap[m][1] == "flag-only"),
     "hierarchies": HIER[name], "G1": G1[name], "invented_keys": INVENTED[name], "dates": DATES[name],
    }

cm = score("CM", CM_R, CM_EXTRA, CM_M)
ao = score("AOCM", AO_R, AO_EXTRA, AO_M)
(OUT/"cm.json").write_text(json.dumps(cm, indent=1))
(OUT/"aocm.json").write_text(json.dumps(ao, indent=1))

def row(label, a, b): return f"| {label} | {a} | {b} |"
L = ["# Level 2: model quality vs answer key (CM vs AOCM)", "",
 "Static YAML read only (CM = tag saxo-cm-frozen, AOCM = HEAD). No engine/MCP/benchmark calls.", "",
 "| Item | CM | AOCM |", "|---|---|---|",
 row("R1-R25 realised (recall)", f"{cm['n_realised']}/25 = {cm['recall']:.0%}", f"{ao['n_realised']}/25 = {ao['recall']:.0%}"),
 row("Recall if R5-R7/R19 must hit public.dates", f"{cm['recall_strict_real_dates_table']:.0%}", f"{ao['recall_strict_real_dates_table']:.0%}"),
 row("Extra joins not in R1-R25", cm['n_extra'], ao['n_extra']),
 row("Precision", f"{cm['precision']:.0%}", f"{ao['precision']:.0%}"),
 row("R5-R7 role-plays", "3/3 SML role-plays (derived calendar)", "2/3 (R6, R7) as LEFT JOINs in SQL; R5 missing"),
 row("R3 top-level contract role", "missing", "missing"),
 row("R20 parent-child", "SQL self-join + Parent/Grandparent attrs; no parent-child hierarchy", "same"),
 row("R18 as LEFT", "yes (SQL)", "yes (SQL)"),
 row("Decoys used (D1-D7)", "D7 (masked by derived calendar)", "none"),
 row("Metrics full/partial/none (M2-M13 usable, 11)", f"{cm['metric_counts']['full']}/{cm['metric_counts']['partial']}/0", f"{ao['metric_counts']['full']}/{ao['metric_counts']['partial']}/0"),
 row("Semi-additive (M2,M3,M5,M9): native / windowed variant / flag-only", f"0 / {cm['semi_additive_handled_variant']} / {cm['semi_additive_flag_only']}", f"0 / {ao['semi_additive_handled_variant']} / {ao['semi_additive_flag_only']}"),
 row("CSR level hierarchy", "yes", "yes"),
 row("Parent-child hierarchy", "no (attrs)", "no (attrs)"),
 row("Snapshot date Year>Month>Day", "yes, derived calendar; month label sorts chronologically", "no calendar dimension"),
 row("G1 Actuals default", "documented default, no hard filter", "documented default (+Actuals baked into some variants), no hard filter"),
 row("Invented keys", "no listed pattern; 1 synthetic End Client dim", "none"),
 "", "## Per relationship", "", "| R | CM | AOCM |", "|---|---|---|"]
for r in R:
    L.append(f"| {r} | {cm['relationships'][r]['how']}: {cm['relationships'][r]['note']} | {ao['relationships'][r]['how']}: {ao['relationships'][r]['note']} |")
L += ["", "Extra joins, CM:"] + [f"- {e}" for e in CM_EXTRA] + ["", "Extra joins, AOCM:"] + [f"- {e}" for e in AO_EXTRA]
L += ["", "## Per metric (M1 and M8 unusable per key, skipped; M9b/M12b scored with M9/M12)", "", "| M | CM | AOCM |", "|---|---|---|"]
for m in CM_M:
    L.append(f"| {m} | {CM_M[m][0]} ({CM_M[m][1]}): {CM_M[m][2]} | {AO_M[m][0]} ({AO_M[m][1]}): {AO_M[m][2]} |")
L += ["", "## Dates", "", f"- CM: {DATES['CM']}", f"- AOCM: {DATES['AOCM']}",
 "", "## Takeaways", "",
 "- Recall is close (CM 88%, AOCM 80%); both miss R3 (top-level contract role-play) and R24/R25 (history from/to dates). The AOCM-only misses are R5 and R19, both from the no-calendar decision.",
 "- Precision favours AOCM (95% vs 76%): CM adds a synthetic End Client dimension joined from 5 columns (incl. aum_demo.counterpartid) and the decoy D7 join; AOCM adds one plausible join (feed counterparty to contract).",
 "- CM's date recall is functional, not real: its calendar is built from fact keys, so R5-R7/R19 'resolve' but never touch public.dates and D7 is hidden. Strict recall CM 72% vs AOCM 80%.",
 "- Metrics: AOCM defaults match the key (Total AUM, Prior Month, Growth on summed rows); CM defaults are dedup'd per client-snapshot, so M2/M3/M4 only match via twins. CM has more windowed latest-snapshot variants (M3 included); neither uses semi_additive config, so the semi-additive rule rests on variants/flags and descriptions.",
 "- Neither builds a parent-child hierarchy for R20 nor a hard Actuals filter (G1); both document the default. Neither invents a dimension for an unresolvable key pattern.",
 "", "## Judgment calls", "",
 "- Relationship counted as realised if the right columns are joined either as SML relationship or in derived SQL; role-play via SQL alias counts for R6/R7.",
 "- CM R5-R7/R19 counted realised (right fact columns, role-plays) although target is a derived calendar; strict number reported alongside.",
 "- R21/R22 in CM counted realised: contractid join in SQL then mk_contractsid relationship.",
 "- Precision = realised / (realised + extra joins); extras de-duplicated by source column, derived fact copies of PAUM counted once.",
 "- Metric rubric: full = plain-named metric matches key and (if semi-additive) a windowed latest-snapshot variant exists; partial = exact only as a twin, or semi-additive flag-only; none = absent. AUM Growth x100 scale vs key formula ignored. M1/M8 skipped (unusable).",
 "- Semi-additive 'native' = SML semi_additive config; neither model uses it (grep)."]
(OUT/"LEVEL2.md").write_text("\n".join(L)+"\n")
print(cm["recall"], cm["precision"], ao["recall"], ao["precision"], cm["metric_counts"], ao["metric_counts"])
