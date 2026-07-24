# WBS extraction — EPC capital project reports

This document is a final report for an EPC (Engineering, Procurement,
Construction) capital project. Extract its Work Breakdown Structure
(WBS) into one row per contractor assignment.

## Where the WBS lives

Look for pages titled "Work Breakdown Structure", "WBS", "Project
Execution Strategy" or "Contracting Strategy". The WBS is usually a
matrix/grid diagram: one axis lists the project lifecycle phases, the
other lists facility/scope areas, and the cells contain contractor
names (sometimes with a contract-type abbreviation). It can also appear
as an organization chart or a plain table. Pages with no WBS content
contribute no rows.

## From matrix to rows

Cross-multiply the matrix: each cell produces one row per contractor it
names, with ACTIVITY = the cell's phase and ASSET_L1 = the cell's
facility area. A cell that visually spans several phases or areas
produces one row for every (phase, area) combination it covers. If
multiple contractors share a cell, emit one row per contractor. The
result is one row per unique (ACTIVITY, ASSET_L1, COMPANY).

## How to fill the columns

- PROJECT_ID — the project's unique id number. Check the report cover
  and headers; it is sometimes encoded in the source file name.
- ACTIVITY — the lifecycle phase. Use these canonical spellings when
  the document matches them: "Project Management", "Basic Design",
  "FEED", "Detailed Engineering", "Procurement", "Construction",
  "Commissioning", "Start-Up", "Operations". Only include phases that
  actually appear in this document's WBS.
- ASSET_L1 — the facility/scope area, formatted as "CATEGORY: Name",
  where CATEGORY is ISBL (inside battery limits: core process units),
  OSBL (outside battery limits: offsites, utilities, interconnects) or
  OTHER (owner-managed or out-of-scope items such as pipelines or
  brownfield work). Examples: "ISBL: APS", "OSBL: Offsites &
  Interconnects", "OTHER: Pipeline".
- COMPANY — the contractor or organization named in the cell.
- ORGANIZATION — the sub-organization when shown, otherwise "None".
- SCOPE_NAME — the named scope package when shown, otherwise "None".
- CONTRACT_TYPE — the compensation-model abbreviation when shown: RC
  (reimbursable cost), FF (fixed fee), RC+FF, RC/FF, LS (lump sum), UR
  (unit rates), SS (single source), LTA (long-term agreement).
  Otherwise "None".
- CONTRACT — the contract number/id when shown, otherwise "None".

Use the literal string "None" for optional fields the document simply
does not provide — that matches the historical table convention. Keep
null only for values that are present in the document but illegible.

## Multiple WBS versions

Reports may contain more than one WBS (e.g. an original plan and a
revised or restart version). Extract every version you find. In
addition to the schema keys, add a "WBS_VERSION" key to every row,
labelling the version it belongs to: use the label the document gives
(e.g. "ORIGINAL", "RESTART", "REV 2"), or "MAIN" when there is only one
unlabelled WBS.
